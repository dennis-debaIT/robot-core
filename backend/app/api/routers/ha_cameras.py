from __future__ import annotations

import json
import re
import urllib.request as _req
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.services.camera_stream_service import CameraStreamService
from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService


router = APIRouter()
CameraStreamService.ensure_started()


def _camera_type(entity_id: str) -> str:
    eid = entity_id.lower()
    if "_snapshot" in eid:
        return "snapshot"
    if "_map" in eid or "_karte" in eid:
        return "map"
    if "_live" in eid:
        return "live"
    return "other"


@router.get("/ha/cameras")
def get_ha_cameras() -> dict[str, Any]:
    from app.search.providers.homeassistant import HomeAssistantProvider

    all_cams = HomeAssistantProvider().get_cameras()
    ring_ids = CameraStreamService.ring_ids()
    camera_configs = CameraStreamService._get_cameras_db_config().get("camera_configs") or {}
    result = []
    for cam in all_cams:
        if cam["entity_id"] not in ring_ids:
            continue
        cfg = camera_configs.get(cam["entity_id"]) or {}
        cam["has_live_stream"] = bool(cfg.get("ring_device_id", "").strip()) and bool(cfg.get("has_live_stream", True))
        result.append(cam)
    return {"cameras": result}


@router.get("/ha/cameras/detect-ring")
async def detect_ring_cameras() -> dict[str, Any]:
    from app.search.providers.homeassistant import HomeAssistantProvider
    from app.services.ha_websocket_service import get_ring_camera_id_map

    ha = HomeAssistantProvider()
    ha_config = HomeAssistantRuntimeConfigService.get_config()
    ha_host = ha_config.get("host", "")
    ha_token = ha_config.get("token", "")
    ha_url = HomeAssistantRuntimeConfigService.build_base_url(ha_config)

    # Ring-IDs via HA WebSocket Device-Registry ermitteln
    ring_id_map = await get_ring_camera_id_map(ha_url, ha_token)

    # Fallback: go2rtc REST API (Port 1984)
    go2rtc_ids: list[str] = []
    try:
        with _req.urlopen(f"http://{ha_host}:1984/api/streams", timeout=3) as resp:
            streams = json.loads(resp.read())
        go2rtc_ids = [
            name for name in streams
            if re.match(r"^[a-f0-9]{10,16}(_live)?$", name, re.IGNORECASE)
        ]
    except Exception:
        pass

    states = ha._get("/states") or []
    cameras: list[dict[str, Any]] = []
    for state in states:
        entity_id = state.get("entity_id", "")
        if not entity_id.startswith("camera."):
            continue
        attrs = state.get("attributes", {})
        # Aus WebSocket-Registry oder stream_source-Attribut
        ring_device_id = ring_id_map.get(entity_id, "")
        if not ring_device_id:
            stream_source = str(attrs.get("stream_source") or "")
            m = re.search(r"/([a-f0-9]{10,16})_live", stream_source)
            if m:
                ring_device_id = m.group(1)
        cam_type = _camera_type(entity_id)
        cameras.append({
            "entity_id": entity_id,
            "name": attrs.get("friendly_name", entity_id),
            "state": state.get("state", "unknown"),
            "type": cam_type,
            "ring_device_id": ring_device_id,
            "detected_via_registry": entity_id in ring_id_map,
        })
    cameras.sort(key=lambda c: c["name"].lower())
    return {"cameras": cameras, "go2rtc_ids": go2rtc_ids}


@router.get("/ha/cameras/{entity_id}/snapshot")
def get_camera_snapshot(entity_id: str) -> Response:
    config = HomeAssistantRuntimeConfigService.get_config()
    ha_url = HomeAssistantRuntimeConfigService.build_base_url(config)
    ha_token = config.get("token", "")
    url = f"{ha_url}/api/camera_proxy/{entity_id}"
    try:
        req = _req.Request(url, headers={"Authorization": f"Bearer {ha_token}"})
        with _req.urlopen(req, timeout=10) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
        return Response(content=data, media_type=ctype, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Snapshot nicht erreichbar: {exc}") from exc


@router.get("/ha/cameras/{entity_id}/mjpeg")
def get_camera_mjpeg(entity_id: str) -> StreamingResponse:
    config = HomeAssistantRuntimeConfigService.get_config()
    ha_url = HomeAssistantRuntimeConfigService.build_base_url(config)
    ha_token = config.get("token", "")
    url = f"{ha_url}/api/camera_proxy_stream/{entity_id}"
    try:
        req = _req.Request(url, headers={"Authorization": f"Bearer {ha_token}"})
        resp = _req.urlopen(req, timeout=60)
        ctype = resp.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=frame")

        def _stream():
            try:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    yield chunk
            finally:
                resp.close()

        return StreamingResponse(_stream(), media_type=ctype, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Stream nicht erreichbar: {exc}") from exc


@router.post("/ha/cameras/{entity_id}/live/start")
def live_start(entity_id: str) -> dict[str, Any]:
    try:
        return CameraStreamService.live_start(entity_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ha/cameras/{entity_id}/live/stop")
def live_stop(entity_id: str) -> dict[str, Any]:
    return CameraStreamService.live_stop(entity_id)


@router.get("/ha/cameras/{entity_id}/stream")
def get_camera_stream(entity_id: str) -> Response:
    try:
        content = CameraStreamService.stream_playlist(entity_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/ha/cameras/{entity_id}/hls/{filename}")
def serve_hls_segment(entity_id: str, filename: str) -> Response:
    try:
        payload = CameraStreamService.read_segment(entity_id, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Segment nicht gefunden") from exc
    return Response(content=payload, media_type="video/mp2t", headers={"Cache-Control": "no-store"})


@router.get("/ha/debug/ring-entities")
def debug_ring_entities() -> dict[str, Any]:
    from app.search.providers.homeassistant import HomeAssistantProvider

    ha = HomeAssistantProvider()
    states = ha._get("/states") or []
    keywords = ["haustur", "haustür", "garten", "terrasse", "ding", "klingel", "motion", "bewegung", "ring", "camera"]
    results = []
    for state in states:
        eid = (state.get("entity_id") or "").lower()
        if any(keyword in eid for keyword in keywords):
            results.append(
                {
                    "entity_id": state.get("entity_id"),
                    "state": state.get("state"),
                    "last_changed": state.get("last_changed"),
                    "friendly_name": state.get("attributes", {}).get("friendly_name"),
                }
            )
    results.sort(key=lambda item: item["entity_id"])
    return {"count": len(results), "entities": results}


@router.post("/ha/cameras/stop-all")
def stop_all_camera_streams() -> dict[str, Any]:
    return {"stopped": CameraStreamService.stop_all()}


@router.get("/ha/cameras/events")
def get_ha_camera_events() -> dict[str, Any]:
    from app.search.providers.homeassistant import HomeAssistantProvider

    return {"events": HomeAssistantProvider().get_camera_events()}
