from __future__ import annotations

import importlib
import io
import json
import math
import os
import re
import wave
from dataclasses import dataclass
from typing import Any

from app.core.settings import SettingsService


@dataclass
class SynthesisResult:
    provider: str
    sample_rate: int
    duration_seconds: float
    audio_bytes: bytes
    audio_format: str = "wav"


class TtsService:
    def __init__(self, settings: SettingsService | None = None) -> None:
        self.settings = settings or SettingsService()
        self._engine: Any = None
        self._engine_signature: tuple[Any, ...] | None = None

    @staticmethod
    def _read_model_name(model_path: str) -> str | None:
        json_path = model_path + ".json"
        try:
            with open(json_path) as f:
                return json.load(f).get("dataset")
        except Exception:
            return None

    def status(self) -> dict[str, Any]:
        config = self.settings.get_effective()
        provider = config.tts_provider
        if provider == "disabled":
            return {
                "provider": provider,
                "ready": False,
                "reason": "disabled",
                "voice_label": config.tts_voice_label,
                "speaker_id": config.tts_speaker_id,
                "speed": config.tts_speed,
            }
        if provider == "mock":
            return {
                "provider": provider,
                "ready": True,
                "reason": "mock_provider",
                "voice_label": config.tts_voice_label or "Mock",
                "speaker_id": config.tts_speaker_id,
                "speed": config.tts_speed,
            }
        if provider == "edge_tts":
            try:
                importlib.import_module("edge_tts")
                ready, reason = True, "ok"
            except Exception as exc:
                ready, reason = False, f"package_unavailable: {exc}"
            return {
                "provider": provider,
                "ready": ready,
                "reason": reason,
                "voice_label": config.tts_voice_label or "Edge TTS",
                "speaker_id": config.tts_speaker_id,
                "speed": config.tts_speed,
            }
        if provider != "sherpa_onnx":
            return {
                "provider": provider,
                "ready": False,
                "reason": "unknown_provider",
                "voice_label": config.tts_voice_label,
                "speaker_id": config.tts_speaker_id,
                "speed": config.tts_speed,
            }

        missing = [
            path
            for path in (config.tts_vits_model, config.tts_tokens, config.tts_data_dir)
            if not path or not os.path.exists(path)
        ]
        if missing:
            return {
                "provider": provider,
                "ready": False,
                "reason": "model_paths_missing",
                "missing_paths": missing,
                "voice_label": config.tts_voice_label,
                "speaker_id": config.tts_speaker_id,
                "speed": config.tts_speed,
            }
        try:
            importlib.import_module("sherpa_onnx")
        except Exception as exc:
            return {
                "provider": provider,
                "ready": False,
                "reason": "package_unavailable",
                "detail": str(exc),
                "voice_label": config.tts_voice_label,
                "speaker_id": config.tts_speaker_id,
                "speed": config.tts_speed,
            }

        return {
            "provider": provider,
            "ready": True,
            "reason": "ok",
            "voice_label": config.tts_voice_label,
            "speaker_id": config.tts_speaker_id,
            "speed": config.tts_speed,
            "model": config.tts_vits_model,
            "model_name": self._read_model_name(config.tts_vits_model),
        }

    # ── Text-Normalisierung vor der Synthese ─────────────────────────────────

    _NUM = r"(\d+(?:[.,]\d+)?)"  # Zahl-Muster

    _ORDINALS_DE: dict[int, str] = {
        1: 'erste', 2: 'zweite', 3: 'dritte', 4: 'vierte', 5: 'fünfte',
        6: 'sechste', 7: 'siebte', 8: 'achte', 9: 'neunte', 10: 'zehnte',
        11: 'elfte', 12: 'zwölfte', 13: 'dreizehnte', 14: 'vierzehnte',
        15: 'fünfzehnte', 16: 'sechzehnte', 17: 'siebzehnte',
        18: 'achtzehnte', 19: 'neunzehnte', 20: 'zwanzigste',
    }

    @classmethod
    def _ordinal_to_de(cls, m: re.Match) -> str:
        n = int(m.group(1))
        return cls._ORDINALS_DE.get(n, f"{n}ste") + ' '

    @staticmethod
    def _year_to_de(m: re.Match) -> str:
        """1100–1999 → deutsche Sprechform (neunzehnhundertneunundachtzig)."""
        _ones = ['', 'ein', 'zwei', 'drei', 'vier', 'fünf', 'sechs', 'sieben',
                 'acht', 'neun', 'zehn', 'elf', 'zwölf', 'dreizehn', 'vierzehn',
                 'fünfzehn', 'sechzehn', 'siebzehn', 'achtzehn', 'neunzehn']
        _tens = ['', '', 'zwanzig', 'dreißig', 'vierzig', 'fünfzig',
                 'sechzig', 'siebzig', 'achtzig', 'neunzig']

        def _two(n: int) -> str:
            if n == 0:   return ''
            if n < 20:   return _ones[n]
            o, t = n % 10, n // 10
            return (_ones[o] + 'und' if o else '') + _tens[t]

        y = int(m.group(1))
        return _two(y // 100) + 'hundert' + _two(y % 100)

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """
        Bereitet Text für TTS auf: Einheiten, Abkürzungen und Sonderzeichen
        werden in sprechbaren Klartext umgewandelt.
        """
        n = cls._NUM

        # Jahreszahlen 1100–1999 → deutsche Sprechform
        # (espeak-ng liest "1989" als "eintausendneunhundert..." statt "neunzehnhundert...")
        text = re.sub(r'\b(1[1-9]\d{2})\b', cls._year_to_de, text)

        # Ordinalzahlen: "2. Platz" → "zweite Platz", "1. Bundesliga" → "erste Bundesliga"
        # Nur 1-2-stellige Zahlen gefolgt von Punkt+Leerzeichen (keine Dezimalzahlen betreffend)
        text = re.sub(r'\b(\d{1,2})\.\s', cls._ordinal_to_de, text)

        # Temperatur
        text = re.sub(rf"{n}\s*°\s*C\b", r"\1 Grad Celsius", text)
        text = re.sub(rf"{n}\s*°\s*F\b", r"\1 Grad Fahrenheit", text)
        text = re.sub(rf"{n}\s*°",       r"\1 Grad", text)

        # Geschwindigkeit / Gewicht / Länge
        text = re.sub(rf"{n}\s*km/h\b",  r"\1 Kilometer pro Stunde", text)
        text = re.sub(rf"{n}\s*m/s\b",   r"\1 Meter pro Sekunde", text)
        text = re.sub(rf"{n}\s*km\b",    r"\1 Kilometer", text, flags=re.IGNORECASE)
        text = re.sub(rf"{n}\s*kg\b",    r"\1 Kilogramm", text, flags=re.IGNORECASE)
        text = re.sub(rf"{n}\s*g\b",     r"\1 Gramm", text)
        text = re.sub(rf"{n}\s*m\b",     r"\1 Meter", text)
        text = re.sub(rf"{n}\s*cm\b",    r"\1 Zentimeter", text, flags=re.IGNORECASE)
        text = re.sub(rf"{n}\s*mm\b",    r"\1 Millimeter", text, flags=re.IGNORECASE)
        text = re.sub(rf"{n}\s*l\b",     r"\1 Liter", text)
        text = re.sub(rf"{n}\s*ml\b",    r"\1 Milliliter", text, flags=re.IGNORECASE)

        # Datenmengen
        text = re.sub(rf"{n}\s*GB\b",    r"\1 Gigabyte", text)
        text = re.sub(rf"{n}\s*MB\b",    r"\1 Megabyte", text)
        text = re.sub(rf"{n}\s*TB\b",    r"\1 Terabyte", text)
        text = re.sub(rf"{n}\s*KB\b",    r"\1 Kilobyte", text)

        # Frequenz
        text = re.sub(rf"{n}\s*GHz\b",   r"\1 Gigahertz", text)
        text = re.sub(rf"{n}\s*MHz\b",   r"\1 Megahertz", text)
        text = re.sub(rf"{n}\s*kHz\b",   r"\1 Kilohertz", text)
        text = re.sub(rf"{n}\s*Hz\b",    r"\1 Hertz", text)

        # Prozent / Währung
        text = re.sub(rf"{n}\s*%",       r"\1 Prozent", text)
        text = re.sub(rf"€\s*{n}",       r"\1 Euro", text)
        text = re.sub(rf"{n}\s*€",       r"\1 Euro", text)
        text = re.sub(rf"\$\s*{n}",      r"\1 Dollar", text)
        text = re.sub(rf"{n}\s*\$",      r"\1 Dollar", text)

        # Abkürzungen
        replacements = [
            ("z.B.", "zum Beispiel"), ("z. B.", "zum Beispiel"),
            ("u.a.", "unter anderem"), ("u. a.", "unter anderem"),
            ("etc.", "et cetera"), ("usw.", "und so weiter"),
            ("bzw.", "beziehungsweise"), ("bzgl.", "bezüglich"),
            ("ca.", "circa"), ("inkl.", "inklusive"), ("exkl.", "exklusive"),
            ("max.", "maximal"), ("min.", "minimal"),
            ("Nr.", "Nummer"), ("Str.", "Straße"),
            ("Dr.", "Doktor"), ("Prof.", "Professor"), ("Hrn.", "Herrn"),
        ]
        for abbr, full in replacements:
            text = text.replace(abbr, full)

        # Sonderzeichen und Symbole
        text = text.replace("&", " und ")
        text = text.replace("→", " wird zu ")
        text = text.replace("←", " kommt von ")
        text = text.replace("–", ", ")
        text = text.replace("—", ", ")
        text = text.replace("|", ", ")
        # Slash nur ersetzen wenn zwischen Buchstaben/Zahlen ohne Protokoll (http:// bleibt)
        text = re.sub(r"(?<!:)(?<!\w)/(?!\w*/)", " oder ", text)

        # Satzenden-Punkte → kurze Pause (Komma) — espeak-ng macht bei "." lange Pausen
        # Nur Punkte die NICHT zwischen Ziffern stehen (Dezimalzahlen bleiben erhalten)
        text = re.sub(r'(?<!\d)\.(?!\d)', ',', text)

        # Leerzeichen bereinigen, überschüssige Kommas am Ende entfernen
        text = re.sub(r"\s{2,}", " ", text).strip().rstrip(',')
        return text

    def synthesize(self, text: str) -> SynthesisResult:
        config = self.settings.get_effective()
        provider = config.tts_provider
        normalized = self.normalize_text(text)
        if provider == "disabled":
            raise RuntimeError("TTS ist aktuell deaktiviert.")
        if provider == "mock":
            return self._synthesize_mock(normalized)
        if provider == "edge_tts":
            return self._synthesize_edge(normalized)
        if provider != "sherpa_onnx":
            raise RuntimeError(f"Unbekannter TTS-Provider: {provider}")
        return self._synthesize_sherpa(normalized)

    def _synthesize_edge(self, text: str) -> SynthesisResult:
        import asyncio, io, os, struct
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts nicht installiert. Bitte 'pip install edge-tts' ausführen.") from exc

        try:
            from app.database.db import get_connection, read_state
            with get_connection() as conn:
                tts_cfg = read_state(conn, "tts_runtime_config", {})
            voice = tts_cfg.get("edge_voice") or os.getenv("ROBOT_TTS_EDGE_VOICE", "de-DE-KatjaNeural")
            rate = tts_cfg.get("edge_rate") or "+0%"
        except Exception:
            voice = os.getenv("ROBOT_TTS_EDGE_VOICE", "de-DE-KatjaNeural")
            rate = "+0%"

        async def _run() -> bytes:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            audio = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
            return audio

        try:
            loop = asyncio.new_event_loop()
            mp3_bytes = loop.run_until_complete(_run())
            loop.close()
        except Exception as exc:
            raise RuntimeError(f"Edge TTS Fehler: {exc}") from exc

        if not mp3_bytes:
            raise RuntimeError("Edge TTS: keine Audiodaten erhalten.")

        return SynthesisResult(
            provider="edge_tts",
            sample_rate=24000,
            duration_seconds=len(mp3_bytes) / 24000,
            audio_bytes=mp3_bytes,
            audio_format="mp3",
        )

    def _synthesize_mock(self, text: str) -> SynthesisResult:
        sample_rate = 22050
        duration = max(0.5, min(3.0, len(text) * 0.03))
        samples: list[float] = []
        total = int(duration * sample_rate)
        for index in range(total):
            t = index / sample_rate
            envelope = 0.4 if (index // 1600) % 2 == 0 else 0.2
            samples.append(math.sin(2 * math.pi * 220 * t) * envelope)
        return SynthesisResult(
            provider="mock",
            sample_rate=sample_rate,
            duration_seconds=duration,
            audio_bytes=self._wav_bytes(samples, sample_rate),
        )

    def _synthesize_sherpa(self, text: str) -> SynthesisResult:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(f"TTS nicht bereit: {status['reason']}")

        config = self.settings.get_effective()
        engine = self._get_or_create_engine()
        sherpa_onnx = importlib.import_module("sherpa_onnx")
        generation = sherpa_onnx.GenerationConfig()
        generation.sid = config.tts_speaker_id
        generation.speed = config.tts_speed
        generation.silence_scale = 0.2
        audio = engine.generate(text, generation)
        samples = list(audio.samples)
        if not samples:
            raise RuntimeError("Sherpa-ONNX hat kein Audio erzeugt.")
        sample_rate = int(audio.sample_rate)
        return SynthesisResult(
            provider="sherpa_onnx",
            sample_rate=sample_rate,
            duration_seconds=len(samples) / sample_rate,
            audio_bytes=self._wav_bytes(samples, sample_rate),
        )

    def _get_or_create_engine(self) -> Any:
        config = self.settings.get_effective()
        signature = (
            config.tts_provider,
            config.tts_vits_model,
            config.tts_tokens,
            config.tts_data_dir,
            config.tts_lexicon,
            config.tts_rule_fsts,
            config.tts_num_threads,
        )
        if self._engine is not None and self._engine_signature == signature:
            return self._engine

        sherpa_onnx = importlib.import_module("sherpa_onnx")
        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=config.tts_vits_model,
                    lexicon=config.tts_lexicon,
                    data_dir=config.tts_data_dir,
                    tokens=config.tts_tokens,
                    noise_scale=0.667,    # Ausdrucksstärke (natürlicher Klang)
                    noise_scale_w=0.8,    # Prosodische Variation (weniger monoton)
                    length_scale=1.0,
                ),
                provider="cpu",
                debug=False,
                num_threads=config.tts_num_threads,
            ),
            rule_fsts=config.tts_rule_fsts,
            max_num_sentences=1,
        )
        if not tts_config.validate():
            raise RuntimeError("Sherpa-ONNX-Konfiguration ist ungültig.")
        self._engine = sherpa_onnx.OfflineTts(tts_config)
        self._engine_signature = signature
        return self._engine

    @staticmethod
    def _wav_bytes(samples: list[float], sample_rate: int) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            pcm = bytearray()
            for sample in samples:
                clamped = max(-1.0, min(1.0, float(sample)))
                value = int(clamped * 32767.0)
                pcm.extend(int(value).to_bytes(2, byteorder="little", signed=True))
            wav_file.writeframes(bytes(pcm))
        return buffer.getvalue()
