"""
Request and configuration validation for the RIS emulator.

Raises ValueError with clear messages on invalid inputs to avoid hangs,
negative counters, and unbounded resource use.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

# --- Tunable limits (availability / robustness) ---
MIN_SAMPLE_RATE = 1.0
MAX_SAMPLE_RATE = 61.44e6  # common SDR upper range
MIN_NUM_SAMPS = 1
MAX_NUM_SAMPS = 50_000_000
MAX_TX_IQ_SAMPLES = 50_000_000
MAX_RIS_ARRAY_DIM = 256
MAX_RIS_ELEMENTS = 65_536  # 256*256
MIN_POSITIVE_FLOAT = 1e-12
VALID_MOBILITY_TYPES = {"static", "random_walk", "random_waypoint", "random_direction", "gauss_markov"}


class ValidationError(ValueError):
    """Invalid emulator request or configuration."""


def samples_per_tick(sample_rate: float, tau: float) -> int:
    """IQ samples processed per engine tick; must be >= 1 for the discrete loop."""
    if not math.isfinite(sample_rate) or not math.isfinite(tau):
        raise ValidationError("sample_rate and tau must be finite numbers.")
    if tau <= 0:
        raise ValidationError("tau must be positive.")
    spt = int(sample_rate * tau)
    if spt < 1:
        raise ValidationError(
            "int(sample_rate * tau) must be >= 1; increase sample_rate, tau, or both."
        )
    return spt


def transmit_ticks(num_iq_samples: int, sample_rate: float, tau: float) -> int:
    """Number of ticks to drain a TX buffer (includes final partial chunk)."""
    if num_iq_samples < 0:
        raise ValidationError("Transmit IQ length cannot be negative.")
    if num_iq_samples == 0:
        return 0
    spt = samples_per_tick(sample_rate, tau)
    return int(math.ceil(num_iq_samples / spt))


def receive_ticks(num_samps: int, sample_rate: float, tau: float) -> int:
    """Number of ticks to fulfill a receive request."""
    if num_samps < 0:
        raise ValidationError("num_samps cannot be negative.")
    if num_samps == 0:
        return 0
    spt = samples_per_tick(sample_rate, tau)
    return int(math.ceil(num_samps / spt))


def trim_iq_block(block: Sequence[Any], remaining: int) -> list[Any]:
    """Return at most ``remaining`` IQ samples from a per-tick block."""
    if not isinstance(remaining, int) or isinstance(remaining, bool):
        raise ValidationError("remaining sample count must be an integer.")
    if remaining < 0:
        raise ValidationError("remaining sample count cannot be negative.")
    if remaining == 0:
        return []
    return list(block[:remaining])


def _is_iq_pair(x: Any) -> bool:
    if not isinstance(x, (list, tuple)) or len(x) != 2:
        return False
    a, b = x[0], x[1]
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isfinite(
        float(a)
    ) and math.isfinite(float(b))


def normalize_transmit_data(data: Any) -> list[list[Any]]:
    """
    Engine expects ``node['data']`` as a list of per-stream sample lists: ``[[iq, iq, ...]]``.
    Accepts either that shape or a flat list of ``[I, Q]`` pairs (common SDR path).
    """
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        raise ValidationError("Transmit data must be a non-string sequence.")
    if len(data) == 0:
        raise ValidationError("Transmit data must be non-empty.")
    first = data[0]
    if _is_iq_pair(first):
        return [list(data)]
    return [list(row) for row in data]


def validate_transmit_request(
    sample_rate: float, data_streams: Sequence[Sequence[Any]], *, tau: float
) -> None:
    if not math.isfinite(sample_rate) or sample_rate <= 0:
        raise ValidationError("sample_rate must be a positive finite number.")
    if sample_rate < MIN_SAMPLE_RATE or sample_rate > MAX_SAMPLE_RATE:
        raise ValidationError(
            f"sample_rate must be in [{MIN_SAMPLE_RATE:g}, {MAX_SAMPLE_RATE:g}] Hz."
        )
    samples_per_tick(sample_rate, tau)  # enforces int(sr*tau) >= 1

    if not isinstance(data_streams, Sequence) or len(data_streams) < 1:
        raise ValidationError("Transmit data must contain at least one stream row.")
    row0 = data_streams[0]
    if not isinstance(row0, Sequence):
        raise ValidationError("Transmit stream row must be a sequence of [I, Q] pairs.")
    n = len(row0)
    if n < 1:
        raise ValidationError("Transmit stream must contain at least one IQ sample.")
    if n > MAX_TX_IQ_SAMPLES:
        raise ValidationError(f"Transmit length exceeds maximum ({MAX_TX_IQ_SAMPLES}).")
    for i, pair in enumerate(row0[: min(32, n)]):
        if not _is_iq_pair(pair):
            raise ValidationError(f"Invalid IQ sample at index {i}: expected [real, imag].")
    if n > 32:
        for j, pair in enumerate(row0[-32:]):
            idx = n - 32 + j
            if not _is_iq_pair(pair):
                raise ValidationError(f"Invalid IQ sample at index {idx}: expected [real, imag].")


def validate_receive_request(sample_rate: float, num_samps: int, *, tau: float) -> None:
    if not math.isfinite(sample_rate) or sample_rate <= 0:
        raise ValidationError("sample_rate must be a positive finite number.")
    if sample_rate < MIN_SAMPLE_RATE or sample_rate > MAX_SAMPLE_RATE:
        raise ValidationError(
            f"sample_rate must be in [{MIN_SAMPLE_RATE:g}, {MAX_SAMPLE_RATE:g}] Hz."
        )
    if not isinstance(num_samps, int) or isinstance(num_samps, bool):
        raise ValidationError("num_samps must be an integer.")
    if num_samps < MIN_NUM_SAMPS or num_samps > MAX_NUM_SAMPS:
        raise ValidationError(
            f"num_samps must be in [{MIN_NUM_SAMPS}, {MAX_NUM_SAMPS}] inclusive."
        )
    samples_per_tick(sample_rate, tau)


def validate_room_config(room: Mapping[str, Any]) -> None:
    try:
        r = room["room"]
        length = float(r["length"])
        width = float(r["width"])
        height = float(r["height"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValidationError("room.json: missing or invalid room.length/width/height.") from e
    for name, v in (("length", length), ("width", width), ("height", height)):
        if not math.isfinite(v) or v < MIN_POSITIVE_FLOAT:
            raise ValidationError(f"room.{name} must be a positive finite number.")


def validate_ris_entry(ris: Mapping[str, Any]) -> None:
    try:
        plane = int(ris["plane"])
        array_size = ris["array_size"]
        m, n = int(array_size[0]), int(array_size[1])
        cfg = ris["configuration_matrix"]
        uml = float(ris["unit_cell_m_length"])
        unl = float(ris["unit_cell_n_length"])
        ugap = float(ris["unit_cell_gap"])
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise ValidationError("ris.json: missing or malformed RIS entry fields.") from e

    if plane < 1 or plane > 6:
        raise ValidationError(f"RIS plane must be 1..6, got {plane}.")
    if m < 1 or n < 1 or m > MAX_RIS_ARRAY_DIM or n > MAX_RIS_ARRAY_DIM:
        raise ValidationError(
            f"RIS array_size must be in [1, {MAX_RIS_ARRAY_DIM}] per dimension, got [{m}, {n}]."
        )
    if m * n > MAX_RIS_ELEMENTS:
        raise ValidationError(f"RIS element count {m * n} exceeds maximum {MAX_RIS_ELEMENTS}.")
    for name, v in (("unit_cell_m_length", uml), ("unit_cell_n_length", unl)):
        if not math.isfinite(v) or v < MIN_POSITIVE_FLOAT:
            raise ValidationError(f"RIS {name} must be a positive finite number.")
    if not math.isfinite(ugap) or ugap < 0:
        raise ValidationError("RIS unit_cell_gap must be a non-negative finite number.")

    if not isinstance(cfg, list) or len(cfg) != m:
        raise ValidationError(
            f"configuration_matrix row count {len(cfg) if isinstance(cfg, list) else 'n/a'} "
            f"does not match array_size[0]={m}."
        )
    for i, row in enumerate(cfg):
        if not isinstance(row, list) or len(row) != n:
            raise ValidationError(
                f"configuration_matrix row {i} length does not match array_size[1]={n}."
            )
        for j, phase in enumerate(row):
            try:
                phase_value = float(phase)
            except (TypeError, ValueError) as e:
                raise ValidationError(
                    f"configuration_matrix[{i}][{j}] must be a finite phase value."
                ) from e
            if not math.isfinite(phase_value):
                raise ValidationError(
                    f"configuration_matrix[{i}][{j}] must be a finite phase value."
                )


def validate_nodes_locations(nodes: Sequence[Mapping[str, Any]], room: Mapping[str, Any]) -> None:
    """Warn-free bounds check: node [x,y,z] must lie inside room box (inclusive lower, exclusive upper ok)."""
    r = room["room"]
    L, W, H = float(r["length"]), float(r["width"]), float(r["height"])
    for node in nodes:
        loc = node.get("location")
        nid = node.get("id", "?")
        if not isinstance(loc, (list, tuple)) or len(loc) != 3:
            raise ValidationError(f"Node {nid}: location must be [x, y, z].")
        x, y, z = float(loc[0]), float(loc[1]), float(loc[2])
        for name, v in (("x", x), ("y", y), ("z", z)):
            if not math.isfinite(v):
                raise ValidationError(f"Node {nid}: {name} must be finite.")
        if x < 0 or x > L or y < 0 or y > W or z < 0 or z > H:
            raise ValidationError(
                f"Node {nid}: location [{x}, {y}, {z}] is outside room "
                f"[0..{L}] x [0..{W}] x [0..{H}]."
            )


def _validate_optional_vector(
    node_id: Any, mobility: Mapping[str, Any], field: str, *, allow_none: bool = True
) -> None:
    if field not in mobility:
        return
    value = mobility[field]
    if value is None and allow_none:
        return
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValidationError(f"Node {node_id}: mobility.{field} must be [x, y, z] or null.")
    for i, component in enumerate(value):
        try:
            component_value = float(component)
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"Node {node_id}: mobility.{field}[{i}] must be finite."
            ) from e
        if not math.isfinite(component_value):
            raise ValidationError(f"Node {node_id}: mobility.{field}[{i}] must be finite.")


def validate_nodes_mobility(nodes: Sequence[Mapping[str, Any]]) -> None:
    for node in nodes:
        nid = node.get("id", "?")
        mobility = node.get("mobility", {"type": "static", "speed": 0.0})
        if not isinstance(mobility, Mapping):
            raise ValidationError(f"Node {nid}: mobility must be an object.")

        mobility_type = mobility.get("type", "static")
        if mobility_type not in VALID_MOBILITY_TYPES:
            raise ValidationError(
                f"Node {nid}: mobility.type must be one of {sorted(VALID_MOBILITY_TYPES)}."
            )

        try:
            speed = float(mobility.get("speed", 0.0))
        except (TypeError, ValueError) as e:
            raise ValidationError(f"Node {nid}: mobility.speed must be finite.") from e
        if not math.isfinite(speed) or speed < 0:
            raise ValidationError(f"Node {nid}: mobility.speed must be a non-negative finite number.")

        _validate_optional_vector(nid, mobility, "waypoint")
        _validate_optional_vector(nid, mobility, "direction_vector")

        if mobility_type == "gauss_markov":
            for field, default in (
                ("alpha", 0.75),
                ("mean_speed", 1.0),
                ("mean_angle", math.pi / 4),
                ("prev_speed", speed),
                ("prev_angle", 0.0),
            ):
                if field not in mobility:
                    continue
                try:
                    value = float(mobility.get(field, default))
                except (TypeError, ValueError) as e:
                    raise ValidationError(f"Node {nid}: mobility.{field} must be finite.") from e
                if not math.isfinite(value):
                    raise ValidationError(f"Node {nid}: mobility.{field} must be finite.")
                if field in {"mean_speed", "prev_speed"} and value < 0:
                    raise ValidationError(
                        f"Node {nid}: mobility.{field} must be non-negative."
                    )
                if field == "alpha" and (value < 0 or value > 1):
                    raise ValidationError(f"Node {nid}: mobility.alpha must be in [0, 1].")


def validate_startup_configs(
    *, room_data: Mapping[str, Any], ris_data: Mapping[str, Any], nodes_data: Mapping[str, Any]
) -> None:
    validate_room_config(room_data)
    ris_list = ris_data.get("ris")
    if not isinstance(ris_list, list):
        raise ValidationError("ris.json: 'ris' must be a list.")
    for entry in ris_list:
        if not isinstance(entry, Mapping):
            raise ValidationError("ris.json: every RIS entry must be an object.")
        validate_ris_entry(entry)
    nodes = nodes_data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValidationError("nodes.json: 'nodes' must be a non-empty list.")
    validate_nodes_locations(nodes, room_data)
    validate_nodes_mobility(nodes)
