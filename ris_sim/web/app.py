"""FastAPI application for the RIS-SIM web dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ris_sim.web.session import (
    DashboardSession,
    list_scenarios,
    list_templates,
    load_scenario,
    load_template,
    save_template,
    validate_scenario,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="RIS-SIM Dashboard", version="2.0")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>RIS-SIM Dashboard</h1><p>index.html not found.</p>")


@app.get("/api/templates")
async def api_templates():
    return {"templates": list_templates()}


@app.get("/api/templates/{name}")
async def api_template(name: str):
    data = load_template(name)
    if data is None:
        return JSONResponse({"error": f"Template {name!r} not found"}, status_code=404)
    return data


@app.post("/api/templates/{name}")
async def api_save_template(name: str, scenario: dict[str, Any]):
    save_template(name, scenario)
    return {"status": "ok", "name": name}


@app.get("/api/scenarios")
async def api_scenarios():
    """Featured scenarios with rich metadata for the scenario-library cards."""
    return {"scenarios": list_scenarios()}


@app.get("/api/scenarios/{scenario_id}")
async def api_scenario(scenario_id: str):
    """Return the inner scenario JSON (envelope unwrapped) for the dashboard
    to drop into the editor and Start."""
    data = load_scenario(scenario_id)
    if data is None:
        return JSONResponse({"error": f"Scenario {scenario_id!r} not found"}, status_code=404)
    return data


@app.post("/api/validate")
async def api_validate(scenario: dict[str, Any]):
    errors = validate_scenario(scenario)
    return {"valid": len(errors) == 0, "errors": errors}


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    session = DashboardSession()

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            cmd = msg.get("type", "")

            if cmd == "start":
                scenario = msg.get("scenario", {})
                errors = validate_scenario(scenario)
                if errors:
                    await websocket.send_json({
                        "type": "config_invalid",
                        "errors": errors,
                    })
                else:
                    try:
                        await websocket.send_json({"type": "config_valid", "errors": []})
                        await session.start(scenario, websocket)
                    except Exception as exc:
                        await websocket.send_json({
                            "type": "config_invalid",
                            "errors": [str(exc)],
                        })

            elif cmd == "stop":
                await session.stop()
                await websocket.send_json({"type": "stopped"})

            elif cmd == "pause":
                await session.pause()

            elif cmd == "resume":
                await session.resume()

            elif cmd == "step":
                await session.step(websocket)

            elif cmd == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        await session.stop()
    except Exception as exc:
        await session.stop()
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
