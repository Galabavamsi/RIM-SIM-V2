"""Small-scale fading models: Rayleigh and Rician.

Generates time-correlated fading using the autoregressive (AR) method,
which guarantees correct Rayleigh statistics for any observation length.
"""

from __future__ import annotations

import math

import numpy as np


def rayleigh_fading(
    n_samples: int,
    fd: float,
    sample_rate: float,
    *,
    seed: int | None = None,
) -> np.ndarray:
    """Generate Rayleigh fading coefficients using AR(1) time correlation.

    Produces a time-varying complex channel coefficient with Rayleigh
    magnitude distribution (unit mean power) and exponential autocorrelation
    with coherence time approximately 1/fd.

    Args:
        n_samples: Number of fading samples to generate.
        fd: Maximum Doppler frequency in Hz.
        sample_rate: Sample rate in Hz.
        seed: RNG seed.

    Returns:
        Complex ndarray of length n_samples, unit mean power.
    """
    rng = np.random.RandomState(seed)

    # Burn-in to reach steady-state distribution
    burn_in = min(500, n_samples // 2)
    total_samples = n_samples + burn_in

    rho = math.exp(-2.0 * math.pi * fd / sample_rate)

    # Each complex sample = I + jQ. For unit complex power, each of I, Q needs
    # variance 0.5 in steady state. The innovation w ~ N(0, 0.5) per component.
    noise_std = math.sqrt(0.5)
    noise_i = rng.normal(0, noise_std, total_samples)
    noise_q = rng.normal(0, noise_std, total_samples)

    fading_all = np.zeros(total_samples, dtype=np.complex128)
    scale = math.sqrt(1.0 - rho * rho)
    fading_all[0] = complex(noise_i[0], noise_q[0])

    for k in range(1, total_samples):
        fading_i = rho * fading_all[k - 1].real + scale * noise_i[k]
        fading_q = rho * fading_all[k - 1].imag + scale * noise_q[k]
        fading_all[k] = complex(fading_i, fading_q)

    return fading_all[burn_in:]


def rician_fading(
    n_samples: int,
    fd: float,
    sample_rate: float,
    k_factor_db: float = 10.0,
    *,
    seed: int | None = None,
) -> np.ndarray:
    """Generate Rician fading coefficients.

    Rician = dominant LOS component + Rayleigh scatterers.
    Power ratio of LOS to scatterers = K (linear).

    Args:
        n_samples: Number of fading samples.
        fd: Maximum Doppler frequency in Hz.
        sample_rate: Sample rate in Hz.
        k_factor_db: K-factor in dB (ratio of LOS power to scatter power).
        seed: RNG seed.

    Returns:
        Complex ndarray with Rician fading (unit mean power).
    """
    k_linear = 10 ** (k_factor_db / 10.0)

    # Rayleigh (scatter) component
    scatter = rayleigh_fading(n_samples, fd, sample_rate, seed=seed)

    # LOS component
    los = np.ones(n_samples, dtype=np.complex128)

    # Combine with correct power ratios
    s = math.sqrt(k_linear / (k_linear + 1.0))
    sigma = math.sqrt(1.0 / (k_linear + 1.0))
    fading = s * los + sigma * scatter

    return fading


def apply_fading(
    samples: list[list[float]],
    fading_coeffs: np.ndarray,
) -> list[list[float]]:
    """Element-wise multiply IQ samples by time-varying fading coefficients.

    Args:
        samples: List of [I, Q] pairs.
        fading_coeffs: Complex fading coefficients (must be at least as long).

    Returns:
        Faded IQ samples.
    """
    if not samples:
        return samples

    n = len(samples)
    coeffs = fading_coeffs[:n]
    result = []
    for k, iq_pair in enumerate(samples):
        c = complex(iq_pair[0], iq_pair[1])
        faded = c * coeffs[k]
        result.append([float(faded.real), float(faded.imag)])
    return result
