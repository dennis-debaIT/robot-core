"""
High-Performance Streaming TTS mit Sherpa-ONNX.

Funktionsweise:
  Text wird an Satzgrenzen aufgeteilt. Sherpa-ONNX ruft pro Satz einen Callback
  mit Audio-Samples auf, die sofort in einen sounddevice-OutputStream geschrieben
  werden — ohne auf die vollständige Generierung zu warten.

Verwendung als Modul:
    from app.voice.stream_tts import build_tts_engine, speak_stream

    tts = build_tts_engine(
        model_path="/models/tts/model.onnx",
        tokens_path="/models/tts/tokens.txt",
        data_dir="/models/tts/espeak-ng-data",
    )
    speak_stream("Hallo, wie kann ich helfen?", tts)

Direkte Ausführung:
    python stream_tts.py "Hallo Welt"
    python stream_tts.py "Hallo Welt" --model /models/tts/model.onnx --speed 1.1
"""

from __future__ import annotations

import re
import queue
import threading
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception:
    sd = None
    _SD_AVAILABLE = False

try:
    import sherpa_onnx
    _SHERPA_AVAILABLE = True
except ImportError:
    _SHERPA_AVAILABLE = False


# ── Konstanten ───────────────────────────────────────────────────────────────

_SILENCE_S = 0.055          # Stille zwischen Sätzen (Sekunden), verhindert Knackser
_CHUNK_SIZE = 512            # Samples pro OutputStream-Write (niedrig = geringe Latenz)
_QUEUE_MAXSIZE = 128         # Max. Chunks in der Queue (Backpressure)
_GEN_TIMEOUT_S = 15.0        # Sekunden bis Timeout pro Satz

# Satzgrenzen: nach . ! ? , ; : — aber nicht bei Abkürzungen wie "z.B."
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ\"\'])|(?<=[,;:])\s+")


# ── Engine-Builder ───────────────────────────────────────────────────────────

def build_tts_engine(
    model_path: str,
    tokens_path: str,
    data_dir: str,
    lexicon: str = "",
    rule_fsts: str = "",
    num_threads: int = 2,
    noise_scale: float = 0.667,
    noise_scale_w: float = 0.8,
    length_scale: float = 1.0,
) -> "sherpa_onnx.OfflineTts":
    """
    Erstellt und validiert eine Sherpa-ONNX TTS-Engine.

    Args:
        model_path:    Pfad zur .onnx-Modelldatei.
        tokens_path:   Pfad zur tokens.txt.
        data_dir:      Pfad zum espeak-ng-data-Verzeichnis.
        lexicon:       Optionaler Pfad zum Lexikon.
        rule_fsts:     Optionale Normalisierungsregeln.
        num_threads:   CPU-Threads für Inferenz.
        noise_scale:   Steuert Ausdrucksstärke/Varianz (0.667 = ausgewogen-freundlich).
        noise_scale_w: Steuert prosodische Variation (0.8 = natürlich).
        length_scale:  1.0 = Normalgeschwindigkeit, >1.0 = langsamer.

    Returns:
        Initialisierte OfflineTts-Instanz.
    """
    if not _SHERPA_AVAILABLE:
        raise RuntimeError(
            "sherpa_onnx ist nicht installiert. "
            "Installation: pip install sherpa-onnx"
        )

    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=model_path,
                tokens=tokens_path,
                data_dir=data_dir,
                lexicon=lexicon,
                noise_scale=noise_scale,
                noise_scale_w=noise_scale_w,
                length_scale=length_scale,
            ),
            provider="cpu",
            debug=False,
            num_threads=num_threads,
        ),
        rule_fsts=rule_fsts,
        max_num_sentences=1,
    )

    if not config.validate():
        raise RuntimeError(
            "Sherpa-ONNX-Konfiguration ungültig. "
            f"Pfade prüfen: model={model_path!r}, tokens={tokens_path!r}, "
            f"data_dir={data_dir!r}"
        )

    return sherpa_onnx.OfflineTts(config)


# ── Streaming-Wiedergabe ─────────────────────────────────────────────────────

def speak_to_file(
    text: str,
    tts: "sherpa_onnx.OfflineTts",
    output_path: str,
    speaker_id: int = 0,
    speed: float = 1.0,
) -> None:
    """
    Generiert Audio für ``text`` und schreibt es als WAV-Datei.
    Nützlich zum Testen ohne Audio-Hardware.
    """
    import wave, io

    sentences = _split_sentences(text)
    sample_rate: int = tts.sample_rate
    all_samples: list[np.ndarray] = []
    silence = np.zeros(int(sample_rate * _SILENCE_S), dtype=np.float32)

    for i, sentence in enumerate(sentences):
        if i > 0:
            all_samples.append(silence.copy())
        result = tts.generate(sentence, sid=speaker_id, speed=speed)
        all_samples.append(np.array(result.samples, dtype=np.float32))

    combined = np.concatenate(all_samples)
    pcm = (np.clip(combined, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def speak_stream(
    text: str,
    tts: "sherpa_onnx.OfflineTts",
    speaker_id: int = 0,
    speed: float = 1.0,
    on_start: Optional[Callable[[], None]] = None,
    on_done: Optional[Callable[[], None]] = None,
) -> None:
    """
    Spricht ``text`` mit minimaler Latenz aus.

    Der Text wird an Satzgrenzen aufgeteilt. Die Generierung läuft in einem
    Hintergrund-Thread; Audio-Chunks werden über eine Queue sofort an
    sounddevice übergeben.

    Args:
        text:       Zu sprechender Text.
        tts:        Initialisierte Sherpa-ONNX OfflineTts-Instanz.
        speaker_id: Sprecher-ID (0 für Einzel-Sprecher-Modelle wie Milly).
        speed:      Sprechgeschwindigkeit (1.0 = normal, 0.9 = etwas langsamer).
        on_start:   Callback sobald der erste Audio-Chunk bereit ist.
        on_done:    Callback wenn die gesamte Wiedergabe beendet ist.

    Raises:
        RuntimeError: Wenn sounddevice nicht installiert ist.
    """
    if not _SD_AVAILABLE:
        raise RuntimeError(
            "sounddevice ist nicht installiert. "
            "Installation: pip install sounddevice"
        )

    text = text.strip()
    if not text:
        return

    sentences = _split_sentences(text)
    sample_rate: int = tts.sample_rate
    silence = np.zeros(int(sample_rate * _SILENCE_S), dtype=np.float32)

    # Queue verbindet Generator-Thread mit Playback-Thread
    audio_queue: queue.Queue[Optional[np.ndarray]] = queue.Queue(maxsize=_QUEUE_MAXSIZE)
    _start_called = False

    def _callback(samples: list[float]) -> int:
        nonlocal _start_called
        chunk = np.array(samples, dtype=np.float32)
        audio_queue.put(chunk)
        if not _start_called and on_start is not None:
            on_start()
            _start_called = True
        return 1  # 1 = weiter generieren, 0 = abbrechen

    def _generate() -> None:
        try:
            for i, sentence in enumerate(sentences):
                if i > 0:
                    audio_queue.put(silence.copy())
                tts.generate(sentence, sid=speaker_id, speed=speed, callback=_callback)
        finally:
            audio_queue.put(None)  # Sentinel → Playback-Loop beenden

    gen_thread = threading.Thread(target=_generate, daemon=True, name="tts-generate")
    gen_thread.start()

    try:
        with sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=_CHUNK_SIZE,
            latency="low",
        ) as stream:
            while True:
                try:
                    chunk = audio_queue.get(timeout=_GEN_TIMEOUT_S)
                except queue.Empty:
                    break
                if chunk is None:
                    break
                stream.write(chunk)
    finally:
        gen_thread.join(timeout=30.0)
        if on_done is not None:
            on_done()


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """
    Teilt Text in sprechbare Einheiten auf.

    Kurze Texte bleiben ungeteilt. Satzgrenzen werden erkannt an: . ! ? , ; :
    Abkürzungen wie "z.B." oder "Dr." werden nicht fälschlich getrennt.
    """
    parts = _SENTENCE_RE.split(text)
    result = []
    buffer = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Sehr kurze Fragmente mit dem nächsten zusammenführen (< 3 Wörter)
        if len(part.split()) < 3 and buffer:
            buffer += " " + part
        else:
            if buffer:
                result.append(buffer)
            buffer = part

    if buffer:
        result.append(buffer)

    return result if result else [text]


# ── Standalone-Ausführung ────────────────────────────────────────────────────

_DEFAULT_MODEL = "/models/tts/model.onnx"
_DEFAULT_TOKENS = "/models/tts/tokens.txt"
_DEFAULT_DATA_DIR = "/models/tts/espeak-ng-data"


def main() -> None:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Streaming TTS mit Sherpa-ONNX — spricht Text sofort aus."
    )
    parser.add_argument(
        "text",
        nargs="?",
        default="Hallo, ich bin Milly. Schön, dich kennenzulernen! Wie kann ich dir heute helfen?",
        help="Zu sprechender Text (Standard: Begrüßung)",
    )
    parser.add_argument("--model", default=_DEFAULT_MODEL, help="Pfad zur .onnx-Datei")
    parser.add_argument("--tokens", default=_DEFAULT_TOKENS, help="Pfad zur tokens.txt")
    parser.add_argument("--data-dir", default=_DEFAULT_DATA_DIR, help="Pfad zu espeak-ng-data")
    parser.add_argument("--speaker-id", type=int, default=0, help="Sprecher-ID")
    parser.add_argument("--speed", type=float, default=1.0, help="Geschwindigkeit (1.0=normal)")
    parser.add_argument("--threads", type=int, default=2, help="CPU-Threads")
    parser.add_argument(
        "--noise-scale", type=float, default=0.667,
        help="Ausdrucksstärke (0.667 = ausgewogen-freundlich)"
    )
    parser.add_argument(
        "--noise-scale-w", type=float, default=0.8,
        help="Prosodische Variation (0.8 = natürlich)"
    )
    parser.add_argument(
        "--save", metavar="DATEI.wav", default=None,
        help="Statt Lautsprecher: Audio als WAV-Datei speichern"
    )
    args = parser.parse_args()

    print(f"Lade Modell: {args.model}")
    t0 = time.monotonic()
    tts = build_tts_engine(
        model_path=args.model,
        tokens_path=args.tokens,
        data_dir=args.data_dir,
        num_threads=args.threads,
        noise_scale=args.noise_scale,
        noise_scale_w=args.noise_scale_w,
    )
    print(f"Modell geladen in {time.monotonic() - t0:.2f}s — Sample-Rate: {tts.sample_rate} Hz")
    print(f"Text: {args.text!r}")

    t1 = time.monotonic()
    if args.save:
        print(f"Modus: Datei → {args.save}")
        speak_to_file(
            text=args.text,
            tts=tts,
            output_path=args.save,
            speaker_id=args.speaker_id,
            speed=args.speed,
        )
        print(f"Gespeichert in {time.monotonic() - t1:.2f}s")
    else:
        print("Modus: Lautsprecher (Streaming)")
        speak_stream(
            text=args.text,
            tts=tts,
            speaker_id=args.speaker_id,
            speed=args.speed,
            on_start=lambda: print(f"Wiedergabe gestartet nach {time.monotonic() - t1:.3f}s"),
            on_done=lambda: print(f"Fertig. Gesamt: {time.monotonic() - t1:.2f}s"),
        )


if __name__ == "__main__":
    main()
