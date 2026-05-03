# Phase G — Advanced Features: Detailed Plan

> Status: Planning | Depends on: Phases A-F complete | Effort: 4-8 weeks

---

## Overview

Phase G covers five advanced features that elevate the emulator from a
single-scenario research tool to a platform capable of real-time control,
large-scale Monte Carlo studies, channel measurement, visualization, and
hardware integration. These are individually large features; each sub-phase
is designed to ship independently.

---

## G1: Real-Time RIS Control Loop (~1 week)

**Goal**: An external controller can reconfigure RIS elements *during* a running
simulation, enabling closed-loop optimization algorithms.

### Architecture

```
                  ┌──────────────────────────┐
  RIS Controller  │  SimulationServer         │
  (Python script) │                           │
     │            │  ┌─────────────────────┐  │
     │  ZMQ REQ   │  │  ris_set_config()   │  │
     ├───────────►│  │                     │  │
     │            │  │  Updates             │  │
     │            │  │  ris.reflection_coeffs│  │
     │ ◄──────────┤  │  (takes effect next  │  │
     │  response  │  │   tick)              │  │
     │            │  └─────────────────────┘  │
                  └──────────────────────────┘
```

### API Design

```python
# Direct (in-process)
sim.ris_set_config("ris_1", np.array([[phase1, phase2, ...], ...]))

# Via ZeroMQ server
transport.request({"cmd": "ris_config", "ris_id": "ris_1", "matrix": [[...]]})

# Synchronous: wait for config to take effect
sim.ris_set_config_sync("ris_1", matrix, wait_ticks=1)
```

### Implementation Steps

1. **`RisController.set_config(matrix)`** — Update `reflection_coeffs` from a new
   phase/gain matrix. Already partially exists via `update_configuration()`.
2. **`Simulation.ris_set_config(ris_id, matrix)`** — Public method that calls
   through to the controller.
3. **Server command `ris_config`** — Add to `_process_requests` dispatch in server.
4. **Config validation** — Ensure matrix dimensions match `array_size`. Values
   should map through `reflection_coefficient()` to complex gains.
5. **Temporal alignment** — Config changes take effect on the *next* tick.
   Document this clearly; add `wait_ticks` parameter for users who need
   deterministic timing.

### Use Cases
- Gradient-descent beam optimization (maximize SNR at a target receiver)
- Genetic algorithm for multi-user beamforming
- Time-varying RIS patterns (e.g., sweeping a beam across the room)
- Studying RIS reconfiguration latency effects

### Integration Test
```python
def test_ris_reconfiguration_mid_simulation():
    sim = Simulation.from_scenario(scenario)
    sim.queue_tx("tx", iq, ...)
    sim.queue_rx("rx", n, ...)
    sim.tick()  # process first few ticks with default config
    sim.ris_set_config("ris_1", new_phase_matrix)
    sim.tick()  # remaining ticks use new config
    # Verify output differs from a run without reconfiguration
```

---

## G2: Parallel Monte Carlo Execution (~1.5 weeks)

**Goal**: Run hundreds of independent simulation trials in parallel,
aggregating results for statistical analysis (SNR distributions, BER curves,
capacity CDFs).

### Architecture

```
  ┌──────────┐
  │ Scenario │
  └────┬─────┘
       │
  ┌────▼──────────────────────────────────┐
  │  parallel_run(scenario, trials=100,    │
  │               workers=8, seeds=range(N))│
  │                                        │
  │  ┌──────┐  ┌──────┐       ┌──────┐   │
  │  │Worker│  │Worker│  ...  │Worker│   │
  │  │  1   │  │  2   │       │  8   │   │
  │  │seed=0│  │seed=1│       │seed=7│   │
  │  └──┬───┘  └──┬───┘       └──┬───┘   │
  │     │         │               │       │
  │     └─────────┴───────────────┘       │
  │               │                        │
  │        ┌──────▼──────┐                │
  │        │  Aggregator │                │
  │        │  (combine   │                │
  │        │   results)  │                │
  │        └─────────────┘                │
  └───────────────────────────────────────┘
```

### API Design

```python
from ris_sim.parallel import parallel_run, MonteCarloResult

# Simple: run N trials, collect all output buffers
results: list[OutputBuffer] = parallel_run(
    scenario, trials=100, workers=8
)

# With progress + aggregation
mc = MonteCarloResult()
for trial_output in parallel_run(scenario, trials=500, workers=8, progress=True):
    snr = trial_output.compute_snr(tx_power=0.01, noise_bw=2940)
    mc.record(snr=snr, samples=trial_output.entries[0].flatten_iq())

print(f"SNR: median={mc.snr_median:.1f} dB, p90={mc.snr_p90:.1f} dB")
mc.plot_snr_cdf("snr_cdf.png")
```

### Implementation Steps

1. **`ris_sim/parallel/__init__.py`** — `parallel_run()` function
2. **`ris_sim/parallel/worker.py`** — Per-trial worker that runs `Simulation`
   with a given seed
3. **`ris_sim/parallel/result.py`** — `MonteCarloResult` dataclass with:
   - `snr_samples: list[float]`
   - `ber_samples: list[float]`
   - `compute_cdf()` → returns (x, cdf) arrays
   - `plot_snr_cdf(path)`, `plot_ber_curve(path)` — quick matplotlib exports
4. **Multiprocessing strategy**:
   - Use `concurrent.futures.ProcessPoolExecutor` (avoids GIL, works on all OS)
   - Each worker instantiates a fresh `Simulation` from the scenario dict
   - Workers return `OutputBuffer` serialized as dict for IPC
5. **Seed management**: `seeds=range(trials)` by default, or accept custom list
6. **Progress**: `tqdm` progress bar showing completed/total trials

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| IPC mechanism | Pickle via `ProcessPoolExecutor` | Simple, built-in, no external deps |
| Per-worker memory | Fresh `Simulation` per trial | Avoids state leakage between trials |
| Output format | Keep `OutputBuffer`; add `.compute_snr(tx_power, noise_bw)` helper | Consistent with existing API |
| Progress reporting | `tqdm` | Standard, good UX for batch jobs |
| Failure handling | Catch exceptions per-trial, report in results | One bad trial shouldn't kill all |

### Risks
- **Memory**: 100 trials × large RIS could blow RAM. Mitigation: stream results
  via generator, discard raw IQ after extracting metrics.
- **Pickle limitations**: Complex numpy arrays in `OutputBuffer` should pickle
  fine, but custom objects (e.g., `RisController`) won't. Solution: workers
  receive scenario dict, not Simulation object.

---

## G3: Channel Sounding Mode (~0.5 week)

**Goal**: Measure the complex channel coefficient between any TX-RX pair by
sending a known pilot signal and computing `h = y / x`.

### API Design

```python
# Direct
h_est = sim.channel_sound(
    tx_node="node_1", rx_node="node_2",
    fc=2.4e9, sample_rate=5880,
    pilot_length=100, pilot_amplitude=1.0,
)

# h_est is a dict:
# {
#   "h_los": complex,          # LOS component
#   "h_ris": complex,          # RIS component (sum of all panels)
#   "h_total": complex,        # Combined channel
#   "path_loss_db": float,     # 20*log10(|h_total|)
#   "phase_deg": float,        # angle(h_total) in degrees
# }

# Sweep: measure channel as RIS phase varies
for phase in np.linspace(0, 2*np.pi, 64):
    sim.ris_set_config("ris_1", uniform_phase_matrix(phase))
    h = sim.channel_sound("tx", "rx", fc=2.4e9)
    results.append(abs(h["h_total"]))
```

### Implementation Steps

1. **`Simulation.channel_sound()`** — Method that:
   - Generates a known pilot sequence (constant `[amplitude, 0]` or Zadoff-Chu)
   - Queues a TX and RX request internally
   - Runs the simulation
   - Computes `h = mean(rx / tx)` over the pilot samples
   - Resets node states so the Simulation can be reused
2. **Decompose into LOS + RIS components** — Optionally run twice:
   once with RIS disabled (h_los), once with RIS enabled (h_total), then
   `h_ris = h_total - h_los`.

### Integration
Builds on existing `free_space_coefficient()` and `total_ris_gain_vectorized()`
— the channel sounding result should match the analytical prediction within
measurement noise.

---

## G4: Web Dashboard (~2 weeks)

**Goal**: Real-time visualization of simulation state via a browser, with
live constellation plots, RIS heatmaps, and node tracking.

### Architecture

```
  Browser ──WebSocket──► FastAPI/Flask ──ZMQ/pipe──► SimulationServer
    │                       │                            │
    │  Renders:             │  Routes:                   │  Ticks every τ
    │  - Constellation      │  - GET /api/state          │  Publishes state
    │  - RIS heatmap        │  - WS /ws/live             │  after each tick
    │  - Room topology      │  - POST /api/tx            │
    │  - Power waterfall    │  - POST /api/rx            │
    │  - Metrics dashboard  │  - POST /api/ris/config    │
```

### Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | FastAPI + `websockets` | Async, modern, auto-generated OpenAPI docs |
| Frontend | Plain HTML/JS with Chart.js + Canvas | No build step, zero npm deps, works offline |
| State push | WebSocket (server→client every tick) | Low latency, no polling |
| Plotting | matplotlib (server-side PNG) or Plotly.js (client-side) | Plotly for interactive, matplotlib for static |
| Auth | None (localhost-only) | This is a research tool, not a production service |

### Pages / Components

1. **Topology View** — Room layout with node positions (updating in real-time
   if mobility is enabled), RIS panel locations
2. **Constellation View** — I/Q scatter plot for each active receiver,
   auto-updating each tick
3. **RIS Heatmap** — Color-grid of RIS element states, updates on reconfiguration
4. **Power Waterfall** — Spectrogram-style view of received power over time
5. **Control Panel** — Buttons/forms to send TX bursts, configure RX,
   set RIS phase matrix
6. **Metrics Dashboard** — Tick rate, avg/max tick time, samples processed,
   memory usage

### Implementation Steps

1. **`ris_sim/web/app.py`** — FastAPI application
2. **`ris_sim/web/static/`** — HTML, JS, CSS (single-page app)
3. **State bridge** — After each tick, serialize `NodeState`, `OutputEntry`
   (latest chunk only, not full history), `RisController` config to JSON
4. **WebSocket protocol** — Server pushes `{"type": "state_update", "data": {...}}`
   after each tick; client sends `{"type": "tx_request", ...}`
5. **CLI integration** — `ris-sim dashboard scenario.json` starts both
   the SimulationServer and the web server

### Risks
- **Tick rate vs rendering**: If the simulation runs at 500+ ticks/sec, pushing
  every tick to the browser will saturate WebSocket. Solution: throttle updates
  to ~20 Hz (every 50ms).
- **Large RIS arrays**: 256×256 RIS heatmap is 65K cells — too many for a
  browser heatmap. Solution: downsample for display, or use PNG rendered
  server-side.

---

## G5: Hardware-in-the-Loop Bridge (~2 weeks)

**Goal**: Connect real SDR hardware (USRP) to the emulator, creating a
mixed environment where some nodes are real radios and others are simulated.

### Architecture — Two Modes

#### Mode A: Emulated Channel, Real Radios

```
  ┌──────────┐         ┌──────────────┐         ┌──────────┐
  │ USRP TX  │──IQ────►│  Emulator    │──IQ────►│ USRP RX  │
  │ (real)   │  UDP    │  (channel +  │  UDP    │ (real)   │
  │          │         │   RIS model) │         │          │
  └──────────┘         └──────────────┘         └──────────┘
```

Real USRP transmits IQ samples via UDP → Emulator applies channel + RIS effects
→ Real USRP receives the impaired samples via UDP.

#### Mode B: Real Channel, Emulated RIS

```
  ┌──────────┐   RF   ┌──────────┐   RF   ┌──────────┐
  │ USRP TX  │───────►│ Real RIS │───────►│ USRP RX  │
  │ (real)   │        │ (hw)     │        │ (real)   │
  └──────────┘        └────┬─────┘        └──────────┘
                           │ control
                     ┌─────▼─────┐
                     │ Emulator  │
                     │ (RIS ctrl)│
                     └───────────┘
```

Real radios + real RIS hardware, but the RIS *controller* runs in the emulator
(useful for testing control algorithms before deploying to real hardware).

### API Design

```python
from ris_sim.hil import HardwareBridge, UsrpNode, EmulatedNode

bridge = HardwareBridge(scenario)

# Register real USRP nodes
bridge.register_tx(UsrpNode(
    id="usrp_tx_1",
    addr="addr=192.168.10.2",
    fc=2.4e9,
    sample_rate=1e6,
    gain=30,
))

bridge.register_rx(UsrpNode(
    id="usrp_rx_1",
    addr="addr=192.168.10.3",
    fc=2.4e9,
    sample_rate=1e6,
    gain=20,
))

# Register emulated nodes
bridge.register_tx(EmulatedNode(id="sim_tx_1", location=[5, 2, 5]))

# Run: each tick reads from USRP RX buffer, applies channel, writes to USRP TX buffer
bridge.run(ticks=1000)
```

### Implementation Steps

1. **`ris_sim/hil/bridge.py`** — `HardwareBridge` class
2. **`ris_sim/hil/usrp_node.py`** — Wrapper around `uhd` Python API:
   - `send(samples)` / `recv(n)` using UHD streamers
   - Buffering + timestamp alignment
3. **`ris_sim/hil/clock.py`** — Timing synchronization:
   - Emulator tick τ maps to real time (wall clock or USRP time)
   - Buffer underrun/overrun detection
4. **Mixed routing** — `HardwareBridge` replaces `Simulation._process_active_nodes`:
   - For emulated TX → emulated RX: use existing channel model
   - For USRP TX → emulated RX: receive real IQ via UHD, apply channel model
   - For emulated TX → USRP RX: compute channel, send IQ via UHD
5. **Dependency**: `uhd` Python package (from Ettus/Official UHD install)

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| UHD binding | `uhd` (official, `pip install uhd`) | Standard, maintained by Ettus/NI |
| Sample transport | UDP via UHD streamers | Matches USRP hardware path |
| Timing model | USRP time-ticks as master clock | Avoids drift between real and simulated |
| Buffer sizing | Configurable, default 2× τ samples | Trade off latency vs underrun protection |
| Error handling | Detect underruns → log warning, insert zeros | Don't crash on transient RF issues |

### Risks
- **UHD driver complexity**: Installing UHD on all platforms is nontrivial.
  Mitigation: make `uhd` an optional extra (`pip install ris-sim[hil]`).
- **Real-time constraints**: Python + ZeroMQ + UHD may not meet hard real-time
  deadlines. Mitigation: use `UHD.set_rx_rate()` / `set_tx_rate()` and large
  buffers to absorb jitter.
- **USRP availability**: Most users won't have hardware. Mitigation: ship a
  `LoopbackBridge` that connects emulated nodes in a loop for testing.

---

## Recommended Implementation Order

```
  G1 (RIS control)    ← Simplest, highest leverage for research
   │
   ├── G3 (sounding)  ← Quick to build on G1 + existing channel model
   │
   ├── G2 (parallel)  ← Enables paper-quality results (SNR CDFs, BER curves)
   │
   ├── G4 (dashboard) ← Big UX improvement, but self-contained
   │
   └── G5 (HIL)       ← Most complex, hardware-dependent, start last
```

G1+G3 can be done together (~1 week). G2 is independent. G4 and G5 are large
and can be separate projects.

---

## Dependency Additions

| Feature | New Dependency | Optional? |
|---------|---------------|-----------|
| G2 (parallel) | `tqdm` | Yes (fallback: no progress bar) |
| G4 (dashboard) | `fastapi`, `uvicorn`, `websockets` | Yes (only needed for web mode) |
| G5 (HIL) | `uhd` | Yes (`[hil]` extra) |

Update `pyproject.toml`:
```toml
[project.optional-dependencies]
hil = ["uhd>=4.0"]
web = ["fastapi>=0.100", "uvicorn>=0.23", "websockets>=12"]
parallel = ["tqdm>=4.65"]
all = ["ris-sim[dev,web,hil,parallel]"]
```

---

## Success Criteria for Phase G

| Feature | Criterion |
|---------|-----------|
| G1 | RIS config can be changed between ticks via both Python API and ZMQ; change takes effect on next tick |
| G2 | 100-trial Monte Carlo with 16×16 RIS completes in <30s on 8 cores; results include SNR CDF |
| G3 | Channel sounding returns h_total within 1% of analytical prediction for LOS-only scenario |
| G4 | Web dashboard renders constellation + topology updating at 10+ fps for a running simulation |
| G5 | Loopback test: emulated TX → USRP TX buffer → USRP RX buffer → emulated RX produces bit-identical output |
