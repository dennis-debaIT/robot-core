from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api.deps import get_core
from app.api.schemas import PersonalityPatchRequest, TtsSynthesisRequest
from app.database.db import get_connection, write_state


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
    return get_core().tts.status()


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

    return Response(
        content=result.audio_bytes,
        media_type="audio/wav",
        headers={
            "X-TTS-Provider": result.provider,
            "X-TTS-Sample-Rate": str(result.sample_rate),
            "X-TTS-Duration": f"{result.duration_seconds:.3f}",
        },
    )
