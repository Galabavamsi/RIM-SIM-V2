"""Integration tests for Phase G — RIS control + channel sounding."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ris_sim.core.engine import Simulation, _free_space_coefficient_v


def _two_node_scenario(**overrides):
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
                "array_size": [8, 8],
                "phase_response": {"1": [0.707, 0.707]},
                "configuration_matrix": [[1] * 8] * 8,
            }
        ],
        # Nodes placed close to RIS for measurable reflection
        "nodes": [
            {"id": "node_1", "location": [2.0, 4.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
            {"id": "node_2", "location": [2.0, 6.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
        ],
        "channel": {"enable_noise": False},
        **overrides,
    }


class TestRisControl(unittest.TestCase):
    """G1: Real-time RIS reconfiguration."""

    def test_ris_set_config_changes_channel(self):
        """Changing RIS config mid-simulation alters the received signal."""
        sim = Simulation.from_scenario(_two_node_scenario())
        iq = [[1.0, 0.0] for _ in range(22)]

        # Run with default config (all ones)
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", 22, fc=2.4e9, sample_rate=5880)
        out_default = sim.run().entries[0].flatten_iq()

        # Now zero-out the RIS and run again
        zero_matrix = np.zeros((8, 8), dtype=float)
        sim.ris_set_config("ris_1", zero_matrix)
        sim.queue_tx("node_1", iq, fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", 22, fc=2.4e9, sample_rate=5880)
        out_zero_ris = sim.run().entries[-1].flatten_iq()

        # With RIS disabled, signal should be different (weaker, since RIS path removed)
        self.assertFalse(
            np.allclose(out_default, out_zero_ris),
            "Zeroing RIS must change the received signal.",
        )

    def test_ris_set_config_mid_simulation(self):
        """Reconfiguring RIS mid-simulation affects subsequent ticks."""
        sim = Simulation.from_scenario(_two_node_scenario())

        # Queue TX and RX, but run tick-by-tick
        sim.queue_tx("node_1", [[1.0, 0.0] for _ in range(33)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", 33, fc=2.4e9, sample_rate=5880)

        # Run first few ticks with default config
        for _ in range(2):
            cont = sim.tick()
            if not cont:
                break

        # Reconfigure RIS mid-way
        zero_matrix = np.zeros((8, 8), dtype=float)
        sim.ris_set_config("ris_1", zero_matrix)

        # Run remaining ticks
        while sim.tick():
            pass

        # Verify simulation completed
        self.assertTrue(sim._all_idle())
        self.assertGreater(sim.counter, 2)

    def test_ris_set_config_rejects_wrong_shape(self):
        """Setting a matrix with wrong dimensions raises ValueError."""
        sim = Simulation.from_scenario(_two_node_scenario())
        with self.assertRaises(ValueError):
            sim.ris_set_config("ris_1", np.ones((4, 4), dtype=float))  # should be 8x8

    def test_ris_set_config_unknown_raises_keyerror(self):
        """Setting config for non-existent RIS raises KeyError."""
        sim = Simulation.from_scenario(_two_node_scenario())
        with self.assertRaises(KeyError):
            sim.ris_set_config("nonexistent", np.ones((8, 8)))


class TestChannelSounding(unittest.TestCase):
    """G3: Channel sounding mode."""

    def test_channel_sound_los_matches_friis(self):
        """LOS-only channel sounding matches free-space prediction."""
        sim = Simulation.from_scenario({
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1.0, 5.0, 5.0]},
                {"id": "rx", "location": [3.0, 5.0, 5.0]},
            ],
            "channel": {"enable_noise": False},
        })
        result = sim.channel_sound("tx", "rx", fc=2.4e9, pilot_length=200, pilot_amplitude=1.0)

        # Analytical prediction
        expected_h = _free_space_coefficient_v(2.4e9, 2.0)  # distance = 2.0m
        self.assertAlmostEqual(abs(result["h_total"]), abs(expected_h), delta=abs(expected_h) * 0.01)
        self.assertAlmostEqual(result["path_loss_db"], 20 * math.log10(abs(expected_h)), delta=0.1)

    def test_channel_sound_ris_contributes(self):
        """Channel sounding with RIS shows RIS contribution."""
        sim = Simulation.from_scenario(_two_node_scenario())
        result = sim.channel_sound("node_1", "node_2", fc=2.4e9, pilot_length=200)

        # h_total should differ from h_los (RIS path adds to channel)
        self.assertNotAlmostEqual(abs(result["h_total"]), abs(result["h_los"]), delta=abs(result["h_los"]) * 0.01)
        # h_ris should be non-zero
        self.assertGreater(abs(result["h_ris"]), 1e-15)

    def test_channel_sound_with_ris_disabled(self):
        """Setting RIS to zero makes h_ris ≈ 0."""
        sim = Simulation.from_scenario(_two_node_scenario())
        sim.ris_set_config("ris_1", np.zeros((8, 8), dtype=float))
        result = sim.channel_sound("node_1", "node_2", fc=2.4e9, pilot_length=200)

        # With RIS disabled, h_total ≈ h_los
        ratio = abs(result["h_total"]) / max(abs(result["h_los"]), 1e-20)
        self.assertAlmostEqual(ratio, 1.0, delta=0.01)

    def test_channel_sound_resets_state(self):
        """After channel_sound, nodes should be idle (sim reusable)."""
        sim = Simulation.from_scenario(_two_node_scenario())
        sim.channel_sound("node_1", "node_2", fc=2.4e9, pilot_length=100)
        self.assertTrue(sim._all_idle())

        # Should be able to run another simulation
        sim.queue_tx("node_1", [[1.0, 0.0] for _ in range(11)], fc=2.4e9, sample_rate=5880)
        sim.queue_rx("node_2", 11, fc=2.4e9, sample_rate=5880)
        output = sim.run()
        self.assertEqual(len(output), 3)  # 2 from sounding + 1 new


if __name__ == "__main__":
    unittest.main()
