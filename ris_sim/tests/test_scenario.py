import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules import json_store
from modules import scenario


def _minimal_scenario():
    return {
        "name": "unit_two_node_ris",
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
                "array_size": [2, 2],
                "phase_response": {"1": [0.707, 0.707]},
                "configuration_matrix": [[1, 1], [1, 1]],
            }
        ],
        "nodes": [
            {"id": "node_1", "location": [5.0, 2.0, 5.0], "mobility": {"type": "static"}},
            {"id": "node_2", "location": [8.0, 8.0, 5.0], "mobility": {"type": "static"}},
        ],
        "traffic": [
            {
                "mode": "transmit",
                "node_id": "node_1",
                "fc": 2.4e9,
                "sample_rate": 1000.0,
                "waveform": {
                    "kind": "bpsk_bits",
                    "bits": [1, 0, 1],
                    "amplitude": 0.5,
                    "samples_per_symbol": 2,
                },
            },
            {
                "mode": "receive",
                "node_id": "node_2",
                "fc": 2.4e9,
                "sample_rate": 1000.0,
                "num_samps": 6,
            },
        ],
    }


class TestScenario(unittest.TestCase):
    def test_apply_scenario_writes_engine_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"

            scenario.apply_scenario(_minimal_scenario(), config_dir)

            room = json_store.load_json(config_dir / "room.json")
            nodes = json_store.load_json(config_dir / "nodes.json")
            output = json_store.load_json(config_dir / "output.json")

        self.assertEqual(room["room"]["length"], 10.0)
        self.assertEqual(nodes["nodes"][0]["current_mode"], "idle")
        self.assertEqual(nodes["nodes"][0]["request"], {})
        self.assertEqual(output, {"outputs": []})

    def test_queue_traffic_adds_valid_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            scenario_data = _minimal_scenario()

            scenario.apply_scenario(scenario_data, config_dir)
            scenario.queue_traffic_requests(scenario_data, config_dir)
            nodes = json_store.load_json(config_dir / "nodes.json")["nodes"]

        tx_node = next(node for node in nodes if node["id"] == "node_1")
        rx_node = next(node for node in nodes if node["id"] == "node_2")
        self.assertEqual(tx_node["request"]["mode"], "transmit")
        self.assertEqual(len(tx_node["request"]["data"][0]), 6)
        self.assertEqual(tx_node["request"]["data"][0][0], [0.5, 0.0])
        self.assertEqual(rx_node["request"]["mode"], "receive")
        self.assertEqual(rx_node["request"]["num_samps"], 6)


if __name__ == "__main__":
    unittest.main()
