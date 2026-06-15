from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any
from urllib import error, request


class MockLLMClient:
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        message = payload["message"].strip()
        personality = payload["personality"]
        prefix = "Klar." if personality["directness"] >= 0.65 else "Gerne."

        if not message:
            reply = "Ich bin bereit."
        elif "hallo" in message.lower():
            reply = "Hallo. Wie kann ich helfen?"
        else:
            reply = f"{prefix} {message[:120]}"

        if personality["humor"] > 0.7 and "witz" in message.lower():
            reply = "Klar. Ein kurzer Roboterwitz passt immer."

        return {"reply": reply, "provider": "mock", "used_fallback": True}

    def stream_generate(self, payload: dict[str, Any]) -> Any:
        result = self.generate(payload)
        yield result["reply"]


class RateLimitError(RuntimeError):
    """Wird ausgelöst wenn der LLM-Provider einen 429 zurückgibt."""


class ExternalLLMClient:
    def __init__(self, model_override: str | None = None) -> None:
        db = self._load_db_config()
        self.api_url     = db.get("api_url")  or os.getenv("LLM_API_URL")
        self.api_key     = db.get("api_key")  or os.getenv("LLM_API_KEY")
        self.model       = model_override or db.get("model") or os.getenv("LLM_MODEL", "").strip()
        self.provider    = "openai_compat"
        self.temperature = self._temperature_from_personality() or (
            float(db["temperature"]) if db.get("temperature") is not None
            else self._read_float_env("LLM_TEMPERATURE", 0.4)
        )
        self.max_tokens = int(db["max_tokens"]) if db.get("max_tokens") is not None else self._read_int_env("LLM_MAX_TOKENS", 320)

    @staticmethod
    def _temperature_from_personality() -> float | None:
        try:
            from app.database.db import get_connection, read_state
            with get_connection() as conn:
                p = read_state(conn, "personality", {}) or {}
            humor         = float(p.get("humor",         0.5))
            curiosity     = float(p.get("curiosity",     0.5))
            talkativeness = float(p.get("talkativeness", 0.5))
            temp = round(0.20 + humor * 0.25 + curiosity * 0.20 + talkativeness * 0.10, 3)
            return max(0.1, min(1.5, temp))
        except Exception:
            return None

    @staticmethod
    def _load_db_config() -> dict[str, Any]:
        try:
            from app.database.db import get_connection, read_state
            with get_connection() as conn:
                cfg = read_state(conn, "llm_config", {}) or {}
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    def is_configured(self) -> bool:
        return bool(self.api_url)

    def generate(self, payload: dict[str, Any], timeout_seconds: int = 15) -> dict[str, Any]:
        if not self.api_url:
            raise RuntimeError("LLM_API_URL is not configured")

        body = self._build_request_body(payload)
        try:
            body = self._post_json(body, timeout_seconds=timeout_seconds)
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        reply = self._extract_reply(body)
        if not reply:
            raise RuntimeError("LLM response did not contain reply text")

        return {"reply": str(reply), "provider": "external", "used_fallback": False}

    def stream_generate(self, payload: dict[str, Any], timeout_seconds: int = 15) -> Any:
        if not self.api_url:
            raise RuntimeError("LLM_API_URL is not configured")

        try:
            body = self._build_request_body(payload, stream=True)
            emitted_fragment = False
            response = self._open_request(body, timeout_seconds=timeout_seconds)
            with response:
                self._save_rate_limit_headers(response.headers)
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    fragment = self._extract_stream_fragment(json.loads(data))
                    if fragment:
                        emitted_fragment = True
                        yield fragment
            if not emitted_fragment:
                yield from self._stream_via_nonstream_fallback(payload, timeout_seconds)
        except (error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            try:
                yield from self._stream_via_nonstream_fallback(payload, timeout_seconds)
            except Exception:
                raise RuntimeError(f"LLM stream request failed: {exc}") from exc

    def _build_request_body(self, payload: dict[str, Any], stream: bool = False) -> dict[str, Any]:
        max_tokens = payload.get("llm_max_tokens", self.max_tokens)
        if self.provider == "openai_compat":
            api_url = (self.api_url or "").lower()
            is_local = "localhost" in api_url or "127.0.0.1" in api_url or "lmstudio" in api_url
            body: dict[str, Any] = {
                "model": self.model or "local-model",
                "messages": payload["messages"],
                "temperature": self.temperature,
                "max_completion_tokens": max_tokens,
                "max_tokens": max_tokens,
            }
            if is_local:
                # Qwen3 Thinking-Modus deaktivieren — nur für lokale Modelle
                body["enable_thinking"] = False
            if stream:
                body["stream"] = True
            return body
        return payload

    def _request_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
        }

    def _stream_via_nonstream_fallback(self, payload: dict[str, Any], timeout_seconds: int) -> Any:
        fallback_body = self._build_request_body(payload, stream=False)
        fallback = self._post_json(fallback_body, timeout_seconds=timeout_seconds)
        reply = self._extract_reply(fallback)
        if not reply:
            return
        for piece in self._chunk_text(str(reply)):
            yield piece

    def _post_json(self, body: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        with self._open_request(body, timeout_seconds=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
            self._save_rate_limit_headers(response.headers)
            return data

    @staticmethod
    def _save_rate_limit_headers(headers: Any) -> None:
        try:
            from app.database.db import get_connection, write_state
            remaining = headers.get("x-ratelimit-remaining-requests")
            limit      = headers.get("x-ratelimit-limit-requests")
            reset_req  = headers.get("x-ratelimit-reset-requests")
            rem_tokens = headers.get("x-ratelimit-remaining-tokens")
            lim_tokens = headers.get("x-ratelimit-limit-tokens")
            if remaining is None:
                return
            from datetime import datetime, timezone
            payload = {
                "remaining_requests": int(remaining) if remaining else None,
                "limit_requests":     int(limit)     if limit     else None,
                "reset_requests":     reset_req,
                "remaining_tokens":   int(rem_tokens) if rem_tokens else None,
                "limit_tokens":       int(lim_tokens) if lim_tokens else None,
                "updated_at":         datetime.now(timezone.utc).isoformat(),
            }
            with get_connection() as conn:
                write_state(conn, "llm_rate_limit", payload)
        except Exception:
            pass

    def _open_request(self, body: dict[str, Any], timeout_seconds: int):
        req = request.Request(
            self.api_url,
            data=json.dumps(body).encode("utf-8"),
            headers=self._request_headers(),
            method="POST",
        )
        try:
            return request.urlopen(req, timeout=timeout_seconds)
        except error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = ""
            if exc.code == 429:
                raise RateLimitError(f"Rate limit erreicht (429): {error_body[:200]}") from exc
            if self._supports_only_user_and_assistant(error_body):
                fallback_body = self._merge_system_into_first_user(body)
                fallback_req = request.Request(
                    self.api_url,
                    data=json.dumps(fallback_body).encode("utf-8"),
                    headers=self._request_headers(),
                    method="POST",
                )
                return request.urlopen(fallback_req, timeout=timeout_seconds)
            raise error.HTTPError(
                exc.url, exc.code,
                f"{exc.reason} — {error_body[:300]}" if error_body else exc.reason,
                exc.headers, None,
            )

    def _supports_only_user_and_assistant(self, error_body: str) -> bool:
        return 'Only user and assistant roles are supported' in error_body

    def _merge_system_into_first_user(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.provider != "openai_compat":
            return body

        messages = deepcopy(body.get("messages") or [])
        if not messages:
            return body

        system_parts = [msg.get("content", "").strip() for msg in messages if msg.get("role") == "system"]
        conversation = [msg for msg in messages if msg.get("role") != "system"]
        if not system_parts or not conversation:
            return body

        merged = "\n\n".join(part for part in system_parts if part).strip()
        first = conversation[0]
        if first.get("role") != "user":
            return body

        first_content = first.get("content", "").strip()
        first["content"] = f"System-Anweisungen für diese Unterhaltung:\n{merged}\n\nNutzeranfrage:\n{first_content}".strip()

        fallback_body = deepcopy(body)
        fallback_body["messages"] = conversation
        return fallback_body

    @staticmethod
    def _chunk_text(text: str, max_chars: int = 80) -> list[str]:
        if len(text) <= max_chars:
            return [text]

        pieces: list[str] = []
        current = ""
        for token in text.split(" "):
            candidate = token if not current else f"{current} {token}"
            if len(candidate) > max_chars and current:
                pieces.append(current)
                current = token
            else:
                current = candidate
        if current:
            pieces.append(current)
        return pieces or [text]

    def _extract_reply(self, body: dict[str, Any]) -> str | None:
        if self.provider == "openai_compat":
            choices = body.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [item.get("text", "") for item in content if isinstance(item, dict)]
                    return "".join(parts).strip() or None
                text = choices[0].get("text")
                if isinstance(text, str):
                    return text
        return body.get("reply") or body.get("message") or body.get("text")

    def _extract_stream_fragment(self, body: dict[str, Any]) -> str | None:
        if self.provider == "openai_compat":
            choices = body.get("choices") or []
            if not choices:
                return None
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [item.get("text", "") for item in content if isinstance(item, dict)]
                text = "".join(parts).strip()
                return text or None
        return None

    @staticmethod
    def _read_float_env(name: str, default: float) -> float:
        value = os.getenv(name)
        if not value:
            return default
        try:
            return float(value)
        except ValueError:
            return default

    @staticmethod
    def _read_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if not value:
            return default
        try:
            return int(value)
        except ValueError:
            return default


class LLMRouter:
    def __init__(self) -> None:
        self.mock = MockLLMClient()

    @staticmethod
    def _fallback_model() -> str | None:
        try:
            from app.database.db import get_connection, read_state
            with get_connection() as conn:
                cfg = read_state(conn, "llm_config", {}) or {}
            return cfg.get("fallback_model") or None
        except Exception:
            return None

    def generate(self, payload: dict[str, Any], timeout_seconds: int = 15) -> dict[str, Any]:
        external = ExternalLLMClient()
        if external.is_configured():
            try:
                return external.generate(payload, timeout_seconds=timeout_seconds)
            except RateLimitError:
                fb = self._fallback_model()
                if fb and fb != external.model:
                    try:
                        return ExternalLLMClient(model_override=fb).generate(payload, timeout_seconds=timeout_seconds)
                    except RuntimeError:
                        pass
            except RuntimeError:
                pass
        return self.mock.generate(payload)

    def stream_generate(self, payload: dict[str, Any], timeout_seconds: int = 15) -> tuple[str, Any, bool]:
        external = ExternalLLMClient()
        if external.is_configured():
            try:
                return "external", external.stream_generate(payload, timeout_seconds=timeout_seconds), False
            except RateLimitError:
                fb = self._fallback_model()
                if fb and fb != external.model:
                    try:
                        fb_client = ExternalLLMClient(model_override=fb)
                        return "external_fallback", fb_client.stream_generate(payload, timeout_seconds=timeout_seconds), False
                    except RuntimeError:
                        pass
            except RuntimeError:
                pass
        return "mock", self.mock.stream_generate(payload), True
