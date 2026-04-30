# An-Emulator-for-Smart-Radio-Environment
This project provides a **Software Emulator** for RIS-assisted wireless communication systems.
The emulator is designed to replicate the behavior of Software Defined Radios (SDRs) and Reconfigurable Intelligent Surfaces (RIS) at the baseband and passband levels, allowing researchers and developers to evaluate RIS-enabled wireless networks without requiring physical hardware.

The emulator exposes standardized interfaces that closely resemble existing SDR APIs (e.g., USRP), making it straightforward to integrate with external baseband signal generators and RIS controllers. It supports a wide range of wireless channel models, realistic RF impairments, mobility models, and programmable RIS abstractions.

Users can define nodes, RIS parameters, and the environment through structured **JSON** and **CSV** configuration files. The emulator then operates in discrete time steps to simulate signal transmission, reception, propagation, and RIS effects. All results, including received IQ samples and event logs, are stored in machine-readable formats for easy analysis and visualization.

By providing a modular and extensible design, the emulator enables rapid prototyping, performance evaluation, and validation of RIS-assisted communication systems in a controlled yet realistic software environment.



## Features

Emulates **RIS-assisted wireless communication channels**
Provides **SDR-like APIs** for seamless integration with external traffic generators
Supports **discrete-time emulation** with real-time control of RIS
Modular architecture for mobility models, channel models, and SDR impairments
JSON/CSV-based configuration for easy scenario setup
Outputs received IQ samples and event logs in structured JSON format

---

## System Design

The Emulator consists of two major blocks:

1. **External Entities** (not part of emulator):

     Baseband signal generators,
     RIS Controller,
     Hardware RIS Driver

2. **Emulation Entities** (implemented in emulator):

     SDR Emulation,
     Core Engine (mobility updates, request handling, channel modeling),
     RIS modeling and control

Communication between external entities and emulator is achieved via **Linux FIFO queues, named pipes, and JSON files**.

## Emulator Workflow

### Initialization Stage

Loads system parameters from JSON files (`Nodes.json`, `Environment.json`, `RIS.json`)
Loads RIS abstraction from CSV in the form:

  ```
  {frequency, configuration_id, phase_response, gain_response, angle_incidence, angle_reflection}
  ```
Users can configure:

  Node locations and mobility models (static, random waypoint, random direction, Gauss-Markov, random walk)
  RIS parameters (dimensions, orientation, reflection properties)
  RF impairments for each node
Initializes IPC interfaces with unique identifiers per node/RIS

### Emulation Stage

The emulator runs in discrete time steps of duration `τ`.

At each step, **Core/Engine.py** performs:

1. **Request Handling** – Reads transmission/reception requests from external entities
2. **Mobility Update** – Updates node positions using mobility models
3. **Channel Emulation** – Generates received IQ samples, applies LOS/NLOS propagation, RIS effects, and RF impairments
4. **RIS Abstraction & Control** – Updates RIS per-element coefficients based on user commands

**Note:** A dummy **RSC** file is included to demonstrate RIS control functionality. This file periodically sends configuration commands to the emulator at every discrete time step, allowing users to observe how RIS parameters are updated in real-time. In practice, this interface can be replaced or extended by an external RIS controller.



## Directory Structure
```
.
├── Core/
│   └── Engine.py
├── Config/
│   ├── Nodes.json
│   ├── Output.json
│   ├── RIS.json
│   └── Environment.json
├── External_traffic/
├── Modules/
│   ├── Channel_functions.py
│   ├── Mobility_functions.py
│   └── Simulator_functions.py
```

## Configuration Files

**Nodes.json** – Defines nodes, IDs, locations, mobility, and operating frequencies
**Output.json** – Stores runtime IQ samples, node states, and logs
**RIS.json** – Defines RIS parameters and per-element responses
**Environment.json** – Defines simulation environment (dimensions, layout)



## Interfaces

The emulator provides SDR-like APIs:

```python
Send_to_sim(Data, Operating_Frequency, Sample_Rate, Node_ID)
Receive_from_sim(Sample_Size, Operating_Frequency, Sample_Rate, Node_ID)
```

These mimic USRP-style functions such as:

```python
usrp.send_waveform(samples, duration, center_freq, sample_rate, channel_ID, gain)
usrp.recv_num_samps(sample_size, center_freq, sample_rate, channel_ID, gain)
```


## Running the Emulator

1. Define nodes and RIS parameters in `Config/Nodes.json` and `Config/RIS.json`.
2. Start by issuing transmission/reception requests via `External_traffic/usrp_tx` and `usrp_rx`.
3. Run the engine: python Core/Engine.py
4. Outputs (IQ samples, logs, state updates) are generated in `Config/Output.json` at each time step `τ`.

## Example Usage

Example initial `Nodes.json` entry:

```json
{
  "nodes": [
    {
      "id": "node_1",
      "location": [5, 2, 5],
      "mobility": {
        "type": "static",
        "speed": 0.0
      },
      "request": {},
      "current_mode": "idle",
      "fc": -1,
      "sample_rate": -1,
      "next_update": -1,
      "req_time": 0,
      "current_counter": -1,
      "data": []
    }
  ]
}
```

When a command is given from `usrp_tx`, the node data and request are updated. Similarly, `usrp_rx` requests trigger reception. Running `Engine.py` processes these requests and updates `Output.json` at each `τ`.


## Important Notes

The emulation continues to run as long as the `current_mode` of each node is set to `idle`.
  When a transmission or reception request is issued, the corresponding node state is updated, and the emulator processes it until the node returns to `idle`.
The file `Config/Output.json` is continuously updated during emulation. If the emulator is executed multiple times without clearing this file, new data will be appended. It is recommended to clear or reset `Output.json` before starting a new run.
A dummy `RSC` file periodically sends RIS configurations at every discrete time step for demonstration purposes.


## Extensibility

Add new mobility models in `Modules/Mobility_functions.py`
Implement custom channel models in `Modules/Channel_functions.py`
Extend SDR emulation APIs in `External_traffic/`


"# RIS-SIM" 
