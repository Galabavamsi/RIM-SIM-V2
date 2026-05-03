"""Parallel Monte Carlo execution for the RIS emulator.

Run hundreds of independent simulation trials across multiple CPU cores,
collecting statistical results (SNR distributions, BER curves, etc.).

Usage::

    from ris_sim.parallel import parallel_run, MonteCarloResult

    mc = MonteCarloResult()
    for output, seed in parallel_run(scenario, trials=100, workers=8):
        snr = _compute_snr(output)
        mc.record_snr(snr)

    mc.plot_snr_cdf("snr_cdf.png")
    print(f"Median SNR: {mc.snr_median:.1f} dB")
"""

from __future__ import annotations

import concurrent.futures
from typing import Any, Iterator

from ris_sim.parallel.result import MonteCarloResult  # noqa: F401
from ris_sim.parallel.worker import _run_single_trial


def parallel_run(
    scenario: dict[str, Any],
    trials: int = 100,
    workers: int | None = None,
    *,
    seeds: list[int] | None = None,
    show_progress: bool = False,
) -> Iterator[tuple[dict[str, Any], int]]:
    """Run simulation trials in parallel and yield results as they complete.

    Args:
        scenario: Scenario dict (same format as ``Simulation.from_scenario``).
            Must include a ``traffic`` section with TX/RX requests.
        trials: Number of independent trials to run.
        workers: Number of worker processes. Default: ``os.cpu_count()``.
        seeds: Custom seed list. Default: ``range(trials)``.
        show_progress: If True, print a progress line after each trial completes.

    Yields:
        Tuple of ``(output_dict, seed)`` where ``output_dict`` is the
        JSON-compatible output from :meth:`OutputBuffer.to_json_compatible`.

    Example::

        for output, seed in parallel_run(scenario, trials=50, workers=4):
            samples = flatten_iq_blocks(output["outputs"][0])
            print(f"Trial {seed}: {len(samples)} samples")
    """
    if seeds is None:
        seeds = list(range(trials))
    if len(seeds) != trials:
        raise ValueError(f"seeds length ({len(seeds)}) must match trials ({trials}).")

    workers = workers or 1
    completed = 0

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_seed = {
            executor.submit(_run_single_trial, scenario, seed): seed
            for seed in seeds
        }

        for future in concurrent.futures.as_completed(future_to_seed):
            seed = future_to_seed[future]
            try:
                output_dict = future.result()
            except Exception as exc:
                # Per-trial failure: report and continue
                output_dict = {
                    "error": str(exc),
                    "seed": seed,
                    "outputs": [],
                }
            yield output_dict, seed

            completed += 1
            if show_progress:
                print(f"\r  Monte Carlo: {completed}/{trials} trials complete", end="", flush=True)

    if show_progress:
        print()  # newline
