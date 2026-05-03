import math
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules import results


class TestResults(unittest.TestCase):
    def test_flatten_iq_blocks_handles_tick_blocks(self):
        entry = {
            "id": "node_2",
            "sample_rate": 4.0,
            "data": [
                [[1.0, 0.0], [0.0, 1.0]],
                [[-1.0, 0.5]],
            ],
        }

        samples = results.flatten_iq_blocks(entry)

        self.assertEqual(samples.tolist(), [1.0 + 0.0j, 0.0 + 1.0j, -1.0 + 0.5j])

    def test_compute_signal_metrics(self):
        samples = [1.0 + 0.0j, 0.0 + 2.0j, 0.0 + 0.0j]

        metrics = results.compute_signal_metrics(samples, sample_rate=3.0)

        self.assertEqual(metrics["num_samples"], 3)
        self.assertAlmostEqual(metrics["duration_s"], 1.0)
        self.assertAlmostEqual(metrics["mean_power"], 5.0 / 3.0)
        self.assertAlmostEqual(metrics["peak_power"], 4.0)
        self.assertAlmostEqual(metrics["rms_amplitude"], math.sqrt(5.0 / 3.0))

    def test_summarize_output_writes_one_record_per_receiver(self):
        output = {
            "outputs": [
                {
                    "request_id": "rx-1",
                    "id": "node_2",
                    "fc": 2.4e9,
                    "sample_rate": 2.0,
                    "num_samps": 2,
                    "data": [[[1.0, 0.0], [0.0, 1.0]]],
                }
            ]
        }

        summary = results.summarize_output(output)

        self.assertEqual(summary["num_outputs"], 1)
        self.assertEqual(summary["outputs"][0]["id"], "node_2")
        self.assertEqual(summary["outputs"][0]["num_samples"], 2)
        self.assertAlmostEqual(summary["outputs"][0]["mean_power"], 1.0)

    def test_save_npz_exports_complex_arrays(self):
        output = {
            "outputs": [
                {
                    "request_id": "rx-1",
                    "id": "node_2",
                    "sample_rate": 2.0,
                    "data": [[[1.0, 0.0], [0.0, 1.0]]],
                }
            ]
        }

        with tempfile.TemporaryDirectory(dir=_ROOT) as tmp:
            path = Path(tmp) / "result.npz"
            results.save_output_npz(output, path)
            loaded = results.load_npz_arrays(path)

        self.assertEqual(loaded["node_2_rx_1"].tolist(), [1.0 + 0.0j, 0.0 + 1.0j])


if __name__ == "__main__":
    unittest.main()
