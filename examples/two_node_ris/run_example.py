"""Run the static two-node RIS example using the new Simulation API."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np

# Allow running from repo root with old-style imports
_EXAMPLE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _EXAMPLE_DIR.parents[1]
_RIS_ROOT = _REPO_ROOT / "ris_sim"

import sys

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ris_sim.core.engine import Simulation
from ris_sim.modules import json_store
from ris_sim.modules import plotting
from ris_sim.modules import results as res
from ris_sim.modules import scenario


def _bpsk_bits_to_iq(bits: list[int], amplitude: float = 0.1, samples_per_symbol: int = 10) -> list[list[float]]:
    """Generate IQ samples from BPSK bitstream."""
    samples = []
    for bit in bits:
        symbol = amplitude if int(bit) == 1 else -amplitude
        samples.extend([[symbol, 0.0] for _ in range(samples_per_symbol)])
    return samples


def run_example(scenario_path: Path, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = run_dir / "plots"

    scenario_data = scenario.load_scenario(scenario_path)

    # Create simulation with in-memory state (no per-tick JSON I/O)
    sim = Simulation.from_scenario(scenario_data)

    # Queue traffic from scenario
    for traffic in scenario_data.get("traffic", []):
        node_id = traffic["node_id"]
        mode = traffic["mode"]
        if mode == "transmit":
            wf = traffic["waveform"]
            if wf["kind"] == "bpsk_bits":
                iq_data = _bpsk_bits_to_iq(
                    wf["bits"],
                    amplitude=float(wf.get("amplitude", 0.1)),
                    samples_per_symbol=int(wf.get("samples_per_symbol", 10)),
                )
            else:
                raise ValueError(f"Unknown waveform kind: {wf['kind']}")
            sim.queue_tx(node_id, iq_data, traffic["fc"], traffic["sample_rate"])
        elif mode == "receive":
            sim.queue_rx(node_id, int(traffic["num_samps"]), traffic["fc"], traffic["sample_rate"])

    # Run the simulation
    output = sim.run()

    # Export results
    output.save_npz(run_dir / "result.npz")
    output_compat = output.to_json_compatible()
    json_store.write_json_atomic(run_dir / "output.json", output_compat)
    json_store.write_json_atomic(run_dir / "scenario.json", scenario_data)

    # Summary
    summary = res.summarize_output(output_compat)
    res.write_summary(summary, run_dir / "summary.json")

    # Plots
    room_data = {"room": scenario_data["room"]}
    nodes_data = {"nodes": scenario_data["nodes"]}
    ris_data = {"ris": scenario_data.get("ris", [])}

    plotting.plot_room_topology(room_data, nodes_data, ris_data, plots_dir / "room_topology.png")
    for ris in ris_data.get("ris", []):
        plotting.plot_ris_heatmap(ris, plots_dir / f"{ris.get('id', 'ris')}_heatmap.png")

    for index, entry in enumerate(output_compat.get("outputs", []), start=1):
        samples_arr = res.flatten_iq_blocks(entry)
        sample_rate = float(entry["sample_rate"])
        stem = f"{entry.get('id', 'rx')}_output_{index}"
        plotting.plot_iq_timeseries(samples_arr, sample_rate, plots_dir / f"{stem}_iq.png")
        plotting.plot_constellation(samples_arr, plots_dir / f"{stem}_constellation.png")
        plotting.plot_power(samples_arr, sample_rate, plots_dir / f"{stem}_power.png")

    print(f"Simulation time: {sim.elapsed:.3f}s, ticks: {sim.counter}")
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=_EXAMPLE_DIR / "scenario.json",
        help="Path to the example scenario JSON.",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=_EXAMPLE_DIR / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S"),
        help="Directory where result artifacts should be written.",
    )
    args = parser.parse_args()

    run_dir = run_example(args.scenario.resolve(), args.run_dir.resolve())
    print(f"Example complete. Artifacts written to: {run_dir}")


if __name__ == "__main__":
    main()
