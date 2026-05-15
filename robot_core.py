from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.brain.decision_engine import CandidateKind, DecisionEngine
from app.brain.initiative import InitiativeEngine
from app.brain.llm_client import LLMRouter
from app.brain.personality import PersonalityService
from app.brain.prompt_builder import PromptBuilder
from app.audit.service import AuditService
from app.cloud.service import CloudBoundaryService
from app.conversation.service import ConversationService
from app.core.settings import SettingsService
from app.database.db import get_connection, read_state, write_state
from app.device.service import DeviceService
from app.hardware.fake_battery import FakeBattery
from app.hardware.fake_camera import FakeCamera
from app.hardware.fake_microphone import FakeMicrophone
from app.memory.service import MemoryService
from app.profile.service import PersonProfileService


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RobotCore:
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA70-\U0001FAFF"
        "]+",
        flags=re.UNICODE,
    )
    BATTERY_QUESTION_PATTERN = re.compile(
        r"\b(akku|batterie|ladestand)\b.*\b(wie viel|wieviel|wie hoch|prozent|stand)\b"
        r"|\b(wie viel|wieviel|wie hoch)\b.*\b(akku|batterie|ladestand)\b",
        re.IGNORECASE,
    )
    UPDATE_QUESTION_PATTERN = re.compile(
        r"\b(update|updates|aktualisierung|aktualisierungen)\b",
        re.IGNORECASE,
    )
    DISPLAY_QUESTION_PATTERN = re.compile(
        r"\b(display|anzeige)\b.*\b(status|zustand|anzeigt|zeigt)\b"
        r"|\b(status|zustand)\b.*\b(display|anzeige)\b",
        re.IGNORECASE,
    )
    DEVICE_STATE_QUESTION_PATTERN = re.compile(
        r"\b(gerÃ¤tezustand|geraetezustand|status|lage)\b",
        re.IGNORECASE,
    )
    KNOWLEDGE_QUESTION_PATTERN = re.compile(
        r"\b(?:was\s+wei(?:ÃŸ|ss)t\s+du\s+Ã¼ber|erzÃ¤hl(?:e)?\s+mir\s+etwas\s+Ã¼ber)\s+([A-Za-zÃ„Ã–ÃœÃ¤Ã¶Ã¼ÃŸ][A-Za-zÃ„Ã–ÃœÃ¤Ã¶Ã¼ÃŸ-]*)",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self.settings = SettingsService()
        self.audit = AuditService()
        self.cloud = CloudBoundaryService()
        self.conversation = ConversationService()
        self.device = DeviceService()
        self.personality = PersonalityService()
        self.memory = MemoryService()
        self.profile = PersonProfileService()
        self.decision_engine = DecisionEngine()
        self.prompt_builder = PromptBuilder()
        self.llm = LLMRouter()
        self.initiative = InitiativeEngine()
        self.camera = FakeCamera()
        self.microphone = FakeMicrophone()
        self.battery = FakeBattery()
        self.cloud.ensure_state()
        self.device.ensure_state()

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO events(event_type, payload, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(payload), now_iso()),
            )

    def _log_message(self, role: str, message: str, person_name: str | None) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages(role, person_name, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (role, person_name, message, now_iso()),
            )

    def _approved_memories_for_prompt(
        self,
        person_name: str | None,
        message: str | None = None,
        limit: int = 4,
    ) -> list[str]:
        if not person_name:
            return []
        items = self.memory.list_approved_for_subject(person_name)
        if not items:
            return []

        query_tokens = self._prompt_keywords(message or "")
        scored: list[tuple[int, int, str]] = []
        for index, item in enumerate(items):
            content = item["content"]
            overlap = len(query_tokens & self._prompt_keywords(content)) if query_tokens else 0
            scored.append((overlap, index, content))

        scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        if query_tokens:
            selected = [content for score, _, content in scored if score > 0][:limit]
            return selected
        return []

    @staticmethod
    def _prompt_keywords(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[A-Za-zÃ„Ã–ÃœÃ¤Ã¶Ã¼ÃŸ0-9-]{3,}", text.casefold())
            if token not in {"und", "oder", "aber", "dass", "weil", "eine", "einer", "einem", "einen"}
        }

    @staticmethod
    def _sanitize_reply_text(reply: str) -> str:
        cleaned = reply.replace("\r", "")
        cleaned = re.sub(r"(?m)^\s*[*-]\s+", "", cleaned)
        cleaned = cleaned.replace("  \n", "\n")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"(?m)^\s*[^\wÄÖÜäöüß0-9\s]{1,3}\s*$", "", cleaned)
        cleaned = RobotCore.EMOJI_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r" *\n *", "\n", cleaned)
        paragraphs: list[str] = []
        seen_paragraphs: set[str] = set()
        for part in cleaned.split("\n\n"):
            normalized = re.sub(r"\s+", " ", part).strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen_paragraphs:
                continue
            seen_paragraphs.add(key)
            paragraphs.append(normalized)
        cleaned = "\n\n".join(paragraphs)
        return cleaned.strip()

    def _personalize_response(
        self,
        *,
        person_name: str | None,
        default_response_style: str,
    ) -> tuple[dict[str, Any], str, list[str]]:
        personality = dict(self.personality.get())
        response_style = default_response_style
        preference_lines: list[str] = []
        preferences = self.profile.get_response_preferences(person_name)

        humor_preference = preferences.get("response_humor_preference")
        if humor_preference == "higher":
            personality["humor"] = min(1.0, personality["humor"] + 0.18)
            personality["friendliness"] = min(1.0, personality["friendliness"] + 0.04)
            preference_lines.append("Diese Person mag eher humorvolle Antworten, solange sie kurz und passend bleiben.")
        elif humor_preference == "lower":
            personality["humor"] = max(0.0, personality["humor"] - 0.18)
            personality["sarcasm"] = max(0.0, personality["sarcasm"] - 0.05)
            preference_lines.append("Diese Person mag eher nüchterne Antworten ohne unnötige Witze.")

        style_preference = preferences.get("response_style_preference")
        if style_preference == "sachlich":
            response_style = "sachlich, klar und präzise"
            personality["directness"] = min(1.0, personality["directness"] + 0.08)
            personality["talkativeness"] = max(0.0, personality["talkativeness"] - 0.08)
            preference_lines.append("Diese Person bevorzugt einen sachlichen, nüchternen Ton.")
        elif style_preference == "locker":
            response_style = "locker, freundlich und natürlich"
            personality["friendliness"] = min(1.0, personality["friendliness"] + 0.05)
            personality["directness"] = max(0.0, personality["directness"] - 0.04)
            preference_lines.append("Diese Person mag einen lockereren, persönlichen Ton.")

        length_preference = preferences.get("response_length_preference")
        if length_preference == "short":
            personality["talkativeness"] = max(0.0, personality["talkativeness"] - 0.16)
            preference_lines.append("Diese Person bevorzugt eher kurze Antworten.")
        elif length_preference == "detailed":
            personality["talkativeness"] = min(1.0, personality["talkativeness"] + 0.16)
            preference_lines.append("Diese Person akzeptiert etwas ausführlichere Antworten, wenn sie hilfreich sind.")

        return personality, response_style, preference_lines

    @staticmethod
    def _materialization_policy(memory: dict[str, Any]) -> dict[str, str]:
        if memory.get("candidate_kind") == CandidateKind.PROFILE.value:
            return {
                "action": "profile_fact",
                "reason": "candidate_marked_as_profile",
            }
        return {
            "action": "person_stub",
            "reason": "memory_only_for_subject",
        }

    def _build_status(self) -> dict[str, Any]:
        settings = self.settings.get_effective()
        device = self.device.get()
        with get_connection() as conn:
            battery_level = read_state(conn, "battery_level", 100)
            display_status = read_state(conn, "display_status", "idle")
            last_person = read_state(conn, "last_person_detected")
            active_person = read_state(conn, "active_person_name")
            last_person_detected_at = read_state(conn, "last_person_detected_at")
            last_conversation_at = read_state(conn, "last_conversation_at")
            initiative_last_suggested_at = read_state(conn, "initiative_last_suggested_at")
            event_count = conn.execute("SELECT COUNT(*) AS total FROM events").fetchone()["total"]
            pending_memory_count = conn.execute(
                "SELECT COUNT(*) AS total FROM memory_entries WHERE status = 'pending'"
            ).fetchone()["total"]

        current_person = active_person or last_person
        known_person = bool(current_person and self.memory.list_approved_for_subject(current_person))
        initiative = self.initiative.evaluate(
            person_name=last_person,
            known_person=known_person,
            battery_level=battery_level,
            last_conversation_at=last_conversation_at,
            initiative_last_suggested_at=initiative_last_suggested_at,
            quiet_minutes=settings.quiet_minutes,
            critical_battery_threshold=settings.critical_battery_threshold,
            greeting_suggestion_template=settings.greeting_suggestion_template,
        )

        return {
            "battery_level": battery_level,
            "display_status": display_status,
            "active_person_name": active_person,
            "last_person_detected": last_person,
            "last_person_detected_at": last_person_detected_at,
            "last_conversation_at": last_conversation_at,
            "known_person_detected": known_person,
            "initiative": initiative,
            "pending_memory_count": pending_memory_count,
            "event_count": event_count,
            "device": device,
            "config": {
                "quiet_minutes": settings.quiet_minutes,
                "critical_battery_threshold": settings.critical_battery_threshold,
                "response_style": settings.response_style,
                "explain_only_on_request": settings.explain_only_on_request,
                "llm_max_tokens": settings.llm_max_tokens,
                "llm_history_turns": settings.llm_history_turns,
                "topic_interest_threshold": settings.topic_interest_threshold,
                "topic_interest_window_days": settings.topic_interest_window_days,
            },
        }

    def get_status(self) -> dict[str, Any]:
        return self._build_status()

    def get_device_identity(self) -> dict[str, Any]:
        return self.cloud.get_device_identity()

    def get_sync_contract(self) -> dict[str, Any]:
        return self.cloud.get_sync_contract()

    def get_device(self) -> dict[str, Any]:
        return self.device.get()

    def update_device(self, patch: dict[str, Any]) -> dict[str, Any]:
        updated = self.device.update(patch)
        self.audit.log(
            action="device.updated",
            target_type="device",
            target_id=updated["device_name"],
            summary="GerÃ¤tezustand wurde aktualisiert.",
            details={
                "device_name": updated["device_name"],
                "effective_state": updated["effective_state"],
                "network_connected": updated["network_connected"],
                "server_connected": updated["server_connected"],
                "update_status": updated["update_status"],
            },
        )
        return updated

    def list_audit_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.audit.list_entries(limit=limit)

    def list_conversation_messages(self, person_name: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        with get_connection() as conn:
            if person_name:
                rows = conn.execute(
                    """
                    SELECT id, role, person_name, message, created_at
                    FROM conversation_messages
                    WHERE lower(coalesce(person_name, '')) = lower(?)
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (person_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, role, person_name, message, created_at
                    FROM conversation_messages
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_person_preferences(self, person_id: int) -> dict[str, Any] | None:
        person = self.profile.get_person_by_id(person_id)
        if not person:
            return None
        return {
            "person_id": person["id"],
            "person_name": person["name"],
            "preferences": self.profile.get_response_preferences(person["name"]),
        }

    def update_person_preferences(self, person_id: int, patch: dict[str, str]) -> dict[str, Any] | None:
        person = self.profile.get_person_by_id(person_id)
        if not person:
            return None

        for trait_type, value in patch.items():
            self.profile.upsert_fact(
                person_name=person["name"],
                trait_type=trait_type,
                value=value,
                source_memory_id=None,
                confidence=1.0,
            )

        updated = self.get_person_preferences(person_id)
        self.audit.log(
            action="profile.preferences_updated",
            target_type="person",
            target_id=str(person_id),
            summary="Antwortpräferenzen der Person wurden geändert.",
            details={"person_name": person["name"], "patch": patch},
        )
        return updated

    def propose_memory(
        self,
        *,
        content: str,
        category: str = "general",
        subject: str | None = None,
        source: str = "api",
    ) -> dict[str, Any]:
        if category == "general":
            decision = self.decision_engine.analyze_chat(content, subject)
            if decision.candidates:
                candidate = decision.candidates[0]
                return self.memory.propose(
                    content=candidate.content,
                    category=candidate.category,
                    subject=candidate.subject,
                    source=source,
                    dedupe_statuses=("pending", "approved"),
                    candidate_kind=candidate.kind.value,
                    decision_reason=candidate.reason,
                    confidence=candidate.confidence,
                )

        return self.memory.propose(
            content=content,
            category=category,
            subject=subject,
            source=source,
        )

    def preview_chat_prompt(self, message: str, person_name: str | None = None) -> dict[str, Any]:
        settings = self.settings.get_effective()
        status = self.get_status()
        effective_personality, effective_response_style, preference_lines = self._personalize_response(
            person_name=person_name,
            default_response_style=settings.response_style,
        )
        recent_messages, selection_meta = self.conversation.select_prompt_messages(
            person_name=person_name,
            current_message=message,
            limit=settings.llm_history_turns,
        )
        payload = self.prompt_builder.build_chat_payload(
            message=message,
            person_name=person_name,
            personality=effective_personality,
            approved_memories=self._approved_memories_for_prompt(person_name, message=message),
            recent_messages=recent_messages,
            runtime_facts={
                "battery_level": status["battery_level"],
                "display_status": status["display_status"],
                "device_state": status["device"]["effective_state"],
            },
            response_style=effective_response_style,
            explain_only_on_request=settings.explain_only_on_request,
            person_preference_lines=preference_lines,
        )
        payload["llm_max_tokens"] = settings.llm_max_tokens
        payload["context"]["selection"] = selection_meta
        return payload

    def _prepare_chat(self, message: str, person_name: str | None = None) -> tuple[str, dict[str, Any], list[dict[str, Any]], Any]:
        settings = self.settings.get_effective()
        captured = self.microphone.capture_text(message)
        decision = self.decision_engine.analyze_chat(captured, person_name)
        proposed_memories = [
            self.memory.propose(
                content=candidate.content,
                category=candidate.category,
                subject=candidate.subject,
                source="chat_auto",
                dedupe_statuses=("pending", "approved"),
                candidate_kind=candidate.kind.value,
                decision_reason=candidate.reason,
                confidence=candidate.confidence,
            )
            for candidate in decision.candidates
            if candidate.kind in {CandidateKind.MEMORY, CandidateKind.PROFILE}
        ]
        interest_signal = self.conversation.detect_interest_signal(
            person_name=person_name,
            text=captured,
            threshold=settings.topic_interest_threshold,
            window_days=settings.topic_interest_window_days,
        )
        if interest_signal:
            proposed_memories.append(
                self.memory.propose(
                    content=interest_signal["content"],
                    category=interest_signal["category"],
                    subject=interest_signal["subject"],
                    source="chat_topic_tracking",
                    dedupe_statuses=("pending", "approved"),
                    candidate_kind=CandidateKind.MEMORY.value,
                    decision_reason=interest_signal["reason"],
                    confidence=interest_signal["confidence"],
                )
            )

        payload = self.preview_chat_prompt(captured, person_name)
        self._log_event("speech_input", {"text": captured, "person_name": person_name})
        self._log_message("user", captured, person_name)
        self.conversation.record_user_topics(person_name, captured)

        with get_connection() as conn:
            write_state(conn, "display_status", "listening")
            write_state(conn, "active_person_name", person_name)

        return captured, payload, proposed_memories, decision

    def _record_direct_chat_input(self, captured: str, person_name: str | None) -> None:
        self._log_event("speech_input", {"text": captured, "person_name": person_name})
        self._log_message("user", captured, person_name)
        self.conversation.record_user_topics(person_name, captured)
        with get_connection() as conn:
            write_state(conn, "display_status", "listening")
            write_state(conn, "active_person_name", person_name)

    def _finalize_chat(self, reply: str, person_name: str | None) -> None:
        sanitized_reply = self._sanitize_reply_text(reply)
        with get_connection() as conn:
            write_state(conn, "display_status", "responding")
            write_state(conn, "last_conversation_at", now_iso())

        self._log_message("assistant", sanitized_reply, person_name)
        self._log_event("display_status", {"status": "responding"})

    def _try_answer_runtime_question(self, message: str) -> str | None:
        status = self.get_status()
        if self.BATTERY_QUESTION_PATTERN.search(message):
            return f"Mein Akkustand liegt gerade bei {status['battery_level']} %."
        if self.UPDATE_QUESTION_PATTERN.search(message):
            update_status = status["device"]["update_status"]
            if update_status == "idle":
                return (
                    "Nein, aktuell lÃ¤uft alles normal.\n"
                    f"Battery: {status['battery_level']}% | Display: {status['display_status']} | GerÃ¤t: {status['device']['effective_state']}"
                )
            if update_status == "available":
                return "Ja, es gibt ein ausstehendes Update. Es wurde noch nicht gestartet."
            if update_status == "failed":
                return "Ein Update ist fehlgeschlagen. Das sollte geprÃ¼ft werden."
            return f"Ein Update lÃ¤uft gerade. Aktueller Stand: {update_status}."
        if self.DISPLAY_QUESTION_PATTERN.search(message):
            return f"Mein Display steht gerade auf {status['display_status']}."
        if self.DEVICE_STATE_QUESTION_PATTERN.search(message) and any(
            token in message.casefold() for token in ("gerÃ¤t", "geraet", "erika", "lage", "status")
        ):
            return (
                f"Gerade bin ich im Zustand {status['device']['effective_state']}."
                f" Akku: {status['battery_level']} %. Display: {status['display_status']}."
            )
        return None

    def _try_answer_person_knowledge_question(self, message: str) -> str | None:
        match = self.KNOWLEDGE_QUESTION_PATTERN.search(message)
        if not match:
            return None

        person_name = match.group(1).strip()
        profile = self.profile.get_person(person_name)
        approved_memories = self.memory.list_approved_for_subject(person_name)

        profile_facts = []
        if profile:
            for fact in profile["facts"]:
                trait = fact["trait_type"]
                value = fact["value"]
                if trait == "person_profile":
                    continue
                if trait == "preference":
                    profile_facts.append(f"{person_name} mag {value}.")
                elif trait == "dislike":
                    profile_facts.append(f"{person_name} mag {value} nicht.")
                elif trait == "height":
                    profile_facts.append(f"{person_name} ist {value} groÃŸ.")
                elif trait == "favorite_color":
                    profile_facts.append(f"{person_name} mag die Farbe {value}.")
                elif trait == "eye_color":
                    profile_facts.append(f"{person_name} hat {value} Augen.")
                elif trait == "age":
                    profile_facts.append(f"{person_name} ist {value} Jahre alt.")
                elif trait == "occupation":
                    profile_facts.append(f"{person_name} arbeitet als {value}.")
                elif trait == "hometown":
                    profile_facts.append(f"{person_name} kommt aus {value}.")
                elif trait == "residence":
                    profile_facts.append(f"{person_name} wohnt in {value}.")
                elif trait == "language":
                    profile_facts.append(f"{person_name} spricht {value}.")
                elif trait == "favorite_food":
                    profile_facts.append(f"{person_name} isst am liebsten {value}.")
                elif trait == "favorite_drink":
                    profile_facts.append(f"{person_name} trinkt am liebsten {value}.")
                elif trait == "pet":
                    if ":" in value:
                        pet_type, pet_name = value.split(":", 1)
                        profile_facts.append(f"{person_name} hat einen {pet_type} namens {pet_name}.")
                    else:
                        profile_facts.append(f"{person_name} hat einen {value}.")
                elif trait == "family_relation":
                    if ":" in value:
                        relation, relation_name = value.split(":", 1)
                        profile_facts.append(f"{self._possessive_form(person_name)} {relation} heiÃŸt {relation_name}.")
                    else:
                        profile_facts.append(f"{person_name}: {value}")
                elif trait == "person_relationship":
                    if ":" in value:
                        relation, other_person = value.split(":", 1)
                        profile_facts.append(f"{other_person} ist {self._possessive_form(person_name)} {relation}.")
                    else:
                        profile_facts.append(f"{person_name}: {value}")
                else:
                    profile_facts.append(f"{trait}: {value}")

        memory_only_items = [
            item["content"]
            for item in approved_memories
            if item.get("candidate_kind") == CandidateKind.MEMORY.value
        ]

        if profile_facts:
            details = " ".join(profile_facts[:3])
            return f"Ãœber {person_name} weiÃŸ ich aktuell Folgendes: {details}"

        if memory_only_items:
            details = " ".join(memory_only_items[:2])
            return (
                f"Ãœber {person_name} gibt es aktuell freigegebene Aussagen, aber noch kein bestÃ¤tigtes Profilwissen. "
                f"Bisher gespeichert ist: {details}"
            )

        if profile:
            return f"Ãœber {person_name} ist aktuell noch kein bestÃ¤tigtes Wissen gespeichert."

        return f"Ãœber {person_name} weiÃŸ ich aktuell noch nichts."

    def chat(self, message: str, person_name: str | None = None) -> dict[str, Any]:
        settings = self.settings.get_effective()
        captured = self.microphone.capture_text(message)
        direct_reply = self._try_answer_runtime_question(captured)
        if direct_reply is None:
            direct_reply = self._try_answer_person_knowledge_question(captured)
        if direct_reply is not None:
            self._record_direct_chat_input(captured, person_name)
            result = {"reply": self._sanitize_reply_text(direct_reply), "provider": "core", "used_fallback": False}
            self._finalize_chat(result["reply"], person_name)
            return {
                "reply": result["reply"],
                "llm_provider": result["provider"],
                "used_fallback": result["used_fallback"],
                "llm_context": self.preview_chat_prompt(captured, person_name),
                "decision": {"should_respond": True, "response_reason": "core_direct_answer", "candidates": []},
                "proposed_memories": [],
                "status": self.get_status(),
            }

        captured, payload, proposed_memories, decision = self._prepare_chat(message, person_name)
        result = self.llm.generate(payload, timeout_seconds=settings.llm_timeout_seconds)
        result["reply"] = self._sanitize_reply_text(result["reply"])
        self._finalize_chat(result["reply"], person_name)

        return {
            "reply": result["reply"],
            "llm_provider": result["provider"],
            "used_fallback": result["used_fallback"],
            "llm_context": payload,
            "decision": decision.to_dict(),
            "proposed_memories": proposed_memories,
            "status": self.get_status(),
        }

    def stream_chat(self, message: str, person_name: str | None = None) -> Any:
        settings = self.settings.get_effective()
        captured = self.microphone.capture_text(message)
        direct_reply = self._try_answer_runtime_question(captured)
        if direct_reply is None:
            direct_reply = self._try_answer_person_knowledge_question(captured)
        if direct_reply is not None:
            self._record_direct_chat_input(captured, person_name)

            def direct_generate() -> Any:
                direct_text = self._sanitize_reply_text(direct_reply)
                yield self._sse_event(
                    "meta",
                    {
                        "llm_provider": "core",
                        "used_fallback": False,
                        "decision": {"should_respond": True, "response_reason": "core_direct_answer", "candidates": []},
                        "proposed_memories": [],
                    },
                )
                yield self._sse_event("delta", {"text": direct_text})
                self._finalize_chat(direct_text, person_name)
                yield self._sse_event(
                    "done",
                    {
                        "reply": direct_text,
                        "llm_provider": "core",
                        "used_fallback": False,
                        "decision": {"should_respond": True, "response_reason": "core_direct_answer", "candidates": []},
                        "proposed_memories": [],
                        "status": self.get_status(),
                    },
                )

            return direct_generate()

        captured, payload, proposed_memories, decision = self._prepare_chat(message, person_name)
        provider, fragments, used_fallback = self.llm.stream_generate(
            payload,
            timeout_seconds=settings.llm_timeout_seconds,
        )

        def generate() -> Any:
            reply_parts: list[str] = []
            yield self._sse_event(
                "meta",
                {
                    "llm_provider": provider,
                    "used_fallback": used_fallback,
                    "decision": decision.to_dict(),
                    "proposed_memories": proposed_memories,
                },
            )
            try:
                for fragment in fragments:
                    reply_parts.append(fragment)
                    for piece in self._stream_delta_pieces(fragment):
                        yield self._sse_event("delta", {"text": piece})
            except Exception as exc:
                yield self._sse_event("error", {"message": str(exc)})
                return

            reply = "".join(reply_parts).strip()
            reply = self._sanitize_reply_text(reply)
            self._finalize_chat(reply, person_name)
            yield self._sse_event(
                "done",
                {
                    "reply": reply,
                    "llm_provider": provider,
                    "used_fallback": used_fallback,
                    "decision": decision.to_dict(),
                    "proposed_memories": proposed_memories,
                    "status": self.get_status(),
                },
            )

        return generate()

    @staticmethod
    def _stream_delta_pieces(fragment: str, max_chars: int = 80) -> list[str]:
        text = str(fragment)
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

    @staticmethod
    def _sse_event(event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def approve_memory(self, memory_id: int) -> dict[str, Any] | None:
        memory = self.memory.approve(memory_id)
        if not memory:
            return None

        profile_update = None
        materialization = self._materialization_policy(memory)
        if materialization["action"] == "profile_fact" and memory.get("subject"):
            profile_value = self._extract_profile_value(memory)
            profile_update = self.profile.upsert_fact(
                person_name=memory["subject"],
                trait_type=memory["category"],
                value=profile_value,
                source_memory_id=memory["id"],
                confidence=memory.get("confidence"),
            )
        elif memory.get("subject"):
            profile_update = self.profile.ensure_person_stub(memory["subject"])

        self.audit.log(
            action="memory.approved",
            target_type="memory",
            target_id=str(memory["id"]),
            summary="Memory wurde freigegeben.",
            details={
                "memory_id": memory["id"],
                "subject": memory.get("subject"),
                "category": memory.get("category"),
                "candidate_kind": memory.get("candidate_kind"),
                "materialization_action": materialization["action"],
                "materialization_reason": materialization["reason"],
            },
        )

        return {"memory": memory, "profile_update": profile_update, "materialization": materialization}

    def reject_memory(self, memory_id: int) -> dict[str, Any] | None:
        memory = self.memory.reject(memory_id)
        if not memory:
            return None

        profile_update = None
        if memory.get("candidate_kind") == CandidateKind.PROFILE.value:
            profile_update = self.profile.remove_fact_by_memory(memory["id"])

        self.audit.log(
            action="memory.rejected",
            target_type="memory",
            target_id=str(memory["id"]),
            summary="Memory wurde abgelehnt oder entfernt.",
            details={
                "memory_id": memory["id"],
                "subject": memory.get("subject"),
                "category": memory.get("category"),
                "candidate_kind": memory.get("candidate_kind"),
            },
        )

        return {"memory": memory, "profile_update": profile_update}

    def delete_person(self, person_id: int) -> dict[str, Any] | None:
        person = self.profile.get_person_by_id(person_id)
        if not person:
            return None

        person_name = person["name"]
        deleted_memories = self.memory.delete_by_subject(person_name)
        deleted_profile = self.profile.delete_person(person_id)

        with get_connection() as conn:
            deleted_messages = conn.execute(
                "DELETE FROM conversation_messages WHERE lower(coalesce(person_name, '')) = lower(?)",
                (person_name,),
            ).rowcount
            last_person = read_state(conn, "last_person_detected")
            if isinstance(last_person, str) and last_person.casefold() == person_name.casefold():
                write_state(conn, "last_person_detected", None)
                write_state(conn, "last_person_detected_at", None)

        self.audit.log(
            action="person.deleted",
            target_type="person",
            target_id=str(person_id),
            summary="Person wurde lokal hart gelÃ¶scht.",
            details={
                "person_name": person_name,
                "deleted_memory_count": deleted_memories,
                "deleted_message_count": deleted_messages,
            },
        )

        return {
            "deleted_person": deleted_profile,
            "deleted_memory_count": deleted_memories,
            "deleted_message_count": deleted_messages,
        }

    @staticmethod
    def _extract_profile_value(memory: dict[str, Any]) -> str:
        if memory["category"] == "person_profile":
            return memory["subject"] or memory["content"]
        if memory["category"] == "height":
            prefix = f"{memory['subject']} ist "
            suffix = " groÃŸ."
            if memory["content"].startswith(prefix) and memory["content"].endswith(suffix):
                return memory["content"][len(prefix):-len(suffix)]
        if memory["category"] == "favorite_color":
            prefix = f"{memory['subject']} mag die Farbe "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "eye_color":
            prefix = f"{memory['subject']} hat "
            suffix = " Augen."
            if memory["content"].startswith(prefix) and memory["content"].endswith(suffix):
                return memory["content"][len(prefix):-len(suffix)]
        if memory["category"] == "age":
            prefix = f"{memory['subject']} ist "
            suffix = " Jahre alt."
            if memory["content"].startswith(prefix) and memory["content"].endswith(suffix):
                return memory["content"][len(prefix):-len(suffix)]
        if memory["category"] == "occupation":
            prefix = f"{memory['subject']} arbeitet als "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "hometown":
            prefix = f"{memory['subject']} kommt aus "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "residence":
            prefix = f"{memory['subject']} wohnt in "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "language":
            prefix = f"{memory['subject']} spricht "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "favorite_food":
            prefix = f"{memory['subject']} isst am liebsten "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "favorite_drink":
            prefix = f"{memory['subject']} trinkt am liebsten "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "response_humor_preference":
            prefix = f"{memory['subject']} mag "
            suffix = "e Antworten."
            if memory["content"].startswith(prefix) and memory["content"].endswith(suffix):
                return memory["content"][len(prefix):-len(suffix)]
        if memory["category"] == "response_style_preference":
            if "sachliche Antworten" in memory["content"]:
                return "sachlich"
            if "lockere Antworten" in memory["content"]:
                return "locker"
        if memory["category"] == "response_length_preference":
            if "kurze Antworten" in memory["content"]:
                return "short"
            if "ausführlichere Antworten" in memory["content"]:
                return "detailed"
        if memory["category"] == "pet":
            named_match = re.match(
                rf"^{re.escape(memory['subject'])} hat einen (.+?) namens (.+)\.$",
                memory["content"],
            )
            if named_match:
                return f"{named_match.group(1)}:{named_match.group(2)}"
            simple_match = re.match(
                rf"^{re.escape(memory['subject'])} hat einen (.+)\.$",
                memory["content"],
            )
            if simple_match:
                return simple_match.group(1)
        if memory["category"] == "family_relation":
            match = re.match(
                rf"^{re.escape(RobotCore._possessive_form(memory['subject']))} (.+?) heiÃŸt (.+)\.$",
                memory["content"],
            )
            if match:
                return f"{match.group(1)}:{match.group(2)}"
        if memory["category"] == "person_relationship":
            match = re.match(
                rf"^(.+?) ist {re.escape(RobotCore._possessive_form(memory['subject']))} (.+)\.$",
                memory["content"],
            )
            if match:
                return f"{match.group(2)}:{match.group(1)}"
        if memory["category"] == "preference":
            prefix = f"{memory['subject']} mag "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "interest":
            prefix = f"{memory['subject']} interessiert sich fÃ¼r "
            return memory["content"][len(prefix):].rstrip(".") if memory["content"].startswith(prefix) else memory["content"]
        if memory["category"] == "dislike":
            prefix = f"{memory['subject']} mag "
            suffix = " nicht."
            if memory["content"].startswith(prefix) and memory["content"].endswith(suffix):
                return memory["content"][len(prefix):-len(suffix)]
        return memory["content"]

    @staticmethod
    def _possessive_form(name: str) -> str:
        if name.casefold().endswith(("s", "ÃŸ", "x", "z")):
            return f"{name}'"
        return f"{name}s"

    def simulate_person(self, person_name: str | None) -> dict[str, Any]:
        detection = self.camera.detect_person(person_name)
        with get_connection() as conn:
            write_state(conn, "last_person_detected", detection.person_name)
            write_state(conn, "last_person_detected_at", now_iso())
            write_state(conn, "display_status", "person_detected" if detection.person_name else "idle")

        self._log_event(
            "person_detected",
            {"person_name": detection.person_name, "confidence": detection.confidence},
        )

        status = self.get_status()
        if status["initiative"]["allowed"]:
            with get_connection() as conn:
                write_state(conn, "initiative_last_suggested_at", now_iso())
            status["initiative"]["recorded"] = True

        return {"event": "person_detected", "detection": detection.__dict__, "status": status}

    def simulate_battery(self, level: int) -> dict[str, Any]:
        normalized = self.battery.update_level(level)
        with get_connection() as conn:
            write_state(conn, "battery_level", normalized)
            write_state(conn, "display_status", "charging_needed" if normalized <= 20 else "idle")
        self._log_event("battery_update", {"level": normalized})
        self._log_event(
            "display_status",
            {"status": "charging_needed" if normalized <= 20 else "idle"},
        )
        return {"event": "battery_update", "battery_level": normalized, "status": self.get_status()}

    def simulate_speech(self, text: str, person_name: str | None = None) -> dict[str, Any]:
        return self.chat(text, person_name)

    def simulate_display(self, status: str) -> dict[str, Any]:
        with get_connection() as conn:
            write_state(conn, "display_status", status)
        self._log_event("display_status", {"status": status})
        return {"event": "display_status", "display_status": status, "status": self.get_status()}

