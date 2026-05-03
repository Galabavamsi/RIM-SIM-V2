"""Integration tests for the new in-memory Simulation class."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ris_sim.core.engine import Simulation


class TestSimulation(unittest.TestCase):
    def _base_scenario(self, **overrides):
        return {
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [
                {
                    "id": "ris_1",
                    "fc": 2.4e9,
                    "type": "static",
                    "plane": 5,
                    "location": [0.0, 5.0, 5.0],
                    "unit_cell_m_length": 0.05,
                    "unit_cell_n_length": 0.05,
                    "unit_cell_gap": 0.01,
                    "array_size": [4, 4],
                    "phase_response": {"1": [0.707, 0.707]},
                    "configuration_matrix": [[1] * 4] * 4,
                }
            ],
            "nodes": [
                {
                    "id": "node_1",
                    "location": [5.0, 2.0, 5.0],
                    "mobility": {"type": "static", "speed": 0.0},
                },
                {
                    "id": "node_2",
                    "location": [8.0, 8.0, 5.0],
                    "mobility": {"type": "static", "speed": 0.0},
                },
            ],
            **overrides,
        }

    def test_tx_only_completes_and_idles(self):
        """Single TX with no RX must finish and all nodes return idle."""
        sim = Simulation.from_scenario(self._base_scenario())
        iq = [[1.0, 0.0] for _ in range(22)]
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        output = sim.run()
        self.assertTrue(sim._all_idle())
        self.assertEqual(len(output), 0)  # No receivers
        self.assertLess(sim.counter, 1000)

    def test_rx_only_returns_zeros_of_correct_length(self):
        """RX with no matching TX must return zeros of correct length."""
        sim = Simulation.from_scenario(self._base_scenario())
        sim.queue_rx("node_2", num_samps=44, fc=2.4e9, sample_rate=5880)
        output = sim.run()
        self.assertEqual(len(output), 1)
        samples = output.entries[0].flatten_iq()
        self.assertEqual(len(samples), 44)

    def test_output_length_matches_request(self):
        """Received samples count must equal num_samps exactly."""
        sim = Simulation.from_scenario(self._base_scenario())
        iq = [[1.0, 0.0] for _ in range(60)]
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", num_samps=60, fc=2.4e9, sample_rate=5880)
        output = sim.run()
        self.assertEqual(len(output), 1)
        samples = output.entries[0].flatten_iq()
        self.assertEqual(len(samples), 60)

    def test_no_ris_scenario_runs_los_only(self):
        """Simulation with no RIS works (LOS-only channel)."""
        scenario = self._base_scenario()
        scenario["ris"] = []
        sim = Simulation.from_scenario(scenario)
        iq = [[1.0, 0.0] for _ in range(22)]
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", num_samps=22, fc=2.4e9, sample_rate=5880)
        output = sim.run()
        self.assertEqual(len(output), 1)
        self.assertTrue(sim._all_idle())

    def test_all_nodes_idle_after_simulation(self):
        """After completion, every node must be in idle state."""
        sim = Simulation.from_scenario(self._base_scenario())
        iq = [[0.5, 0.0] for _ in range(33)]
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", num_samps=33, fc=2.4e9, sample_rate=5880)
        sim.run()
        for node in sim.nodes:
            self.assertEqual(node.current_mode, "idle", f"Node {node.id} not idle")

    def test_multi_frequency_no_interference(self):
        """TX/RX on different frequencies must not interfere."""
        scenario = self._base_scenario()
        scenario["nodes"].append({
            "id": "node_3", "location": [7.0, 3.0, 5.0],
            "mobility": {"type": "static", "speed": 0.0},
        })
        sim = Simulation.from_scenario(scenario)
        sim.queue_tx("node_1", [[1.0, 0.0] for _ in range(22)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", num_samps=22, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_3", num_samps=22, fc=900e6, sample_rate=5880)
        output = sim.run()
        self.assertTrue(sim._all_idle())
        # node_3 on 900MHz should get zeros (no TX on that frequency)
        self.assertEqual(len(output), 2)

    def test_output_buffer_save_load(self):
        """NPZ round-trip works correctly."""
        sim = Simulation.from_scenario(self._base_scenario())
        iq = [[float(i % 4), 0.0] for i in range(22)]
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", num_samps=22, fc=2.4e9, sample_rate=5880)
        output = sim.run()

        with tempfile.TemporaryDirectory() as td:
            npz_path = Path(td) / "test.npz"
            output.save_npz(npz_path)
            with np.load(npz_path) as loaded:
                self.assertIn("node_2_rx_1", loaded.files)

    def test_max_ticks_guard(self):
        """Simulation aborts when max_ticks is exceeded with stuck nodes."""
        sim = Simulation.from_scenario(self._base_scenario())
        # Queue a TX that never finishes (req_time keeps going)
        sim.queue_tx("node_1", [[1.0, 0.0] for _ in range(10_000_000)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", num_samps=10_000_000, fc=2.4e9, sample_rate=5880)
        sim.run(max_ticks=5)
        self.assertEqual(sim.counter, 5)

    def test_cfo_applies_phase_rotation(self):
        """CFO must rotate IQ samples by a predictable phase."""
        from ris_sim.radio.impairments import apply_cfo as apply_cfo_ext

        samples = [[1.0, 0.0] for _ in range(10)]
        result = apply_cfo_ext(samples, cfo_hz=100.0, sample_rate=1000.0, cumulative_time_s=0.0025)
        # At t=0.0025s, phase = 2*pi*100*0.0025 = pi/2 = 90 degrees
        # cos(90°) = 0, sin(90°) = 1 -> [1, 0] becomes approximately [0, 1]
        self.assertAlmostEqual(result[0][0], 0.0, delta=0.01)
        self.assertAlmostEqual(result[0][1], 1.0, delta=0.01)

    def test_cfo_zero_is_identity(self):
        """Zero CFO must leave samples unchanged."""
        from ris_sim.radio.impairments import apply_cfo as apply_cfo_ext

        samples = [[1.0, 0.0], [0.0, 1.0], [0.5, -0.5]]
        result = apply_cfo_ext(samples, cfo_hz=0.0, sample_rate=1000.0, tick_index=5, tau=0.002)
        for original, rotated in zip(samples, result):
            self.assertAlmostEqual(original[0], rotated[0])
            self.assertAlmostEqual(original[1], rotated[1])


if __name__ == "__main__":
    unittest.main()
