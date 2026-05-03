# Production-Grade Implementation Plan

> Status: Planning | Target: RIS Emulator v2.0

---

## Overview

This plan describes the phased work to transform the current research-prototype RIS emulator into a production-grade simulation platform. Each phase is independently shippable and builds on the previous one.

**Current baseline**: The emulator runs reliably for the two-node RIS example. All critical correctness bugs from the project review have been fixed (TX-only completion, tail-sample `ceil`, `[0,0]` padding, `req_time <= 0` guards, atomic JSON writes, signed RIS visibility, `phase_response` lookup, input validation, vectorized `total_nlos_gain`).

---

## Phase A: Performance & In-Memory State (Week 1-2)

**Goal**: Eliminate per-tick JSON I/O and Python-loop bottlenecks. 256×256 RIS arrays should process in <1ms per tick.

### A1 — Introduce `Simulation` class with in-memory state

Currently `engine.py` is a top-level script with globals. Pull it into a class that holds all simulation state in memory.

```python
# ris_sim/core/engine.py (new)
class Simulation:
    def __init__(self, room: dict, ris: list[dict], nodes: list[dict], tau: float = 0.002):
        self.tau = tau
        self.room = RoomConfig(room)
        self.ris_controllers = [RisController(r) for r in ris]
        self.nodes = [NodeState(n) for n in nodes]
        self.output = OutputBuffer()
        self.counter = 0

    def tick(self) -> bool:
        """Advance one step. Returns True if simulation should continue."""
        self._update_ris()
        self._advance_mobility()
        self._assign_requests()
        self._process_transmissions()
        self._process_receptions()
        self.counter += 1
        return not self._all_idle()

    def run(self, max_ticks: int = 1_000_000) -> OutputBuffer:
        while self.tick() and self.counter < max_ticks:
            pass
        return self.output
```

- Convert `NodeState` to a dataclass (no more dict-mutation spaghetti)
- Convert `RisController` to hold precomputed element coordinates as numpy arrays
- `OutputBuffer` accumulates samples in memory as `list[OutputEntry]`, writes to disk only on completion or explicit flush

### A2 — Precompute RIS element coordinates

`coordinate_matrix_gen` is called every tick inside `total_nlos_gain`. For a static RIS, element positions never change.

- Compute `(M, N, 3)` numpy array of element centers once at `RisController.__init__`
- Only recompute if the RIS moves (future: mobile RIS support)

```python
class RisController:
    def __init__(self, config: dict):
        self.coordinates: np.ndarray  # shape (M, N, 3), precomputed
        self.phase_response: dict
        self.configuration_matrix: np.ndarray  # shape (M, N)
        self.normal: np.ndarray
```

### A3 — Vectorize `total_nlos_gain` with NumPy broadcasting

Current implementation uses nested Python `for i / for j` loops. Replace with vectorized operations:

```python
def total_nlos_gain(fc, tx_loc, rx_loc, ris: RisController) -> complex:
    tx = np.array(tx_loc)
    rx = np.array(rx_loc)
    elements = ris.coordinates  # (M, N, 3)

    # All element→TX and element→RX vectors at once
    r_in_vecs = elements - tx          # (M, N, 3)
    r_out_vecs = rx - elements         # (M, N, 3)
    r_in = np.linalg.norm(r_in_vecs, axis=2)   # (M, N)
    r_out = np.linalg.norm(r_out_vecs, axis=2) # (M, N)

    # Visibility mask (cos_i > 0 and cos_r > 0)
    cos_i = np.sum(r_in_vecs * ris.normal, axis=2) / r_in
    cos_r = np.sum(r_out_vecs * ris.normal, axis=2) / r_out
    visible = (cos_i > 0) & (cos_r > 0)
    visibility = np.sqrt(cos_i * cos_r) * visible

    # Per-element reflection coefficients from config matrix
    bn = ris.get_reflection_coefficients()  # (M, N) complex

    # Free-space coefficients for all paths
    h_in = free_space_coefficient_vectorized(fc, r_in)   # (M, N)
    h_out = free_space_coefficient_vectorized(fc, r_out) # (M, N)

    # Total cascaded gain
    element_gains = bn * visibility * h_in * h_out  # (M, N)
    return np.sum(element_gains)  # scalar complex
```

**Expected speedup**: ~100× for 16×16 RIS, ~500× for 256×256 RIS.

### A4 — Stream output in binary chunks

- `OutputBuffer` writes `.npz` chunks every N ticks (or at simulation end)
- Keep metadata (request_id, fc, sample_rate) in a companion JSONL file
- Drop the full-JSON output path entirely; it was ~10× larger and ~50× slower than binary

### A5 — Benchmark suite

Add `ris_sim/tests/test_benchmarks.py`:
- 1 tick with 16×16 RIS, 2 nodes: target <5ms
- 1 tick with 256×256 RIS, 2 nodes: target <50ms
- 1000-tick simulation with 16×16 RIS: target <2s total
- Memory: 1000-tick simulation with 256×256 RIS <500MB RSS

### Phase A Deliverables
- `Simulation` class replaces top-level `engine.py` script
- RIS coordinates precomputed once
- Vectorized RIS channel computation
- Binary output streaming
- Benchmarks passing for all RIS sizes

---

## Phase B: Real IPC & API (Week 2-4)

**Goal**: Replace JSON-file IPC with proper message passing. External scripts should not touch `config/*.json` at all.

### B1 — Message queue architecture

Use **ZeroMQ** (pyzmq) for cross-process communication:

```
                    ┌──────────────┐
   usrp_tx.py ─────▶│  REQ/REP     │──────▶ Simulation.process_tx()
   usrp_rx.py ◀─────│  (per-node)  │◀────── Simulation.process_rx()
   dummy_rsc.py ────▶│  PUB/SUB     │──────▶ Simulation.update_ris()
                    └──────────────┘
```

- Each node gets a `REQ` socket for TX and a `REP` socket for RX
- RIS controller uses `PUB` socket, engine subscribes
- Messages are **msgpack** or **protobuf** serialized (binary, schema'd, 10× smaller than JSON)
- Engine runs as a long-lived process; external scripts connect, send requests, get responses

### B2 — New API surface

```python
# ris_sim/radio/api.py

def send_to_simulator(data: np.ndarray, fc: float, sample_rate: float, node_id: str,
                      tau: float = 0.002, timeout: float = None) -> str:
    """Send IQ samples for transmission. Returns request_id."""

def receive_from_simulator(num_samps: int, fc: float, sample_rate: float, node_id: str,
                           tau: float = 0.002, timeout: float = None) -> np.ndarray:
    """Block until num_samps IQ samples are received. Returns complex ndarray."""

def receive_async(num_samps: int, fc: float, sample_rate: float, node_id: str,
                  callback: Callable[[np.ndarray], None], tau: float = 0.002):
    """Non-blocking receive with callback on completion."""
```

Backward-compatible: keep the old `recieve_from_simulator` and `send_to_simulator` (JSON-file path) as deprecated wrappers.

### B3 — Simulation server mode

```bash
# Start the engine as a background server
python -m ris_sim serve --config scenarios/two_node_ris.json

# External scripts connect and interact
python -m ris_sim tx --node node_1 --fc 2.4e9 --rate 5880 --file tx_iq.npy
python -m ris_sim rx --node node_2 --fc 2.4e9 --rate 5880 --samples 1024 --output rx.npy
```

### B4 — Request queuing and lifecycle

- A node can have **one active TX or RX request** at a time
- New requests for a busy node are queued (FIFO, max depth configurable)
- Requests carry a TTL; expired requests are dropped with an error response
- Node state machine: `IDLE → TX_QUEUED → TX_ACTIVE → TX_COMPLETE → IDLE`

### Phase B Deliverables
- ZeroMQ-based request/response channels
- Blocking + non-blocking receive APIs that actually return samples
- CLI server mode (`ris_sim serve`)
- Old JSON-file API preserved as deprecated fallback

---

## Phase C: Signal Model Completeness (Week 4-7)

**Goal**: Make the wireless channel physically credible and configurable for research use.

### C1 — Re-enable AWGN noise

`channel_functions.noise()` already exists but is commented out in the engine. Wire it in:

```python
# In Simulation._process_receptions():
noise_floor_db = self.room.get("noise_floor_db", -174)  # dBm/Hz thermal
bandwidth = float(node.sample_rate) / 2  # Nyquist bandwidth
noise_power = 10 ** ((noise_floor_db - 30) / 10) * bandwidth  # linear
noise_scale = np.sqrt(noise_power / 2)  # per I/Q component
output_data = channel.add_noise(output_data, noise_scale)
```

Make noise configurable per node:
```json
{
    "id": "node_2",
    "rf": {
        "noise_figure_db": 5.0,
        "rx_gain_db": 20.0
    }
}
```

### C2 — Small-scale fading (Rayleigh / Rician)

Add multipath as an optional channel component:

```python
# ris_sim/channel/fading.py
def rayleigh_fading(n_samples: int, fd: float, sample_rate: float, seed=None) -> np.ndarray:
    """Generate Rayleigh fading coefficients using Clarke's model (sum-of-sinusoids)."""

def rician_fading(n_samples, fd, sample_rate, k_factor_db=10, seed=None) -> np.ndarray:
    """Rician fading: dominant LOS + Rayleigh scatterers."""

def apply_fading(samples: np.ndarray, fading_coeffs: np.ndarray) -> np.ndarray:
    """Element-wise multiply IQ samples by time-varying fading coefficients."""
```

Config per scenario:
```json
{
    "channel": {
        "small_scale": {
            "model": "rayleigh",
            "max_doppler_hz": 50.0
        }
    }
}
```

### C3 — RF impairments module

```python
# ris_sim/radio/impairments.py

def apply_phase_noise(samples, sample_rate, phase_noise_dbc_hz=-90, seed=None) -> np.ndarray:
    """Add oscillator phase noise (Wiener process model)."""

def apply_cfo(samples, sample_rate, cfo_hz=100.0) -> np.ndarray:
    """Apply carrier frequency offset as a rotating phasor."""

def apply_iq_imbalance(samples, amplitude_imbalance_db=0.5, phase_imbalance_deg=2.0) -> np.ndarray:
    """Apply I/Q imbalance: gain mismatch + phase skew."""

def apply_sfo(samples, sample_rate, sfo_ppm=10.0) -> np.ndarray:
    """Resample with sample frequency offset using linear interpolation."""

def apply_nonlinearity(samples, ip3_db=30.0) -> np.ndarray:
    """Apply 3rd-order Rapp or Saleh PA nonlinearity."""

def apply_impairments(samples, sample_rate, impairments: dict) -> np.ndarray:
    """Pipeline: apply all enabled impairments in correct physical order."""
```

Per-node config:
```json
{
    "id": "node_1",
    "rf": {
        "cfo_hz": 150.0,
        "phase_noise_dbc_hz": -85.0,
        "iq_imbalance": {"gain_db": 0.3, "phase_deg": 1.5},
        "sfo_ppm": 5.0,
        "pa_model": {"type": "rapp", "smoothness": 2.0, "p_sat_db": 30.0}
    }
}
```

Impairment application order (physical correctness):
1. TX: SFO → IQ imbalance → PA nonlinearity → (channel) → RX: CFO → Phase noise → IQ imbalance → SFO

### C4 — OFDM subcarrier support

```python
# ris_sim/radio/ofdm.py

def ofdm_modulate(symbols: np.ndarray, n_subcarriers: int, cp_len: int) -> np.ndarray:
    """OFDM modulate: serial→parallel, IFFT, add cyclic prefix. Returns IQ samples."""

def ofdm_demodulate(samples: np.ndarray, n_subcarriers: int, cp_len: int) -> np.ndarray:
    """OFDM demodulate: remove CP, FFT, parallel→serial. Returns received symbols."""

def ofdm_pilot_insert(symbols: np.ndarray, pilot_indices: list[int], pilot_values) -> np.ndarray:
    """Insert known pilot symbols for channel estimation."""

def ofdm_channel_estimate(rx_pilots, tx_pilots, pilot_indices) -> np.ndarray:
    """LS/MMSE channel estimation from pilots."""
```

### C5 — Analytical validation

Add tests that compare simulated results against known formulas:
- **LOS only, no RIS**: Received power must match Friis equation within 0.1dB
- **Single RIS element, normal incidence**: Match radar range equation
- **AWGN only, no signal**: Sample variance must match configured noise power
- **CFO only**: Constellation rotation rate must match configured CFO in Hz
- **IQ imbalance only**: Image rejection ratio must match configured values

### Phase C Deliverables
- Configurable AWGN per node
- Rayleigh/Rician small-scale fading
- RF impairment pipeline (CFO, phase noise, IQ imbalance, SFO, PA nonlinearity)
- OFDM modulation/demodulation with pilot-based channel estimation
- Analytical validation tests for each model

---

## Phase D: Testing, Reproducibility & CI (Week 7-9)

**Goal**: Every commit is validated. Every simulation is reproducible.

### D1 — Deterministic mode

```python
# ris_sim/core/random.py
import numpy as np

_GLOBAL_RNG = np.random.RandomState(None)

def set_seed(seed: int):
    """Set global seed for all stochastic components."""
    _GLOBAL_RNG.seed(seed)
    np.random.seed(seed)

def get_rng() -> np.random.RandomState:
    return _GLOBAL_RNG
```

- All stochastic code (mobility, noise, fading, impairments) uses `get_rng()` instead of bare `np.random`
- Scene header records the seed:
  ```json
  {"seed": 42, "room": {...}, ...}
  ```

### D2 — Golden output regression tests

```python
# ris_sim/tests/test_regression.py
class TestRegression(unittest.TestCase):
    def test_two_node_ris_golden(self):
        """Two-node RIS scenario produces bit-identical output with fixed seed."""
        sim = Simulation.from_scenario("scenarios/golden/two_node_ris.json", seed=42)
        output = sim.run()
        expected = np.load("scenarios/golden/two_node_ris_output.npz")
        for name in expected.files:
            np.testing.assert_array_almost_equal(output.arrays[name], expected[name], decimal=10)
```

- Store golden outputs in `ris_sim/tests/golden/` (small files: 16×16 RIS, 120 samples)
- Run on every commit

### D3 — Engine integration tests

```python
class TestEngineIntegration(unittest.TestCase):
    def test_tx_only_completes_and_idles(self):
        """Single TX node with no RX must finish and return to idle."""
        ...

    def test_rx_only_returns_noise(self):
        """RX with no matching TX must return noise/zeros of correct length."""
        ...

    def test_output_length_matches_request(self):
        """Received samples count must equal num_samps exactly."""
        ...

    def test_no_ris_scenario(self):
        """Simulation with no RIS in config must run with LOS-only channel."""
        ...

    def test_multi_node_concurrent_tx_rx(self):
        """Multiple TX/RX pairs on different frequencies must not interfere."""
        ...

    def test_mobility_changes_location(self):
        """Random walk node must move between ticks."""
        ...

    def test_max_ticks_guard(self):
        """Simulation with stuck node must abort at MAX_TICKS."""
        ...
```

### D4 — CI/CD pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e ".[dev]"
      - run: pytest --cov=ris_sim --cov-report=xml
      - run: ruff check ris_sim/
      - run: mypy ris_sim/

  benchmarks:
    runs-on: ubuntu-latest
    steps:
      - run: pytest ris_sim/tests/test_benchmarks.py --benchmark-json=bench.json
      - uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: pytest
          output-file-path: bench.json
```

### D5 — Scenario fixtures library

```
scenarios/
├── golden/
│   ├── two_node_ris.json
│   └── two_node_ris_output.npz
├── edge_cases/
│   ├── tx_only_no_rx.json
│   ├── rx_only_no_tx.json
│   └── no_ris_los_only.json
├── stress/
│   ├── large_ris_256x256.json
│   └── hundred_node_mobility.json
└── rf_impairments/
    ├── cfo_500hz.json
    ├── rayleigh_50hz_doppler.json
    └── ofdm_64subcarrier.json
```

### Phase D Deliverables
- Deterministic seed control across all stochastic modules
- Golden output regression tests
- 12+ engine integration tests
- GitHub Actions CI on 3 OS × 3 Python versions
- Scenario fixtures library for testing and demos
- 80%+ code coverage

---

## Phase E: Packaging, CLI & Documentation (Week 9-10)

**Goal**: Anyone can `pip install` and run the emulator in 30 seconds.

### E1 — Proper Python packaging

```
ris_sim/
├── pyproject.toml          # build config, deps, entry points
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── engine.py           # Simulation class
│   ├── state.py            # NodeState, RisController dataclasses
│   └── random.py           # Seeded RNG
├── radio/
│   ├── __init__.py
│   ├── api.py              # send_to_sim, receive_from_sim
│   ├── impairments.py
│   ├── ofdm.py
│   └── waveforms.py        # BPSK, QPSK, QAM generators
├── channel/
│   ├── __init__.py
│   ├── los.py              # free_space_coefficient
│   ├── ris.py              # total_nlos_gain, element_visibility
│   ├── fading.py           # Rayleigh, Rician
│   └── noise.py            # AWGN generator
├── mobility/
│   ├── __init__.py
│   └── models.py           # all mobility functions
├── io/
│   ├── __init__.py
│   ├── json_store.py       # atomic reads/writes
│   └── output_buffer.py    # binary output streaming
├── config/
│   ├── __init__.py
│   └── validation.py
├── analysis/
│   ├── __init__.py
│   ├── results.py
│   └── plotting.py
├── cli/
│   ├── __init__.py
│   └── main.py             # CLI entry points
├── controllers/
│   ├── __init__.py
│   └── dummy_rsc.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── golden/
    ├── test_engine.py
    ├── test_channel.py
    ├── test_impairments.py
    ├── test_mobility.py
    ├── test_api.py
    ├── test_regression.py
    └── test_benchmarks.py
```

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "ris-sim"
version = "2.0.0"
description = "Open Emulator for Smart Radio Environments with RIS"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "numpy>=1.24",
    "matplotlib>=3.7",
    "pyzmq>=25",
    "msgpack>=1.0",
]
[project.optional-dependencies]
dev = [
    "pytest>=7",
    "pytest-cov>=4",
    "pytest-benchmark>=4",
    "ruff>=0.3",
    "mypy>=1.8",
]

[project.scripts]
ris-sim = "ris_sim.cli.main:main"
```

### E2 — CLI

```bash
# Serve: start simulation engine as a background process
ris-sim serve --scenario scenarios/two_node_ris.json --port 5555

# Run-and-exit: run a complete scenario and export results
ris-sim run scenarios/two_node_ris.json --output results/

# Send a TX request
ris-sim tx --node node_1 --fc 2.4e9 --rate 5880 --iq-file tx_samples.npy

# Send an RX request, block until complete, save to file
ris-sim rx --node node_2 --fc 2.4e9 --rate 5880 --samples 1024 --output rx.npy

# Generate scenario from template
ris-sim scenario new my_scenario --nodes 3 --ris 16x16
```

### E3 — README audit

Split into clearly labeled sections:
- **What works now** (with exact config examples that run)
- **What's experimental** (any partial features)
- **What's planned** (roadmap summary linking to this plan)

Remove any claims not yet implemented (FIFO, named pipes, CSV RIS, event logs, multiple channel models) unless they're implemented.

### E4 — Docker image

```dockerfile
FROM python:3.12-slim
RUN pip install ris-sim
ENTRYPOINT ["ris-sim"]
```

```bash
docker run --rm -v $(pwd)/scenarios:/scenarios ris-sim run /scenarios/two_node_ris.json
```

### Phase E Deliverables
- `pip install ris-sim` works
- `ris-sim` CLI with `serve`, `run`, `tx`, `rx`, `scenario` subcommands
- Clean README with runnable examples
- Docker image
- Type hints on all public APIs
- `ruff` lint and `mypy` typecheck pass clean

---

## Phase F: Observability & Operations (Week 10-11)

**Goal**: Understand what the emulator is doing during long runs.

### F1 — Structured logging

Replace all `print()` with `loguru`:

```python
from loguru import logger

logger.info("Simulation started: {nodes} nodes, {ris} RIS panels, tau={tau}s",
            nodes=len(self.nodes), ris=len(self.ris_controllers), tau=self.tau)
logger.debug("Tick {counter}: {tx_active} TX, {rx_active} RX active",
             counter=self.counter, tx_active=..., rx_active=...)
logger.warning("Node {id}: RF impairment cfo_hz={cfo} is unusually large", id=..., cfo=...)
```

Log levels: `DEBUG` (per-tick details), `INFO` (simulation progress), `WARNING` (unusual configs), `ERROR` (failures).

### F2 — Progress reporting

```python
# For long simulations, show progress every N ticks or N seconds
with ProgressLogger(total_ticks=expected_ticks, interval_s=1.0) as progress:
    while sim.tick():
        progress.update(sim.counter)
```

Output:
```
Simulation: 142/218 ticks (65.1%) | 45.2 ticks/s | ETA 1.7s | Mem: 84MB
```

### F3 — Metrics & instrumentation

```python
class SimulationMetrics:
    tick_durations: list[float]        # per-tick wall-clock time
    samples_processed: int             # total IQ samples through channel
    ris_element_computations: int      # total RIS element evaluations
    bytes_written: int                 # output data written
    peak_memory_mb: float              # max RSS

    def report(self) -> str:
        """Human-readable summary at simulation end."""
```

### F4 — Graceful shutdown

```python
import signal

class Simulation:
    def run(self, max_ticks=1_000_000):
        self._shutdown_requested = False
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        while self.tick() and self.counter < max_ticks:
            if self._shutdown_requested:
                logger.info("Shutdown requested, saving checkpoint...")
                self.save_checkpoint()
                break
        return self.output
```

### F5 — Health checks

```bash
ris-sim healthcheck --port 5555
# Returns: {"status": "ok", "uptime_s": 342, "nodes": 2, "ticks_processed": 171}
```

### Phase F Deliverables
- Structured logging with log levels
- Progress bar for CLI runs
- Metrics report at end of each simulation
- SIGINT/SIGTERM graceful shutdown with checkpoint
- Health check endpoint for server mode

---

## Phase G: Advanced Features (Week 11-12+)

**Goal**: Features that distinguish this from basic channel simulators.

### G1 — Real-time RIS control loop

Allow an external RIS controller to reconfigure the RIS during a running simulation (not just at startup):

```python
# External controller script
for tick in range(100):
    # Run optimization algorithm
    new_phase_matrix = optimize_beam_direction(target_rx)
    sim.ris_update("ris_1", new_phase_matrix)
    time.sleep(0.002)  # match tau
```

### G2 — Multiple independent scenarios / parallel execution

```python
# Run N Monte Carlo trials in parallel
results = ris_sim.parallel_run(scenario, trials=100, workers=8)
snr_curves = [r.compute_snr() for r in results]
```

### G3 — Channel sounding mode

```python
# Send a known pilot sequence and estimate the channel
h_est = sim.channel_sound(tx_node="node_1", rx_node="node_2", fc=2.4e9)
# h_est is the complex channel coefficient (LOS + RIS)
```

### G4 — Web dashboard

Optional Flask/FastAPI dashboard for real-time visualization:
- Live constellation plot
- RIS heatmap with animated state changes
- Node position tracking
- Power-over-time waterfall

### G5 — Hardware-in-the-loop (HIL) bridge

- Replace the `usrp_tx.py` dummy with actual USRP UHD bindings
- Replace `usrp_rx.py` with actual USRP receive
- Mixed mode: some nodes are emulated, some are real hardware

---

## Dependency Graph

```
Phase A (Performance)
  └── No prerequisites — start immediately
      └── Phase B (IPC & API)
          └── Phase C (Signal Model)
              └── Phase D (Testing & CI)
                  ├── Phase E (Packaging & Docs)
                  └── Phase F (Observability)
                      └── Phase G (Advanced Features)
```

Phases A-C can partially overlap (e.g., the vectorized RIS math from A3 is independent of the IPC work in B1).

---

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| ZeroMQ introduces Windows/Linux portability issues | Medium | Abstract transport behind a `Transport` protocol; fall back to multiprocessing queues on Windows if needed |
| Vectorized RIS uses too much memory for large arrays | Medium | Block processing: compute 8×8 tiles, accumulate partial sums |
| Breaking changes to scenario JSON format | Low | Version the schema; Phase E includes a migration tool |
| Performance targets not met for 256×256 RIS | Low | Plan B: optional Numba/Cython JIT compilation for hot loops |
| External dependency creep | Low | Keep `pyzmq` and `msgpack` optional; core engine runs with only `numpy` |

---

## Success Criteria

A simulation is "production-grade" when:

1. **Correctness**: TX/RX sample counts are exact; all nodes return to idle; no hangs or crashes with any valid config
2. **Performance**: 256×256 RIS processes <50ms per tick; 10,000-tick simulation completes in <5 minutes
3. **Reproducibility**: Same seed → bit-identical output on any platform
4. **Usability**: `pip install ris-sim && ris-sim run scenario.json` works on all 3 OSes
5. **Testability**: >80% coverage; golden regression tests on every commit; CI green
6. **Extensibility**: New channel model = new file in `channel/` + register in config; no engine changes needed
7. **Observability**: Logs, metrics, progress bar, health check all work out of the box
