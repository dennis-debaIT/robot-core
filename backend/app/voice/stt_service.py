from __future__ import annotations

import os
import tempfile
from typing import Any


_MODEL_SIZE = os.getenv("WHISPER_MODEL", "tiny")
_model: Any = None


def _get_model() -> Any:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


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
    return {
        "available": available,
        "model": _MODEL_SIZE,
        "loaded": _model is not None,
    }
