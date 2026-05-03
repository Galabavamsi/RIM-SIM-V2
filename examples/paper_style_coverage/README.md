# Paper-Style Coverage Example

This example creates a spatial received-power plot similar to the validation
figure in the paper:

- one static transmitter
- one static RIS
- `5 x 5` receiver grid
- one BPSK burst
- one receive request per receiver point

Run from the repository root:

```powershell
python examples\two_node_ris\run_example.py --scenario examples\paper_style_coverage\scenario.json --run-dir examples\paper_style_coverage\runs\smoke
```

The most relevant plots are:

- `plots/receiver_power_map.png`: labeled receiver positions with mean received power in dBm.
- `plots/room_coverage_heatmap.png`: interpolated room coverage heatmap from the receiver grid.

The interpolation is inverse-distance weighting over emulator receiver samples.
It is meant for visualization and comparison, not as an additional propagation
model.
