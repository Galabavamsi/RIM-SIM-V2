"""RF impairment models for the RIS emulator.

All functions operate on lists of [I, Q] pairs and return the same format.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def _to_complex(samples: Sequence[Sequence[float]]) -> np.ndarray:
    return np.array([complex(s[0], s[1]) for s in samples], dtype=np.complex128)


def _to_iq_pairs(complex_samples: np.ndarray) -> list[list[float]]:
    return [[float(v.real), float(v.imag)] for v in complex_samples]


def apply_cfo(
    samples: list[list[float]],
    cfo_hz: float,
    sample_rate: float,
    cumulative_time_s: float = 0.0,
    *,
    tick_index: int = 0,
    tau: float = 0.002,
) -> list[list[float]]:
    """Apply carrier frequency offset as a rotating phasor.

    The CFO introduces a time-varying phase rotation: ``exp(j * 2*pi * cfo * t)``.

    Args:
        samples: List of [I, Q] pairs.
        cfo_hz: Carrier frequency offset in Hz.
        sample_rate: Sample rate in Hz.
        cumulative_time_s: Cumulative time offset in seconds (overrides tick_index+tau).
        tick_index: Current simulation tick (used with tau if cumulative_time_s not set).
        tau: Tick duration in seconds.

    Returns:
        CFO-rotated IQ samples.
    """
    if cfo_hz == 0.0 or not samples:
        return samples

    if cumulative_time_s == 0.0:
        cumulative_time_s = tick_index * tau

    c = _to_complex(samples)
    n_samps = len(c)
    t = cumulative_time_s + np.arange(n_samps) / sample_rate
    phase = 2.0 * math.pi * cfo_hz * t
    rotated = c * np.exp(1j * phase)
    return _to_iq_pairs(rotated)


def apply_phase_noise(
    samples: list[list[float]],
    sample_rate: float,
    phase_noise_dbc_hz: float = -90.0,
    seed: int | None = None,
) -> list[list[float]]:
    """Apply oscillator phase noise using a Wiener process model.

    Args:
        samples: List of [I, Q] pairs.
        sample_rate: Sample rate in Hz.
        phase_noise_dbc_hz: Single-sideband phase noise at some offset (approximate).
        seed: RNG seed for reproducibility.

    Returns:
        IQ samples with phase noise applied.
    """
    if not samples:
        return samples

    rng = np.random.RandomState(seed)
    c = _to_complex(samples)
    n = len(c)

    # Approximate phase noise variance per sample
    # Higher phase_noise_dbc_hz (less negative) = more noise
    phase_std = 10 ** (phase_noise_dbc_hz / 20) * math.sqrt(sample_rate)
    phase_wander = rng.normal(0, max(phase_std, 1e-15), n).cumsum()

    noisy = c * np.exp(1j * phase_wander)
    return _to_iq_pairs(noisy)


def apply_iq_imbalance(
    samples: list[list[float]],
    amplitude_imbalance_db: float = 0.0,
    phase_imbalance_deg: float = 0.0,
) -> list[list[float]]:
    """Apply I/Q imbalance: gain mismatch and phase skew.

    Model: I' = I * sqrt(g),  Q' = Q / sqrt(g) + I * sin(phi)
    where g = 10^(amplitude_imbalance_db / 20) is the I/Q gain ratio,
    and phi is the phase skew in radians.

    For A dB imbalance, I is A dB stronger than Q, so I' gets +A/2 dB
    and Q' gets -A/2 dB relative to the ideal.

    Args:
        samples: List of [I, Q] pairs.
        amplitude_imbalance_db: I/Q gain ratio in dB.
        phase_imbalance_deg: Phase skew in degrees.

    Returns:
        IQ samples with imbalance applied.
    """
    if not samples:
        return samples
    if amplitude_imbalance_db == 0.0 and phase_imbalance_deg == 0.0:
        return samples

    arr = np.array(samples, dtype=np.float64)
    i_vals = arr[:, 0]
    q_vals = arr[:, 1]

    g = 10 ** (amplitude_imbalance_db / 20.0)  # I/Q gain ratio
    phi = math.radians(phase_imbalance_deg)

    i_new = i_vals * math.sqrt(g)
    q_new = q_vals / math.sqrt(g) + i_vals * math.sin(phi)

    return [[float(i_new[k]), float(q_new[k])] for k in range(len(samples))]


def apply_sfo(
    samples: list[list[float]],
    sample_rate: float,
    sfo_ppm: float = 0.0,
) -> list[list[float]]:
    """Apply sample frequency offset via linear resampling.

    The effective sample rate becomes ``sample_rate * (1 + sfo_ppm / 1e6)``.

    Args:
        samples: List of [I, Q] pairs.
        sample_rate: Sample rate in Hz.
        sfo_ppm: Sample frequency offset in parts per million.

    Returns:
        IQ samples at the new effective rate.
    """
    if sfo_ppm == 0.0 or not samples:
        return samples

    c = _to_complex(samples)
    n = len(c)
    ratio = 1.0 + sfo_ppm / 1e6
    new_n = max(1, int(round(n * ratio)))
    old_indices = np.linspace(0, n - 1, new_n)

    # Linear interpolation
    floor_idx = np.floor(old_indices).astype(int)
    ceil_idx = np.minimum(floor_idx + 1, n - 1)
    frac = old_indices - floor_idx

    result = c[floor_idx] * (1 - frac) + c[ceil_idx] * frac
    return _to_iq_pairs(result)


def apply_impairments(
    samples: list[list[float]],
    sample_rate: float,
    impairments: dict,
    *,
    tick_index: int = 0,
    tau: float = 0.002,
    seed: int | None = None,
) -> list[list[float]]:
    """Apply a pipeline of RF impairments in physically correct order.

    Order: CFO → Phase Noise → IQ Imbalance → SFO

    Args:
        samples: List of [I, Q] pairs.
        sample_rate: Sample rate in Hz.
        impairments: Dict of impairment parameters (cfo_hz, phase_noise_dbc_hz,
                     amplitude_imbalance_db, phase_imbalance_deg, sfo_ppm).
        tick_index: Current simulation tick.
        tau: Tick duration.
        seed: RNG seed.

    Returns:
        Impaired IQ samples.
    """
    result = list(samples)

    cfo_hz = float(impairments.get("cfo_hz", 0.0))
    if cfo_hz != 0.0:
        result = apply_cfo(result, cfo_hz, sample_rate, tick_index=tick_index, tau=tau)

    phase_noise = float(impairments.get("phase_noise_dbc_hz", 0.0))
    if phase_noise != 0.0:
        result = apply_phase_noise(result, sample_rate, phase_noise, seed=seed)

    amp_imbal = float(impairments.get("amplitude_imbalance_db", 0.0))
    phase_imbal = float(impairments.get("phase_imbalance_deg", 0.0))
    if amp_imbal != 0.0 or phase_imbal != 0.0:
        result = apply_iq_imbalance(result, amp_imbal, phase_imbal)

    sfo_ppm = float(impairments.get("sfo_ppm", 0.0))
    if sfo_ppm != 0.0:
        result = apply_sfo(result, sample_rate, sfo_ppm)

    return result


def apply_pa_nonlinearity(
    samples: list[list[float]],
    model: str = "rapp",
    p_sat_db: float = 30.0,
    smoothness: float = 2.0,
    gain_db: float = 0.0,
) -> list[list[float]]:
    """Apply power amplifier nonlinearity.

    Models: Rapp (solid-state PA) or soft-limiter (clipping).

    Rapp model: A_out = A_in * gain / (1 + (A_in * gain / A_sat)^(2p))^(1/(2p))
    where p = smoothness, A_sat = saturation amplitude.

    Args:
        samples: List of [I, Q] pairs.
        model: "rapp" or "soft_limiter".
        p_sat_db: Saturation power in dB relative to linear scale.
        smoothness: Rapp smoothness factor (>0, higher = sharper knee).
        gain_db: Linear gain in dB.

    Returns:
        PA-distorted IQ samples.
    """
    if not samples:
        return samples

    if model == "none":
        return samples

    c = _to_complex(samples)
    amplitude = np.abs(c)
    phase = np.angle(c)

    gain_linear = 10 ** (gain_db / 20.0)
    a_sat = 10 ** (p_sat_db / 20.0)

    if model == "rapp":
        denominator = (1.0 + (amplitude * gain_linear / a_sat) ** (2.0 * smoothness)) ** (1.0 / (2.0 * smoothness))
        a_out = amplitude * gain_linear / denominator
    elif model == "soft_limiter":
        a_out = a_sat * np.tanh(amplitude * gain_linear / a_sat)
    else:
        raise ValueError(f"Unknown PA model: {model!r}")

    result = a_out * np.exp(1j * phase)
    return _to_iq_pairs(result)


def apply_tx_impairments(
    samples: list[list[float]],
    sample_rate: float,
    impairments: dict,
    *,
    tick_index: int = 0,
    tau: float = 0.002,
    seed: int | None = None,
) -> list[list[float]]:
    """Apply TX-side impairments in physically correct order.

    TX order: SFO → IQ Imbalance → PA nonlinearity → (channel)
    """
    result = list(samples)

    sfo_ppm = float(impairments.get("sfo_ppm", 0.0))
    if sfo_ppm != 0.0:
        result = apply_sfo(result, sample_rate, sfo_ppm)

    amp_imbal = float(impairments.get("amplitude_imbalance_db", 0.0))
    phase_imbal = float(impairments.get("phase_imbalance_deg", 0.0))
    if amp_imbal != 0.0 or phase_imbal != 0.0:
        result = apply_iq_imbalance(result, amp_imbal, phase_imbal)

    pa_model = impairments.get("pa_model", "none")
    if isinstance(pa_model, dict):
        result = apply_pa_nonlinearity(
            result,
            model=pa_model.get("type", "rapp"),
            p_sat_db=float(pa_model.get("p_sat_db", 30.0)),
            smoothness=float(pa_model.get("smoothness", 2.0)),
            gain_db=float(pa_model.get("gain_db", 0.0)),
        )
    elif pa_model != "none":
        result = apply_pa_nonlinearity(result, model=str(pa_model))

    return result


def apply_rx_impairments(
    samples: list[list[float]],
    sample_rate: float,
    impairments: dict,
    *,
    tick_index: int = 0,
    tau: float = 0.002,
    seed: int | None = None,
) -> list[list[float]]:
    """Apply RX-side impairments in physically correct order.

    RX order: CFO → Phase Noise → IQ Imbalance → SFO
    """
    result = list(samples)

    cfo_hz = float(impairments.get("cfo_hz", 0.0))
    if cfo_hz != 0.0:
        result = apply_cfo(result, cfo_hz, sample_rate, tick_index=tick_index, tau=tau)

    phase_noise = float(impairments.get("phase_noise_dbc_hz", 0.0))
    if phase_noise != 0.0:
        result = apply_phase_noise(result, sample_rate, phase_noise, seed=seed)

    amp_imbal = float(impairments.get("amplitude_imbalance_db", 0.0))
    phase_imbal = float(impairments.get("phase_imbalance_deg", 0.0))
    if amp_imbal != 0.0 or phase_imbal != 0.0:
        result = apply_iq_imbalance(result, amp_imbal, phase_imbal)

    sfo_ppm = float(impairments.get("sfo_ppm", 0.0))
    if sfo_ppm != 0.0:
        result = apply_sfo(result, sample_rate, sfo_ppm)

    return result
