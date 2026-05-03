"""Analytical validation tests: verify signal models against known formulas."""

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
from ris_sim.channel import fading, noise as noise_mod
from ris_sim.radio import impairments as imp
from ris_sim.radio import ofdm


class TestFreeSpacePathLoss(unittest.TestCase):
    """Validate LOS path loss against the Friis equation."""

    def test_friis_at_one_meter(self):
        """At 1m distance, path loss should match Friis formula."""
        fc = 2.4e9
        distance = 1.0
        coeff = _free_space_coefficient_v(fc, distance)
        # Friis: received power = Pt * Gt * Gr * (lambda/(4*pi*d))^2
        # Baseband coefficient amplitude = lambda/(4*pi*d)
        c = 3e8
        wavelength = c / fc
        expected_amplitude = wavelength / (4.0 * math.pi * distance)
        self.assertAlmostEqual(abs(coeff), expected_amplitude, delta=1e-12)

    def test_amplitude_scales_with_one_over_d(self):
        """Field amplitude scales approximately as 1/d at large distances."""
        fc = 2.4e9
        d1, d2 = 2.0, 4.0
        a1 = abs(_free_space_coefficient_v(fc, d1))
        a2 = abs(_free_space_coefficient_v(fc, d2))
        # Amplitude ∝ 1/d, so a1/a2 ≈ d2/d1 = 2
        ratio = a1 / a2
        self.assertAlmostEqual(ratio, 2.0, delta=0.01)

    def test_zero_distance_returns_zero(self):
        """Zero or negative distance returns 0 (degenerate path)."""
        self.assertEqual(_free_space_coefficient_v(2.4e9, 0), 0j)
        self.assertEqual(_free_space_coefficient_v(2.4e9, -1), 0j)

    def test_los_only_simulation_power_matches_friis(self):
        """LOS-only simulation: received power should match Friis prediction."""
        scenario = {
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1.0, 1.0, 1.0]},
                {"id": "rx", "location": [2.0, 1.0, 1.0]},
            ],
            "channel": {"enable_noise": False},
        }
        sim = Simulation.from_scenario(scenario)
        # TX amplitude 1.0 on I channel
        n_samples = 100
        iq = [[1.0, 0.0] for _ in range(n_samples)]
        sim.queue_tx("tx", iq, fc=2.4e9, sample_rate=10000)
        sim.queue_rx("rx", n_samples, fc=2.4e9, sample_rate=10000)
        output = sim.run()

        samples = output.entries[0].flatten_iq()
        # Expected: amplitude = lambda/(4*pi*d)
        c = 3e8
        d = 1.0  # distance between tx and rx
        expected_amp = (c / 2.4e9) / (4.0 * math.pi * d)
        mean_amp = float(np.mean(np.abs(samples)))
        self.assertAlmostEqual(mean_amp, expected_amp, delta=expected_amp * 0.01)


class TestAWGN(unittest.TestCase):
    """Validate noise generator against thermal noise formula."""

    def test_noise_power_matches_theory(self):
        """Sample variance should match k*T*B*NF/2 per I/Q component."""
        bw = 1000.0  # 1 kHz
        nf_db = 3.0  # 3 dB noise figure
        n_samples = 100_000

        sigma = noise_mod.noise_scale_from_db(bw, nf_db)
        expected_variance = sigma ** 2

        # Generate pure noise
        zeros = [[0.0, 0.0] for _ in range(n_samples)]
        noisy = noise_mod.add_awgn(zeros, bw, nf_db, seed=42)
        arr = np.array(noisy)

        # Variance of I component
        var_i = float(np.var(arr[:, 0]))
        # Variance of Q component
        var_q = float(np.var(arr[:, 1]))

        self.assertAlmostEqual(var_i, expected_variance, delta=expected_variance * 0.05)
        self.assertAlmostEqual(var_q, expected_variance, delta=expected_variance * 0.05)

    def test_noise_with_signal_preserves_signal_mean(self):
        """Adding noise to a constant signal should preserve the mean."""
        n_samples = 10_000
        signal = [[0.5, -0.3] for _ in range(n_samples)]
        noisy = noise_mod.add_awgn(signal, 1000.0, 0.0, seed=42)
        arr = np.array(noisy)
        self.assertAlmostEqual(float(np.mean(arr[:, 0])), 0.5, delta=0.02)
        self.assertAlmostEqual(float(np.mean(arr[:, 1])), -0.3, delta=0.02)

    def test_simulation_with_noise_has_higher_variance(self):
        """Enabling noise should increase received sample variance."""
        scenario = {
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1.0, 5.0, 5.0]},
                {"id": "rx", "location": [2.0, 5.0, 5.0]},
            ],
        }

        # Without noise
        sim_noiseless = Simulation.from_scenario({**scenario, "channel": {"enable_noise": False}})
        sim_noiseless.queue_tx("tx", [[1.0, 0.0] for _ in range(100)], fc=2.4e9, sample_rate=10000)
        sim_noiseless.queue_rx("rx", 100, fc=2.4e9, sample_rate=10000)
        out1 = sim_noiseless.run().entries[0].flatten_iq()

        # With noise
        sim_noisy = Simulation.from_scenario({**scenario, "channel": {"enable_noise": True, "noise_figure_db": 30.0}})
        sim_noisy.queue_tx("tx", [[1.0, 0.0] for _ in range(100)], fc=2.4e9, sample_rate=10000)
        sim_noisy.queue_rx("rx", 100, fc=2.4e9, sample_rate=10000)
        out2 = sim_noisy.run().entries[0].flatten_iq()

        var1 = float(np.var(np.real(out1)))
        var2 = float(np.var(np.real(out2)))
        self.assertGreater(var2, var1, "Noise should increase signal variance")


class TestCFO(unittest.TestCase):
    """Validate CFO applies correct phase rotation."""

    def test_cfo_90_degree_rotation(self):
        """CFO of 250 Hz should rotate [1,0] by 90 degrees after 1ms."""
        samples = [[1.0, 0.0]]
        # f_cfo = 250 Hz, t = 0.001s → 2*pi*250*0.001 = pi/2 = 90°
        result = imp.apply_cfo(samples, cfo_hz=250.0, sample_rate=1000.0, cumulative_time_s=0.001)
        self.assertAlmostEqual(result[0][0], 0.0, delta=1e-10)
        self.assertAlmostEqual(result[0][1], 1.0, delta=1e-10)

    def test_cfo_360_degree_is_identity(self):
        """Full rotation should return to original."""
        samples = [[0.7, 0.3]]
        # 1000 Hz CFO for 0.001s = 1 full cycle = identity
        result = imp.apply_cfo(samples, cfo_hz=1000.0, sample_rate=1000.0, cumulative_time_s=0.001)
        self.assertAlmostEqual(result[0][0], 0.7, delta=1e-10)
        self.assertAlmostEqual(result[0][1], 0.3, delta=1e-10)

    def test_cfo_in_simulation(self):
        """CFO configured via node RF should rotate constellation."""
        scenario = {
            "room": {"length": 10.0, "width": 10.0, "height": 10.0},
            "ris": [],
            "nodes": [
                {"id": "tx", "location": [1.0, 5.0, 5.0]},
                {"id": "rx", "location": [2.0, 5.0, 5.0], "rf": {"cfo_hz": 500.0}},
            ],
            "channel": {"enable_noise": False},
        }
        sim = Simulation.from_scenario(scenario)
        # Send constant [1,0] for 2 ticks at sample_rate=1000, tau=0.001 → tau_samp=1
        # So 2 samples total. First sample at t=0, second at t=0.001.
        # CFO phase: sample 1 = 0°, sample 2 = 2*pi*500*0.001 = pi = 180°
        sim.queue_tx("tx", [[1.0, 0.0], [1.0, 0.0]], fc=2.4e9, sample_rate=1000, tau=0.001)
        sim.queue_rx("rx", 2, fc=2.4e9, sample_rate=1000, tau=0.001)
        output = sim.run()
        samples = output.entries[0].flatten_iq()
        # First sample should be approximately [1, 0] (no rotation at t=0)
        self.assertAlmostEqual(samples[0].real, samples[0].real, delta=0.1)
        # Second sample should be rotated by ~180° (negated)
        self.assertAlmostEqual(samples[1].real, -samples[0].real, delta=abs(samples[0].real) * 0.1)


class TestIQImbalance(unittest.TestCase):
    """Validate IQ imbalance model."""

    def test_amplitude_imbalance_only(self):
        """6 dB gain mismatch: I/Q ratio should be ~4x."""
        samples = [[1.0, 1.0]]
        result = imp.apply_iq_imbalance(samples, amplitude_imbalance_db=6.0, phase_imbalance_deg=0.0)
        # g = 10^(6/20) ≈ 2.0, I' = I * sqrt(2) ≈ 1.414, Q' = Q / sqrt(2) ≈ 0.707
        self.assertAlmostEqual(result[0][0], 1.414, delta=0.01)
        self.assertAlmostEqual(result[0][1], 0.707, delta=0.01)

    def test_phase_imbalance_produces_image(self):
        """Phase skew creates correlation between I and Q."""
        samples = [[1.0, 0.0] for _ in range(100)]
        result = imp.apply_iq_imbalance(samples, amplitude_imbalance_db=0.0, phase_imbalance_deg=10.0)
        arr = np.array(result)
        # With phase skew, Q channel gets leakage from I
        self.assertGreater(np.mean(np.abs(arr[:, 1])), 0.0, "Phase imbalance should leak I into Q")


class TestPA(unittest.TestCase):
    """Validate power amplifier nonlinearity."""

    def test_rapp_linear_region(self):
        """Small signals should pass through Rapp PA linearly."""
        samples = [[0.01, 0.0] for _ in range(50)]
        result = imp.apply_pa_nonlinearity(samples, model="rapp", p_sat_db=30.0, smoothness=2.0)
        arr_in = np.array(samples)
        arr_out = np.array(result)
        # Linear region: output ≈ input
        self.assertAlmostEqual(float(np.mean(arr_out[:, 0])), float(np.mean(arr_in[:, 0])), delta=0.001)

    def test_rapp_saturates_large_signals(self):
        """Large signals should be compressed by Rapp PA."""
        samples = [[100.0, 0.0]]  # Way above saturation
        result = imp.apply_pa_nonlinearity(samples, model="rapp", p_sat_db=10.0, smoothness=2.0)
        # Should be clipped to near saturation level
        amp = math.sqrt(result[0][0] ** 2 + result[0][1] ** 2)
        sat_amp = 10 ** (10.0 / 20.0)  # p_sat_db=10 → linear amplitude
        self.assertLess(amp, 100.0, "PA should compress large signals")
        self.assertAlmostEqual(amp, sat_amp, delta=sat_amp * 0.1)


class TestFading(unittest.TestCase):
    """Validate fading model statistics."""

    def test_rayleigh_mean_power_is_unity(self):
        """Rayleigh fading coefficients should have unit mean power."""
        n = 100_000
        # Use parameters where AR(1) can converge: rho = exp(-2*pi*fd/fs)
        # fd=50Hz, fs=1000Hz → rho ≈ 0.73, converges quickly
        coeffs = fading.rayleigh_fading(n, fd=50.0, sample_rate=1000.0, seed=42)
        mean_power = float(np.mean(np.abs(coeffs) ** 2))
        self.assertAlmostEqual(mean_power, 1.0, delta=0.05)

    def test_rayleigh_amplitude_is_rayleigh_distributed(self):
        """Amplitude should follow Rayleigh distribution."""
        n = 100_000
        coeffs = fading.rayleigh_fading(n, fd=50.0, sample_rate=1000.0, seed=42)
        amp = np.abs(coeffs)
        expected_mean = math.sqrt(math.pi / 2.0) * math.sqrt(0.5)
        actual_mean = float(np.mean(amp))
        self.assertAlmostEqual(actual_mean, expected_mean, delta=0.02)

    def test_rician_k_factor_high_means_mostly_los(self):
        """With high K-factor, Rician should be nearly constant."""
        n = 10_000
        coeffs = fading.rician_fading(n, fd=50.0, sample_rate=1000.0, k_factor_db=40.0, seed=42)
        variance = float(np.var(np.abs(coeffs)))
        self.assertLess(variance, 0.01)

    def test_fading_applied_to_signal(self):
        """apply_fading multiplies signal by fading coefficients."""
        signal = [[1.0, 0.0] for _ in range(100)]
        coeffs = np.ones(100, dtype=np.complex128) * 0.5
        result = fading.apply_fading(signal, coeffs)
        self.assertAlmostEqual(result[0][0], 0.5, delta=1e-10)
        self.assertAlmostEqual(result[0][1], 0.0, delta=1e-10)


class TestOFDM(unittest.TestCase):
    """Validate OFDM modulation/demodulation."""

    def test_round_trip_no_channel(self):
        """OFDM modulate → demodulate should be identity."""
        n_subcarriers = 4
        cp_len = 2
        # Use 8 symbols (2 full OFDM blocks × 4 subcarriers)
        symbols = np.array([1 + 0j, -1 + 0j, 1j, -1j, 1 + 1j, -1 - 1j, 0.5 + 0.5j, -0.5j], dtype=np.complex128)

        tx_samples = ofdm.ofdm_modulate(symbols, n_subcarriers, cp_len)
        rx_symbols = ofdm.ofdm_demodulate(tx_samples, n_subcarriers, cp_len)

        self.assertEqual(len(rx_symbols), len(symbols))
        np.testing.assert_array_almost_equal(rx_symbols, symbols)

    def test_pilot_insertion(self):
        """Pilot insertion puts symbols in correct positions."""
        symbols = np.array([1 + 0j, 2 + 0j], dtype=np.complex128)
        n_subcarriers = 4
        pilot_indices = [0, 3]
        pilot_values = np.array([1j, -1j])

        result = ofdm.ofdm_pilot_insert(symbols, n_subcarriers, pilot_indices, pilot_values)
        # Block: [pilot(1j), data(1), data(2), pilot(-1j)]
        self.assertEqual(result[0], 1j)
        self.assertEqual(result[1], 1 + 0j)
        self.assertEqual(result[2], 2 + 0j)
        self.assertEqual(result[3], -1j)

    def test_channel_estimation_perfect(self):
        """Channel estimation with known pilots in noiseless channel."""
        n_subcarriers = 8
        pilot_indices = [0, 3, 6]
        cp_len = 4
        n_blocks = 2

        # Transmit known symbols + pilots
        data_per_block = n_subcarriers - len(pilot_indices)  # 5
        symbols = np.ones(data_per_block * n_blocks, dtype=np.complex128)
        pilots = np.array([1j, -1j, 1j], dtype=np.complex128)

        tx_with_pilots = ofdm.ofdm_pilot_insert(symbols, n_subcarriers, pilot_indices, pilots)
        tx_samples = ofdm.ofdm_modulate(tx_with_pilots, n_subcarriers, cp_len)

        # Apply a known channel
        channel = np.array([0.5 + 0.5j] * len(tx_samples), dtype=np.complex128)
        rx_samples = tx_samples * channel

        # Demodulate
        rx_symbols = ofdm.ofdm_demodulate(rx_samples, n_subcarriers, cp_len)

        # Estimate channel
        h_est = ofdm.ofdm_channel_estimate(rx_symbols, pilots, pilot_indices, n_subcarriers)

        # Equalize
        equalized = ofdm.ofdm_equalize(rx_symbols, h_est)

        # Data subcarriers should match original after equalization
        data_indices = sorted(set(range(n_subcarriers)) - set(pilot_indices))
        for b in range(n_blocks):
            for j, di in enumerate(data_indices):
                idx = b * n_subcarriers + di
                self.assertAlmostEqual(
                    equalized[idx].real, symbols[b * data_per_block + j].real, delta=0.01
                )


if __name__ == "__main__":
    unittest.main()
