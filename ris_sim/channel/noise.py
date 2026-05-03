"""Configurable AWGN noise generator for the RIS emulator."""

from __future__ import annotations

import math

import numpy as np


def thermal_noise_power(bandwidth_hz: float, temperature_k: float = 290.0) -> float:
    """Thermal noise power in watts: P = k * T * B.

    Args:
        bandwidth_hz: Bandwidth in Hz (typically sample_rate / 2 for baseband).
        temperature_k: Temperature in Kelvin (default 290K = ~17°C).

    Returns:
        Noise power in linear watts.
    """
    k = 1.380649e-23  # Boltzmann constant
    return k * temperature_k * bandwidth_hz


def noise_scale_from_db(
    bandwidth_hz: float,
    noise_figure_db: float = 0.0,
    temperature_k: float = 290.0,
) -> float:
    """Compute per-I/Q-component AWGN standard deviation.

    The total noise power is k*T*B*NF. Split equally between I and Q
    components, so each gets half the power: sigma = sqrt(P_noise / 2).

    Args:
        bandwidth_hz: Bandwidth in Hz.
        noise_figure_db: Receiver noise figure in dB.
        temperature_k: Temperature in Kelvin.

    Returns:
        Standard deviation for np.random.normal per I/Q component.
    """
    p_noise = thermal_noise_power(bandwidth_hz, temperature_k)
    nf_linear = 10 ** (noise_figure_db / 10.0)
    total_power = p_noise * nf_linear
    return math.sqrt(total_power / 2.0)


def add_awgn(
    samples: list[list[float]],
    bandwidth_hz: float,
    noise_figure_db: float = 0.0,
    temperature_k: float = 290.0,
    *,
    seed: int | None = None,
) -> list[list[float]]:
    """Add Additive White Gaussian Noise to a block of IQ samples.

    Args:
        samples: List of [I, Q] pairs.
        bandwidth_hz: Noise bandwidth in Hz (typically sample_rate / 2).
        noise_figure_db: Receiver noise figure in dB.
        temperature_k: Temperature in Kelvin.
        seed: RNG seed for reproducibility.

    Returns:
        IQ samples with AWGN added.
    """
    if not samples:
        return samples

    sigma = noise_scale_from_db(bandwidth_hz, noise_figure_db, temperature_k)
    return add_awgn_scaled(samples, sigma, seed=seed)


def add_awgn_scaled(
    samples: list[list[float]],
    sigma: float,
    *,
    seed: int | None = None,
) -> list[list[float]]:
    """Add AWGN with explicit sigma per I/Q component.

    Args:
        samples: List of [I, Q] pairs.
        sigma: Standard deviation of the Gaussian noise per component.
        seed: RNG seed.

    Returns:
        IQ samples with AWGN added.
    """
    if sigma <= 0 or not samples:
        return samples

    rng = np.random.RandomState(seed)
    n = len(samples)
    noise_i = rng.normal(0, sigma, n)
    noise_q = rng.normal(0, sigma, n)

    result = []
    for k, (iq_pair, ni, nq) in enumerate(zip(samples, noise_i, noise_q)):
        result.append([float(iq_pair[0]) + float(ni), float(iq_pair[1]) + float(nq)])
    return result
