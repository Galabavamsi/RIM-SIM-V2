"""Helpers for turning emulator output JSON into analysis-ready arrays."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

import modules.json_store as store


def load_output(path: str | Path) -> dict[str, Any]:
    return store.load_json(path, default={"outputs": []})


def flatten_iq_blocks(entry: Mapping[str, Any]) -> np.ndarray:
    samples = []
    for block in entry.get("data", []):
        for pair in block:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("Output data must contain [I, Q] pairs.")
            samples.append(complex(float(pair[0]), float(pair[1])))
    return np.asarray(samples, dtype=np.complex128)


def compute_signal_metrics(samples: Sequence[complex], sample_rate: float) -> dict[str, float | int]:
    values = np.asarray(samples, dtype=np.complex128)
    if sample_rate <= 0 or not math.isfinite(float(sample_rate)):
        raise ValueError("sample_rate must be a positive finite number.")

    power = np.abs(values) ** 2
    if len(values) == 0:
        mean_power = 0.0
        peak_power = 0.0
    else:
        mean_power = float(np.mean(power))
        peak_power = float(np.max(power))

    return {
        "num_samples": int(len(values)),
        "duration_s": float(len(values) / float(sample_rate)),
        "mean_power": mean_power,
        "peak_power": peak_power,
        "rms_amplitude": float(math.sqrt(mean_power)),
    }


def summarize_output(output_data: Mapping[str, Any]) -> dict[str, Any]:
    summaries = []
    for index, entry in enumerate(output_data.get("outputs", []), start=1):
        samples = flatten_iq_blocks(entry)
        metrics = compute_signal_metrics(samples, float(entry["sample_rate"]))
        summaries.append(
            {
                "index": index,
                "request_id": entry.get("request_id"),
                "id": entry.get("id"),
                "fc": entry.get("fc"),
                "sample_rate": entry.get("sample_rate"),
                "requested_num_samps": entry.get("num_samps"),
                **metrics,
            }
        )
    return {"num_outputs": len(summaries), "outputs": summaries}


def write_summary(summary: Mapping[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=4), encoding="utf-8")


def _entry_array_name(entry: Mapping[str, Any], index: int) -> str:
    node_id = str(entry.get("id") or "rx").replace("-", "_")
    return f"{node_id}_rx_{index}"


def save_output_npz(output_data: Mapping[str, Any], path: str | Path) -> None:
    arrays = {}
    for index, entry in enumerate(output_data.get("outputs", []), start=1):
        arrays[_entry_array_name(entry, index)] = flatten_iq_blocks(entry)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(str(target), **arrays)


def load_npz_arrays(path: str | Path) -> dict[str, np.ndarray]:
    with np.load(path) as data:
        return {name: data[name] for name in data.files}
