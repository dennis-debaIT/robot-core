import os
from typing import Any
from urllib import error

from app.brain.llm_client import ExternalLLMClient, LLMRouter
from app.database.db import get_connection


def test_openai_compatible_reply_extraction(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_URL", "http://example.invalid/v1/chat/completions")
    client = ExternalLLMClient()

    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hallo. Ich bin bereit.",
                }
            }
        ]
    }

    assert client._extract_reply(body) == "Hallo. Ich bin bereit."


def test_openai_compatible_request_body(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_URL", "http://example.invalid/v1/chat/completions")
    monkeypatch.setenv("LLM_MODEL", "qwen-local")
    monkeypatch.setenv("LLM_MAX_TOKENS", "320")
    client = ExternalLLMClient()

    payload = {
        "messages": [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hallo"},
        ]
    }

    request_body = client._build_request_body(payload)
    assert request_body["model"] == "qwen-local"
    assert request_body["messages"][0]["role"] == "system"
    assert request_body["temperature"] == 0.4
    assert request_body["max_tokens"] == 320


def test_openai_compatible_request_body_uses_payload_max_tokens(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_URL", "http://example.invalid/v1/chat/completions")
    client = ExternalLLMClient()

    payload = {
        "messages": [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hallo"},
        ],
        "llm_max_tokens": 512,
    }

    request_body = client._build_request_body(payload)
    assert request_body["max_tokens"] == 512


def test_merge_system_into_first_user_for_models_without_system_support(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_URL", "http://example.invalid/v1/chat/completions")
    client = ExternalLLMClient()

    body = {
        "model": "mistral-local",
        "messages": [
            {"role": "system", "content": "Antworte kurz."},
            {"role": "user", "content": "Hallo"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Wie geht es dir?"},
        ],
    }

    merged = client._merge_system_into_first_user(body)
    assert merged["messages"][0]["role"] == "user"
    assert "System-Anweisungen für diese Unterhaltung" in merged["messages"][0]["content"]
    assert "Antworte kurz." in merged["messages"][0]["content"]
    assert "Nutzeranfrage:\nHallo" in merged["messages"][0]["content"]
    assert all(message["role"] != "system" for message in merged["messages"])


def test_detects_user_assistant_only_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_URL", "http://example.invalid/v1/chat/completions")
    client = ExternalLLMClient()

    class DummyResponse:
        def __init__(self, payload: str) -> None:
            self.payload = payload.encode("utf-8")

        def read(self) -> bytes:
            return self.payload

        def close(self) -> None:
            return None

    exc = error.HTTPError(
        url="http://example.invalid",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=DummyResponse('{"error":"Only user and assistant roles are supported"}'),
    )

    assert client._supports_only_user_and_assistant(exc.read().decode("utf-8")) is True


def _configure_fallback_model(fallback_model: str | None) -> None:
    from app.database.db import write_state

    with get_connection() as conn:
        write_state(conn, "llm_config", {"fallback_model": fallback_model} if fallback_model else {})


def _error_log_entries() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE target_id='llm.fallback' ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


class _FakeExternalGenerate:
    """Simuliert ExternalLLMClient.generate() mit pro-Modell konfigurierbarem Verhalten."""

    behavior: dict[str, Any] = {}

    def __init__(self, model_override=None):
        self.model = model_override or "primary-model"

    def is_configured(self):
        return True

    def generate(self, payload, timeout_seconds=15):
        outcome = self.behavior[self.model]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_router_generate_uses_primary_model_on_success(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalGenerate.behavior = {"primary-model": {"reply": "Hallo", "provider": "external", "used_fallback": False}}
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalGenerate)
    _configure_fallback_model("fallback-model")

    result = LLMRouter().generate({"messages": []})

    assert result["reply"] == "Hallo"
    assert result["provider"] == "external"
    assert _error_log_entries() == []


def test_router_generate_falls_back_to_fallback_model_on_timeout(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalGenerate.behavior = {
        "primary-model": RuntimeError("LLM request failed: timed out"),
        "fallback-model": {"reply": "Fallback-Antwort", "provider": "external", "used_fallback": False},
    }
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalGenerate)
    _configure_fallback_model("fallback-model")

    result = LLMRouter().generate({"messages": []})

    assert result["reply"] == "Fallback-Antwort"
    entries = _error_log_entries()
    # Ein Eintrag für den primären Fehlschlag (mit Fehlerdetails fürs
    # Debugging), einer für den erfolgreichen Umstieg aufs Fallback-Modell —
    # beide "warning", kein "error", da am Ende doch eine echte Antwort kam.
    assert [e["level"] for e in entries] == ["warning", "warning"]
    assert "Primäres LLM" in entries[0]["summary"]
    assert "Fallback-Modell" in entries[1]["summary"]


def test_router_generate_falls_back_to_mock_when_both_models_fail(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalGenerate.behavior = {
        "primary-model": RuntimeError("timed out"),
        "fallback-model": RuntimeError("timed out too"),
    }
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalGenerate)
    _configure_fallback_model("fallback-model")

    result = LLMRouter().generate({"messages": [], "message": "Hallo", "personality": {"directness": 0.9}})

    assert result["provider"] == "mock"
    entries = _error_log_entries()
    levels = [e["level"] for e in entries]
    assert levels.count("warning") == 1
    assert levels.count("error") == 2


def test_router_generate_without_configured_fallback_model_goes_straight_to_mock(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalGenerate.behavior = {"primary-model": RuntimeError("timed out")}
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalGenerate)
    _configure_fallback_model(None)

    result = LLMRouter().generate({"messages": [], "message": "Hallo", "personality": {"directness": 0.9}})

    assert result["provider"] == "mock"
    entries = _error_log_entries()
    assert [e["level"] for e in entries] == ["warning", "error"]


class _FakeExternalStream:
    """Simuliert ExternalLLMClient.stream_generate() mit pro-Modell konfigurierbarem Verhalten.

    behavior[model] ist entweder eine Exception (wird beim ersten next()
    geworfen, wie bei einem echten Verbindungs-/Timeout-Fehler) oder eine
    Liste von Text-Fragmenten.
    """

    behavior: dict[str, Any] = {}

    def __init__(self, model_override=None):
        self.model = model_override or "primary-model"

    def is_configured(self):
        return True

    def stream_generate(self, payload, timeout_seconds=15):
        outcome = self.behavior[self.model]
        if isinstance(outcome, Exception):
            raise outcome
        yield from outcome


def test_router_stream_generate_primes_and_returns_primary_fragments(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalStream.behavior = {"primary-model": ["Hallo", " Welt"]}
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalStream)
    _configure_fallback_model("fallback-model")

    provider, fragments, used_fallback = LLMRouter().stream_generate({"messages": []})

    assert provider == "external"
    assert used_fallback is False
    assert list(fragments) == ["Hallo", " Welt"]
    assert _error_log_entries() == []


def test_router_stream_generate_switches_to_fallback_model_on_connection_error(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalStream.behavior = {
        # Die echte ExternalLLMClient.stream_generate() fängt Timeouts/
        # Verbindungsfehler intern ab und wirft nach außen immer eine
        # generische RuntimeError (siehe llm_client.py) — das bildet die
        # Fake hier nach, statt einen rohen TimeoutError zu werfen.
        "primary-model": RuntimeError("LLM stream request failed: timed out"),
        "fallback-model": ["Fallback", " Antwort"],
    }
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalStream)
    _configure_fallback_model("fallback-model")

    provider, fragments, used_fallback = LLMRouter().stream_generate({"messages": []})

    assert provider == "external_fallback"
    assert used_fallback is False
    assert list(fragments) == ["Fallback", " Antwort"]
    entries = _error_log_entries()
    assert [e["level"] for e in entries] == ["warning", "warning"]


def test_router_stream_generate_falls_back_to_mock_when_both_models_fail(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalStream.behavior = {
        "primary-model": RuntimeError("timed out"),
        "fallback-model": RuntimeError("timed out too"),
    }
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalStream)
    _configure_fallback_model("fallback-model")

    provider, fragments, used_fallback = LLMRouter().stream_generate({"messages": [], "message": "Hallo", "personality": {"directness": 0.9}})

    assert provider == "mock"
    assert used_fallback is True
    assert list(fragments)  # Mock liefert mindestens ein Fragment
    entries = _error_log_entries()
    levels = [e["level"] for e in entries]
    assert levels.count("warning") == 1
    assert levels.count("error") == 2


def test_router_stream_generate_empty_primary_response_is_not_treated_as_error(monkeypatch, temp_db):
    import app.brain.llm_client as mod

    _FakeExternalStream.behavior = {"primary-model": []}
    monkeypatch.setattr(mod, "ExternalLLMClient", _FakeExternalStream)
    _configure_fallback_model("fallback-model")

    provider, fragments, used_fallback = LLMRouter().stream_generate({"messages": []})

    assert provider == "external"
    assert used_fallback is False
    assert list(fragments) == []
    assert _error_log_entries() == []
