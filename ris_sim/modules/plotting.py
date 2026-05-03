"""Plotting helpers for RIS emulator scenarios and outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def _save(fig, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(target, dpi=160)
    plt.close(fig)


def _samples_array(samples: Sequence[complex]) -> np.ndarray:
    return np.asarray(samples, dtype=np.complex128)


def plot_room_topology(
    room_data: Mapping[str, Any],
    nodes_data: Mapping[str, Any],
    ris_data: Mapping[str, Any],
    path: str | Path,
) -> None:
    room = room_data["room"]
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.set_title("Room Topology")
    ax.set_xlim(0, float(room["length"]))
    ax.set_ylim(0, float(room["width"]))
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.grid(True, alpha=0.25)

    for node in nodes_data.get("nodes", []):
        x, y, _ = node["location"]
        ax.scatter([x], [y], s=70, label=node.get("id", "node"))
        ax.annotate(node.get("id", "node"), (x, y), xytext=(5, 5), textcoords="offset points")

    for ris in ris_data.get("ris", []):
        x, y, _ = ris["location"]
        ax.scatter([x], [y], marker="s", s=110, label=ris.get("id", "ris"))
        ax.annotate(ris.get("id", "ris"), (x, y), xytext=(5, -12), textcoords="offset points")

    ax.legend(loc="best")
    _save(fig, path)


def plot_ris_heatmap(ris: Mapping[str, Any], path: str | Path) -> None:
    matrix = np.asarray(ris["configuration_matrix"], dtype=float)
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(matrix, origin="lower", aspect="auto", cmap="viridis")
    ax.set_title(f"RIS Configuration: {ris.get('id', 'ris')}")
    ax.set_xlabel("n index")
    ax.set_ylabel("m index")
    fig.colorbar(im, ax=ax, label="state")
    _save(fig, path)


def plot_iq_timeseries(samples: Sequence[complex], sample_rate: float, path: str | Path) -> None:
    values = _samples_array(samples)
    t = np.arange(len(values)) / float(sample_rate) if sample_rate else np.arange(len(values))

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(t, values.real, label="I", linewidth=1.4)
    ax.plot(t, values.imag, label="Q", linewidth=1.4)
    ax.set_title("Received IQ Time Series")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("amplitude")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    _save(fig, path)


def plot_constellation(samples: Sequence[complex], path: str | Path) -> None:
    values = _samples_array(samples)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(values.real, values.imag, s=12, alpha=0.75)
    ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.4)
    ax.axvline(0.0, color="black", linewidth=0.8, alpha=0.4)
    ax.set_title("Received Constellation")
    ax.set_xlabel("I")
    ax.set_ylabel("Q")
    ax.grid(True, alpha=0.25)
    ax.set_aspect("equal", adjustable="datalim")
    _save(fig, path)


def plot_power(samples: Sequence[complex], sample_rate: float, path: str | Path) -> None:
    values = _samples_array(samples)
    power = np.abs(values) ** 2
    t = np.arange(len(values)) / float(sample_rate) if sample_rate else np.arange(len(values))

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(t, power, linewidth=1.4)
    ax.set_title("Received Power")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("|IQ|^2")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def _power_points(receiver_metrics: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    xs = []
    ys = []
    values = []
    labels = []
    for item in receiver_metrics:
        loc = item.get("location")
        if not isinstance(loc, (list, tuple)) or len(loc) < 2:
            continue
        if "mean_power_dbm" not in item:
            continue
        xs.append(float(loc[0]))
        ys.append(float(loc[1]))
        values.append(float(item["mean_power_dbm"]))
        labels.append(str(item.get("id", "")))
    return np.asarray(xs), np.asarray(ys), np.asarray(values), labels


def _room_axes(ax, room_data: Mapping[str, Any]) -> None:
    room = room_data["room"]
    ax.set_xlim(0, float(room["length"]))
    ax.set_ylim(0, float(room["width"]))
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.grid(True, alpha=0.2)


def plot_receiver_power_map(
    receiver_metrics: Sequence[Mapping[str, Any]],
    room_data: Mapping[str, Any],
    path: str | Path,
) -> None:
    xs, ys, dbm, labels = _power_points(receiver_metrics)
    if len(dbm) == 0:
        raise ValueError("receiver_metrics must include location and mean_power_dbm values.")

    fig, ax = plt.subplots(figsize=(8, 6))
    sc = ax.scatter(xs, ys, c=dbm, s=140, cmap="viridis", edgecolor="black", linewidth=0.6)
    for x, y, value, label in zip(xs, ys, dbm, labels):
        text = f"{label}\n{value:.2f} dBm" if label else f"{value:.2f} dBm"
        ax.annotate(text, (x, y), xytext=(5, 5), textcoords="offset points", fontsize=7)
    ax.set_title("Received Power Map")
    _room_axes(ax, room_data)
    fig.colorbar(sc, ax=ax, label="received power (dBm)")
    _save(fig, path)


def _idw_interpolate(xs: np.ndarray, ys: np.ndarray, values: np.ndarray, grid_x, grid_y) -> np.ndarray:
    grid = np.zeros_like(grid_x, dtype=float)
    weight_sum = np.zeros_like(grid_x, dtype=float)
    for x, y, value in zip(xs, ys, values):
        dist2 = (grid_x - x) ** 2 + (grid_y - y) ** 2
        exact = dist2 < 1e-12
        weights = 1.0 / np.maximum(dist2, 1e-12)
        grid += weights * value
        weight_sum += weights
        grid[exact] = value
        weight_sum[exact] = 1.0
    return grid / np.maximum(weight_sum, 1e-12)


def plot_room_coverage_heatmap(
    receiver_metrics: Sequence[Mapping[str, Any]],
    room_data: Mapping[str, Any],
    path: str | Path,
    *,
    grid_size: int = 120,
) -> None:
    xs, ys, dbm, labels = _power_points(receiver_metrics)
    if len(dbm) < 3:
        raise ValueError("At least three receiver points are needed for a coverage heatmap.")

    room = room_data["room"]
    x_axis = np.linspace(0, float(room["length"]), grid_size)
    y_axis = np.linspace(0, float(room["width"]), grid_size)
    grid_x, grid_y = np.meshgrid(x_axis, y_axis)
    grid_dbm = _idw_interpolate(xs, ys, dbm, grid_x, grid_y)

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(
        grid_dbm,
        origin="lower",
        extent=[0, float(room["length"]), 0, float(room["width"])],
        aspect="auto",
        cmap="viridis",
    )
    ax.scatter(xs, ys, c="white", s=30, edgecolor="black", linewidth=0.5)
    for x, y, label in zip(xs, ys, labels):
        if label:
            ax.annotate(label, (x, y), xytext=(3, 3), textcoords="offset points", fontsize=7)
    ax.set_title("Room Coverage Heatmap")
    _room_axes(ax, room_data)
    fig.colorbar(im, ax=ax, label="received power (dBm)")
    _save(fig, path)
