import os
from typing import Any

from pydantic import BaseModel, Field

from app.database.db import get_connection, read_state, write_state


def env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


class CoreSettings(BaseModel):
    quiet_minutes: int = Field(default=5, ge=1, le=120)
    critical_battery_threshold: int = Field(default=20, ge=0, le=100)
    greeting_suggestion_template: str = "Kurze Begrüßung für {person_name} vorschlagen."
    response_style: str = "kurz, freundlich und präzise"
    explain_only_on_request: bool = True
    llm_timeout_seconds: int = Field(default=45, ge=1, le=120)
    llm_max_tokens: int = Field(default=320, ge=64, le=2048)
    llm_history_turns: int = Field(default=8, ge=0, le=20)
    topic_interest_threshold: int = Field(default=3, ge=2, le=10)
    topic_interest_window_days: int = Field(default=14, ge=1, le=90)
    personality_friendliness: float = Field(default=0.90, ge=0.0, le=1.0)
    personality_humor: float = Field(default=0.65, ge=0.0, le=1.0)
    personality_curiosity: float = Field(default=0.75, ge=0.0, le=1.0)
    personality_talkativeness: float = Field(default=0.45, ge=0.0, le=1.0)
    personality_caution: float = Field(default=0.80, ge=0.0, le=1.0)
    personality_directness: float = Field(default=0.70, ge=0.0, le=1.0)
    personality_sarcasm: float = Field(default=0.15, ge=0.0, le=1.0)
    personality_patience: float = Field(default=0.85, ge=0.0, le=1.0)
    tts_provider: str = "disabled"
    tts_voice_label: str = ""
    tts_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_speaker_id: int = Field(default=0, ge=0, le=200)
    tts_num_threads: int = Field(default=2, ge=1, le=16)
    tts_vits_model: str = ""
    tts_tokens: str = ""
    tts_data_dir: str = ""
    tts_lexicon: str = ""
    tts_rule_fsts: str = ""


class SettingsService:
    state_key = "runtime_config_overrides"

    def load_env_defaults(self) -> CoreSettings:
        return CoreSettings(
            quiet_minutes=env_int("ROBOT_QUIET_MINUTES", 5),
            critical_battery_threshold=env_int("ROBOT_CRITICAL_BATTERY_THRESHOLD", 20),
            greeting_suggestion_template=env_str(
                "ROBOT_GREETING_SUGGESTION_TEMPLATE",
                "Kurze Begrüßung für {person_name} vorschlagen.",
            ),
            response_style=env_str(
                "ROBOT_RESPONSE_STYLE",
                "kurz, freundlich und präzise",
            ),
            explain_only_on_request=env_str("ROBOT_EXPLAIN_ONLY_ON_REQUEST", "true").lower() != "false",
            llm_timeout_seconds=env_int("ROBOT_LLM_TIMEOUT_SECONDS", 45),
            llm_max_tokens=env_int("ROBOT_LLM_MAX_TOKENS", 320),
            llm_history_turns=env_int("ROBOT_LLM_HISTORY_TURNS", 8),
            topic_interest_threshold=env_int("ROBOT_TOPIC_INTEREST_THRESHOLD", 3),
            topic_interest_window_days=env_int("ROBOT_TOPIC_INTEREST_WINDOW_DAYS", 14),
            personality_friendliness=env_float("ROBOT_DEFAULT_FRIENDLINESS", 0.90),
            personality_humor=env_float("ROBOT_DEFAULT_HUMOR", 0.65),
            personality_curiosity=env_float("ROBOT_DEFAULT_CURIOSITY", 0.75),
            personality_talkativeness=env_float("ROBOT_DEFAULT_TALKATIVENESS", 0.45),
            personality_caution=env_float("ROBOT_DEFAULT_CAUTION", 0.80),
            personality_directness=env_float("ROBOT_DEFAULT_DIRECTNESS", 0.70),
            personality_sarcasm=env_float("ROBOT_DEFAULT_SARCASM", 0.15),
            personality_patience=env_float("ROBOT_DEFAULT_PATIENCE", 0.85),
            tts_provider=env_str("ROBOT_TTS_PROVIDER", "disabled"),
            tts_voice_label=env_str("ROBOT_TTS_VOICE_LABEL", ""),
            tts_speed=env_float("ROBOT_TTS_SPEED", 1.0),
            tts_speaker_id=env_int("ROBOT_TTS_SPEAKER_ID", 0),
            tts_num_threads=env_int("ROBOT_TTS_NUM_THREADS", 2),
            tts_vits_model=env_str("ROBOT_TTS_VITS_MODEL", ""),
            tts_tokens=env_str("ROBOT_TTS_TOKENS", ""),
            tts_data_dir=env_str("ROBOT_TTS_DATA_DIR", ""),
            tts_lexicon=env_str("ROBOT_TTS_LEXICON", ""),
            tts_rule_fsts=env_str("ROBOT_TTS_RULE_FSTS", ""),
        )

    def ensure_runtime_state(self) -> None:
        with get_connection() as conn:
            existing = conn.execute("SELECT 1 FROM system_state WHERE key = ?", (self.state_key,)).fetchone()
            if not existing:
                write_state(conn, self.state_key, {})

    def get_runtime_overrides(self) -> dict[str, Any]:
        with get_connection() as conn:
            return read_state(conn, self.state_key, {})

    def get_effective(self) -> CoreSettings:
        base = self.load_env_defaults().model_dump()
        merged = {**base, **self.get_runtime_overrides()}
        return CoreSettings(**merged)

    def update_runtime_overrides(self, patch: dict[str, Any]) -> CoreSettings:
        current = self.get_runtime_overrides()
        updated = {**current, **patch}
        validated = CoreSettings(**{**self.load_env_defaults().model_dump(), **updated})
        with get_connection() as conn:
            write_state(conn, self.state_key, updated)
        return validated

    def describe(self) -> dict[str, Any]:
        return {
            "environment_defaults": self.load_env_defaults().model_dump(),
            "runtime_overrides": self.get_runtime_overrides(),
            "effective": self.get_effective().model_dump(),
        }
