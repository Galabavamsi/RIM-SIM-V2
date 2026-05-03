"""Scenario helpers for repeatable emulator examples."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import modules.json_store as store
import modules.validation as val


def load_scenario(path: str | Path) -> dict[str, Any]:
    return store.load_json(path)


def write_scenario(scenario_data: Mapping[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(scenario_data, indent=4), encoding="utf-8")


def _runtime_node(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": node["id"],
        "location": list(node["location"]),
        "mobility": dict(node.get("mobility", {"type": "static", "speed": 0.0})),
        "request": {},
        "current_mode": "idle",
        "fc": -1,
        "sample_rate": -1,
        "next_update": -1,
        "req_time": 0,
        "current_counter": -1,
        "data": [],
        "request_id": None,
        "remaining_samples": 0,
    }


def engine_config_from_scenario(scenario_data: Mapping[str, Any]) -> dict[str, Any]:
    room_data = {"room": dict(scenario_data["room"])}
    ris_data = {"ris": [dict(entry) for entry in scenario_data.get("ris", [])]}
    nodes_data = {"nodes": [_runtime_node(node) for node in scenario_data.get("nodes", [])]}
    val.validate_startup_configs(
        room_data=room_data, ris_data=ris_data, nodes_data=nodes_data
    )
    return {"room": room_data, "ris": ris_data, "nodes": nodes_data}


def apply_scenario(scenario_data: Mapping[str, Any], config_dir: str | Path) -> None:
    config_path = Path(config_dir)
    config = engine_config_from_scenario(scenario_data)
    store.write_json_atomic(config_path / "room.json", config["room"])
    store.write_json_atomic(config_path / "ris.json", config["ris"])
    store.write_json_atomic(config_path / "nodes.json", config["nodes"])
    store.write_json_atomic(config_path / "output.json", {"outputs": []})


def _bpsk_bits_waveform(spec: Mapping[str, Any]) -> list[list[float]]:
    bits = spec.get("bits", [])
    if not isinstance(bits, Sequence) or isinstance(bits, (str, bytes)) or not bits:
        raise ValueError("bpsk_bits waveform requires a non-empty bits list.")
    amplitude = float(spec.get("amplitude", 1.0))
    samples_per_symbol = int(spec.get("samples_per_symbol", 1))
    if samples_per_symbol < 1:
        raise ValueError("samples_per_symbol must be >= 1.")

    samples = []
    for bit in bits:
        symbol = amplitude if int(bit) == 1 else -amplitude
        samples.extend([[symbol, 0.0] for _ in range(samples_per_symbol)])
    return samples


def waveform_to_iq(waveform: Mapping[str, Any]) -> list[list[float]]:
    kind = waveform.get("kind")
    if kind == "iq_pairs":
        return [list(pair) for pair in waveform.get("samples", [])]
    if kind == "bpsk_bits":
        return _bpsk_bits_waveform(waveform)
    raise ValueError(f"Unsupported waveform kind: {kind!r}.")


def _queue_tx_request(node: dict[str, Any], traffic: Mapping[str, Any]) -> None:
    streams = val.normalize_transmit_data(waveform_to_iq(traffic["waveform"]))
    sample_rate = float(traffic["sample_rate"])
    val.validate_transmit_request(sample_rate, streams, tau=float(traffic.get("tau", 0.002)))
    node["request"] = {
        "request_id": str(uuid.uuid4()),
        "mode": "transmit",
        "fc": traffic["fc"],
        "sample_rate": sample_rate,
        "data": streams,
    }


def _queue_rx_request(node: dict[str, Any], traffic: Mapping[str, Any]) -> None:
    sample_rate = float(traffic["sample_rate"])
    num_samps = int(traffic["num_samps"])
    val.validate_receive_request(sample_rate, num_samps, tau=float(traffic.get("tau", 0.002)))
    node["request"] = {
        "request_id": str(uuid.uuid4()),
        "mode": "receive",
        "fc": traffic["fc"],
        "sample_rate": sample_rate,
        "num_samps": num_samps,
    }


def queue_traffic_requests(scenario_data: Mapping[str, Any], config_dir: str | Path) -> None:
    config_path = Path(config_dir)
    traffic_items = scenario_data.get("traffic", [])

    def mutate(nodes_data):
        nodes_by_id = {node["id"]: node for node in nodes_data["nodes"]}
        for traffic in traffic_items:
            node_id = traffic["node_id"]
            if node_id not in nodes_by_id:
                raise ValueError(f"Traffic references unknown node_id {node_id!r}.")
            node = nodes_by_id[node_id]
            mode = traffic["mode"]
            if mode == "transmit":
                _queue_tx_request(node, traffic)
            elif mode == "receive":
                _queue_rx_request(node, traffic)
            else:
                raise ValueError(f"Unsupported traffic mode: {mode!r}.")
        return nodes_data

    store.update_json_file(config_path / "nodes.json", mutate)


def prepare_scenario_run(scenario_data: Mapping[str, Any], config_dir: str | Path) -> None:
    apply_scenario(scenario_data, config_dir)
    queue_traffic_requests(scenario_data, config_dir)
