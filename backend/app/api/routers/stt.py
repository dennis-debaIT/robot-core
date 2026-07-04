from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

router = APIRouter(prefix="/stt", tags=["stt"])

_SUFFIX_MAP = {
    "audio/webm": ".webm", "audio/ogg": ".ogg",
    "audio/wav": ".wav", "audio/wave": ".wav",
    "audio/mpeg": ".mp3", "audio/mp4": ".mp4", "audio/x-m4a": ".m4a",
}
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@router.get("/status")
def stt_status() -> dict:
    try:
        from app.voice import stt_service
        return stt_service.status()
    except Exception as exc:
        return {"available": False, "state": "error", "error": str(exc)}


@router.post("/download")
def stt_download() -> dict[str, str]:
    """Startet den Modell-Download im Hintergrund (idempotent)."""
    try:
        from app.voice import stt_service
        stt_service.ensure_downloaded()
        return {"ok": True, "state": stt_service.status()["state"]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/transcribe")
async def transcribe(file: UploadFile) -> dict[str, str]:
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    audio_bytes = await file.read()
    if len(audio_bytes) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="Audio zu groß (max 10 MB)")
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Leere Audio-Datei")

    suffix = _SUFFIX_MAP.get(content_type, ".webm")
    try:
        from app.voice import stt_service
        text = stt_service.transcribe(audio_bytes, audio_suffix=suffix)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transkription fehlgeschlagen: {exc}") from exc

    return {"text": text}
