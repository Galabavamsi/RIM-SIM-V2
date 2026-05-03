"""Per-trial worker function for parallel execution.

Runs in a subprocess via :class:`concurrent.futures.ProcessPoolExecutor`.
Receives a scenario dict, instantiates a Simulation, runs it, and returns
the output as a JSON-serializable dict.
"""

from __future__ import annotations

from typing import Any

from ris_sim.core.engine import Simulation


def _run_single_trial(scenario: dict[str, Any], seed: int) -> dict[str, Any]:
    sim = Simulation.from_scenario(scenario, seed=seed)

    for traffic in scenario.get("traffic", []):
        node_id = traffic["node_id"]
        mode = traffic["mode"]
        if mode == "transmit":
            wf = traffic.get("waveform", {})
            iq_data = _waveform_to_iq(wf)
            sim.queue_tx(
                node_id, iq_data,
                fc=float(traffic["fc"]),
                sample_rate=float(traffic["sample_rate"]),
                tau=float(traffic.get("tau", sim.tau)),
            )
        elif mode == "receive":
            sim.queue_rx(
                node_id,
                num_samps=int(traffic["num_samps"]),
                fc=float(traffic["fc"]),
                sample_rate=float(traffic["sample_rate"]),
                tau=float(traffic.get("tau", sim.tau)),
            )

    output = sim.run()
    return output.to_json_compatible()


def _waveform_to_iq(wf: dict[str, Any]) -> list[list[float]]:
    kind = wf.get("kind", "iq_pairs")
    if kind == "iq_pairs":
        return [list(p) for p in wf.get("samples", [])]
    if kind == "bpsk_bits":
        bits = wf.get("bits", [])
        amp = float(wf.get("amplitude", 0.1))
        spp = int(wf.get("samples_per_symbol", 10))
        samples = []
        for bit in bits:
            symbol = amp if int(bit) == 1 else -amp
            samples.extend([[symbol, 0.0] for _ in range(spp)])
        return samples
    raise ValueError(f"Unknown waveform kind: {kind!r}")
