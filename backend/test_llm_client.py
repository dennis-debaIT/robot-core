import os
from urllib import error

from app.brain.llm_client import ExternalLLMClient


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

    exc = error.HTTPError(
        url="http://example.invalid",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=DummyResponse('{"error":"Only user and assistant roles are supported"}'),
    )

    assert client._supports_only_user_and_assistant(exc) is True
