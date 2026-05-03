# Two-Node RIS Example

This example demonstrates the current emulator output flow in a repeatable way:

1. Load `scenario.json`.
2. Convert it into engine config files under `ris_sim/config`.
3. Queue one TX request and one RX request.
4. Run `ris_sim/core/engine.py`.
5. Export analysis artifacts into a run directory.
6. Restore the original working config files.

Run from the repository root:

```powershell
python examples\two_node_ris\run_example.py
```

The run directory contains:

- `scenario.json`: the scenario used for the run.
- `output.json`: the raw emulator output.
- `summary.json`: compact per-receiver metrics.
- `result.npz`: compressed NumPy arrays of complex IQ samples.
- `original_config/`: the config files before the example ran.
- `final_config/`: the engine config files after the simulation completed.
- `plots/room_topology.png`: room, node, and RIS positions.
- `plots/ris_1_heatmap.png`: RIS state matrix.
- `plots/node_2_output_1_iq.png`: received I/Q over time.
- `plots/node_2_output_1_constellation.png`: received constellation.
- `plots/node_2_output_1_power.png`: received power over time.

The raw output JSON has this shape:

```json
{
    "outputs": [
        {
            "request_id": "...",
            "id": "node_2",
            "fc": 2399996950.0,
            "sample_rate": 5880.0,
            "num_samps": 120,
            "data": [
                [[0.0, 0.0], [0.0, 0.0]]
            ]
        }
    ]
}
```

`data` is a list of per-tick blocks. Each sample is `[I, Q]`. For programmatic
analysis, prefer `result.npz` because large numerical arrays are slow and bulky
in JSON.
