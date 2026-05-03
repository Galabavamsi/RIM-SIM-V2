import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules import plotting


class TestPlotting(unittest.TestCase):
    def test_plot_helpers_create_png_files(self):
        room = {"room": {"length": 10.0, "width": 10.0, "height": 10.0}}
        nodes = {
            "nodes": [
                {"id": "node_1", "location": [1.0, 2.0, 3.0]},
                {"id": "node_2", "location": [8.0, 7.0, 3.0]},
            ]
        }
        ris = {
            "ris": [
                {
                    "id": "ris_1",
                    "location": [0.0, 5.0, 5.0],
                    "configuration_matrix": [[1, 2], [3, 4]],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            plotting.plot_room_topology(room, nodes, ris, out_dir / "room.png")
            plotting.plot_ris_heatmap(ris["ris"][0], out_dir / "ris.png")
            plotting.plot_iq_timeseries([1 + 0j, 0 + 1j], 2.0, out_dir / "iq.png")
            plotting.plot_constellation([1 + 0j, 0 + 1j], out_dir / "constellation.png")
            plotting.plot_power([1 + 0j, 0 + 1j], 2.0, out_dir / "power.png")
            plotting.plot_receiver_power_map(
                [
                    {"id": "node_1", "location": [1.0, 2.0, 3.0], "mean_power_dbm": -20.0},
                    {"id": "node_2", "location": [8.0, 7.0, 3.0], "mean_power_dbm": -30.0},
                ],
                room,
                out_dir / "rx_map.png",
            )
            plotting.plot_room_coverage_heatmap(
                [
                    {"id": "node_1", "location": [1.0, 2.0, 3.0], "mean_power_dbm": -20.0},
                    {"id": "node_2", "location": [8.0, 7.0, 3.0], "mean_power_dbm": -30.0},
                    {"id": "node_3", "location": [5.0, 5.0, 3.0], "mean_power_dbm": -24.0},
                ],
                room,
                out_dir / "coverage.png",
            )

            for name in (
                "room.png",
                "ris.png",
                "iq.png",
                "constellation.png",
                "power.png",
                "rx_map.png",
                "coverage.png",
            ):
                self.assertGreater((out_dir / name).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
