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
    status["edge_rate"] = tts_cfg.get("edge_rate") or "+0%"
    return status


@router.get("/tts/voices")
def get_tts_voices() -> list[dict[str, Any]]:
    """Gibt verfügbare Stimmen für den aktuellen oder angegebenen Provider zurück."""
    import asyncio
    try:
        import edge_tts
    except ImportError:
        return _edge_voices_fallback()
    try:
        async def _list() -> list[dict]:
            return await edge_tts.list_voices()
        loop = asyncio.new_event_loop()
        all_voices = loop.run_until_complete(_list())
        loop.close()
        result = []
        for v in all_voices:
            locale = v.get("Locale", "")
            if not locale.startswith("de-"):
                continue
            result.append({
                "value": v.get("ShortName", ""),
                "label": _voice_display_name(v),
                "locale": locale,
                "gender": v.get("Gender", ""),
            })
        return sorted(result, key=lambda x: (x["locale"], x["label"]))
    except Exception:
        return _edge_voices_fallback()


def _voice_display_name(v: dict) -> str:
    short = v.get("ShortName", "")
    gender_de = "♀" if v.get("Gender") == "Female" else "♂"
    locale_labels = {"de-DE": "Deutsch", "de-AT": "Österreich", "de-CH": "Schweiz"}
    locale = locale_labels.get(v.get("Locale", ""), v.get("Locale", ""))
    name = short.split("-")[-1].replace("Neural", "")
    return f"{name} ({locale}, {gender_de})"


def _edge_voices_fallback() -> list[dict[str, Any]]:
    return [
        {"value": "de-DE-KatjaNeural",     "label": "Katja (Deutsch, ♀)",       "locale": "de-DE", "gender": "Female"},
        {"value": "de-DE-ConradNeural",     "label": "Conrad (Deutsch, ♂)",      "locale": "de-DE", "gender": "Male"},
        {"value": "de-DE-AmalaNeural",      "label": "Amala (Deutsch, ♀)",       "locale": "de-DE", "gender": "Female"},
        {"value": "de-DE-BerndNeural",      "label": "Bernd (Deutsch, ♂)",       "locale": "de-DE", "gender": "Male"},
        {"value": "de-DE-ChristophNeural",  "label": "Christoph (Deutsch, ♂)",   "locale": "de-DE", "gender": "Male"},
        {"value": "de-DE-ElkeNeural",       "label": "Elke (Deutsch, ♀)",        "locale": "de-DE", "gender": "Female"},
        {"value": "de-DE-MajaNeural",       "label": "Maja (Deutsch, ♀)",        "locale": "de-DE", "gender": "Female"},
        {"value": "de-DE-RalfNeural",       "label": "Ralf (Deutsch, ♂)",        "locale": "de-DE", "gender": "Male"},
        {"value": "de-DE-SeraphinaNeural",  "label": "Seraphina (Deutsch, ♀)",   "locale": "de-DE", "gender": "Female"},
        {"value": "de-AT-IngridNeural",     "label": "Ingrid (Österreich, ♀)",   "locale": "de-AT", "gender": "Female"},
        {"value": "de-AT-JonasNeural",      "label": "Jonas (Österreich, ♂)",    "locale": "de-AT", "gender": "Male"},
        {"value": "de-CH-LeniNeural",       "label": "Leni (Schweiz, ♀)",        "locale": "de-CH", "gender": "Female"},
        {"value": "de-CH-JanNeural",        "label": "Jan (Schweiz, ♂)",         "locale": "de-CH", "gender": "Male"},
    ]


@router.post("/system/tts-config")
def save_tts_config(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("tts_provider") or "disabled").strip()
    voice = str(payload.get("edge_voice") or "de-DE-KatjaNeural").strip()
    rate = str(payload.get("edge_rate") or "+0%").strip()
    get_core().settings.update_runtime_overrides({"tts_provider": provider})
    with get_connection() as conn:
        write_state(conn, "tts_runtime_config", {"provider": provider, "edge_voice": voice, "edge_rate": rate})
    return {"ok": True, "provider": provider, "edge_voice": voice, "edge_rate": rate}


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


@router.post("/tts/watchdog")
def tts_watchdog_event() -> dict:
    """Wird aufgerufen wenn der 30s-TTS-Watchdog im Frontend auslöst."""
    from app.database.db import get_connection, read_state, write_state
    from datetime import datetime, timezone
    with get_connection() as conn:
        stats = read_state(conn, "tts_watchdog_stats") or {"count": 0, "last_at": None}
        stats["count"] = int(stats.get("count", 0)) + 1
        stats["last_at"] = datetime.now(timezone.utc).isoformat()
        write_state(conn, "tts_watchdog_stats", stats)
    return {"ok": True, "count": stats["count"]}


@router.get("/tts/watchdog")
def tts_watchdog_stats() -> dict:
    from app.database.db import get_connection, read_state
    with get_connection() as conn:
        stats = read_state(conn, "tts_watchdog_stats") or {"count": 0, "last_at": None}
    return stats
