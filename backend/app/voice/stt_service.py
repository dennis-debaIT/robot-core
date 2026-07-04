from __future__ import annotations

import os
import tempfile
import threading
from typing import Any


_MODEL_SIZE = os.getenv("WHISPER_MODEL", "tiny")
_model: Any = None
_state: str = "idle"   # idle | downloading | ready | error
_error_msg: str = ""
_lock = threading.Lock()


def _get_model() -> Any:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def ensure_downloaded() -> None:
    """Startet den Modell-Download im Hintergrund falls noch nicht geschehen."""
    global _state
    with _lock:
        if _state in ("downloading", "ready"):
            return
        _state = "downloading"
    t = threading.Thread(target=_download_worker, daemon=True)
    t.start()


def _download_worker() -> None:
    global _state, _error_msg
    try:
        _get_model()
        with _lock:
            _state = "ready"
            _error_msg = ""
    except Exception as exc:
        with _lock:
            _state = "error"
            _error_msg = str(exc)


def transcribe(audio_bytes: bytes, audio_suffix: str = ".webm") -> str:
    model = _get_model()
    with tempfile.NamedTemporaryFile(suffix=audio_suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        segments, _ = model.transcribe(tmp_path, language="de", beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def status() -> dict[str, Any]:
    try:
        import faster_whisper  # noqa: F401
        available = True
    except ImportError:
        available = False
    with _lock:
        state = _state if _model is None else "ready"
        err = _error_msg
    return {
        "available": available,
        "model": _MODEL_SIZE,
        "state": state,
        "error": err or None,
    }
