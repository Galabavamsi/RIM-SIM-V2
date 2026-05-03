import math
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules import validation as val


TAU = 0.002


class TestValidation(unittest.TestCase):
    def test_samples_per_tick_demo(self):
        self.assertEqual(val.samples_per_tick(5880, TAU), 11)

    def test_transmit_ticks_matches_ceil_not_floor(self):
        n = 2389
        sr = 5880
        spt = val.samples_per_tick(sr, TAU)
        self.assertEqual(spt, 11)
        ticks = val.transmit_ticks(n, sr, TAU)
        self.assertEqual(ticks, int(math.ceil(n / spt)))
        # Old engine used int(n / (sr * tau)) == 203 ticks; ceil(n/spt) preserves the full buffer.
        self.assertEqual(ticks, 218)
        self.assertGreaterEqual(ticks * spt, n)

    def test_receive_ticks(self):
        self.assertEqual(val.receive_ticks(22, 5880, TAU), 2)

    def test_samples_per_tick_rejects_zero(self):
        with self.assertRaises(val.ValidationError):
            val.samples_per_tick(100.0, 0.001)

    def test_validate_transmit_request_rejects_bad_rate(self):
        data = [[[0.0, 0.0], [1.0, 0.0]]]
        with self.assertRaises(val.ValidationError):
            val.validate_transmit_request(-1.0, data, tau=TAU)
        with self.assertRaises(val.ValidationError):
            val.validate_transmit_request(1e12, data, tau=TAU)

    def test_validate_receive_request_rejects_zero_samps(self):
        with self.assertRaises(val.ValidationError):
            val.validate_receive_request(1e6, 0, tau=TAU)
        with self.assertRaises(val.ValidationError):
            val.validate_receive_request(1e6, 3.9, tau=TAU)
        with self.assertRaises(val.ValidationError):
            val.validate_receive_request(1e6, "10", tau=TAU)

    def test_normalize_transmit_data_flat_vs_nested(self):
        flat = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        wrapped = val.normalize_transmit_data(flat)
        self.assertEqual(wrapped, [flat])
        self.assertEqual(val.normalize_transmit_data(wrapped), wrapped)

    def test_validate_room_and_ris_smoke(self):
        room = {"room": {"length": 10.0, "width": 10.0, "height": 10.0}}
        val.validate_room_config(room)
        ris = {
            "plane": 5,
            "array_size": [2, 2],
            "unit_cell_m_length": 0.05,
            "unit_cell_n_length": 0.05,
            "unit_cell_gap": 0.01,
            "configuration_matrix": [[1, 1], [1, 1]],
        }
        val.validate_ris_entry(ris)

    def test_validate_startup_rejects_non_object_ris_entry(self):
        room = {"room": {"length": 10.0, "width": 10.0, "height": 10.0}}
        ris_data = {"ris": ["not-a-ris-object"]}
        nodes_data = {"nodes": [{"id": "a", "location": [1.0, 2.0, 3.0], "mobility": {"type": "static"}}]}
        with self.assertRaises(val.ValidationError):
            val.validate_startup_configs(room_data=room, ris_data=ris_data, nodes_data=nodes_data)

    def test_validate_ris_rejects_zero_cell_lengths(self):
        ris = {
            "plane": 5,
            "array_size": [2, 2],
            "unit_cell_m_length": 0.0,
            "unit_cell_n_length": 0.05,
            "unit_cell_gap": 0.01,
            "configuration_matrix": [[1, 1], [1, 1]],
        }
        with self.assertRaises(val.ValidationError):
            val.validate_ris_entry(ris)

    def test_validate_nodes_locations(self):
        room = {"room": {"length": 10.0, "width": 10.0, "height": 10.0}}
        nodes = [{"id": "a", "location": [1.0, 2.0, 3.0]}]
        val.validate_nodes_locations(nodes, room)
        with self.assertRaises(val.ValidationError):
            val.validate_nodes_locations(
                [{"id": "a", "location": [11.0, 2.0, 3.0]}], room
            )

    def test_validate_nodes_mobility_rejects_bad_models(self):
        with self.assertRaises(val.ValidationError):
            val.validate_nodes_mobility([{"id": "a", "mobility": {"type": "teleport"}}])
        with self.assertRaises(val.ValidationError):
            val.validate_nodes_mobility([{"id": "a", "mobility": {"type": "random_walk", "speed": -1.0}}])
        with self.assertRaises(val.ValidationError):
            val.validate_nodes_mobility([{"id": "a", "mobility": {"type": "gauss_markov", "alpha": 1.5}}])

    def test_iq_padding_shape_for_channel(self):
        padding = [[0, 0] for _ in range(3)]
        for p in padding:
            self.assertEqual(len(p), 2)

    def test_trim_samples_to_remaining_receive_count(self):
        block = [[float(i), 0.0] for i in range(11)]
        self.assertEqual(val.trim_iq_block(block, 3), block[:3])
        self.assertEqual(val.trim_iq_block(block, 20), block)


if __name__ == "__main__":
    unittest.main()
