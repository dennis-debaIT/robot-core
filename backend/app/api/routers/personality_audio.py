from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api.deps import get_core
from app.api.schemas import PersonalityPatchRequest, TtsSynthesisRequest
from app.database.db import get_connection, read_state, write_state


router = APIRouter()


@router.get("/personality")
def get_personality() -> dict[str, Any]:
    data = dict(get_core().personality.get())
    data["relationship_state"] = get_core().relationship.get_global_state()
    return data


@router.patch("/personality")
def patch_personality(payload: PersonalityPatchRequest) -> dict[str, Any]:
    patch = payload.to_patch()
    result = get_core().personality.update(patch)
    get_core().audit.log(
        action="personality.updated",
        target_type="personality",
        target_id="default_personality",
        summary="Persönlichkeit wurde geändert.",
        details={"patch": patch},
    )
    return result


@router.post("/personality/reset")
def reset_global_persona() -> dict[str, Any]:
    return get_core().reset_global_persona()


@router.get("/tts/status")
def get_tts_status() -> dict[str, Any]:
    import os
    status = get_core().tts.status()
    try:
        with get_connection() as conn:
            tts_cfg = read_state(conn, "tts_runtime_config", {})
    except Exception:
        tts_cfg = {}
    status["edge_voice"] = tts_cfg.get("edge_voice") or os.getenv("ROBOT_TTS_EDGE_VOICE", "de-DE-KatjaNeural")
    return status


@router.post("/system/tts-config")
def save_tts_config(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("tts_provider") or "disabled").strip()
    voice = str(payload.get("edge_voice") or "de-DE-KatjaNeural").strip()
    # Write provider into runtime_config_overrides so settings.get_effective() picks it up instantly
    get_core().settings.update_runtime_overrides({"tts_provider": provider})
    # Store edge_voice separately (edge-TTS specific, not a CoreSettings field)
    with get_connection() as conn:
        write_state(conn, "tts_runtime_config", {"provider": provider, "edge_voice": voice})
    return {"ok": True, "provider": provider, "edge_voice": voice}


@router.post("/tts/synthesize")
def synthesize_tts(payload: TtsSynthesisRequest) -> Response:
    expires = (datetime.now(timezone.utc) + timedelta(seconds=40)).isoformat()
    try:
        with get_connection() as conn:
            write_state(conn, "last_speech_text", {"text": payload.text, "expires_at": expires})
    except Exception:
        pass

    try:
        result = get_core().tts.synthesize(payload.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    fmt = getattr(result, "audio_format", "wav")
    media_type = "audio/mpeg" if fmt == "mp3" else "audio/wav"
    return Response(
        content=result.audio_bytes,
        media_type=media_type,
        headers={
            "X-TTS-Provider": result.provider,
            "X-TTS-Sample-Rate": str(result.sample_rate),
            "X-TTS-Duration": f"{result.duration_seconds:.3f}",
            "X-TTS-Format": fmt,
        },
    )
