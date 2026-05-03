"""Deterministic random number generation for reproducible simulations.

A master seed is split into independent sub-seeds for each stochastic
component (mobility, noise, fading, impairments) using a simple counter
scheme. This ensures bit-identical output when the same master seed is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.random import RandomState

MAX_SEED = 2**31 - 1


class SeedSequence:
    def __init__(self, master_seed: int | None):
        self._master = master_seed
        self._counter = 0
        if master_seed is not None:
            self._rng: RandomState | None = np.random.RandomState(master_seed)
        else:
            self._rng = None

    def next(self) -> int | None:
        """Return a derived seed for the next stochastic component."""
        if self._master is None or self._rng is None:
            return None
        seed = int(self._rng.randint(0, MAX_SEED))
        self._counter += 1
        return seed

    def next_tick(self, tick: int) -> int | None:
        """Return a seed deterministically derived from tick index.

        This ensures that the same tick always gets the same random state
        for a given master seed, regardless of call order.
        """
        if self._master is None:
            return None
        return int((self._master * 1103515245 + tick * 12345 + self._counter) % MAX_SEED)

    @property
    def master(self) -> int | None:
        return self._master
