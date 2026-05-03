# Example Scenario Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable example workflow that turns a scenario JSON into an engine run, numerical output files, plots, and summary metrics.

**Architecture:** Keep the simulator core independent. Add small modules for scenario setup, output/result analysis, and plotting. The example runner adapts those modules to the current file-backed engine while preserving/restoring the working config.

**Tech Stack:** Python standard library, NumPy, Matplotlib, existing `json_store` and validation helpers.

---

### Task 1: Result Analysis Helpers

**Files:**
- Create: `ris_sim/modules/results.py`
- Test: `ris_sim/tests/test_results.py`

- [x] **Step 1: Write tests for IQ flattening, metrics, summary output, and NPZ export**

Run: `python tests\test_results.py -v`

Expected first result: fail because `modules.results` does not exist.

- [x] **Step 2: Implement `flatten_iq_blocks`, `compute_signal_metrics`, `summarize_output`, `write_summary`, and `save_output_npz`**

The helpers convert output JSON tick blocks into complex NumPy arrays and compact metrics.

- [x] **Step 3: Run tests**

Run: `python tests\test_results.py -v`

Expected result: all result tests pass.

### Task 2: Scenario Setup Helpers

**Files:**
- Create: `ris_sim/modules/scenario.py`
- Test: `ris_sim/tests/test_scenario.py`

- [x] **Step 1: Write tests for scenario application and request queuing**

Run: `python tests\test_scenario.py -v`

Expected first result: fail because `modules.scenario` does not exist.

- [x] **Step 2: Implement scenario conversion**

`apply_scenario` writes `room.json`, `ris.json`, `nodes.json`, and an empty `output.json`. `queue_traffic_requests` writes TX/RX requests into nodes.

- [x] **Step 3: Run tests**

Run: `python tests\test_scenario.py -v`

Expected result: all scenario tests pass.

### Task 3: Plotting Helpers

**Files:**
- Create: `ris_sim/modules/plotting.py`
- Test: `ris_sim/tests/test_plotting.py`

- [x] **Step 1: Write tests that verify PNG files are created**

Run: `python tests\test_plotting.py -v`

Expected first result: fail because `modules.plotting` does not exist.

- [x] **Step 2: Implement Matplotlib plotting helpers**

Add room topology, RIS heatmap, IQ time series, constellation, and power plots using the `Agg` backend.

- [x] **Step 3: Run tests**

Run: `python tests\test_plotting.py -v`

Expected result: all plotting tests pass.

### Task 4: Two-Node RIS Example

**Files:**
- Create: `examples/two_node_ris/scenario.json`
- Create: `examples/two_node_ris/run_example.py`
- Create: `examples/two_node_ris/README.md`
- Modify: `requirements.txt`

- [x] **Step 1: Add a static two-node RIS scenario**

Use one TX, one RX, one `16 x 16` RIS, and a BPSK burst.

- [x] **Step 2: Add the runner**

The runner backs up config, applies the scenario, runs the engine, exports `output.json`, `summary.json`, `result.npz`, plots, and restores config.

- [x] **Step 3: Add documentation and dependency**

Document the run command and artifacts. Add `matplotlib>=3.7` to `requirements.txt`.

- [x] **Step 4: Smoke run**

Run: `python examples\two_node_ris\run_example.py --run-dir examples\two_node_ris\runs\smoke`

Expected result: run artifacts and plots are created.
