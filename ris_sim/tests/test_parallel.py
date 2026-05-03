"""Integration tests for parallel Monte Carlo (G2)."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ris_sim.parallel import parallel_run
from ris_sim.parallel.result import MonteCarloResult, compute_snr_from_output


def _scenario_with_noise(seed_offset: int = 0) -> dict:
    return {
        "room": {"length": 10.0, "width": 10.0, "height": 10.0},
        "ris": [],
        "nodes": [
            {"id": "tx", "location": [1.0, 5.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
            {"id": "rx", "location": [3.0, 5.0, 5.0], "mobility": {"type": "static", "speed": 0.0}},
        ],
        "channel": {"enable_noise": True, "noise_figure_db": 10.0},
        "traffic": [
            {
                "mode": "transmit", "node_id": "tx", "fc": 2.4e9, "sample_rate": 5880.0,
                "waveform": {"kind": "bpsk_bits", "bits": [0, 1, 0, 1, 1, 1, 0, 0],
                             "amplitude": 0.1, "samples_per_symbol": 10},
            },
            {
                "mode": "receive", "node_id": "rx", "fc": 2.4e9, "sample_rate": 5880.0,
                "num_samps": 80,
            },
        ],
    }


class TestParallelRun(unittest.TestCase):
    """G2: Parallel Monte Carlo execution."""

    def test_single_trial_returns_output(self):
        """A single trial should return valid output."""
        results = list(parallel_run(_scenario_with_noise(), trials=1, workers=1))
        self.assertEqual(len(results), 1)
        output, seed = results[0]
        self.assertIn("outputs", output)
        self.assertEqual(len(output["outputs"]), 1)
        self.assertEqual(output["outputs"][0]["id"], "rx")

    def test_multiple_trials_return_unique_seeds(self):
        """Each trial gets a different seed."""
        results = list(parallel_run(_scenario_with_noise(), trials=4, workers=1))
        self.assertEqual(len(results), 4)
        seeds = [s for _, s in results]
        self.assertEqual(len(set(seeds)), 4)

    def test_different_seeds_produce_varying_snr(self):
        """With noise enabled, different seeds should produce different SNR."""
        results = list(parallel_run(_scenario_with_noise(), trials=5, workers=1))
        snrs = []
        for output, _ in results:
            snr = compute_snr_from_output(output["outputs"][0])
            if math.isfinite(snr):
                snrs.append(snr)

        self.assertGreater(len(snrs), 1)
        # With noise, SNRs should vary
        self.assertGreater(np.std(snrs), 0.01,
                          "Noisy trials should produce varying SNR.")

    def test_multi_worker_completes(self):
        """Multiple workers should all complete successfully."""
        results = list(parallel_run(_scenario_with_noise(), trials=4, workers=2))
        self.assertEqual(len(results), 4)
        for output, _ in results:
            self.assertIn("outputs", output)
            self.assertNotIn("error", output)


class TestMonteCarloResult(unittest.TestCase):
    """G2: MonteCarloResult aggregation."""

    def test_empty_result_has_nan_stats(self):
        mc = MonteCarloResult()
        self.assertTrue(math.isnan(mc.snr_median))
        self.assertEqual(mc.num_trials, 0)

    def test_record_and_stats(self):
        mc = MonteCarloResult()
        snrs = [5.0, 10.0, 15.0, 20.0, 25.0]
        for s in snrs:
            mc.record_snr(s)
        self.assertEqual(mc.num_trials, 5)
        self.assertAlmostEqual(mc.snr_median, 15.0)
        self.assertAlmostEqual(mc.snr_mean, 15.0)
        self.assertAlmostEqual(mc.snr_p10, 7.0, delta=0.1)
        self.assertAlmostEqual(mc.snr_p90, 23.0, delta=0.1)

    def test_snr_cdf_shape(self):
        mc = MonteCarloResult()
        for s in [1.0, 2.0, 3.0]:
            mc.record_snr(s)
        x, y = mc.snr_cdf()
        self.assertEqual(len(x), 3)
        self.assertEqual(len(y), 3)
        self.assertAlmostEqual(y[-1], 1.0)
        self.assertAlmostEqual(y[0], 1.0 / 3.0)

    def test_plot_snr_cdf_creates_file(self):
        mc = MonteCarloResult()
        for s in [5.0, 10.0, 15.0]:
            mc.record_snr(s)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snr_cdf.png"
            mc.plot_snr_cdf(path)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 100)

    def test_summary_string(self):
        mc = MonteCarloResult()
        mc.record_snr(10.0)
        summary = mc.summary()
        self.assertIn("10.00", summary)
        self.assertIn("Monte Carlo", summary)

    def test_repr(self):
        mc = MonteCarloResult()
        mc.record_snr(12.5)
        r = repr(mc)
        self.assertIn("12.5", r)

    def test_infinite_snr_ignored(self):
        mc = MonteCarloResult()
        mc.record_snr(float("inf"))
        mc.record_snr(-float("inf"))
        mc.record_snr(10.0)
        self.assertEqual(mc.num_trials, 1)
        self.assertAlmostEqual(mc.snr_median, 10.0)

    def test_end_to_end_with_parallel(self):
        """Full pipeline: parallel_run -> MonteCarloResult -> CDF."""
        mc = MonteCarloResult()
        for output, _ in parallel_run(_scenario_with_noise(), trials=3, workers=1):
            snr = compute_snr_from_output(output["outputs"][0])
            mc.record_snr(snr)

        self.assertEqual(mc.num_trials, 3)
        self.assertTrue(math.isfinite(mc.snr_median))
        self.assertTrue(math.isfinite(mc.snr_mean))
        self.assertGreater(mc.snr_std, 0.0)


if __name__ == "__main__":
    unittest.main()
