"""CLI entry points for the RIS emulator.

Commands:
    serve    Start the emulation server (ZeroMQ IPC).
    run      Run a scenario directly (no server, just run-and-export).
    tx       Send a TX request to a running server.
    rx       Send an RX request to a running server and save results.
    status   Query server status.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from ris_sim.core.server import SimulationServer
from ris_sim.io.transport import DEFAULT_SERVER_ADDR, ClientTransport


def _cmd_serve(args: argparse.Namespace) -> None:
    scenario_path = Path(args.scenario).resolve()
    if not scenario_path.exists():
        print(f"Error: scenario file not found: {scenario_path}")
        sys.exit(1)

    server = SimulationServer.from_scenario_file(
        str(scenario_path),
        seed=args.seed,
        bind_addr=args.bind,
    )
    server.serve()


def _cmd_run(args: argparse.Namespace) -> None:
    from ris_sim.core.engine import Simulation
    from ris_sim.modules import json_store, results as res

    scenario_path = Path(args.scenario).resolve()
    with open(scenario_path) as f:
        scenario_data = json.load(f)

    sim = Simulation.from_scenario(scenario_data, seed=args.seed)

    # Queue traffic from scenario
    for traffic in scenario_data.get("traffic", []):
        node_id = traffic["node_id"]
        mode = traffic["mode"]
        if mode == "transmit":
            # Generate IQ from waveform
            wf = traffic["waveform"]
            iq_data = _waveform_to_iq(wf)
            sim.queue_tx(node_id, iq_data, traffic["fc"], traffic["sample_rate"])
        elif mode == "receive":
            sim.queue_rx(node_id, int(traffic["num_samps"]), traffic["fc"], traffic["sample_rate"])

    output = sim.run()
    print(f"Simulation complete: {sim.counter} ticks in {sim.elapsed:.3f}s")

    # Export
    out_dir = Path(args.output).resolve() if args.output else Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    output.save_npz(out_dir / "result.npz")
    json_store.write_json_atomic(out_dir / "output.json", output.to_json_compatible())
    json_store.write_json_atomic(out_dir / "scenario.json", scenario_data)
    summary = res.summarize_output(output.to_json_compatible())
    res.write_summary(summary, out_dir / "summary.json")
    print(f"Results exported to {out_dir}")


def _waveform_to_iq(wf: dict) -> list[list[float]]:
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
    raise ValueError(f"Unknown waveform kind: {kind}")


def _cmd_tx(args: argparse.Namespace) -> None:
    from ris_sim.radio.api import send_to_simulator

    if args.iq_file:
        data = np.load(args.iq_file)
    else:
        # Generate a simple BPSK burst
        bits = [0, 0, 1, 1, 0, 1] * 5
        data = _waveform_to_iq({"kind": "bpsk_bits", "bits": bits, "amplitude": 0.1, "samples_per_symbol": 10})

    rid = send_to_simulator(
        data, args.fc, args.sample_rate, args.node,
        tau=args.tau, server_addr=args.server,
    )
    print(f"TX request queued: {rid}")


def _cmd_rx(args: argparse.Namespace) -> None:
    from ris_sim.radio.api import receive_from_simulator

    result = receive_from_simulator(
        args.samples, args.fc, args.sample_rate, args.node,
        tau=args.tau, server_addr=args.server, timeout=args.timeout,
    )

    out_path = Path(args.output) if args.output else Path(f"rx_{args.node}.npy")
    np.save(out_path, result)
    print(f"Received {len(result)} samples -> {out_path}")


def _cmd_status(args: argparse.Namespace) -> None:
    transport = ClientTransport(args.server)
    response = transport.request({"cmd": "status"}, timeout_ms=5000)
    transport.close()
    print(json.dumps(response, indent=2))


def _cmd_stop(args: argparse.Namespace) -> None:
    transport = ClientTransport(args.server)
    response = transport.request({"cmd": "stop"}, timeout_ms=5000)
    transport.close()
    print(response.get("message", "Stop command sent."))


def _cmd_dashboard(args: argparse.Namespace) -> None:
    """Start the web dashboard."""
    import uvicorn
    from ris_sim.web.app import app

    print(f"RIS-SIM Dashboard: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def _cmd_ris_config(args: argparse.Namespace) -> None:
    """Update a RIS panel configuration."""
    import json

    if args.matrix_file:
        with open(args.matrix_file) as f:
            matrix = json.load(f)
    elif args.uniform is not None:
        # Generate uniform matrix from a single value
        # Need to know array_size — query server status first
        transport = ClientTransport(args.server)
        transport.request({"cmd": "status"}, timeout_ms=5000)
        transport.close()
        # Find array_size from scenario info — approximate from ris_count
        # For now, use a reasonable default
        size = 16
        matrix = [[float(args.uniform)] * size] * size
    else:
        print("Error: specify --matrix-file or --uniform")
        return

    from ris_sim.radio.api import ris_set_config
    ris_set_config(args.ris_id, matrix, server_addr=args.server)
    print(f"RIS {args.ris_id!r} config queued.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RIS-SIM: Open Emulator for Smart Radio Environments",
        prog="ris-sim",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── serve ──
    p_serve = sub.add_parser("serve", help="Start the emulation server")
    p_serve.add_argument("scenario", help="Path to scenario JSON file")
    p_serve.add_argument("--bind", default=DEFAULT_SERVER_ADDR, help="ZeroMQ bind address")
    p_serve.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    p_serve.set_defaults(func=_cmd_serve)

    # ── run ──
    p_run = sub.add_parser("run", help="Run a scenario directly (no server)")
    p_run.add_argument("scenario", help="Path to scenario JSON file")
    p_run.add_argument("--output", "-o", default=None, help="Output directory")
    p_run.add_argument("--seed", type=int, default=None, help="Random seed")
    p_run.set_defaults(func=_cmd_run)

    # ── tx ──
    p_tx = sub.add_parser("tx", help="Send a TX request to a running server")
    p_tx.add_argument("--node", required=True, help="Target node ID")
    p_tx.add_argument("--fc", type=float, required=True, help="Center frequency (Hz)")
    p_tx.add_argument("--sample-rate", type=float, required=True, help="Sample rate (Hz)")
    p_tx.add_argument("--iq-file", default=None, help="NPY file with complex IQ samples")
    p_tx.add_argument("--server", default=DEFAULT_SERVER_ADDR, help="Server address")
    p_tx.add_argument("--tau", type=float, default=0.002, help="Tick duration (s)")
    p_tx.set_defaults(func=_cmd_tx)

    # ── rx ──
    p_rx = sub.add_parser("rx", help="Send an RX request to a running server")
    p_rx.add_argument("--node", required=True, help="Target node ID")
    p_rx.add_argument("--fc", type=float, required=True, help="Center frequency (Hz)")
    p_rx.add_argument("--sample-rate", type=float, required=True, help="Sample rate (Hz)")
    p_rx.add_argument("--samples", type=int, required=True, help="Number of IQ samples")
    p_rx.add_argument("--output", "-o", default=None, help="Output NPY file path")
    p_rx.add_argument("--server", default=DEFAULT_SERVER_ADDR, help="Server address")
    p_rx.add_argument("--tau", type=float, default=0.002, help="Tick duration (s)")
    p_rx.add_argument("--timeout", type=float, default=30.0, help="Timeout (s)")
    p_rx.set_defaults(func=_cmd_rx)

    # ── status ──
    p_status = sub.add_parser("status", help="Query server status")
    p_status.add_argument("--server", default=DEFAULT_SERVER_ADDR, help="Server address")
    p_status.set_defaults(func=_cmd_status)

    # ── stop ──
    p_stop = sub.add_parser("stop", help="Stop a running server")
    p_stop.add_argument("--server", default=DEFAULT_SERVER_ADDR, help="Server address")
    p_stop.set_defaults(func=_cmd_stop)

    # ── ris-config ──
    p_ris = sub.add_parser("ris-config", help="Update RIS panel configuration")
    p_ris.add_argument("ris_id", help="RIS panel ID (e.g. ris_1)")
    p_ris.add_argument("--matrix-file", default=None, help="JSON file with (M,N) matrix")
    p_ris.add_argument("--uniform", type=float, default=None, help="Set all elements to this state value")
    p_ris.add_argument("--server", default=DEFAULT_SERVER_ADDR, help="Server address")
    p_ris.set_defaults(func=_cmd_ris_config)

    # ── dashboard ──
    p_dash = sub.add_parser("dashboard", help="Start the web dashboard")
    p_dash.add_argument("--port", type=int, default=8080, help="Server port")
    p_dash.add_argument("--host", default="127.0.0.1", help="Bind address")
    p_dash.set_defaults(func=_cmd_dashboard)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
