# RIS-SIM v2 — Open Emulator for Smart Radio Environments

[![Tests](https://img.shields.io/badge/tests-103%20passed-brightgreen)](https://github.com/Galabavamsi/RIM-SIM-V2/actions)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://pypi.org/project/ris-sim/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/badge/ruff-0%20errors-0)](https://github.com/astral-sh/ruff)
[![Mypy](https://img.shields.io/badge/mypy-0%20errors-0)](https://mypy-lang.org/)

A production-grade software emulator for **Reconfigurable Intelligent Surface (RIS)** assisted wireless communication systems. Replicates SDR behavior and RIS effects at the baseband level — no physical hardware required.

```bash
pip install ris-sim
ris-sim dashboard
```

---

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [Python API](#python-api)
  - [CLI Commands](#cli-commands)
  - [Web Dashboard](#web-dashboard)
  - [ZeroMQ Server/Client](#zeromq-serverclient)
  - [Parallel Monte Carlo](#parallel-monte-carlo)
- [Scenario Format](#scenario-format)
- [Signal Models](#signal-models)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)
- [Citation](#citation)

---

## Architecture

```mermaid
graph TB
    subgraph Consumers["Entry Points"]
        CLI["CLI<br/>tx / rx / run / serve / dashboard"]
        PYAPI["Python API<br/>Simulation class"]
        ZMQ["ZMQ Server<br/>machine-to-machine"]
        WEB["Web Dashboard<br/>human-in-the-loop"]
        MC["Parallel MC<br/>batch studies"]
    end

    subgraph Core["Core Engine"]
        SIM["Simulation<br/>discrete-time tick loop"]
        CH["Channel Models<br/>LOS / RIS / Fading / Noise / OFDM"]
        RADIO["RF Impairments<br/>CFO / Phase Noise / IQ Imbalance / SFO / PA"]
        MOB["Mobility<br/>5 models"]
    end

    subgraph Infra["Infrastructure"]
        LOG["Logging<br/>structured key=value"]
        MET["Metrics<br/>per-tick timing"]
        SEED["SeedSequence<br/>deterministic RNG"]
        OUT["OutputBuffer<br/>NPZ streaming"]
    end

    CLI --> SIM
    PYAPI --> SIM
    ZMQ --> SIM
    WEB --> SIM
    MC --> SIM
    SIM --> CH
    SIM --> RADIO
    SIM --> MOB
    SIM --> LOG
    SIM --> MET
    SIM --> SEED
    SIM --> OUT
```

### Signal Processing Pipeline

```mermaid
graph LR
    TX[TX IQ Samples] --> TX_IMP[TX Impairments<br/>SFO → IQ Imb → PA]
    TX_IMP --> CHAN[Channel<br/>h = h_los + Σ h_ris + fading]
    CHAN --> RX_IMP[RX Impairments<br/>CFO → PN → IQ Imb → SFO]
    RX_IMP --> NOISE[AWGN<br/>k·T·B·NF]
    NOISE --> RX[RX IQ Samples]
```

### Tick Loop

```mermaid
graph TB
    START([Start Tick]) --> RIS[Update RIS Config]
    RIS --> MOB[Advance Mobility]
    MOB --> ASSIGN[Assign Queued Requests]
    ASSIGN --> COLLECT[Collect TX Chunks]
    COLLECT --> PROCESS[Process RX: Channel + Impairments + Noise]
    PROCESS --> IDLE{All Nodes Idle?}
    IDLE -->|No| START
    IDLE -->|Yes| DONE([End Simulation])
```

---

## Quick Start

```bash
# Install
pip install ris-sim

# Run a scenario directly
ris-sim run examples/two_node_ris/scenario.json

# Start the web dashboard (configure everything in browser)
ris-sim dashboard

# Or use python -m
python -m ris_sim.cli.main dashboard
```

Open `http://127.0.0.1:8080` — select topology + signal from dropdowns, press **Start**.

---

## Installation

```bash
# From PyPI (when published)
pip install ris-sim

# From source
git clone https://github.com/Galabavamsi/RIM-SIM-V2.git
cd RIM-SIM-V2
pip install -e .

# With optional dependencies
pip install -e ".[dev]"    # pytest, ruff, mypy
pip install -e ".[web]"    # fastapi, uvicorn (dashboard)
```

**Requirements**: Python 3.10+, numpy, matplotlib, pyzmq. See `pyproject.toml` for full list.

---

## Usage

### Python API

```python
from ris_sim.core.engine import Simulation
import numpy as np

# Create simulation from a scenario dict
sim = Simulation.from_scenario_file("scenario.json")

# Or build programmatically
sim = Simulation.from_scenario({
    "room": {"length": 10, "width": 10, "height": 10},
    "ris": [],
    "nodes": [
        {"id": "tx", "location": [1, 5, 5]},
        {"id": "rx", "location": [9, 5, 5]},
    ],
    "channel": {"enable_noise": False},
})

# Queue TX (IQ samples) and RX (sample count)
sim.queue_tx("tx", [[1.0, 0.0] for _ in range(100)], fc=2.4e9, sample_rate=5880)
sim.queue_rx("rx", num_samps=100, fc=2.4e9, sample_rate=5880)

# Run with progress bar
output = sim.run(show_progress=True)

# Access results
samples = output.entries[0].flatten_iq()  # complex ndarray
output.save_npz("results.npz")

# Metrics
print(sim.metrics.report())
```

### Channel Sounding

```python
# Measure complex channel coefficients between two nodes
result = sim.channel_sound("tx", "rx", fc=2.4e9, pilot_length=200)
print(f"h_los:  {result['h_los']}")
print(f"h_ris:  {result['h_ris']}")
print(f"h_total: {result['h_total']}")
print(f"Path loss: {result['path_loss_db']} dB")
print(f"Phase: {result['phase_deg']} deg")
```

### RF Impairments

```python
# Configure per-node RF impairments in the scenario
scenario = {
    "nodes": [{
        "id": "rx",
        "rf": {
            "cfo_hz": 150.0,              # Carrier Frequency Offset
            "phase_noise_dbc_hz": -85.0,   # Phase noise
            "amplitude_imbalance_db": 0.5, # IQ gain mismatch
            "phase_imbalance_deg": 2.0,    # IQ phase skew
            "sfo_ppm": 5.0,                # Sample Frequency Offset
            "pa_model": {"type": "rapp", "p_sat_db": 30.0}  # PA nonlinearity
        }
    }],
    "channel": {
        "enable_noise": True,
        "noise_figure_db": 5.0,           # Receiver noise figure
        "small_scale": {
            "enabled": True,
            "model": "rayleigh",          # or "rician"
            "max_doppler_hz": 50.0
        }
    }
}
```

### Live RIS Control

```python
# Reconfigure RIS mid-simulation
sim.ris_set_config("ris_1", np.zeros((8, 8)))  # disable RIS
sim.tick()  # next tick uses new config

sim.ris_set_config("ris_1", np.ones((8, 8)))   # re-enable (all ones)
sim.tick()
```

### CLI Commands

```bash
# Direct simulation (run-and-export)
ris-sim run scenario.json -o results/

# Server mode (accepts ZMQ requests from clients)
ris-sim serve scenario.json --bind tcp://127.0.0.1:5555

# Client: send TX
ris-sim tx --node node_1 --fc 2.4e9 --sample-rate 5880

# Client: receive RX (blocks until data ready)
ris-sim rx --node node_2 --fc 2.4e9 --sample-rate 5880 --samples 120 -o rx.npy

# Query server status
ris-sim status

# Update RIS config on running server
ris-sim ris-config ris_1 --uniform 0.5

# Stop server
ris-sim stop

# Web dashboard
ris-sim dashboard --port 8080
```

### Web Dashboard

```bash
ris-sim dashboard
```

Opens at `http://127.0.0.1:8080` with 4 tabs:

| Tab | Content |
|-----|---------|
| **Configuration** | Two-column JSON editor (Room, Nodes, RIS, Traffic, Channel). Independent topology + signal dropdowns with pre-built templates. |
| **Room Topology** | Interactive canvas — click to add nodes, drag to reposition, color-coded by mode. |
| **Live View** | 2×2 grid: Constellation (I/Q), IQ Time Series, Received Power, RIS Heatmap. Updates during simulation. |
| **Results** | Final constellation, Channel Analysis bar chart (LOS/RIS/Total/Boost), FFT spectrum, Room signal heatmap, Metrics table. |

### ZeroMQ Server/Client

```python
from ris_sim.radio.api import send_to_simulator, receive_from_simulator

# These connect to a running `ris-sim serve` instance
send_to_simulator(iq_data, fc=2.4e9, sample_rate=5880, node_id="node_1")
result = receive_from_simulator(120, fc=2.4e9, sample_rate=5880, node_id="node_2")
# result is a complex ndarray
```

### Parallel Monte Carlo

```python
from ris_sim.parallel import parallel_run, MonteCarloResult

mc = MonteCarloResult()
for output, seed in parallel_run(scenario, trials=100, workers=8, show_progress=True):
    snr = compute_snr_from_output(output["outputs"][0])
    mc.record_snr(snr)

print(mc.summary())
# Monte Carlo: 100 trials (0 errors)
#   SNR mean:    12.45 dB
#   SNR median:  11.93 dB
#   SNR p10-p90: 8.2 - 16.1 dB

mc.plot_snr_cdf("snr_cdf.png")
```

---

## Scenario Format

```json
{
    "room": {"length": 10.0, "width": 10.0, "height": 10.0},
    "ris": [{
        "id": "ris_1",
        "fc": 2400000000.0,
        "type": "static",
        "plane": 5,
        "location": [0.0, 5.0, 5.0],
        "unit_cell_m_length": 0.05,
        "unit_cell_n_length": 0.05,
        "unit_cell_gap": 0.01,
        "array_size": [8, 8],
        "phase_response": {"1": [0.707, 0.707]},
        "configuration_matrix": [[1,1,1,1,1,1,1,1], ...]
    }],
    "nodes": [
        {
            "id": "TX",
            "location": [2.0, 4.0, 5.0],
            "mobility": {"type": "static", "speed": 0.0},
            "rf": {"cfo_hz": 0.0}
        },
        {
            "id": "RX",
            "location": [2.0, 6.0, 5.0],
            "mobility": {"type": "static", "speed": 0.0},
            "rf": {"cfo_hz": 150.0}
        }
    ],
    "channel": {
        "enable_noise": true,
        "noise_figure_db": 5.0,
        "temperature_k": 290.0,
        "small_scale": {
            "enabled": false,
            "model": "rayleigh",
            "max_doppler_hz": 50.0,
            "k_factor_db": 10.0
        }
    },
    "traffic": [
        {
            "mode": "transmit",
            "node_id": "TX",
            "fc": 2400000000.0,
            "sample_rate": 5880.0,
            "waveform": {
                "kind": "bpsk_bits",
                "bits": [0,0,1,1,0,1,1,0],
                "amplitude": 0.1,
                "samples_per_symbol": 10
            }
        },
        {
            "mode": "receive",
            "node_id": "RX",
            "fc": 2400000000.0,
            "sample_rate": 5880.0,
            "num_samps": 80
        }
    ]
}
```

### Waveform Types

| Kind | Description | Fields |
|------|-------------|--------|
| `bpsk_bits` | BPSK modulated from bitstream | `bits`, `amplitude`, `samples_per_symbol` |
| `iq_pairs` | Raw [I, Q] sample pairs | `samples` — list of `[real, imag]` |

### Mobility Models

| Type | Parameters |
|------|-----------|
| `static` | `speed: 0` |
| `random_walk` | `speed` (m/s) |
| `random_waypoint` | `speed` (m/s) |
| `random_direction` | `speed` (m/s) |
| `gauss_markov` | `speed`, `alpha`, `mean_speed`, `mean_angle` |

---

## Signal Models

### Channel

| Component | Description |
|-----------|-------------|
| **LOS** | Free-space path loss: `h = λ/(4πd) × exp(-j2πd/λ)` |
| **RIS** | Per-element cascaded: `Σ b_n × √(cosθ_i·cosθ_r) × h_in × h_out` |
| **Fading** | Rayleigh / Rician with AR(1) time correlation, configurable Doppler |
| **Noise** | Thermal AWGN: `σ² = k·T·B·NF / 2` per I/Q component |

### Impairments

| Impairment | Model | Parameter |
|-----------|-------|-----------|
| **CFO** | Rotating phasor: `exp(j·2π·cfo·t)` | `cfo_hz` |
| **Phase Noise** | Wiener process | `phase_noise_dbc_hz` |
| **IQ Imbalance** | Gain: `I'=I×√g, Q'=Q/√g + I×sin(φ)` | `amplitude_imbalance_db`, `phase_imbalance_deg` |
| **SFO** | Linear resampling | `sfo_ppm` |
| **PA** | Rapp model: `A_out = A_in×G / (1+(A_in×G/A_sat)^(2p))^(1/(2p))` | `pa_model` |

### OFDM

```python
from ris_sim.radio.ofdm import ofdm_modulate, ofdm_demodulate

# Modulate
tx_samples = ofdm_modulate(symbols, n_subcarriers=64, cp_len=16)

# ...channel...

# Demodulate + estimate + equalize
rx_symbols = ofdm_demodulate(rx_samples, n_subcarriers=64, cp_len=16)
h_est = ofdm_ofdm_channel_estimate(rx_symbols, pilots, pilot_indices, 64)
equalized = ofdm_equalize(rx_symbols, h_est)
```

---

## Project Structure

```
RIM-SIM-V2/
├── pyproject.toml              # Package config, dependencies, CLI entry point
├── Dockerfile                  # Docker build
├── README.md
├── .gitignore
├── .github/workflows/ci.yml    # CI: 3 OS × 3 Python
│
├── ris_sim/
│   ├── __init__.py
│   ├── core/
│   │   ├── engine.py           # Simulation class (main entry)
│   │   ├── state.py            # NodeState, RisController, OutputBuffer
│   │   ├── server.py           # SimulationServer (ZMQ IPC)
│   │   ├── random.py           # SeedSequence (deterministic RNG)
│   │   ├── logging.py          # Structured logging
│   │   └── metrics.py          # Per-tick timing instrumentation
│   │
│   ├── channel/
│   │   ├── noise.py            # AWGN (thermal + noise figure)
│   │   └── fading.py           # Rayleigh, Rician (AR1)
│   │
│   ├── radio/
│   │   ├── api.py              # SDR-like client API
│   │   ├── impairments.py      # CFO, PN, IQ, SFO, PA
│   │   └── ofdm.py             # OFDM mod/demod, channel estimation
│   │
│   ├── io/
│   │   └── transport.py        # ZeroMQ transport layer
│   │
│   ├── parallel/               # Monte Carlo execution
│   │   ├── __init__.py         # parallel_run()
│   │   ├── worker.py           # Per-trial subprocess
│   │   └── result.py           # MonteCarloResult + CDF plotting
│   │
│   ├── web/                    # Dashboard
│   │   ├── app.py              # FastAPI app
│   │   ├── session.py          # DashboardSession
│   │   ├── static/index.html   # Frontend (single-file SPA)
│   │   └── templates/          # 10 pre-built scenario templates
│   │
│   ├── modules/                # Legacy modules (kept for compat)
│   │   ├── channel_functions.py
│   │   ├── mobility_functions.py
│   │   ├── simulator_functions.py
│   │   ├── validation.py
│   │   ├── json_store.py
│   │   ├── scenario.py
│   │   ├── results.py
│   │   └── plotting.py
│   │
│   ├── cli/
│   │   └── main.py             # CLI entry point (serve, run, tx, rx, dashboard, ...)
│   │
│   ├── config/                 # Default JSON configs
│   └── tests/
│       ├── test_engine.py      # 10 tests
│       ├── test_channel_model.py
│       ├── test_validation.py
│       ├── test_server.py      # 5 tests
│       ├── test_signal_model.py # 21 analytical validation tests
│       ├── test_parallel.py    # 12 tests
│       ├── test_phase_g.py     # 8 tests (RIS control + channel sounding)
│       ├── test_dashboard.py   # 10 tests
│       ├── test_golden.py      # 10 tests (regression + edge cases)
│       ├── test_json_store.py
│       ├── test_plotting.py
│       ├── test_results.py
│       ├── test_scenario.py
│       └── golden/             # Reference output for regression
│
├── examples/
│   └── two_node_ris/           # Self-contained example
│       ├── run_example.py
│       └── scenario.json
│
└── scenarios/                  # Fixture library
    ├── edge_cases/
    └── rf_impairments/
```

---

## Testing

```bash
# Run all 103 tests
python -m pytest ris_sim/tests -v

# Run with coverage
pip install -e ".[dev]"
python -m pytest ris_sim/tests --cov=ris_sim

# Golden regression (bit-identical output with fixed seed)
python -m pytest ris_sim/tests/test_golden.py -v

# Lint + typecheck
python -m ruff check ris_sim
python -m mypy ris_sim
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Install dev dependencies: `pip install -e ".[dev]"`
4. Make changes, add tests
5. Run `python -m pytest ris_sim/tests -v` — all 103 must pass
6. Run `python -m ruff check ris_sim` — must be 0 errors
7. Submit a pull request

### Adding a new channel model
Add a file to `ris_sim/channel/`, import it in `engine.py`, and add a flag in the scenario `channel` config. No engine changes needed for the tick loop.

### Adding a new mobility model
Add to `ris_sim/modules/mobility_functions.py`, register the type string in `validation.py:VALID_MOBILITY_TYPES`.

---

## Citation

If you use this emulator in your research, please cite:

```bibtex
@inproceedings{ris-sim-v2,
  title     = {An Open Emulator for Smart Radio Environments},
  booktitle = {IEEE ANTS 2025},
  year      = {2025},
  note      = {Software available at https://github.com/Galabavamsi/RIM-SIM-V2}
}
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
