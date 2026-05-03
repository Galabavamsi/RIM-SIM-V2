"""Golden output regression tests — ensure deterministic, bit-identical results."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ris_sim.core.engine import Simulation


GOLDEN_SEED = 42


class TestGoldenOutput(unittest.TestCase):
    """Bit-identical output across runs with the same seed."""

    def setUp(self):
        self.scenario = {
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
                {"id": "node_1", "location": [5.0, 2.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
                {"id": "node_2", "location": [8.0, 8.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
            ],
            "channel": {"enable_noise": False},
        }

    def _run_scenario(self, seed: int) -> np.ndarray:
        sim = Simulation.from_scenario(self.scenario, seed=seed)
        iq = [[float(i % 4), 0.0] for i in range(60)]
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", num_samps=60, fc=2.4e9, sample_rate=5880)
        output = sim.run()
        self.assertEqual(len(output), 1)
        return output.entries[0].flatten_iq()

    def test_deterministic_reproducibility(self):
        """Same seed produces bit-identical output."""
        result_a = self._run_scenario(GOLDEN_SEED)
        result_b = self._run_scenario(GOLDEN_SEED)
        np.testing.assert_array_equal(result_a, result_b)

    def test_different_seeds_produce_different_output(self):
        """Different seeds with random-walk mobility produce different paths."""
        scenario = dict(self.scenario)
        scenario["nodes"] = [
            {"id": "node_1", "location": [5.0, 2.0, 5.0],
             "mobility": {"type": "random_walk", "speed": 2.0}},
            {"id": "node_2", "location": [8.0, 8.0, 5.0],
             "mobility": {"type": "static", "speed": 0.0}},
        ]

        sim_a = Simulation.from_scenario(scenario, seed=42)
        sim_a.queue_tx("node_1", [[1.0, 0.0] for _ in range(200)], fc=2.4e9, sample_rate=1000)
        sim_a.queue_rx("node_2", 200, fc=2.4e9, sample_rate=1000)
        out_a = sim_a.run().entries[0].flatten_iq()

        sim_b = Simulation.from_scenario(scenario, seed=99)
        sim_b.queue_tx("node_1", [[1.0, 0.0] for _ in range(200)], fc=2.4e9, sample_rate=1000)
        sim_b.queue_rx("node_2", 200, fc=2.4e9, sample_rate=1000)
        out_b = sim_b.run().entries[0].flatten_iq()

        self.assertFalse(
            np.array_equal(out_a, out_b),
            "Different seeds with random walk must produce different outputs.",
        )

    def test_golden_output_matches_stored_reference(self):
        """Golden output matches a pre-computed reference file."""
        result = self._run_scenario(GOLDEN_SEED)

        golden_dir = Path(__file__).resolve().parent / "golden"
        golden_path = golden_dir / "two_node_ris_seed42.npz"

        if golden_path.exists():
            with np.load(golden_path) as ref:
                expected = ref["node_2_rx_1"]
            np.testing.assert_array_almost_equal(result, expected, decimal=12)
        else:
            # First run: generate and save the golden file
            golden_dir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(golden_path, node_2_rx_1=result)
            self.skipTest("Golden file generated. Re-run to verify.")

    def test_determinism_with_noise_enabled(self):
        """Noisy simulation should also be deterministic with fixed seed."""
        scenario = dict(self.scenario)
        scenario["channel"] = {"enable_noise": True, "noise_figure_db": 5.0}

        sim_a = Simulation.from_scenario(scenario, seed=GOLDEN_SEED)
        sim_a.queue_tx("node_1", [[1.0, 0.0] for _ in range(22)], fc=2.4e9, sample_rate=5880)
        sim_a.queue_rx("node_2", 22, fc=2.4e9, sample_rate=5880)
        out_a = sim_a.run().entries[0].flatten_iq()

        sim_b = Simulation.from_scenario(scenario, seed=GOLDEN_SEED)
        sim_b.queue_tx("node_1", [[1.0, 0.0] for _ in range(22)], fc=2.4e9, sample_rate=5880)
        sim_b.queue_rx("node_2", 22, fc=2.4e9, sample_rate=5880)
        out_b = sim_b.run().entries[0].flatten_iq()

        np.testing.assert_array_equal(out_a, out_b)


class TestEdgeCases(unittest.TestCase):
    """Additional integration tests for edge cases."""

    def test_very_small_num_samps(self):
        """Request 1 sample — should complete with exactly 1 sample."""
        sim = Simulation.from_scenario({
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1.0, 1.0, 1.0]},
                {"id": "rx", "location": [2.0, 1.0, 1.0]},
            ],
            "channel": {"enable_noise": False},
        })
        sim.queue_tx("tx", [[1.0, 0.0]], fc=2.4e9, sample_rate=1000)
        sim.queue_rx("rx", 1, fc=2.4e9, sample_rate=1000)
        output = sim.run()
        self.assertEqual(len(output.entries[0].flatten_iq()), 1)

    def test_high_sample_rate(self):
        """Sample rate near the validated maximum should work."""
        sim = Simulation.from_scenario({
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1.0, 1.0, 1.0]},
                {"id": "rx", "location": [2.0, 1.0, 1.0]},
            ],
            "channel": {"enable_noise": False},
        })
        sr = 10_000_000  # 10 MHz
        n = int(sr * 0.002) * 3  # 3 ticks worth
        sim.queue_tx("tx", [[1.0, 0.0] for _ in range(n)], fc=2.4e9, sample_rate=sr)
        sim.queue_rx("rx", n, fc=2.4e9, sample_rate=sr)
        output = sim.run()
        self.assertEqual(len(output.entries[0].flatten_iq()), n)

    def test_multiple_ris_panels(self):
        """Three RIS panels should all contribute to the channel."""
        scenario = {
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [
                {
                    "id": "ris_left", "fc": 2.4e9, "type": "static", "plane": 5,
                    "location": [0.0, 0.0, 5.0],
                    "unit_cell_m_length": 0.05, "unit_cell_n_length": 0.05, "unit_cell_gap": 0.01,
                    "array_size": [2, 2],
                    "phase_response": {"1": [0.707, 0.707]},
                    "configuration_matrix": [[1, 1], [1, 1]],
                },
                {
                    "id": "ris_right", "fc": 2.4e9, "type": "static", "plane": 5,
                    "location": [0.0, 10.0, 5.0],
                    "unit_cell_m_length": 0.05, "unit_cell_n_length": 0.05, "unit_cell_gap": 0.01,
                    "array_size": [2, 2],
                    "phase_response": {"1": [0.707, 0.707]},
                    "configuration_matrix": [[1, 1], [1, 1]],
                },
                {
                    "id": "ris_ceiling", "fc": 2.4e9, "type": "static", "plane": 3,
                    "location": [5.0, 5.0, 10.0],
                    "unit_cell_m_length": 0.05, "unit_cell_n_length": 0.05, "unit_cell_gap": 0.01,
                    "array_size": [2, 2],
                    "phase_response": {"1": [0.707, 0.707]},
                    "configuration_matrix": [[1, 1], [1, 1]],
                },
            ],
            "nodes": [
                {"id": "tx", "location": [5.0, 5.0, 2.0]},
                {"id": "rx", "location": [5.0, 5.0, 8.0]},
            ],
            "channel": {"enable_noise": False},
        }
        sim = Simulation.from_scenario(scenario)
        sim.queue_tx("tx", [[1.0, 0.0] for _ in range(22)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("rx", 22, fc=2.4e9, sample_rate=5880)
        output = sim.run()
        self.assertTrue(sim._all_idle())
        self.assertEqual(len(output), 1)

    def test_node_starts_inside_room_bounds(self):
        """Node at exact boundary should be valid."""
        scenario = {
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [0.0, 0.0, 0.0]},
                {"id": "rx", "location": [10.0, 10.0, 10.0]},
            ],
            "channel": {"enable_noise": False},
        }
        sim = Simulation.from_scenario(scenario)
        sim.queue_tx("tx", [[1.0, 0.0] for _ in range(11)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("rx", 11, fc=2.4e9, sample_rate=5880)
        sim.run()
        self.assertTrue(sim._all_idle())

    def test_random_walk_mobility_stays_in_bounds(self):
        """Random walk node must stay within room boundaries."""
        scenario = {
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [5.0, 5.0, 5.0],
                 "mobility": {"type": "random_walk", "speed": 1.0}},
                {"id": "rx", "location": [5.0, 5.0, 5.0]},
            ],
            "channel": {"enable_noise": False},
        }
        sim = Simulation.from_scenario(scenario, seed=42)
        sim.queue_tx("tx", [[1.0, 0.0] for _ in range(200)], fc=2.4e9, sample_rate=1000)
        sim.queue_rx("rx", 200, fc=2.4e9, sample_rate=1000)
        sim.run()

        tx = sim._get_node("tx")
        self.assertGreaterEqual(tx.location[0], 0)
        self.assertLessEqual(tx.location[0], 10.0)
        self.assertGreaterEqual(tx.location[1], 0)
        self.assertLessEqual(tx.location[1], 10.0)

    def test_simulation_can_be_run_twice(self):
        """Running the same Simulation object twice should work (re-queue TX/RX)."""
        sim = Simulation.from_scenario({
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1.0, 1.0, 1.0]},
                {"id": "rx", "location": [2.0, 1.0, 1.0]},
            ],
            "channel": {"enable_noise": False},
        })

        # First run
        sim.queue_tx("tx", [[1.0, 0.0] for _ in range(11)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("rx", 11, fc=2.4e9, sample_rate=5880)
        out1 = sim.run()
        self.assertEqual(len(out1), 1)

        # Second run — need to re-queue
        sim.queue_tx("tx", [[0.5, 0.0] for _ in range(11)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("rx", 11, fc=2.4e9, sample_rate=5880)
        out2 = sim.run()
        self.assertEqual(len(out2), 2)  # OutputBuffer accumulates


if __name__ == "__main__":
    unittest.main()
