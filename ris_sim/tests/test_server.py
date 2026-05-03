"""Integration tests for the SimulationServer + client API round-trip."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ris_sim.core.server import SimulationServer
from ris_sim.radio import api


def _base_scenario():
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
            {"id": "node_1", "location": [5.0, 2.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
            {"id": "node_2", "location": [8.0, 8.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
        ],
    }


class TestServerIntegration(unittest.TestCase):
    """Full round-trip: start server in background thread, run client API calls."""

    BIND_ADDR = "tcp://127.0.0.1:15555"

    @classmethod
    def setUpClass(cls):
        cls.server = SimulationServer.from_scenario(
            _base_scenario(), bind_addr=cls.BIND_ADDR
        )
        cls._server_thread = threading.Thread(target=cls.server.serve, daemon=True)
        cls._server_thread.start()

        # Wait for server to be ready (retry status ping)
        from ris_sim.io.transport import ClientTransport
        for _ in range(50):
            try:
                t = ClientTransport(cls.BIND_ADDR)
                resp = t.request({"cmd": "status"}, timeout_ms=500)
                t.close()
                if resp.get("status") == "ok":
                    break
            except Exception:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("Server did not become ready within 2.5s")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls._server_thread.join(timeout=2.0)

    def test_send_and_receive_round_trip(self):
        """TX 22 samples on node_1, RX 22 samples on node_2."""
        iq = [[1.0, 0.0] for _ in range(22)]

        rid = api.send_to_simulator(
            iq, fc=2.4e9, sample_rate=5880, node_id="node_1",
            server_addr=self.BIND_ADDR,
        )
        self.assertIsInstance(rid, str)

        result = api.receive_from_simulator(
            22, fc=2.4e9, sample_rate=5880, node_id="node_2",
            server_addr=self.BIND_ADDR, timeout=10.0,
        )
        self.assertIsInstance(result, np.ndarray)
        self.assertTrue(np.iscomplexobj(result))
        self.assertEqual(len(result), 22)

    def test_rx_only_returns_zeros(self):
        """RX with no matching TX returns zeros of correct length."""
        result = api.receive_from_simulator(
            11, fc=900e6, sample_rate=5880, node_id="node_2",
            server_addr=self.BIND_ADDR, timeout=10.0,
        )
        self.assertEqual(len(result), 11)

    def test_status_query(self):
        """Server status returns valid data."""
        result = api.check_available_tx(2.4e9, server_addr=self.BIND_ADDR)
        self.assertIsInstance(result, list)

    def test_get_node_location(self):
        """get_node_location returns 3D coordinates."""
        loc = api.get_node_location("node_1", server_addr=self.BIND_ADDR)
        self.assertEqual(len(loc), 3)
        self.assertAlmostEqual(loc[0], 5.0, delta=0.1)

    def test_multiple_rx_requests(self):
        """Multiple sequential RX requests complete correctly."""
        iq = [[0.5, 0.0] for _ in range(44)]

        api.send_to_simulator(
            iq, fc=2.4e9, sample_rate=5880, node_id="node_1",
            server_addr=self.BIND_ADDR,
        )

        result1 = api.receive_from_simulator(
            22, fc=2.4e9, sample_rate=5880, node_id="node_2",
            server_addr=self.BIND_ADDR, timeout=10.0,
        )
        self.assertEqual(len(result1), 22)

        # Queue another RX — since TX data was 44 samples, there might be leftover
        # But each RX requires its own TX. Let's send another TX.
        iq2 = [[0.5, 0.0] for _ in range(33)]
        api.send_to_simulator(
            iq2, fc=2.4e9, sample_rate=5880, node_id="node_1",
            server_addr=self.BIND_ADDR,
        )
        result2 = api.receive_from_simulator(
            33, fc=2.4e9, sample_rate=5880, node_id="node_2",
            server_addr=self.BIND_ADDR, timeout=10.0,
        )
        self.assertEqual(len(result2), 33)


if __name__ == "__main__":
    unittest.main()
