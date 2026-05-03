"""Integration tests for the G4 web dashboard."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient
from ris_sim.web.app import app
from ris_sim.web.session import list_templates, load_template, validate_scenario

client = TestClient(app)


class TestDashboardHTTP(unittest.TestCase):
    def test_index_returns_html(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("RIS-SIM", response.text)
        self.assertIn("<!DOCTYPE html>", response.text)

    def test_api_templates_returns_list(self):
        response = client.get("/api/templates")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("templates", data)
        self.assertIsInstance(data["templates"], list)

    def test_api_template_by_name(self):
        response = client.get("/api/templates/topo_two_nodes_ris")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("room", data)
        self.assertIn("nodes", data)

    def test_api_template_404(self):
        response = client.get("/api/templates/nonexistent")
        self.assertEqual(response.status_code, 404)

    def test_validate_valid_scenario(self):
        scenario = {
            "room": {"length": 10, "width": 10, "height": 10},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1, 1, 1]},
                {"id": "rx", "location": [2, 2, 2]},
            ],
            "channel": {"enable_noise": False},
            "traffic": [
                {"mode": "transmit", "node_id": "tx", "fc": 2.4e9, "sample_rate": 5880,
                 "waveform": {"kind": "bpsk_bits", "bits": [0, 1], "amplitude": 0.1, "samples_per_symbol": 10}},
                {"mode": "receive", "node_id": "rx", "fc": 2.4e9, "sample_rate": 5880, "num_samps": 20},
            ],
        }
        response = client.post("/api/validate", json=scenario)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"], f"Expected valid, got errors: {data.get('errors')}")

    def test_validate_invalid_scenario(self):
        scenario = {
            "room": {"length": 10, "width": 10, "height": 10},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [100, 100, 100]},  # outside room
            ],
            "channel": {"enable_noise": False},
            "traffic": [],
        }
        response = client.post("/api/validate", json=scenario)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["valid"])


class TestDashboardSession(unittest.TestCase):
    def test_list_templates_includes_defaults(self):
        templates = list_templates()
        self.assertIn("topo_two_nodes_ris", templates)
        self.assertIn("sig_bpsk_burst", templates)
        self.assertGreater(len(templates), 4)

    def test_load_template_returns_dict(self):
        data = load_template("topo_two_nodes_ris")
        self.assertIsInstance(data, dict)
        self.assertIn("room", data)

    def test_load_template_nonexistent(self):
        self.assertIsNone(load_template("nonexistent"))

    def test_validate_scenario_returns_errors_for_bad_config(self):
        errors = validate_scenario({"room": {}, "nodes": []})
        self.assertGreater(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
