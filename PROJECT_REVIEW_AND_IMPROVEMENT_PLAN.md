# Project Review And Improvement Plan

## Context

This repository is a hand-written Python prototype for an open emulator for smart radio environments, centered on RIS-assisted wireless communication. It corresponds to the paper `An_Open_Emulator_for_Smart_Radio_Environments__ANTS2025 (1).pdf` and implements a local emulator that mimics SDR-style transmit/receive behavior, node mobility, channel propagation, and RIS control using JSON-backed state files.

The project is best understood as a research artifact:

- The paper describes the emulator architecture and intended interfaces.
- The codebase implements a compact working prototype by hand.
- The current implementation is local and file-driven rather than a production service.
- The strongest next step is to stabilize correctness, timing, IPC, and physical modeling before adding more features.

## Current Architecture

Main runtime pieces:

- `ris_sim/core/engine.py`: main discrete-time event loop.
- `ris_sim/modules/simulator_functions.py`: SDR-like API helpers for transmit and receive requests.
- `ris_sim/modules/channel_functions.py`: LOS/NLOS channel processing, RIS gain, pulse shaping/downconversion logic.
- `ris_sim/modules/mobility_functions.py`: node movement models.
- `ris_sim/external_traffic/usrp_tx.py`: demo transmitter script.
- `ris_sim/external_traffic/usrp_rx.py`: demo receiver script.
- `ris_sim/external_traffic/dummy_rsc.py`: dummy RIS controller.
- `ris_sim/config/*.json`: file-based simulator state and configuration.

Current data flow:

1. External scripts write requests into `config/nodes.json`.
2. The engine reads `nodes.json`, `ris.json`, `room.json`, and `output.json`.
3. Each simulation tick updates RIS config, node mobility, request state, and received samples.
4. Results are appended to `config/output.json`.

## Security Scan Summary

A repository-wide security scan was completed and saved under:

`./.codex-security-scans/An-Emulator-for-Smart-Radio-Environment/nogit_20260503_060007/report.md`

Two reportable availability findings survived validation:

1. **P2 / medium: unvalidated request timing and sample sizing**
   - `sample_rate`, `num_samps`, and transmit data are accepted without bounds or type checks.
   - Bad values can crash the engine, keep nodes from returning to idle, or amplify CPU/disk usage.

2. **P3 / low: unbounded RIS array size**
   - `array_size` controls nested allocation and per-element channel processing.
   - Large or malformed RIS configs can exhaust CPU/memory or crash the emulator.

The scan did **not** find evidence of:

- Shell command injection.
- Unsafe deserialization.
- SQL/NoSQL injection.
- SSRF.
- Web auth/session issues.
- Arbitrary file path traversal.

The security risk is mainly availability and robustness, not remote compromise, because the current repo is a local emulator and does not expose a network service.

## Critical Correctness Bugs

### 1. TX-only simulations never complete

Location:

- `ris_sim/core/engine.py:259-264`

Problem:

Transmitters are decremented only when a receiver consumes their ID through `all_used_ids`. If a transmit request exists without a matching receiver, the transmitter remains in `transmit` forever and the engine never reaches `all_idle`.

Impact:

- Infinite loop.
- Engine hangs.
- Simulation cannot complete for TX-only or unmatched-frequency scenarios.

Fix:

- Advance TX duration every tick independently of whether a receiver exists.
- Treat transmission state as time-based, not receiver-consumption-based.

### 2. Tail samples are dropped

Location:

- `ris_sim/core/engine.py:111`
- `ris_sim/core/engine.py:169-172`

Problem:

`req_time` is computed using:

```python
int(len(node['data'][0]) / (node['sample_rate'] * tau))
```

but per-tick processing uses:

```python
tau_samp = int(node['sample_rate'] * tau)
```

These two floored calculations do not match. With the current demo values:

- Packet length: `2389`
- Sample rate: `5880`
- `tau = 0.002`
- `tau_samp = 11`
- Current `req_time = 203`
- Samples processed: `203 * 11 = 2233`
- Dropped tail: `156` samples

Impact:

- Silent data loss.
- Incorrect received output.
- Simulation results become unreliable.

Fix:

- Compute `tau_samp` once.
- Use `ceil(total_samples / tau_samp)`.
- Or better: track remaining samples directly and stop when the data buffer is empty.

### 3. Final padding shape crashes channel processing

Location:

- `ris_sim/core/engine.py:175-180`
- `ris_sim/modules/channel_functions.py:327`

Problem:

The final partial transmit block is padded with scalar `0` values:

```python
padding.append(0)
```

but channel processing expects each sample to be a two-item IQ pair:

```python
complex(sample[0], sample[1])
```

Impact:

- Final partial block can crash with `TypeError: int object is not subscriptable`.

Fix:

- Pad with `[0, 0]`.
- Or convert the internal representation to complex numbers and keep it consistent everywhere.

### 4. Receive-only or no-TX receive behavior is incomplete

Location:

- `ris_sim/core/engine.py:203-225`

Problem:

If a receiver is active but no transmitter is available on the same frequency, `output_data` remains empty.

Impact:

- A receive request may return empty chunks rather than noise or zeros.
- Output length may not match requested sample count.
- SDR-like behavior is violated.

Fix:

- If no TX exists, append a block of zeros or receiver noise with exactly `tau_samp` samples.
- Keep output length deterministic.

### 5. `req_time == 0` terminal check is fragile

Location:

- `ris_sim/core/engine.py:249`
- `ris_sim/core/engine.py:264`

Problem:

The engine only resets a node when `req_time == 0`. Invalid or edge-case values can jump below zero and never reset.

Examples:

- `num_samps = 0` gives `req_time = 0`, then decrements to `-1`.
- Negative sample rate gives negative `req_time`.

Impact:

- Node may never return to idle.
- Engine may hang.

Fix:

- Validate inputs before accepting requests.
- Use `req_time <= 0` as a defensive terminal condition.

## Race Conditions And IPC Problems

### 1. JSON state updates race

Locations:

- `ris_sim/modules/simulator_functions.py:12-34`
- `ris_sim/modules/simulator_functions.py:45-59`
- `ris_sim/core/engine.py`

Problem:

The engine and external scripts repeatedly perform read-modify-write cycles on the same JSON files:

- `nodes.json`
- `ris.json`
- `output.json`

There is no:

- File lock.
- Atomic replace.
- Request queue.
- Transaction boundary.
- Version check.

Impact:

- TX and RX requests can overwrite each other.
- Engine can read partially written JSON.
- Output can be corrupted.
- Updates can be lost.

Fix options:

1. Short-term:
   - Add file locks.
   - Write to a temp file, then atomic replace.
   - Keep one writer per file.

2. Medium-term:
   - Use SQLite for state and request queues.
   - Use separate request files per node and atomic rename.

3. Long-term:
   - Use sockets, ZeroMQ, multiprocessing queues, or a proper message bus.

### 2. `output.json` is rewritten every tick

Location:

- `ris_sim/core/engine.py:230-244`

Problem:

The engine loads the entire output file, appends one chunk, and writes the entire file back every tick.

Impact:

- Very slow for long simulations.
- Memory grows with output history.
- Higher chance of corruption during concurrent access.

Fix:

- Stream output as JSONL, HDF5, NumPy `.npy`, Zarr, or chunked files.
- Store metadata separately from sample arrays.

## DSP And Signal Processing Issues

### 1. Channel filter breaks for many valid sample rates

Location:

- `ris_sim/modules/channel_functions.py:236-297`

Problem:

The channel model hardcodes:

```python
Fs = 60000
```

Then it derives:

```python
Ts = tau / len(complex_data)
BN = 1 / (2 * Ts)
cutoff = 5 * BN
lowpass = scipy.signal.firwin(lowpass_order, cutoff / (Fs / 2))
```

For many normal sample rates, `cutoff / (Fs / 2)` exceeds `1`, which makes `firwin` invalid.

Examples:

- `sample_rate = 24000` gives normalized cutoff about `2.0`.
- `sample_rate = 44100` gives normalized cutoff about `3.67`.

Impact:

- Channel processing crashes for many valid sample rates.
- The emulator is tied to a narrow hidden rate regime.

Fix:

- Pass the actual `sample_rate` into `process_samples` and `signal`.
- Use `Fs = sample_rate` or a deliberate internal oversampling rate.
- Ensure filter cutoff is below Nyquist.
- Validate sample rates before processing.

### 2. Incoming IQ samples are treated like symbols

Location:

- `ris_sim/modules/channel_functions.py:249-255`

Problem:

`process_samples` receives IQ samples, but `signal` treats them like discrete symbols and applies pulse shaping again.

Impact:

- If the input is already sampled IQ, the signal is shaped twice.
- Timing and bandwidth become physically inconsistent.

Fix:

- Decide whether the API accepts symbols or IQ samples.
- If it accepts symbols, rename and document it.
- If it accepts IQ samples, do not run symbol pulse shaping again.

### 3. Receiver output length is not guaranteed

Location:

- `ris_sim/modules/channel_functions.py:315`

Problem:

The function returns:

```python
y_output = y_samples[:N]
```

but earlier filter delays, invalid `ups`, and convolution lengths can reduce or distort the output.

Impact:

- Receive output may not contain exactly the requested number of IQ samples.

Fix:

- Add explicit length guarantees.
- Pad/truncate deterministically at the final API boundary.
- Add tests that assert exact sample count.

### 4. Noise is disabled

Location:

- `ris_sim/core/engine.py:227-228`

Problem:

Noise is commented out:

```python
# output_data = channel.noise(output_data, tau_samp)
```

Impact:

- No-TX reception does not model receiver noise.
- SNR experiments are not meaningful.

Fix:

- Add configurable AWGN.
- Support noise figure, thermal noise, bandwidth, and receiver gain later.

## Physical Modeling Issues

### 1. LOS path loss is oversimplified

Location:

- `ris_sim/modules/channel_functions.py:288-289`

Problem:

Downconversion divides by `distance`, but free-space path loss depends on wavelength and usually scales in received power as roughly `1 / d^2`, with field amplitude roughly `1 / d`.

Impact:

- Results may not scale correctly with frequency.
- Changing carrier frequency does not produce realistic path loss.

Fix:

- Use a clear baseband channel coefficient:

```text
h_los = sqrt(path_gain) * exp(-j * 2*pi*d / lambda)
```

- Use Friis/free-space path loss for baseline LOS.

### 2. RIS incidence/reflection direction is physically suspect

Location:

- `ris_sim/modules/channel_functions.py:194-216`

Problem:

The incidence vector is computed as:

```python
r_in_vec = element_coordinate - tx_location
```

Then negative cosine values are converted using:

```python
abs(cos(phi))
```

This can allow back-side illumination or reflection to contribute instead of rejecting it or modeling the correct orientation.

Impact:

- RIS may reflect energy from physically invalid directions.
- Surface orientation becomes less meaningful.

Fix:

- Use signed incident and reflection vectors consistently.
- Reject or attenuate paths on the wrong side of the RIS plane.
- Only use `abs` if the physical model explicitly calls for it.

### 3. `nlos_element` phase has a complex exponential inside another exponential

Location:

- `ris_sim/modules/channel_functions.py:92-95`

Problem:

`phi_n_phase` is already complex:

```python
phi_n_phase = np.exp(2j * ...)
```

Then it is used inside another exponential:

```python
np.exp(1j * phi_n_phase)
```

Impact:

- This is mathematically wrong for a normal phase term.
- It is probably why the newer `total_nlos_gain` function does a different calculation.

Fix:

- Remove or rewrite `nlos_element`.
- Use phase angle directly:

```python
phase = -2 * np.pi * fc * path_length / c
gain = amplitude * np.exp(1j * phase)
```

### 4. RIS `phase_response` is ignored

Location:

- `ris_sim/modules/channel_functions.py:133-148`
- `ris_sim/config/ris.json`

Problem:

`phase_matrix_gen` uses:

```python
np.exp(np.pi/4 * 1j) * element_config
```

It does not use the configured `phase_response` table.

Impact:

- RIS configuration states do not map to realistic phase/gain values.
- `ris.json` contains data that is not actually used.

Fix:

- Define each element state as a complex reflection coefficient:

```text
Gamma_n = gain(state, f, angle) * exp(j * phase(state, f, angle))
```

- Use `phase_response` and add `gain_response`.

### 5. RIS dimensions and array geometry need validation

Location:

- `ris_sim/config/ris.json`
- `ris_sim/modules/channel_functions.py:108-130`

Problems:

- No cap on `array_size`.
- No validation of positive unit-cell lengths.
- No check that `configuration_matrix` matches `array_size`.
- Coordinate generation builds full nested matrices every tick.

Fix:

- Validate RIS schema.
- Precompute element coordinates once unless RIS geometry changes.
- Store arrays as NumPy arrays instead of nested Python lists.

## Mobility Model Issues

### 1. Room height is loaded but unused

Location:

- `ris_sim/core/engine.py:21-23`

Problem:

The engine loads `room_height`, but mobility clamps only x/y.

Impact:

- z-coordinate can be outside bounds.
- 3D room config is only partially enforced.

Fix:

- Either document all mobility as 2D with fixed z, or clamp/check z as well.

### 2. Node starts outside the room

Location:

- `ris_sim/config/nodes.json`
- `ris_sim/config/room.json`

Problem:

Room length is `10.0`, but `node_2` starts at x-coordinate `15`.

Impact:

- Initial scenario violates room bounds.
- Channel and mobility behavior are harder to interpret.

Fix:

- Correct node positions or enlarge room dimensions.
- Validate all initial coordinates before simulation starts.

### 3. Gauss-Markov alpha can produce NaN

Location:

- `ris_sim/modules/mobility_functions.py:109-117`

Problem:

The model uses:

```python
np.sqrt(1 - alpha**2)
```

If `alpha > 1` or `alpha < -1`, this becomes NaN.

Fix:

- Validate `0 <= alpha <= 1`.

### 4. Unknown mobility type returns `None`

Location:

- `ris_sim/modules/mobility_functions.py`

Problem:

There is no final `else` branch for unsupported mobility types.

Impact:

- Node location may become `None`.
- Later channel logic crashes.

Fix:

- Raise a clear validation error for unknown mobility types.

## API And Interface Issues

### 1. Function name typo

Location:

- `ris_sim/modules/simulator_functions.py:44`

Problem:

Function is named:

```python
recieve_from_simulator
```

Correct spelling is:

```python
receive_from_simulator
```

Fix:

- Add correctly spelled function.
- Keep old spelling as deprecated alias if needed.

### 2. API does not return received samples

Location:

- `ris_sim/modules/simulator_functions.py`

Problem:

`recieve_from_simulator` writes a receive request but does not return samples. The user must inspect `output.json`.

Impact:

- Not really USRP-like yet.

Fix:

- Add blocking and non-blocking receive APIs.
- Return exactly `num_samps` IQ samples.

### 3. Gain arguments are ignored

Location:

- `README.md`
- `usrp_tx.py`

Problem:

README shows USRP-like gain parameters, and `usrp_tx.py` defines `gain = 70`, but gain is not passed or modeled.

Fix:

- Add TX/RX gain fields.
- Model gain in channel or RF impairment layer.

## Redundancy And Dead Code

Candidates for removal or rewrite:

- Duplicate `import time` in `engine.py`.
- Unused `math` and `np` imports in `engine.py`.
- Unused `os` import in `simulator_functions.py`.
- Unused `os`, `json`, `sys` imports in `mobility_functions.py`.
- Unused `random` import in `dummy_rsc.py`.
- `nlos_element` appears unused and internally inconsistent.
- `add_signal` appears unused.
- `interpolate_data` appears unused.
- `noise` is defined but disabled.
- Large commented WAV/audio block in `usrp_tx.py`.
- `packetize_symbol` is currently unused.
- `gain` in `usrp_tx.py` is unused.
- `t_rrc`, `t_samples`, and several comments/variables in `channel_functions.py` are unused.

## Documentation Mismatches

The README describes several features that are not fully implemented yet:

- Linux FIFO queues / named pipes.
- CSV-based RIS abstraction.
- RF impairments.
- Multiple wireless channel models.
- SDR-like receive API that returns samples.
- Event logs.
- Real-time RIS controller interface.

Recommendation:

- Split README into:
  - Implemented now.
  - Prototype/demo behavior.
  - Planned architecture.

This will make the project look more honest and stronger to reviewers.

## Prioritized Roadmap

### Phase 1: Make The Engine Correct

Goal:

The simulator should complete reliably and preserve sample counts.

Tasks:

- Fix TX-only completion.
- Use `ceil` or remaining-sample accounting.
- Pad IQ samples as `[0, 0]`.
- Ensure RX-only output returns zeros/noise.
- Replace `req_time == 0` with safer state completion logic.
- Add max iteration guard.
- Add tests for TX-only, RX-only, matched TX/RX, tail chunk, and invalid request values.

### Phase 2: Validate Config And Requests

Goal:

Bad inputs should fail early with clear errors.

Tasks:

- Add schema validation for `nodes.json`, `ris.json`, and `room.json`.
- Validate positive finite sample rates.
- Validate `num_samps`.
- Validate IQ sample shape.
- Validate node locations and room bounds.
- Validate mobility model parameters.
- Validate RIS array dimensions and matrix shape.

### Phase 3: Fix IPC And State Storage

Goal:

External TX/RX/controller updates should not race or corrupt state.

Tasks:

- Replace in-place JSON rewrites with atomic writes.
- Add file locks if staying with JSON.
- Split request queues from persistent state.
- Consider SQLite or JSONL for events/output.
- Store IQ samples in binary/chunked format.

### Phase 4: Clarify The Signal Model

Goal:

The emulator should have a consistent baseband/passband abstraction.

Tasks:

- Decide whether API input is symbols or IQ samples.
- Pass sample rate into channel functions.
- Remove hardcoded `Fs = 60000`.
- Make filter cutoff valid for all supported sample rates.
- Add exact output length guarantees.
- Re-enable configurable noise.
- Add unit tests for sample rates.

### Phase 5: Improve Physical Channel/RIS Model

Goal:

The wireless model should be physically interpretable.

Tasks:

- Implement LOS channel as a complex baseband coefficient.
- Add frequency/wavelength-dependent path loss.
- Use signed RIS incidence/reflection geometry.
- Use configured RIS phase/gain responses.
- Validate front-side/back-side illumination.
- Precompute RIS coordinates.
- Add optional direct-only, RIS-only, and combined channel modes.

### Phase 6: Clean API And Packaging

Goal:

Make the emulator easier to use and extend.

Tasks:

- Rename `recieve_from_simulator` to `receive_from_simulator`.
- Package `ris_sim` with proper imports instead of `sys.path.append`.
- Add CLI entry points.
- Add a `requirements.txt` or `pyproject.toml`.
- Add structured logging.
- Add output directory per run.
- Add README examples that actually run.

### Phase 7: Testing And Research Reproducibility

Goal:

Results should be reproducible and credible.

Tasks:

- Add deterministic random seeds.
- Add scenario fixtures.
- Add regression tests for output length and state transitions.
- Add comparison tests for simple analytical channel cases.
- Add performance tests for RIS sizes.
- Add notebook or script to reproduce paper figures.

## Suggested File Structure After Refactor

```text
ris_sim/
  __init__.py
  cli.py
  config/
    schema.py
    defaults/
  core/
    engine.py
    scheduler.py
    state.py
    events.py
  io/
    json_store.py
    output_writer.py
    queues.py
  radio/
    api.py
    samples.py
    impairments.py
  channel/
    los.py
    ris.py
    noise.py
    filters.py
  mobility/
    models.py
  controllers/
    dummy_rsc.py
  tests/
```

## Immediate Next Fixes

Start here:

1. Fix TX-only completion.
2. Fix tail sample accounting.
3. Fix `[0, 0]` padding.
4. Add request/config validation.
5. Add tests for the above.

These are the highest-leverage fixes because they make the emulator trustworthy before deeper RF/RIS modeling work.

