# G4 — Web Dashboard: Plan (Updated — Full JSON Editor)

> Status: Planning | Effort: 4-5 days

---

## Approach: JSON-First Configuration

The user can configure **everything** from the browser — room, nodes, RIS,
channel, traffic — via editable JSON panels. No pre-existing scenario file
required. A visual topology canvas lets you drag nodes into position.

```
┌─ Sidebar ───────────┬─ Main View ──────────────────────────┐
│                     │                                       │
│  [Template: ▼]      │  ┌── Room Topology ──┬── Constell ──┐│
│  two_node_ris       │  │  Canvas + drag    │  Chart.js    ││
│                     │  │  nodes to place   │              ││
│  ── Room ────────── │  └──────────────────┴──────────────┘│
│  {                  │                                       │
│   "length": 10,     │  ┌── RIS Heatmap ────┬── Controls ──┐│
│   "width": 10,      │  │  Canvas           │  [▶ Start]   ││
│   "height": 10      │  │                   │  [⏸ Pause]   ││
│  }                  │  │                   │  [⏭ Step]    ││
│                     │  └──────────────────┴──────────────┘│
│  ── Nodes ───────── │                                       │
│  [                   │  ── Metrics ─────────────────────── │
│   {                  │  tick: 42 | 1250 t/s | ETA 0.1s     │
│    "id": "node_1",   │  samples: 2389 | avg: 720us         │
│    "location": [...] │                                       │
│   }                  │                                       │
│  ]                   │                                       │
│                     │                                       │
│  ── RIS ─────────── │                                       │
│  [                   │                                       │
│   {                  │                                       │
│    "id": "ris_1",    │                                       │
│    ...               │                                       │
│   }                  │                                       │
│  ]                   │                                       │
│                     │                                       │
│  ── Traffic ─────── │                                       │
│  [...]              │                                       │
│                     │                                       │
│  ── Channel ─────── │                                       │
│  {...}              │                                       │
│                     │                                       │
│  [Save JSON]        │                                       │
│  [Load JSON]        │                                       │
└─────────────────────┴───────────────────────────────────────┘
```

---

## Updated Components

### 1. Sidebar — JSON Configuration Panel

**5 collapsible sections**, each with a syntax-highlighted `<textarea>`:

| Section | Default JSON | Purpose |
|---------|-------------|---------|
| Room | `{"length":10,"width":10,"height":10}` | Room dimensions |
| Nodes | `[{"id":"node_1","location":[5,2,5],"mobility":{"type":"static"}}]` | Node definitions |
| RIS | `[{"id":"ris_1","plane":5,"location":[0,5,5],...}]` | RIS panel definitions |
| Traffic | `[{"mode":"transmit","node_id":"node_1",...}]` | TX/RX requests |
| Channel | `{"enable_noise":true,"noise_figure_db":5}` | Channel + RF config |

**Features**:
- **Validation**: Red border + error message on invalid JSON
- **Auto-sync**: Editing location in JSON updates the topology canvas in real-time
- **Sync back**: Dragging a node on the canvas updates the JSON textarea
- **Templates dropdown**: Pre-built scenarios (two_node_ris, los_only, cfo_demo, etc.)
- **Save/Load**: Download current config as `.json` file, or upload an existing one
- **Undo**: Basic undo stack (last 20 edits)

### 2. Topology Canvas — Visual Node Placement

- **Click to add node**: Click empty space → new node appears → auto-added to Nodes JSON
- **Drag to move**: Drag existing node → location updates in JSON in real-time
- **Right-click to delete**: Context menu to remove node from both canvas and JSON
- **RIS panels**: Shown as rectangles with orientation arrows; drag to reposition
- **Room bounds**: Gray rectangle; nodes snap to bounds

### 3. Template System

Pre-built templates stored as JSON files in `ris_sim/web/templates/`:

```
ris_sim/web/templates/
├── two_node_ris.json
├── los_only.json
├── cfo_500hz.json
├── rayleigh_fading.json
├── ofdm_64subcarrier.json
└── large_ris_32x32.json
```

Also exposed via API: `GET /api/templates` → `{"templates": ["two_node_ris", ...]}`

`GET /api/templates/two_node_ris` → full scenario JSON

### 4. Controls

| Button | Action |
|--------|--------|
| **▶ Start** | Build scenario from JSON textareas → validate → create Simulation → run |
| **⏸ Pause** | Pause simulation (holds current tick) |
| **⏭ Step** | Advance one tick when paused |
| **⏹ Stop** | Stop simulation, reset to idle |

---

## Data Flow (Updated)

```
  Sidebar              Topology Canvas         Backend
  ────────             ────────────────         ───────
  JSON textarea ─────────sync────────► Canvas render
       ▲                                    │
       │                            Drag node updates
       │                                    │
       └──────────sync───────────── location change
                                          
  [▶ Start] → POST /api/scenario {room, nodes, ris, traffic, channel}
                  ↓
              Simulation created, starts ticking
                  ↓
              WS push: state every 50ms
                  ↓
              Constellation + Heatmap update
```

### WebSocket Protocol (Updated)

Server → Client:
```json
{"type": "state", "tick": 42, "nodes": [...], "ris": [...],
 "latest_iq": {"node_2": [[0.1,0.2],...]}, "metrics": {...}}
{"type": "simulation_complete", "tick": 218, "elapsed_s": 0.174}
{"type": "config_valid", "errors": []}
{"type": "config_invalid", "errors": ["Node node_1 location outside room"]}
```

Client → Server:
```json
{"type": "start", "scenario": {...full scenario dict...}}
{"type": "stop"}
{"type": "tick"}
{"type": "validate", "scenario": {...}}
```

---

## Implementation Steps (Updated)

### Step 1: Backend (`ris_sim/web/app.py`) — ~200 lines
- FastAPI app, static file serving
- `WS /ws/live` — state push + command receive
- `GET /api/templates` — list available templates
- `GET /api/templates/{name}` — get template JSON
- `POST /api/validate` — validate a scenario dict, return errors

### Step 2: Dashboard Session (`ris_sim/web/session.py`) — ~100 lines
- `DashboardSession` — holds Simulation, manages tick loop
- Throttled state pushes (max 20 Hz)
- Handles start/stop/pause/step commands
- Extracts latest IQ per Rx node for constellation

### Step 3: Frontend (`ris_sim/web/static/index.html`) — ~500 lines
- **Sidebar** (left 350px): 5 collapsible JSON panels + template dropdown + save/load
- **Topology Canvas** (center-top): room + nodes (click to add, drag to move)
- **Constellation** (right-top): Chart.js scatter (I/Q)
- **RIS Heatmap** (bottom-center): Canvas grid
- **Controls** (bottom-right): Start/Stop/Step buttons + status
- **Metrics bar** (bottom strip): tick, rate, ETA

### Step 4: Templates (`ris_sim/web/templates/`) — 6 JSON files
- Copy from `scenarios/` directory or create new ones

### Step 5: CLI (`ris_sim/cli/main.py`) — ~20 lines
```bash
ris-sim dashboard                    # Start with blank config
ris-sim dashboard scenario.json      # Pre-load scenario JSON
ris-sim dashboard --port 9000        # Custom port
```

### Step 6: Tests — ~80 lines
- HTTP `/` returns HTML
- `GET /api/templates` returns list
- WebSocket connect + receive state
- WebSocket send start command → simulation runs
- Validate endpoint catches bad config

---

## Dependencies

```
pip install ris-sim[web]
# Adds: fastapi, uvicorn
```

No npm, no webpack, no React. Single `index.html` with:
- Chart.js 4 from CDN (`<script src="cdn.jsdelivr.net/npm/chart.js">`)
- All CSS/JS inline in `<style>` / `<script>` tags
- Total HTML file ~500 lines

---

## Success Criteria

1. `ris-sim dashboard` opens a browser with blank config + empty topology
2. User types JSON into sidebar panels, sees topology update in real-time
3. Clicking on topology canvas adds a node to the JSON
4. Dragging a node updates its location in the JSON
5. Selecting a template fills all JSON panels
6. Pressing Start validates config, runs simulation, pushes state to browser
7. Constellation chart updates at ~20 fps during simulation
8. RIS heatmap updates on reconfiguration
9. Metrics bar shows live tick rate, progress, ETA
10. "Save JSON" downloads current config as a `.json` file
