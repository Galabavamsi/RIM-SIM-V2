import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules import channel_functions as channel


class TestChannelModel(unittest.TestCase):
    def test_process_samples_preserves_length_at_common_rates(self):
        data = [[1.0, 0.0] for _ in range(32)]
        for sample_rate in (5_880, 24_000, 44_100, 1_000_000):
            with self.subTest(sample_rate=sample_rate):
                out = channel.process_samples(
                    data,
                    [1.0, 1.0, 1.0],
                    [3.0, 1.0, 1.0],
                    2.4e9,
                    0,
                    0.002,
                    sample_rate,
                )
                self.assertEqual(len(out), len(data))
                self.assertTrue(all(len(sample) == 2 for sample in out))
                self.assertTrue(all(math.isfinite(x) for sample in out for x in sample))

    def test_ris_back_side_paths_are_blocked_not_abs_flipped(self):
        normal = np.array([1.0, 0.0, 0.0])
        element = [0.0, 0.0, 0.0]
        front_tx = [1.0, 0.0, 0.0]
        front_rx = [2.0, 0.0, 0.0]
        back_tx = [-1.0, 0.0, 0.0]

        self.assertGreater(
            channel.element_visibility(front_tx, element, front_rx, normal), 0.0
        )
        self.assertEqual(
            channel.element_visibility(back_tx, element, front_rx, normal), 0.0
        )

    def test_phase_response_table_is_used_for_ris_state(self):
        ris = {"phase_response": {"1": [0.0, 1.0], "2": [-1.0, 0.0]}}
        self.assertEqual(channel.reflection_coefficient(ris, 1), 1j)
        self.assertEqual(channel.reflection_coefficient(ris, 2), -1 + 0j)

    def test_total_nlos_gain_uses_configured_phase_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            ris_data = {
                "ris": [
                    {
                        "id": "ris_1",
                        "fc": 2.4e9,
                        "type": "static",
                        "plane": 5,
                        "location": [0.0, 0.0, 0.0],
                        "unit_cell_m_length": 0.05,
                        "unit_cell_n_length": 0.05,
                        "unit_cell_gap": 0.0,
                        "array_size": [1, 1],
                        "phase_response": {"1": [0.0, 1.0]},
                        "configuration_matrix": [[1]],
                    }
                ]
            }
            (root / "config" / "ris.json").write_text(json.dumps(ris_data))

            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                gain = channel.total_nlos_gain(2.4e9, [1.0, 0.0, 0.0], [2.0, 0.0, 0.0])
            finally:
                os.chdir(old_cwd)

        self.assertNotEqual(gain, 0j)
        self.assertAlmostEqual(abs(gain), abs(gain.imag), delta=abs(gain) * 0.1)


if __name__ == "__main__":
    unittest.main()
