from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.database.db import get_connection
from app.services.integration_config_service import IntegrationConfigService
from app.services.light_service import LightService


router = APIRouter()


@router.get("/ha/lights")
def get_ha_lights() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    return {"lights": LightService().list_lights(config)}


@router.post("/ha/lights/control")
def control_ha_light(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return LightService().control_light(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ha/select/{entity_id}/set")
def set_select_option(entity_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return LightService().set_select_option(entity_id, body.get("option", ""))


@router.post("/ha/button/{entity_id}/press")
def press_button(entity_id: str) -> dict[str, Any]:
    return LightService().press_button(entity_id)


@router.get("/ha/entity/{entity_id:path}/state")
def get_entity_state(entity_id: str) -> dict[str, Any]:
    state = LightService().get_entity_state(entity_id)
    if not state:
        raise HTTPException(status_code=404, detail=entity_id)
    return state


# ── Licht-Szenen ─────────────────────────────────────────────────────────────

@router.get("/ha/lights/scenes")
def list_light_scenes() -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM light_scenes ORDER BY created_at ASC"
        ).fetchall()
    return {"scenes": [{"id": r["id"], "name": r["name"], "created_at": r["created_at"]} for r in rows]}


@router.post("/ha/lights/scenes")
def save_light_scene(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name fehlt")
    states = payload.get("light_states")
    if not isinstance(states, list) or not states:
        raise HTTPException(status_code=400, detail="Lichtzustände fehlen")
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO light_scenes(name, light_states, created_at) VALUES (?, ?, ?)",
            (name, json.dumps(states), now),
        )
        row = conn.execute("SELECT id FROM light_scenes WHERE name = ?", (name,)).fetchone()
    return {"ok": True, "id": row["id"], "name": name}


@router.post("/ha/lights/scenes/{scene_id}/apply")
def apply_light_scene(scene_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT light_states FROM light_scenes WHERE id = ?", (scene_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Szene nicht gefunden")
    states: list[dict] = json.loads(row["light_states"])
    svc = LightService()
    for light in states:
        entity_id = light.get("entity_id", "")
        if not entity_id:
            continue
        if light.get("state") == "off":
            svc.control_light({"entity_id": entity_id, "service": "turn_off"})
        else:
            cmd: dict[str, Any] = {"entity_id": entity_id, "service": "turn_on"}
            if light.get("brightness_pct") is not None:
                cmd["brightness_pct"] = light["brightness_pct"]
            if light.get("hs_color"):
                cmd["hs_color"] = light["hs_color"]
            elif light.get("color_temp_kelvin"):
                cmd["color_temp_kelvin"] = light["color_temp_kelvin"]
            elif light.get("rgb_color"):
                cmd["rgb_color"] = light["rgb_color"]
            svc.control_light(cmd)
    return {"ok": True, "applied": len(states)}


@router.delete("/ha/lights/scenes/{scene_id}")
def delete_light_scene(scene_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute("DELETE FROM light_scenes WHERE id = ?", (scene_id,))
    return {"ok": True}
