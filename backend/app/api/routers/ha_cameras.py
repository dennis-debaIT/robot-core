from __future__ import annotations

import urllib.request as _req
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.services.camera_stream_service import CameraStreamService
from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService


router = APIRouter()
CameraStreamService.ensure_started()


@router.get("/ha/cameras")
def get_ha_cameras() -> dict[str, Any]:
    from app.search.providers.homeassistant import HomeAssistantProvider

    all_cams = HomeAssistantProvider().get_cameras()
    ring_ids = CameraStreamService.ring_ids()
    return {"cameras": [cam for cam in all_cams if cam["entity_id"] in ring_ids]}


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
