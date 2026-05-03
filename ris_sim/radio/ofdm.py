"""OFDM modulation and demodulation for the RIS emulator.

Supports configurable subcarrier count, cyclic prefix length, and
pilot-based channel estimation.
"""

from __future__ import annotations

import math

import numpy as np


def ofdm_modulate(
    symbols: np.ndarray,
    n_subcarriers: int,
    cp_len: int,
) -> np.ndarray:
    """OFDM modulate: serial→parallel, IFFT, add cyclic prefix.

    Args:
        symbols: Complex symbols to modulate, length must be multiple of n_subcarriers.
        n_subcarriers: Number of subcarriers per OFDM symbol.
        cp_len: Cyclic prefix length in samples.

    Returns:
        Complex IQ samples ready for transmission.
    """
    if len(symbols) % n_subcarriers != 0:
        raise ValueError(
            f"Number of symbols ({len(symbols)}) must be a multiple of n_subcarriers ({n_subcarriers})."
        )

    n_symbols = len(symbols) // n_subcarriers
    output = []

    for i in range(n_symbols):
        block = symbols[i * n_subcarriers : (i + 1) * n_subcarriers]
        # IFFT
        time_domain = np.fft.ifft(block, n=n_subcarriers) * math.sqrt(n_subcarriers)
        # Add cyclic prefix
        with_cp = np.concatenate([time_domain[-cp_len:], time_domain])
        output.append(with_cp)

    return np.concatenate(output)


def ofdm_demodulate(
    samples: np.ndarray,
    n_subcarriers: int,
    cp_len: int,
) -> np.ndarray:
    """OFDM demodulate: remove CP, FFT, parallel→serial.

    Args:
        samples: Received complex IQ samples.
        n_subcarriers: Number of subcarriers per OFDM symbol.
        cp_len: Cyclic prefix length in samples.

    Returns:
        Complex received symbols (length is multiple of n_subcarriers).
    """
    symbol_len = n_subcarriers + cp_len
    n_symbols = len(samples) // symbol_len
    output = []

    for i in range(n_symbols):
        with_cp = samples[i * symbol_len : (i + 1) * symbol_len]
        # Remove CP
        time_domain = with_cp[cp_len:]
        # FFT
        freq_domain = np.fft.fft(time_domain, n=n_subcarriers) / math.sqrt(n_subcarriers)
        output.append(freq_domain)

    if not output:
        return np.array([], dtype=np.complex128)
    return np.concatenate(output)


def ofdm_pilot_insert(
    symbols: np.ndarray,
    n_subcarriers: int,
    pilot_indices: list[int],
    pilot_values: np.ndarray | list[complex] | None = None,
) -> np.ndarray:
    """Insert known pilot symbols at specified subcarrier indices.

    Args:
        symbols: Data symbols to transmit. Length = n_data_symbols_per_block * n_blocks.
        n_subcarriers: Total subcarriers per block.
        pilot_indices: Subcarrier indices where pilots are placed.
        pilot_values: Pilot values (complex). If None, uses [1+0j, 1+0j, ...].

    Returns:
        Symbols with pilots inserted. Length = (n_subcarriers * n_blocks).
    """
    n_data_per_block = n_subcarriers - len(pilot_indices)
    n_blocks = len(symbols) // n_data_per_block

    if pilot_values is None:
        pilot_values = [1.0 + 0j] * len(pilot_indices)
    pilot_values = np.asarray(pilot_values, dtype=np.complex128)

    data_indices = sorted(set(range(n_subcarriers)) - set(pilot_indices))
    output = []

    for b in range(n_blocks):
        block = np.zeros(n_subcarriers, dtype=np.complex128)
        block[data_indices] = symbols[b * n_data_per_block : (b + 1) * n_data_per_block]
        block[pilot_indices] = pilot_values
        output.append(block)

    return np.concatenate(output)


def ofdm_channel_estimate(
    rx_symbols: np.ndarray,
    tx_pilots: np.ndarray,
    pilot_indices: list[int],
    n_subcarriers: int,
) -> np.ndarray:
    """Least-squares channel estimation from pilot subcarriers with linear interpolation.

    Args:
        rx_symbols: Received symbols (after OFDM demodulation). Shape (n_subcarriers * n_blocks,).
        tx_pilots: Transmitted pilot values. Shape (n_pilots,) or (n_pilots * n_blocks,).
        pilot_indices: Subcarrier indices of pilots.
        n_subcarriers: Total subcarriers per block.

    Returns:
        Estimated channel for all subcarriers. Shape (n_subcarriers * n_blocks,).
    """
    n_pilots = len(pilot_indices)
    n_blocks = len(rx_symbols) // n_subcarriers

    if len(tx_pilots) == n_pilots:
        tx_pilots = np.tile(tx_pilots, n_blocks)

    h_est_per_block = np.zeros((n_blocks, n_subcarriers), dtype=np.complex128)

    for b in range(n_blocks):
        start = b * n_subcarriers
        rx_block = rx_symbols[start : start + n_subcarriers]
        tx_p = tx_pilots[b * n_pilots : (b + 1) * n_pilots]

        # LS estimate at pilot positions
        h_pilots = rx_block[pilot_indices] / tx_p

        # Linear interpolation across subcarriers
        pilot_idx_sorted = np.array(sorted(pilot_indices))
        all_subcarriers = np.arange(n_subcarriers)
        h_est_per_block[b] = np.interp(
            all_subcarriers, pilot_idx_sorted, np.abs(h_pilots)
        ) * np.exp(1j * np.interp(
            all_subcarriers, pilot_idx_sorted, np.angle(h_pilots)
        ))

    return h_est_per_block.ravel()


def ofdm_equalize(
    rx_symbols: np.ndarray,
    channel_estimate: np.ndarray,
) -> np.ndarray:
    """Zero-forcing equalization: rx / h_est.

    Args:
        rx_symbols: Received symbols.
        channel_estimate: Estimated channel (same length).

    Returns:
        Equalized symbols.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        equalized = np.where(channel_estimate != 0, rx_symbols / channel_estimate, 0j)
    return equalized


def ofdm_total_samples(
    n_data_symbols: int,
    n_subcarriers: int,
    n_pilots: int,
    cp_len: int,
) -> int:
    """Compute total IQ samples for an OFDM transmission.

    Args:
        n_data_symbols: Number of data (QAM/PSK) symbols.
        n_subcarriers: Subcarriers per OFDM symbol.
        n_pilots: Number of pilot subcarriers per OFDM symbol.
        cp_len: Cyclic prefix length.

    Returns:
        Total IQ sample count.
    """
    n_data_per_block = n_subcarriers - n_pilots
    n_blocks = int(math.ceil(n_data_symbols / n_data_per_block))
    return n_blocks * (n_subcarriers + cp_len)
