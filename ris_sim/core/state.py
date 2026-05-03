"""In-memory state objects for the RIS emulator. No JSON I/O per tick."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class NodeState:
    """Mutable state for a single simulated radio node."""

    id: str
    location: list[float]
    mobility: dict[str, Any] = field(default_factory=lambda: {"type": "static", "speed": 0.0})

    # Request queue (one pending request at a time)
    request: dict[str, Any] = field(default_factory=dict)

    # Runtime state
    current_mode: str = "idle"
    fc: float = -1.0
    sample_rate: float = -1.0
    req_time: int = 0
    current_counter: int = -1
    data: list[list[list[float]]] = field(default_factory=list)
    request_id: str | None = None
    remaining_samples: int = 0
    next_update: int = -1

    def reset(self) -> None:
        self.current_mode = "idle"
        self.next_update = -1
        self.current_counter = -1
        self.fc = -1.0
        self.sample_rate = -1.0
        self.data = []
        self.request_id = None

    @property
    def is_idle(self) -> bool:
        return self.current_mode == "idle"

    @property
    def is_transmit(self) -> bool:
        return self.current_mode == "transmit"

    @property
    def is_receive(self) -> bool:
        return self.current_mode == "receive"


@dataclass
class RisController:
    """Precomputed state for a single RIS panel."""

    id: str
    fc: float
    type: str
    plane: int
    location: list[float]
    unit_cell_m_length: float
    unit_cell_n_length: float
    unit_cell_gap: float
    array_size: tuple[int, int]
    phase_response: dict[str, list[float]]
    configuration_matrix: np.ndarray  # (M, N)
    coordinates: np.ndarray  # (M, N, 3) — precomputed once
    normal: np.ndarray  # (3,) — unit normal vector
    reflection_coeffs: np.ndarray  # (M, N) complex

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> RisController:
        plane = int(config["plane"])
        m, n = int(config["array_size"][0]), int(config["array_size"][1])
        location = [float(v) for v in config["location"]]

        normal = _get_normal(plane)
        coordinates = _compute_coordinates(
            plane,
            location,
            float(config["unit_cell_m_length"]),
            float(config["unit_cell_n_length"]),
            float(config["unit_cell_gap"]),
            (m, n),
        )

        phase_response = {str(k): list(v) for k, v in config.get("phase_response", {}).items()}
        cfg_matrix = np.asarray(config["configuration_matrix"], dtype=float)
        reflection_coeffs = _compute_reflection_coeffs(cfg_matrix, phase_response)

        return cls(
            id=config.get("id", "ris_unknown"),
            fc=float(config.get("fc", 2.4e9)),
            type=config.get("type", "static"),
            plane=plane,
            location=location,
            unit_cell_m_length=float(config["unit_cell_m_length"]),
            unit_cell_n_length=float(config["unit_cell_n_length"]),
            unit_cell_gap=float(config["unit_cell_gap"]),
            array_size=(m, n),
            phase_response=phase_response,
            configuration_matrix=cfg_matrix,
            coordinates=coordinates,
            normal=normal,
            reflection_coeffs=reflection_coeffs,
        )

    def update_configuration(self, new_matrix: np.ndarray) -> None:
        self.configuration_matrix = new_matrix
        self.reflection_coeffs = _compute_reflection_coeffs(new_matrix, self.phase_response)

    @property
    def element_count(self) -> int:
        return self.array_size[0] * self.array_size[1]


def _compute_reflection_coeffs(
    config_matrix: np.ndarray, phase_response: dict[str, list[float]]
) -> np.ndarray:
    coeffs = np.zeros(config_matrix.shape, dtype=np.complex128)
    if not phase_response:
        coeffs = config_matrix.astype(np.complex128)
    else:
        for i in range(config_matrix.shape[0]):
            for j in range(config_matrix.shape[1]):
                key = str(int(config_matrix[i, j]))
                if key in phase_response:
                    val = phase_response[key]
                    coeffs[i, j] = complex(float(val[0]), float(val[1]))
                else:
                    coeffs[i, j] = complex(config_matrix[i, j])
    return coeffs


def _compute_coordinates(
    plane: int,
    location: list[float],
    cell_m: float,
    cell_n: float,
    gap: float,
    array_size: tuple[int, int],
) -> np.ndarray:
    m, n = array_size
    coords = np.zeros((m, n, 3), dtype=np.float64)
    lx, ly, lz = location

    for i in range(m):
        for j in range(n):
            if plane in (1, 4):
                coords[i, j] = [
                    lx + cell_n / 2 + gap + j * (cell_n + gap),
                    ly + cell_m / 2 + gap + i * (cell_m + gap),
                    lz,
                ]
            elif plane in (2, 5):
                coords[i, j] = [
                    lx,
                    ly + cell_n / 2 + gap + j * (cell_n + gap),
                    lz + cell_m / 2 + gap + i * (cell_m + gap),
                ]
            elif plane in (3, 6):
                coords[i, j] = [
                    lx + cell_n / 2 + gap + j * (cell_n + gap),
                    ly,
                    lz + cell_m / 2 + gap + i * (cell_m + gap),
                ]
            else:
                raise ValueError(f"Invalid plane: {plane}")
    return coords


def _get_normal(plane: int) -> np.ndarray:
    mapping = {
        1: np.array([0, 0, -1], dtype=np.float64),
        2: np.array([-1, 0, 0], dtype=np.float64),
        3: np.array([0, -1, 0], dtype=np.float64),
        4: np.array([0, 0, 1], dtype=np.float64),
        5: np.array([1, 0, 0], dtype=np.float64),
        6: np.array([0, 1, 0], dtype=np.float64),
    }
    if plane not in mapping:
        raise ValueError(f"Invalid plane: {plane}")
    return mapping[plane]


@dataclass
class OutputEntry:
    """A single receiver's output stored in memory."""

    request_id: str
    node_id: str
    fc: float
    sample_rate: float
    requested_num_samps: int
    data: list[list[list[float]]] = field(default_factory=list)  # [[[I,Q],...], ...]

    def flatten_iq(self) -> np.ndarray:
        samples = []
        for block in self.data:
            for pair in block:
                samples.append(complex(float(pair[0]), float(pair[1])))
        return np.asarray(samples, dtype=np.complex128)

    def append_chunk(self, chunk: list[list[float]]) -> None:
        self.data.append(chunk)


@dataclass
class OutputBuffer:
    """Collects all receiver outputs during a simulation run."""

    entries: list[OutputEntry] = field(default_factory=list)

    def add_entry(self, entry: OutputEntry) -> None:
        self.entries.append(entry)

    def find_entry(self, request_id: str) -> OutputEntry | None:
        for entry in self.entries:
            if entry.request_id == request_id:
                return entry
        return None

    def save_npz(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        arrays: dict[str, np.ndarray] = {}
        for i, entry in enumerate(self.entries, start=1):
            name = f"{entry.node_id.replace('-', '_')}_rx_{i}"
            arrays[name] = entry.flatten_iq()
        np.savez_compressed(str(target), **arrays)  # type: ignore[arg-type]

    def to_json_compatible(self) -> dict[str, Any]:
        return {
            "outputs": [
                {
                    "request_id": e.request_id,
                    "id": e.node_id,
                    "fc": e.fc,
                    "sample_rate": e.sample_rate,
                    "num_samps": e.requested_num_samps,
                    "data": e.data,
                }
                for e in self.entries
            ]
        }

    def __len__(self) -> int:
        return len(self.entries)
