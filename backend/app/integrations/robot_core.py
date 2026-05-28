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
from app.profile.relationship import PersonRelationshipService
from app.voice.service import TtsService
from app.search.service import SearchService


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
    LIGHT_COMMAND_PATTERN = re.compile(
        r"\b(?:schalte?|mach[e]?|dreh[e]?|tu[e]?|dimm[e]?|stell[e]?|setz[e]?|bring[e]?|regulier[e]?)\b.{0,80}\b(?:licht(?:er)?|lampe[n]?|beleuchtung|aus|ein|an)\b"
        r"|\b(?:licht(?:er)?|lampe[n]?|beleuchtung)\b.{0,50}\b(?:an|ein|aus|hell|dunkel|\d+\s*(?:prozent\b|%))"
        r"|\ball[e]?\s+(?:licht(?:er)?|lampe[n]?|beleuchtung|aus|an|ein)\b"
        r"|\b(?:alles?|alle)\s+(?:aus|an|ein)\b"
        r"|\b(?:kannst\s+du|bitte)\b.{0,40}\b(?:licht|lampe|beleuchtung)\b.{0,30}\b(?:aus|an|ein|hell|dunkler|dimmen)\b"
        r"|\blicht\s+(?:aus|an|ein|hell|dunkel|dimmen)\b"
        r"|\b(?:mach|schalte?)\s+(?:es\s+)?(?:hell|dunkel|dunkler|heller)\b",
        re.IGNORECASE | re.DOTALL,
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
        r"\b(gerätezustand|geraetezustand|status|lage)\b",
        re.IGNORECASE,
    )
    KNOWLEDGE_QUESTION_PATTERN = re.compile(
        r"\b(?:was\s+wei(?:ß|ss)t\s+du\s+über|erzähl(?:e)?\s+mir\s+etwas\s+über)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]*)",
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
        self.relationship = PersonRelationshipService()
        self.tts = TtsService(self.settings)
        self.decision_engine = DecisionEngine()
        self.prompt_builder = PromptBuilder()
        self.llm = LLMRouter()
        self.initiative = InitiativeEngine()
        self.search = SearchService()
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

    _FACT_LABELS: dict[str, str] = {
        "age":             "Du bist {v} Jahre alt.",
        "favorite_color":  "Deine Lieblingsfarbe ist {v}.",
        "favorite_food":   "Dein Lieblingsessen ist {v}.",
        "favorite_drink":  "Dein Lieblingsgetränk ist {v}.",
        "occupation":      "Du arbeitest als {v}.",
        "hometown":        "Du kommst aus {v}.",
        "residence":       "Du wohnst in {v}.",
        "interest":        "Du interessierst dich für {v}.",
        "preference":      "Du magst {v}.",
        "dislike":         "Du magst {v} nicht.",
        "nickname":        "Dein Spitzname ist {v}.",
    }

    def _profile_facts_for_prompt(self, person_name: str) -> list[str]:
        person = self.profile.get_person(person_name)
        if not person:
            return []
        lines = []
        for fact in (person.get("facts") or []):
            tt = fact.get("trait_type", "")
            v = str(fact.get("value", "")).strip()
            if not v:
                continue
            template = self._FACT_LABELS.get(tt)
            if template:
                lines.append(template.format(v=v))
            elif tt not in {"person_profile", "response_humor_preference",
                            "response_style_preference", "response_length_preference"}:
                lines.append(f"{tt.replace('_', ' ').capitalize()}: {v}.")
        return lines

    # Kategorie-Boost: wie wertvoll ist eine Memory-Kategorie als Kontext
    _MEM_CAT_BOOST: dict[str, float] = {
        "interest_signal":  1.4,
        "support_signal":   1.1,
        "general":          0.9,
        "recherche":        0.85,
    }

    @staticmethod
    def _recency_weight(created_at: str | None) -> float:
        """Neuere Erinnerungen stärker gewichten."""
        if not created_at:
            return 1.0
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
            if age_days <= 7:   return 1.5
            if age_days <= 30:  return 1.2
            if age_days <= 90:  return 1.0
            return 0.7
        except Exception:
            return 1.0

    def _notes_for_prompt(self, person_name: str | None) -> list[str]:
        try:
            from app.services.note_service import NoteService
            from app.profile.service import ProfileService
            person_id = None
            if person_name:
                p = ProfileService().get_by_name(person_name)
                if p:
                    person_id = p["id"]
            svc = NoteService()
            notes = svc.list_notes(person_id=person_id)[:15]
            return [f"[{n['title']}]: {n['content']}" for n in notes]
        except Exception:
            return []

    def _approved_memories_for_prompt(
        self,
        person_name: str | None,
        message: str | None = None,
        limit: int = 6,
    ) -> list[str]:
        if not person_name:
            return []

        fact_lines = self._profile_facts_for_prompt(person_name)

        items = self.memory.list_approved_for_subject(person_name)
        if not items:
            return fact_lines

        SKIP_CATEGORIES = {"person_profile", "preference", "dislike", "interest", "age",
                           "occupation", "favorite_food", "favorite_drink", "favorite_color"}
        query_tokens = self._prompt_keywords(message or "")

        # Scoring: keyword_overlap × kategorie_boost × recency × confidence
        scored: list[tuple[float, int, str]] = []
        for index, item in enumerate(items):
            if item.get("category") in SKIP_CATEGORIES:
                continue
            content = item["content"]
            content_tokens = self._prompt_keywords(content)
            overlap = len(query_tokens & content_tokens) if query_tokens else 0
            if overlap == 0:
                continue
            cat_boost   = self._MEM_CAT_BOOST.get(item.get("category", ""), 1.0)
            recency     = self._recency_weight(item.get("created_at"))
            confidence  = float(item.get("confidence") or 0.7)
            score = overlap * cat_boost * recency * confidence
            scored.append((score, index, content))

        scored.sort(key=lambda e: (e[0], -e[1]), reverse=True)

        # Duplikate entfernen: ähnliche Contents (>50% Token-Overlap) → nur besten behalten
        seen_tokens: list[set[str]] = []
        deduped: list[str] = []
        for _, _, content in scored:
            ctoks = self._prompt_keywords(content)
            duplicate = any(
                len(ctoks & s) / max(len(ctoks | s), 1) > 0.5
                for s in seen_tokens
            )
            if not duplicate:
                seen_tokens.append(ctoks)
                deduped.append(content)

        # Dynamisches Limit: bei hoher Relevanz mehr Kontext mitgeben
        top_score = scored[0][0] if scored else 0.0
        dynamic_limit = min(limit + 2, 8) if top_score >= 2.0 else limit

        topic_items = [self._to_second_person(c, person_name) for c in deduped[:dynamic_limit]]
        return fact_lines + topic_items

    _COMPLEX_QUESTION = re.compile(
        r"\b(?:erkläre?|beschreibe?|erzähl|nenn(?:e|)\s+mir|liste?\s+auf|"
        r"wie\s+funktioniert|was\s+ist\s+der\s+unterschied|was\s+ist\s+besser|"
        r"was\s+sind\s+die|vergleiche?|fasse?\s+zusammen|warum|weshalb|wieso)\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _dynamic_max_tokens(message: str, base: int) -> int:
        """Erhöht max_tokens für komplexe/lange Fragen."""
        if len(message) > 80 or RobotCore._COMPLEX_QUESTION.search(message):
            return min(base + 150, 500)
        if len(message) > 50:
            return min(base + 80, 400)
        return base

    @staticmethod
    def _to_second_person(content: str, person_name: str) -> str:
        """
        Wandelt Dritte-Person-Aussagen über person_name in direkte Du-Ansprache um.
        Beispiel: "Dennis mag Kaffee." → "Du magst Kaffee."
        """
        name = re.escape(person_name)

        # Verb-Paare: 3. Person → 2. Person (Singular)
        VERB_PAIRS = [
            ("interessiert sich", "interessierst dich"),
            ("ist", "bist"),
            ("hat", "hast"),
            ("mag", "magst"),
            ("liebt", "liebst"),
            ("möchte", "möchtest"),
            ("verfolgt", "verfolgst"),
            ("fragt", "fragst"),
            ("spricht", "sprichst"),
            ("bevorzugt", "bevorzugst"),
            ("arbeitet", "arbeitest"),
            ("wohnt", "wohnst"),
            ("kommt", "kommst"),
            ("heißt", "heißt"),
            ("trinkt", "trinkst"),
            ("isst", "isst"),
            ("spielt", "spielst"),
            ("hört", "hörst"),
            ("schaut", "schaust"),
            ("liest", "liest"),
        ]

        result = content
        for verb3, verb2 in VERB_PAIRS:
            # "Dennis mag" → "Du magst"
            result = re.sub(
                rf"\b{name}\s+{re.escape(verb3)}\b",
                f"Du {verb2}",
                result,
                flags=re.IGNORECASE,
            )

        # Possessivform: "Dennis'" oder "Dennis's" → "Dein"
        result = re.sub(rf"\b{name}(?:'s?|s')\s+", "Dein ", result, flags=re.IGNORECASE)

        # Reiner Name am Satzanfang (nach vorherigen Ersetzungen noch übrig)
        result = re.sub(rf"(?m)^{name}\b", "Du", result, flags=re.IGNORECASE)

        # Kapitalisiierung nach Satzanfang normalisieren
        result = re.sub(r"(?m)^du\b", "Du", result)

        return result

    @staticmethod
    def _prompt_keywords(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[A-Za-zÄÖÜäöüß0-9-]{3,}", text.casefold())
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
        global_state = self.relationship.get_global_state()
        mood = self.relationship.get_mood()

        personality["friendliness"] = max(0.0, min(1.0, personality["friendliness"] + float(global_state["warmth"]) * 0.05 - float(global_state["tension"]) * 0.04))
        personality["patience"] = max(0.0, min(1.0, personality["patience"] + float(global_state["warmth"]) * 0.04 - float(global_state["tension"]) * 0.05))
        personality["directness"] = max(0.0, min(1.0, personality["directness"] + float(global_state["tension"]) * 0.04))
        personality["sarcasm"] = max(0.0, min(1.0, personality["sarcasm"] + float(global_state["tension"]) * 0.03))

        # Stimmungseinfluss auf Persönlichkeit und Ton
        mood_score = float(mood.get("score", 0.0))
        if mood_score >= 0.5:
            personality["friendliness"] = min(1.0, personality["friendliness"] + 0.08)
            personality["humor"] = min(1.0, personality["humor"] + 0.05)
            preference_lines.append("Erikas Stimmung ist aktuell sehr gut — antworte lebhaft und herzlich.")
        elif mood_score >= 0.2:
            personality["friendliness"] = min(1.0, personality["friendliness"] + 0.04)
            preference_lines.append("Erikas Stimmung ist aktuell gut.")
        elif mood_score <= -0.55:
            personality["talkativeness"] = max(0.0, personality["talkativeness"] - 0.14)
            personality["patience"] = max(0.0, personality["patience"] - 0.08)
            preference_lines.append("Erika ist aktuell gereizt — antworte sehr knapp und sachlich, kein Small Talk.")
        elif mood_score <= -0.25:
            personality["talkativeness"] = max(0.0, personality["talkativeness"] - 0.07)
            preference_lines.append("Erika ist aktuell etwas müde — Antworten dürfen kürzer und nüchterner ausfallen.")

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

        if person_name:
            person = self.profile.get_person(person_name)
            if person:
                state = self.relationship.get_person_state(person["id"])
                warmth = float(state["warmth"])
                tension = float(state["tension"])
                openness = float(state["openness"])
                interaction_count = int(state.get("interaction_count", 0))
                personality["friendliness"] = max(0.0, min(1.0, personality["friendliness"] + warmth * 0.18 - tension * 0.20))
                personality["patience"] = max(0.0, min(1.0, personality["patience"] + warmth * 0.12 - tension * 0.24))
                personality["directness"] = max(0.0, min(1.0, personality["directness"] + tension * 0.16))
                personality["sarcasm"] = max(0.0, min(1.0, personality["sarcasm"] + tension * 0.18))
                personality["humor"] = max(0.0, min(1.0, personality["humor"] + warmth * 0.06))
                personality["talkativeness"] = max(0.0, min(1.0, personality["talkativeness"] + openness * 0.08))
                if tension >= 0.55 and warmth <= -0.15:
                    preference_lines.append(
                        "Diese Person war zuletzt häufig gereizt — antworte knapp und sachlich, "
                        "keine langen Ausführungen, keine persönlichen Anmerkungen, direkt zur Antwort."
                    )
                elif warmth >= 0.55 and tension <= 0.15:
                    preference_lines.append(
                        "Mit dieser Person ist das Verhältnis sehr warm und vertraut — du darfst herzlich antworten. "
                        "Formulierungen wie 'natürlich', 'sehr gerne', 'kein Problem' klingen authentisch."
                    )
                elif warmth >= 0.35 and tension <= 0.2:
                    preference_lines.append("Mit dieser Person ist der Ton zuletzt warm und vertraut — du darfst etwas herzlicher antworten.")
                if interaction_count >= 30:
                    preference_lines.append(
                        f"Du hast bereits {interaction_count} Gespräche mit dieser Person geführt — "
                        "du kannst direkter antworten und musst nicht jeden Begriff erklären."
                    )

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
            person_name=current_person,
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
            summary="Gerätezustand wurde aktualisiert.",
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

    def generate_greeting(self, person_id: int) -> dict[str, Any] | None:
        """Erzeugt eine kontextuelle Begrüßung basierend auf Beziehungsstatus, Stimmung, Zeit und aktiven Themen."""
        import random
        person = self.profile.get_person_by_id(person_id)
        if not person:
            return None

        name = person["name"]
        state = self.relationship.get_person_state(person_id)
        warmth  = float(state.get("warmth", 0.0))
        tension = float(state.get("tension", 0.0))
        mood = self.relationship.get_mood()
        mood_score = float(mood.get("score", 0.0))

        # Zeit seit letztem Gespräch dieser Person (nicht global)
        minutes_since = 99999
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT MAX(created_at) as last_at FROM conversation_messages
                WHERE lower(coalesce(person_name,'')) = lower(?) AND role = 'user'
                """,
                (name,),
            ).fetchone()
            last_at = row["last_at"] if row else None

            # Aktive Themen dieser Person
            topic_rows = conn.execute(
                "SELECT title FROM active_topics WHERE person_name=? AND status='active' "
                "ORDER BY importance DESC, mentions DESC LIMIT 3",
                (name,),
            ).fetchall()

        if last_at:
            try:
                dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
                minutes_since = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
            except Exception:
                pass

        # Weniger als 8 Minuten → keine Begrüßung
        if minutes_since < 8:
            return {"text": None, "skip": True, "reason": "too_recent"}

        # Abwesenheitskontext
        if minutes_since > 1440:  # > 1 Tag
            absence = "long"
        elif minutes_since > 240:  # > 4 Stunden
            absence = "medium"
        elif minutes_since > 30:
            absence = "short"
        else:
            absence = "none"

        # Ton basierend auf Beziehungsstatus
        if tension >= 0.45 and warmth <= 0.1:
            tone = "reserved"
        elif warmth >= 0.5 and tension <= 0.25:
            tone = "warm"
        elif warmth >= 0.2:
            tone = "friendly"
        else:
            tone = "neutral"

        # Schlechte Stimmung → Ton eine Stufe kühler
        if mood_score <= -0.5 and tone == "warm":
            tone = "friendly"
        elif mood_score <= -0.5 and tone == "friendly":
            tone = "neutral"

        # Begrüßungstexte nach Ton und Abwesenheit
        _GREETINGS: dict[str, dict[str, list[str]]] = {
            "warm": {
                "long":   [f"Oh, {name}! Schön, dass du wieder da bist.", f"Hey {name}, ich hab dich vermisst! Wie war's?", f"Willkommen zurück, {name}! Schön, dich zu sehen."],
                "medium": [f"Hey {name}! Schön, dich wieder zu sehen.", f"Da bist du ja wieder, {name}! Alles gut?"],
                "short":  [f"Hallo {name}!", f"Hey {name}!"],
                "none":   [f"Hallo {name}!", f"Hey {name}!"],
            },
            "friendly": {
                "long":   [f"Hallo {name}, lange nicht gesehen!", f"Oh, {name}! Schön, dass du wieder da bist."],
                "medium": [f"Hallo {name}!", f"Hey {name}, wie geht's?"],
                "short":  [f"Hallo {name}!"],
                "none":   [f"Hallo {name}!"],
            },
            "neutral": {
                "long":   [f"Hallo {name}.", f"{name}."],
                "medium": [f"Hallo {name}."],
                "short":  [f"Hallo."],
                "none":   [f"Hallo."],
            },
            "reserved": {
                "long":   [f"{name}."],
                "medium": [f"Hm."],
                "short":  [f"Hm."],
                "none":   [f"Hm."],
            },
        }

        options = _GREETINGS.get(tone, _GREETINGS["neutral"]).get(absence, ["Hallo."])
        text = random.choice(options)

        # Themen-Addon — Erika bringt ein aktives Gesprächsthema ein
        topics = [r["title"] for r in topic_rows]
        topic_used = None
        if topics and tone not in ("reserved",):
            topic = random.choice(topics[:2])
            topic_used = topic
            if absence == "none":
                # Proaktive Ansprache (25min Stille): Erika bricht das Schweigen mit einer konkreten Frage
                proactive = [
                    f"Ich wollte kurz fragen — wie sieht's aus mit {topic}?",
                    f"Darf ich kurz stören? Ich musste gerade an {topic} denken.",
                    f"Hey, kurze Frage: {topic} — alles im Griff?",
                ]
                if mood_score >= 0.2:
                    proactive.append(f"Sag mal, {topic} — gibt's da was Neues?")
                text += " " + random.choice(proactive)
            elif absence in ("medium", "long"):
                # Nach längerer Abwesenheit: Thema erwähnen
                addons = [
                    f"Du hast zuletzt öfter über {topic} gesprochen — noch aktuell?",
                    f"Wie läuft's übrigens mit {topic}?",
                ]
                text += " " + random.choice(addons)

        return {
            "text": text,
            "skip": False,
            "tone": tone,
            "absence": absence,
            "minutes_since": minutes_since,
            "warmth": warmth,
            "tension": tension,
            "mood_label": mood.get("label", "neutral"),
            "topic": topic_used,
        }

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

    def list_profiles(self) -> list[dict[str, Any]]:
        people = self.profile.list_people()
        for item in people:
            item["relationship_state"] = self.relationship.get_person_state(item["id"])
            item["facts_count"] = len(item.get("facts") or [])
            memories = self.memory.list_memories(subject=item["name"])
            item["memory_count"] = sum(1 for m in memories if m.get("status") == "approved")
            item["pending_count"] = sum(1 for m in memories if m.get("status") == "pending")
        return people

    def get_person_workspace(self, person_id: int) -> dict[str, Any] | None:
        person = self.profile.get_person_by_id(person_id)
        if not person:
            return None
        return {
            "person": person,
            "relationship_state": self.relationship.get_person_state(person_id),
            "global_relationship_state": self.relationship.get_global_state(),
            "memories": self.memory.list_memories(subject=person["name"]),
            "conversation": self.list_conversation_messages(person_name=person["name"], limit=60),
        }

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

        conflicts: list[dict[str, Any]] = []
        for trait_type, value in patch.items():
            if value == "default":
                self.profile.clear_trait(person["name"], trait_type)
            else:
                result = self.profile.upsert_fact_resolved(
                    person_name=person["name"],
                    trait_type=trait_type,
                    value=value,
                    source_memory_id=None,
                    confidence=1.0,
                )
                if result["conflict"]:
                    conflicts.append(result["conflict"])

        updated = self.get_person_preferences(person_id)
        self.audit.log(
            action="profile.preferences_updated",
            target_type="person",
            target_id=str(person_id),
            summary="Antwortpräferenzen der Person wurden geändert.",
            details={"person_name": person["name"], "patch": patch, "conflicts": conflicts},
        )
        return {
            **updated,
            "conflicts": conflicts,
        }

    def reset_global_persona(self) -> dict[str, Any]:
        personality = self.personality.reset_defaults()
        relationship = self.relationship.reset_global_state()
        self.audit.log(
            action="persona.global_reset",
            target_type="personality",
            target_id="default_personality",
            summary="Globale Persönlichkeit und globale Beziehungsdynamik wurden zurückgesetzt.",
            details={"personality": personality, "relationship": relationship},
        )
        return {"personality": personality, "global_relationship_state": relationship}

    def reset_person_persona(self, person_id: int) -> dict[str, Any] | None:
        person = self.profile.get_person_by_id(person_id)
        if not person:
            return None

        for trait_type in (
            "response_humor_preference",
            "response_style_preference",
            "response_length_preference",
        ):
            self.profile.clear_trait(person["name"], trait_type)

        relationship = self.relationship.reset_person_state(person_id)
        preferences = self.get_person_preferences(person_id)
        self.audit.log(
            action="persona.person_reset",
            target_type="person",
            target_id=str(person_id),
            summary="Personenspezifische Antwortdynamik wurde zurückgesetzt.",
            details={"person_name": person["name"], "relationship": relationship},
        )
        return {
            "person_id": person_id,
            "person_name": person["name"],
            "relationship_state": relationship,
            "preferences": preferences["preferences"] if preferences else {},
        }

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

    def preview_chat_prompt(
        self,
        message: str,
        person_name: str | None = None,
        search_context: str | None = None,
    ) -> dict[str, Any]:
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
        notes_lines = self._notes_for_prompt(person_name)
        from app.services.memory_service import MemoryService
        session_memory = MemoryService().build_session_context(person_name)
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
            search_context=search_context,
            notes_lines=notes_lines,
            session_memory=session_memory,
        )
        payload["llm_max_tokens"] = settings.llm_max_tokens
        payload["context"]["selection"] = selection_meta
        return payload

    def _learn_from_interaction(self, person_name: str | None, message: str) -> dict[str, Any] | None:
        if not person_name:
            return None
        person = self.profile.get_person(person_name)
        if not person:
            return None
        return self.relationship.apply_user_message(person_id=person["id"], message=message)

    def _prepare_chat(self, message: str, person_name: str | None = None) -> tuple[str, dict[str, Any], list[dict[str, Any]], Any, Any]:
        from app.search.service import SearchResult
        settings = self.settings.get_effective()
        captured = self.microphone.capture_text(message)
        decision = self.decision_engine.analyze_chat(captured, person_name)
        self._learn_from_interaction(person_name, captured)
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

        # Auto-approve hochkonfidente Profil-Fakten direkt (Alter, Farbe, Sprache etc.)
        if person_name:
            for candidate in decision.candidates:
                if (
                    candidate.kind == CandidateKind.PROFILE
                    and candidate.confidence >= 0.90
                    and getattr(candidate, "profile_value", None)
                ):
                    self.profile.upsert_fact_resolved(
                        person_name=person_name,
                        trait_type=candidate.category,
                        value=str(candidate.profile_value),
                        source_memory_id=None,
                        confidence=candidate.confidence,
                    )

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
            # Auto-Promote: Bei doppeltem Schwellwert wird Interesse zu Profilwissen
            promote_threshold = settings.topic_interest_threshold * 2
            if (
                interest_signal["category"] == "interest_signal"
                and interest_signal.get("mention_score", 0) >= promote_threshold
                and person_name
            ):
                topic_label = interest_signal.get("topic", "").capitalize()
                # Grüße und Funktionswörter niemals als Interesse promoten
                _NO_PROMOTE = {
                    "guten", "gute", "hallo", "hello", "moin", "morgen", "abend",
                    "nacht", "tschüss", "okay", "danke", "soll", "sollte",
                    "machen", "macht", "welchen", "welche", "letzten", "ersten",
                    "nächsten", "wurde", "werden", "haben", "sein",
                    # Verben / Partizipien
                    "gespielt", "gemacht", "gesagt", "geworden", "gegeben",
                    "gesehen", "gehört", "gefunden", "gesucht", "gefragt",
                    "steht", "stehen", "liegt", "liegen", "läuft", "sitzt",
                    "passiert", "existiert", "geboren", "gestorben",
                    # Generische Nomen
                    "platz", "stelle", "ort", "punkt", "lage", "fall",
                    "schritt", "teil", "form", "grund", "tage", "wochen",
                    "monat", "jahr", "uhr", "zeit", "zahl", "wert", "name",
                    # Adjektive
                    "bekannt", "berühmt", "wichtig", "richtig", "falsch",
                    "möglich", "nötig", "fertig", "klein", "groß", "neu", "alt",
                }
                if topic_label and topic_label.lower() not in _NO_PROMOTE and len(topic_label) >= 5:
                    promoted = self.profile.upsert_fact_if_missing(
                        person_name=person_name,
                        trait_type="interest",
                        value=topic_label,
                        confidence=0.8,
                    )
                    if promoted:
                        self.audit.log(
                            action="interest.auto_promoted",
                            target_type="profile_fact",
                            target_id=person_name,
                            summary=f"Interesse '{topic_label}' automatisch zu Profilwissen promoviert.",
                            details={"topic": topic_label, "score": interest_signal.get("mention_score")},
                        )

        # Web-Recherche wenn nötig
        search_result: SearchResult | None = None
        search_context: str | None = None
        if self.search.needs_search(captured):
            query = self.search.extract_query(captured)
            search_result = self.search.search(query)
            if search_result:
                search_context = self.search.format_prompt_block(search_result)

        # Kurze Bestätigung ("ja gerne", "bitte", etc.) → prüfe was Erika zuletzt angeboten hat
        _AFFIRMATION = re.compile(
            r"^\s*(ja|jo|ok|gerne|bitte|klar|super|toll|natürlich|genau|stimmt|richtig|"
            r"ja\s+gerne|ja\s+bitte|ja\s+klar|sehr\s+gerne|ja\s+natürlich|"
            r"ja\s+genau|ja\s+stimmt|ja\s+richtig|ja\s+super|das\s+stimmt|"
            r"klingt\s+gut|mach\s+das|go|yes)\s*[!.?]?\s*$",
            re.IGNORECASE,
        )
        if not search_result and _AFFIRMATION.match(captured.strip()):
            try:
                with get_connection() as conn:
                    row = conn.execute(
                        "SELECT message FROM conversation_messages "
                        "WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1"
                    ).fetchone()
                last_reply = (row["message"] if row else "").lower()
                forced: str | None = None
                if any(w in last_reply for w in ("wetter", "vorhersage", "temperatur", "grad")):
                    forced = "wetter heute morgen"
                elif any(w in last_reply for w in ("termin", "kalender", "liegt an", "steht an",
                                                    "veranstaltung", "abrufen")):
                    forced = "was liegt heute an"
                if forced:
                    search_result = self.search.search(forced)
                    if search_result:
                        search_context = self.search.format_prompt_block(search_result)
            except Exception:
                pass

        payload = self.preview_chat_prompt(captured, person_name, search_context=search_context)
        self._log_event("speech_input", {"text": captured, "person_name": person_name})
        self._log_message("user", captured, person_name)
        self.conversation.record_user_topics(person_name, captured)

        with get_connection() as conn:
            write_state(conn, "display_status", "listening")
            write_state(conn, "active_person_name", person_name)

        return captured, payload, proposed_memories, decision, search_result

    # ── Fakten-Extraktion aus User-Nachrichten ───────────────
    _FACT_PATTERNS: list[tuple[str, str]] = [
        # Alter
        (r'\bich\s+bin\s+(?:jetzt\s+)?(\d{1,3})\s*(?:jahre?\s+alt)?\b', 'age'),
        (r'\b(\d{1,3})\s+jahre?\s+alt\b', 'age'),
        (r'\bmein\s+alter\s+(?:ist|beträgt|war)\s+(\d{1,3})\b', 'age'),
        (r'\bich\s+bin\s+(\d{2})\b(?!\s*uhr)', 'age'),
        (r'\bich\s+wurde\s+(\d{1,3})\b', 'age'),
        # Lieblingsfarbe
        (r'\bmeine?\s+lieblingsfarbe\s+ist\s+(\w+)', 'favorite_color'),
        (r'\bich\s+mag\s+(?:die\s+farbe\s+)?(\w+)\s+am\s+liebsten', 'favorite_color'),
        # Abneigungen (dislike) — VOR preference, da "ich mag kein/keine" sonst als Vorliebe gilt
        (r'\bich\s+mag\s+(?:kein|keine|keinen)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)(?:\.|,|$)', 'dislike'),
        (r'\bich\s+(?:hasse|verabscheue|ekle\s+mich\s+vor)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)(?:\.|,|$)', 'dislike'),
        (r'\b([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)\s+mag\s+ich\s+(?:gar\s+|überhaupt\s+)?nicht\b', 'dislike'),
        (r'\bich\s+mag\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)\s+(?:gar\s+nicht|überhaupt\s+nicht|so\s+gar\s+nicht|wirklich\s+nicht)\b', 'dislike'),
        (r'\bich\s+esse?\s+(?:kein|keine|keinen)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)(?:\.|,|$)', 'dislike'),
        # Vorlieben (preference) — kein "kein/keine/keinen" (würde Abneigung sein)
        (r'\bich\s+liebe\s+(?:es\s+)?([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,30}?)(?:\.|,|$|\s+sehr|\s+wirklich)', 'preference'),
        (r'\bich\s+mag\s+(?!kein|keine|keinen)(?:sehr\s+)?([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)(?:\s+sehr)?(?:\.|,|$)', 'preference'),
        (r'\b([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)\s+(?:esse|trinke|mag)\s+ich\s+(?:sehr\s+)?gerne?\b', 'preference'),
        # Interessen
        (r'\bich\s+interessiere\s+mich\s+(?:sehr\s+)?für\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,30}?)(?:\.|,|$)', 'interest'),
        (r'\b([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,25}?)\s+ist\s+mein\s+(?:lieblingsverein|lieblingsklub)\b', 'interest'),
        # Wohnort / Herkunft
        (r'\bich\s+(?:wohne|lebe)\s+in\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,30}?)(?:\.|,|$)', 'residence'),
        (r'\bich\s+komme\s+(?:aus|ursprünglich\s+aus)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,30}?)(?:\.|,|$)', 'hometown'),
        (r'\bmein(?:e)?\s+(?:heimat(?:ort)?|heimatstadt)\s+ist\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s\-]{1,30}?)(?:\.|,|$)', 'hometown'),
        # Name (Spitzname)
        (r'\bnenн mich\s+(.+?)(?:\.|,|$)', 'nickname'),
        (r'\bich\s+heiße\s+(?:eigentlich\s+)?(.+?)(?:\.|,|$)', 'nickname'),
    ]

    def _build_search_query_from_context(
        self,
        llm_reply: str,
        user_message: str,
        person_name: str | None,
    ) -> str:
        """
        Baut einen sinnvollen Suchbegriff aus dem LLM-Reply + User-Nachricht.
        Strategie:
        1. Eigennamen/Entitäten aus LLM-Reply extrahieren (z.B. 'SV Darmstadt')
        2. Persönliche Pronomen in User-Nachricht durch Profil-Fakten ersetzen
        3. Fallback: User-Nachricht bereinigt
        """
        import re as _re

        # 1. Entitäten aus LLM-Reply extrahieren
        # Sucht nach "über X", "zu X", "von X" gefolgt von Eigenname
        entity_match = _re.search(
            r'(?:über|zu|von|bei|für)\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9\s\.\-]{2,40}?)(?:\.|,|\?|!|$|\s+(?:weiß|habe|kann|soll))',
            llm_reply, _re.IGNORECASE
        )
        entity = entity_match.group(1).strip() if entity_match else ""

        # 2. Persönliche Referenzen in User-Nachricht durch Profil-Fakten ersetzen
        query = user_message
        if person_name:
            person = self.profile.get_person(person_name)
            facts = {f["trait_type"]: f["value"] for f in (person.get("facts") or [])} if person else {}

            _PERSONAL_REPLACEMENTS = [
                (_re.compile(r'\bmein(?:en?)?\s+lieblingsverein\b', _re.I), facts.get("interest", "")),
                (_re.compile(r'\bmein(?:e)?\s+lieblingsfarbe\b', _re.I), facts.get("favorite_color", "")),
                (_re.compile(r'\bmein(?:en?)?\s+lieblingsessen\b', _re.I), facts.get("favorite_food", "")),
                (_re.compile(r'\bmein(?:e)?\s+vorliebe\b', _re.I), facts.get("preference", "")),
                (_re.compile(r'\bmein(?:e)?\s+(?:hobby|interesse)\b', _re.I), facts.get("interest", "")),
                (_re.compile(r'\bmeinen?\s+verein\b', _re.I), facts.get("interest", "")),
                (_re.compile(r'\bich\b', _re.I), person_name or ""),
            ]
            for pattern, replacement in _PERSONAL_REPLACEMENTS:
                if replacement:
                    query = pattern.sub(replacement, query)

        # 3. Bestes Ergebnis wählen: Eigenname > ersetzte Query > Original
        if entity and len(entity) > 3:
            return entity
        query = query.strip()
        if query and not _re.match(r'^(was|wie|wer|wo|wann|welche[rs]?)\s+weißt\b', query, _re.I):
            return query
        return user_message.strip()

    def _try_extract_fact_update(self, message: str, person_name: str) -> None:
        import re as _re
        for pattern, trait_type in self._FACT_PATTERNS:
            m = _re.search(pattern, message, _re.IGNORECASE)
            if m:
                value = m.group(1).strip().rstrip('.,!? ')
                if not value or (not value.isdigit() and len(value) < 2):
                    continue
                value = value[0].upper() + value[1:]
                try:
                    self.profile.upsert_fact(
                        person_name=person_name,
                        trait_type=trait_type,
                        value=value,
                        source_memory_id=None,
                        confidence=0.95,
                    )
                except Exception:
                    pass
                break  # nur ein Fakt pro Nachricht

    def _record_direct_chat_input(self, captured: str, person_name: str | None) -> None:
        self._log_event("speech_input", {"text": captured, "person_name": person_name})
        self._log_message("user", captured, person_name)
        self.conversation.record_user_topics(person_name, captured)
        with get_connection() as conn:
            write_state(conn, "display_status", "listening")
            if person_name is not None:
                write_state(conn, "active_person_name", person_name)

    def _finalize_chat(self, reply: str, person_name: str | None) -> None:
        sanitized_reply = self._sanitize_reply_text(reply)
        with get_connection() as conn:
            write_state(conn, "display_status", "responding")
            write_state(conn, "last_conversation_at", now_iso())
            # active_person_name wird hier NICHT geändert — wird nur über
            # das Display-Dropdown oder Kamera-Erkennung gesetzt/gelöscht

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
                    "Nein, aktuell läuft alles normal.\n"
                    f"Battery: {status['battery_level']}% | Display: {status['display_status']} | Gerät: {status['device']['effective_state']}"
                )
            if update_status == "available":
                return "Ja, es gibt ein ausstehendes Update. Es wurde noch nicht gestartet."
            if update_status == "failed":
                return "Ein Update ist fehlgeschlagen. Das sollte geprüft werden."
            return f"Ein Update läuft gerade. Aktueller Stand: {update_status}."
        if self.DISPLAY_QUESTION_PATTERN.search(message):
            return f"Mein Display steht gerade auf {status['display_status']}."
        if self.DEVICE_STATE_QUESTION_PATTERN.search(message) and any(
            token in message.casefold() for token in ("gerät", "geraet", "erika", "lage", "status")
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
                    profile_facts.append(f"{person_name} ist {value} groß.")
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
                        profile_facts.append(f"{self._possessive_form(person_name)} {relation} heißt {relation_name}.")
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
            return f"Über {person_name} weiß ich aktuell Folgendes: {details}"

        if memory_only_items:
            details = " ".join(memory_only_items[:2])
            return (
                f"Über {person_name} gibt es aktuell freigegebene Aussagen, aber noch kein bestätigtes Profilwissen. "
                f"Bisher gespeichert ist: {details}"
            )

        if profile:
            return f"Über {person_name} ist aktuell noch kein bestätigtes Wissen gespeichert."

        return f"Über {person_name} weiß ich aktuell noch nichts."

    def chat(self, message: str, person_name: str | None = None) -> dict[str, Any]:
        settings = self.settings.get_effective()
        captured = self.microphone.capture_text(message)
        self._learn_from_interaction(person_name, captured)
        direct_reply = self._try_answer_runtime_question(captured)
        if direct_reply is None:
            direct_reply = self._try_answer_person_knowledge_question(captured)
        if direct_reply is None:
            light_sched_reply = self._try_light_schedule_command(captured, person_name)
            if light_sched_reply:
                direct_reply = light_sched_reply
        if direct_reply is None:
            light_reply = self._try_light_command(captured)
            if light_reply:
                direct_reply = light_reply
                self._set_lights_display_intent()
        if direct_reply is not None:
            self._record_direct_chat_input(captured, person_name)
            reply = self._sanitize_reply_text(direct_reply)
            self._finalize_chat(reply, person_name)
            self._store_reply_text(reply)
            return {
                "reply": reply,
                "llm_provider": "core",
                "used_fallback": False,
                "llm_context": self.preview_chat_prompt(captured, person_name),
                "decision": {"should_respond": True, "response_reason": "core_direct_answer", "candidates": []},
                "proposed_memories": [],
                "status": self.get_status(),
            }

        robot_reply = self._try_robot_query(captured) or self._try_robot_command(captured)
        if robot_reply:
            self._record_direct_chat_input(captured, person_name)
            reply = self._sanitize_reply_text(robot_reply)
            self._finalize_chat(reply, person_name)
            self._store_reply_text(reply)
            return {"reply": reply, "llm_provider": "template", "used_fallback": False,
                    "decision": {"should_respond": True, "response_reason": "robot_command", "candidates": []},
                    "proposed_memories": [], "status": self.get_status()}

        template_text, search_result = self._try_template_search(captured)
        reply_text = template_text or "Das kann ich noch nicht beantworten."
        self._record_direct_chat_input(captured, person_name)
        reply = self._sanitize_reply_text(reply_text)
        self._finalize_chat(reply, person_name)
        self._store_reply_text(reply)
        if search_result:
            self._update_display_intent(search_result, person_name)
        return {"reply": reply, "llm_provider": "template", "used_fallback": template_text is None,
                "decision": {"should_respond": True, "response_reason": "template", "candidates": []},
                "proposed_memories": [], "status": self.get_status()}

    def stream_chat(self, message: str, person_name: str | None = None) -> Any:
        settings = self.settings.get_effective()
        captured = self.microphone.capture_text(message)
        self._learn_from_interaction(person_name, captured)
        self._save_evening_recap_response(captured, person_name)
        if person_name:
            self._try_extract_fact_update(captured, person_name)
        direct_reply = self._try_answer_runtime_question(captured)
        if direct_reply is None:
            direct_reply = self._try_answer_person_knowledge_question(captured)
        if direct_reply is None:
            light_sched_reply = self._try_light_schedule_command(captured, person_name)
            if light_sched_reply:
                direct_reply = light_sched_reply
        if direct_reply is None:
            light_reply = self._try_light_command(captured)
            if light_reply:
                direct_reply = light_reply
                self._set_lights_display_intent()
        if direct_reply is None:
            scene_reply = self._try_scene_command(captured)
            if scene_reply:
                direct_reply = scene_reply
        if direct_reply is None:
            calendar_reply = self._try_calendar_command(captured, person_name)
            if calendar_reply:
                direct_reply = calendar_reply
        if direct_reply is None:
            vehicle_reply = self._try_vehicle_query(captured)
            if vehicle_reply:
                direct_reply = vehicle_reply
        if direct_reply is None:
            conv_summary = self._try_conversation_summary(captured, person_name)
            if conv_summary:
                direct_reply = conv_summary
        if direct_reply is None:
            summary_reply = self._try_summary_command(captured, person_name)
            if summary_reply:
                direct_reply = summary_reply
        if direct_reply is None:
            reminder_reply = self._try_reminder_command(captured, person_name)
            if reminder_reply:
                direct_reply = reminder_reply
        if direct_reply is None:
            note_reply = self._try_note_command(captured, person_name)
            if note_reply:
                direct_reply = note_reply
        if direct_reply is None:
            timer_reply = self._try_timer_command(captured)
            if timer_reply:
                direct_reply = timer_reply
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

        robot_reply = self._try_robot_query(captured) or self._try_robot_command(captured)
        template_search_result = None
        if robot_reply:
            template_text = robot_reply
            reason = "robot_command"
        else:
            template_text, template_search_result = self._try_template_search(captured)
            reason = "template" if template_text else "llm"

        if not template_text:
            # LLM-Pfad: externes Modell oder Mock
            search_result = None
            search_context = None
            if self.search.needs_search(captured):
                query = self.search.extract_query(captured)
                search_result = self.search.search(query)
                if search_result:
                    search_context = self.search.format_prompt_block(search_result)

            # Affirmations-Handler: "ja" nach Angebot des LLM
            _AFFIRM = re.compile(
                r"^\s*(ja|jo|ok|gerne|bitte|klar|super|natürlich|genau|stimmt|"
                r"ja\s+gerne|ja\s+bitte|ja\s+klar|sehr\s+gerne|"
                r"klingt\s+gut|mach\s+das)\s*[!.?]?\s*$", re.IGNORECASE
            )
            if not search_result and _AFFIRM.match(captured.strip()):
                try:
                    with get_connection() as conn:
                        last_assistant_row = conn.execute(
                            "SELECT message FROM conversation_messages "
                            "WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1"
                        ).fetchone()
                        # Letzte User-Nachricht vor "ja" = die eigentliche Frage
                        prev_user_row = conn.execute(
                            "SELECT message FROM conversation_messages "
                            "WHERE role = 'user' ORDER BY created_at DESC LIMIT 1"
                        ).fetchone()
                    last_reply = (last_assistant_row["message"] if last_assistant_row else "").lower()
                    forced: str | None = None

                    # Szenario 1: LLM hat Wetter angeboten
                    if any(w in last_reply for w in ("wetter", "vorhersage", "temperatur", "grad", "regen")):
                        forced = "wetter heute"
                    # Szenario 2: LLM hat Kalender angeboten
                    elif any(w in last_reply for w in ("termin", "kalender", "liegt an", "steht an", "veranstaltung")):
                        forced = "was liegt heute an"
                    # Szenario 3: LLM hat Internet-Suche angeboten
                    elif any(w in last_reply for w in (
                        "internet", "nachschauen", "nachschau", "recherch",
                        "suchen", "schauen", "herausfind", "informationen",
                        "nachsehen", "im netz", "online",
                    )):
                        # Suchbegriff aus LLM-Antwort extrahieren (z.B. "SV Darmstadt")
                        # oder Profil-Fakten als Kontext nutzen
                        original_query = prev_user_row["message"].strip() if prev_user_row else ""
                        search_query = self._build_search_query_from_context(
                            last_reply, original_query, person_name
                        )
                        if search_query:
                            from app.search.providers.web import WebProvider
                            web_raw = WebProvider().search(search_query)
                            if web_raw:
                                from app.search.service import SearchResult
                                search_result = SearchResult(
                                    query=search_query,
                                    snippet=web_raw["snippet"],
                                    title=web_raw["title"],
                                    url=web_raw.get("url", ""),
                                )
                                search_context = self.search.format_prompt_block(search_result)

                    if forced:
                        search_result = self.search.search(forced)
                        if search_result:
                            search_context = self.search.format_prompt_block(search_result)
                except Exception:
                    pass
            payload = self.preview_chat_prompt(captured, person_name, search_context=search_context)
            payload["llm_max_tokens"] = self._dynamic_max_tokens(captured, payload.get("llm_max_tokens", settings.llm_max_tokens))
            self._record_direct_chat_input(captured, person_name)

            # Interest-Signal erkennen und als Vorschlag speichern
            proposed_memories: list[dict] = []
            if person_name:
                interest_signal = self.conversation.detect_interest_signal(
                    person_name=person_name,
                    text=captured,
                    threshold=settings.topic_interest_threshold,
                    window_days=settings.topic_interest_window_days,
                )
                if interest_signal:
                    mem = self.memory.propose(
                        content=interest_signal["content"],
                        category=interest_signal["category"],
                        subject=interest_signal["subject"],
                        source="chat_auto",
                        dedupe_statuses=("pending", "approved"),
                        candidate_kind="memory",
                        decision_reason=interest_signal["reason"],
                        confidence=interest_signal["confidence"],
                    )
                    if mem:
                        proposed_memories.append(mem)

            def llm_generate() -> Any:
                yield self._sse_event("meta", {
                    "llm_provider": "external", "used_fallback": False,
                    "decision": {"should_respond": True, "response_reason": "llm", "candidates": []},
                    "proposed_memories": proposed_memories,
                })
                full_reply = ""
                provider, fragments, used_fallback = self.llm.stream_generate(payload)
                try:
                    for fragment in fragments:
                        full_reply += fragment
                        for piece in self._stream_delta_pieces(fragment):
                            yield self._sse_event("delta", {"text": piece})
                            self._store_reply_text(full_reply, done=False)
                except Exception:
                    if not full_reply:
                        full_reply = "Das kann ich leider gerade nicht beantworten."
                        yield self._sse_event("delta", {"text": full_reply})
                reply = self._sanitize_reply_text(full_reply)
                self._finalize_chat(reply, person_name)
                self._store_reply_text(reply, done=True)
                if search_result:
                    self._update_display_intent(search_result, person_name)
                yield self._sse_event("done", {
                    "reply": reply, "llm_provider": provider, "used_fallback": used_fallback,
                    "decision": {"should_respond": True, "response_reason": "llm", "candidates": []},
                    "proposed_memories": proposed_memories, "status": self.get_status(),
                })

            return llm_generate()

        self._record_direct_chat_input(captured, person_name)

        def template_generate() -> Any:
            text = self._sanitize_reply_text(template_text)
            yield self._sse_event("meta", {"llm_provider": "template", "used_fallback": False,
                                           "decision": {"should_respond": True, "response_reason": reason, "candidates": []},
                                           "proposed_memories": []})
            yield self._sse_event("delta", {"text": text})
            self._finalize_chat(text, person_name)
            self._store_reply_text(text, done=True)
            if template_search_result:
                self._update_display_intent(template_search_result, person_name)
            yield self._sse_event("done", {"reply": text, "llm_provider": "template",
                                           "used_fallback": False,
                                           "decision": {"should_respond": True, "response_reason": reason, "candidates": []},
                                           "proposed_memories": [], "status": self.get_status()})

        return template_generate()

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
        conflict = None
        materialization = self._materialization_policy(memory)
        if materialization["action"] == "profile_fact" and memory.get("subject"):
            profile_value = self._extract_profile_value(memory)
            profile_result = self.profile.upsert_fact_resolved(
                person_name=memory["subject"],
                trait_type=memory["category"],
                value=profile_value,
                source_memory_id=memory["id"],
                confidence=memory.get("confidence"),
            )
            profile_update = profile_result["person"]
            conflict = profile_result["conflict"]
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
                "conflict": conflict,
            },
        )

        return {
            "memory": memory,
            "profile_update": profile_update,
            "materialization": materialization,
            "conflict": conflict,
        }

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
            summary="Person wurde lokal hart gelöscht.",
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
            match = re.match(
                rf"^{re.escape(memory['subject'])} ist (.+?) gro(?:ß|ss)\.$",
                memory["content"],
            )
            if match:
                return match.group(1)
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
            if "humorvolle Antworten" in memory["content"]:
                return "higher"
            if "nüchterne Antworten" in memory["content"]:
                return "lower"
        if memory["category"] == "response_style_preference":
            if "sachlich" in memory["content"]:
                return "sachlich"
            if "locker" in memory["content"]:
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
                rf"^{re.escape(RobotCore._possessive_form(memory['subject']))} (.+?) hei(?:ß|ss)t (.+)\.$",
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
            match = re.match(
                rf"^{re.escape(memory['subject'])} interessiert sich für (.+)\.$",
                memory["content"],
            )
            if match:
                return match.group(1)
        if memory["category"] == "dislike":
            prefix = f"{memory['subject']} mag "
            suffix = " nicht."
            if memory["content"].startswith(prefix) and memory["content"].endswith(suffix):
                return memory["content"][len(prefix):-len(suffix)]
        return memory["content"]

    @staticmethod
    def _possessive_form(name: str) -> str:
        if name.casefold().endswith(("s", "ß", "x", "z")):
            return f"{name}'"
        return f"{name}s"

    def _try_template_search(self, query: str) -> tuple[str | None, Any]:
        """Versucht Football/Wetter/Kalender-Anfragen ohne LLM zu beantworten."""
        from app.search.providers.football import FootballProvider
        from app.search.providers.weather import WeatherProvider
        from app.search.providers.homeassistant import HomeAssistantProvider
        from app.search.service import SearchResult

        for Provider in (WeatherProvider, FootballProvider, HomeAssistantProvider):
            try:
                p = Provider()
                if not p.can_handle(query):
                    continue
                raw = p.search(query)
                if not raw or not raw.get("snippet"):
                    return None, None
                sr = SearchResult(
                    query=query,
                    snippet=raw["snippet"],
                    title=raw.get("title", ""),
                    url=raw.get("url", ""),
                    is_stable=raw.get("is_stable", False),
                    memory_content=None,
                    meta={k: v for k, v in raw.items() if k not in ("snippet", "title", "url", "is_stable")},
                )
                return sr.snippet, sr
            except Exception:
                continue
        return None, None

    _ROBOT_WORDS = r"(?:roboter|saugroboter|mähroboter|staubsauger|mäher|rasenmäher|roborock|roomba)"
    _ROBOT_ART   = r"(?:der|die|den|mein(?:en?)?|man|unser(?:en?)?)"  # 'man' = STT-Fehler für 'mein'

    ROBOT_QUERY_PATTERN = re.compile(
        r"\b(?:"
        r"was\s+macht\s+" + r"(?:der|die|den|mein(?:en?)?|man|unser(?:en?)?)?\s*" + r"(?:roboter|saugroboter|mähroboter|staubsauger|mäher|rasenmäher|roborock|roomba)"
        r"|was\s+macht\s+(?:roboter|saugroboter|mähroboter|staubsauger|mäher)\s+\w+"
        r"|wie\s+(?:ist|steht|viel|weit|lange)\s+.{0,20}(?:roboter|saugroboter|mähroboter|staubsauger|mäher|rasenmäher)"
        r"|(?:ist|sind)\s+.{0,20}(?:roboter|saugroboter|mähroboter|staubsauger|mäher)\s+.{0,20}(?:fertig|zuhause|laden|fehler|aktiv|beschäftigt|kaputt)"
        r"|status\s+.{0,20}(?:roboter|saugroboter|mähroboter|staubsauger|mäher)"
        r"|(?:roboter|saugroboter|mähroboter|staubsauger|mäher)\s+.{0,20}(?:status|akku|batterie|fertig|fehler|läuft|aktiv)"
        r"|wo\s+(?:ist|sind)\s+.{0,20}(?:roboter|saugroboter|mähroboter|staubsauger|mäher)"
        r"|wann\s+(?:ist|war|wird)\s+.{0,20}(?:roboter|saugroboter|mähroboter|staubsauger|mäher)\s+.{0,15}(?:fertig|zurück|zuhause)"
        r")\b",
        re.IGNORECASE,
    )

    ROBOT_COMMAND_PATTERN = re.compile(
        r"\b(?:schick(?:e)?|send[e]?|lass|fahr(?:e)?|starte?|reinig(?:e)?|saug(?:e)?|wisch(?:e)?|putz(?:e)?|schick\s+los"
        r"|mäh(?:en|e)?|mow|leg\s+los|soll\s+(?:mähen|saugen|wischen|reinigen|starten|loslegen|nach\s+hause|pausieren)"
        r"|schick\s+\w+\s+nach\s+hause|fahr\s+\w+\s+(?:nach\s+hause|zur\s+basis))\b",
        re.IGNORECASE,
    )

    def _try_robot_query(self, query: str) -> str | None:
        """Beantwortet Statusfragen zu Robotern direkt aus HA-Daten."""
        if not self.ROBOT_QUERY_PATTERN.search(query):
            return None
        try:
            from app.services.robot_service import RobotService
            from app.services.integration_config_service import IntegrationConfigService
            from app.services.summary_service import _translate_robot_state
            cfg = IntegrationConfigService().get_config() or {}
            svc = RobotService()
            robots = svc.list_robots_with_config(cfg)
            if not robots:
                return None

            q = query.lower()
            matched = None
            for r in robots:
                name_words = [w for w in re.split(r"\s+", r.get("name", "").lower()) if len(w) > 2]
                if any(w in q for w in name_words):
                    matched = r
                    break
            targets = [matched] if matched else robots

            _ACTIVE_STATES = {"cleaning", "sweeping", "mopping", "sweeping_and_mopping",
                              "mowing", "cutting", "edgecut", "spot", "auto", "cruising"}

            parts = []
            for r in targets:
                name = r["name"]
                state_raw = (r.get("state") or "unknown").lower()
                state_de = _translate_robot_state(state_raw)
                battery = r.get("battery")
                extras = r.get("extras", {})

                line = f"{name} {state_de}"
                if battery is not None:
                    try:
                        line += f" ({int(float(battery))} % Akku)"
                    except (ValueError, TypeError):
                        pass

                # Fehler
                error = (extras.get("fehler", {}).get("state") or "").strip().lower()
                if error and error not in {"kein fehler", "no_error", "none", "ok", "", "unknown"}:
                    line += f" — Fehler: {svc._translate_error_state(error)}"

                # Gereinigte Fläche nur bei aktivem Reinigen (nicht bei Trocknen, Laden etc.)
                if state_raw in _ACTIVE_STATES:
                    area = extras.get("total_cleaned_area", {}).get("state")
                    if area:
                        try:
                            line += f", bisher {round(float(area))} m² gereinigt"
                        except (ValueError, TypeError):
                            pass

                parts.append(line)

            if not parts:
                return None
            return ". ".join(parts) + "."
        except Exception:
            return None

    def _try_robot_command(self, query: str) -> str | None:
        """Erkennt Roboter-Befehle und führt sie direkt aus."""
        if not self.ROBOT_COMMAND_PATTERN.search(query):
            return None
        try:
            from app.services.robot_service import RobotService
            from app.services.integration_config_service import IntegrationConfigService

            svc = RobotService()
            full_cfg = IntegrationConfigService().get_config() or {}
            robots_cfg = full_cfg.get("robots") or {}
            vacuum_configs = robots_cfg.get("vacuum_configs") or {}
            all_robots = svc.list_robots_with_config(full_cfg)

            q = query.lower()

            # ── Mähroboter-Pfad ─────────────────────────────────────────────
            _MOWER_INTENT = re.compile(
                r"\b(?:mäh(?:en|e)?|rasenmäher|mähroboter|mäher"
                r"|soll\s+mähen|starte?\s+(?:den\s+)?(?:mähroboter|mäher|rasenmäher)"
                r"|nach\s+hause|zur\s+basis|zurück(?:\s+zur\s+basis)?|dock(?:en)?"
                r"|pausier(?:en|e)?|anhalten|stopp(?:en)?)\b",
                re.IGNORECASE,
            )
            _MOWER_DOCK = re.compile(
                r"\b(?:nach\s+hause|zur\s+(?:basis|ladestation)|zurück|dock(?:en)?"
                r"|aufhören|hör\s+auf|abbrechen|stopp)\b",
                re.IGNORECASE,
            )
            _MOWER_PAUSE = re.compile(
                r"\b(?:pausier(?:en|e)?|anhalten|halt)\b",
                re.IGNORECASE,
            )
            mowers = [r for r in all_robots if r.get("domain") == "lawn_mower"]
            if mowers and (_MOWER_INTENT.search(query) or not [r for r in all_robots if r.get("domain") == "vacuum"]):
                mower = None
                for r in mowers:
                    name_words = [w for w in re.split(r"\s+", r.get("name", "").lower()) if len(w) > 2]
                    if any(w in q for w in name_words):
                        mower = r
                        break
                if not mower and len(mowers) == 1:
                    mower = mowers[0]
                if mower:
                    if _MOWER_DOCK.search(query):
                        svc.command(mower["entity_id"], "dock")
                        return f"Okay, {mower['name']} fährt jetzt nach Hause."
                    elif _MOWER_PAUSE.search(query):
                        svc.command(mower["entity_id"], "pause")
                        return f"Okay, {mower['name']} ist pausiert."
                    else:
                        svc.command(mower["entity_id"], "start_mowing")
                        return f"Okay, {mower['name']} fängt jetzt an zu mähen."

            # ── Saugroboter-Pfad ─────────────────────────────────────────────
            vacuums = [r for r in all_robots if r.get("domain") == "vacuum"]
            if not vacuums:
                return None

            robot = None
            for r in vacuums:
                name_words = [w for w in re.split(r"\s+", r.get("name", "").lower()) if len(w) > 2]
                if any(w in q for w in name_words):
                    robot = r
                    break
            if not robot and len(vacuums) == 1:
                robot = vacuums[0]
            if not robot:
                return None

            eid = robot["entity_id"]
            vcfg = vacuum_configs.get(eid) or {}
            rooms = vcfg.get("rooms") or []

            # Modus erkennen
            if re.search(r"\bwisch(?:en|e)?\b", q) and re.search(r"\bsaug(?:en|e)?\b", q):
                mode_option, mode_label = "sweeping_and_mopping", "Saugen und Wischen"
            elif re.search(r"\bwisch(?:en|e)?\b", q):
                mode_option, mode_label = "mopping", "Wischen"
            else:
                mode_option, mode_label = "sweeping", "Saugen"

            # Räume erkennen
            selected = []
            if re.search(r"\ball(?:e|en)?\s*r[äa]ume?\b|\ball(?:e|en)?\b", q):
                selected = [r["id"] for r in rooms]
            else:
                for room in rooms:
                    if room["name"].lower() in q:
                        selected.append(room["id"])

            if not selected:
                return None

            svc.clean_segments({
                "entity_id": eid,
                "segments": selected,
                "cleaning_mode_option": mode_option,
                "cleaning_times": 1,
            })

            room_names = [r["name"] for r in rooms if r["id"] in selected]
            room_str = " und ".join(room_names)
            return f"{robot['name']} fährt jetzt zum {mode_label} in: {room_str}."
        except Exception:
            return None

    _TIMER_PATTERN = re.compile(
        r"\b(?:stell(?:e|en)?(?:\s+(?:mir|einen|ein|mal))?\s+)?timer\b"
        r"|\btimer\s+(?:auf|für|von|starten|setzen)\b"
        r"|\b(?:alarm|wecker)\s+(?:in|auf|für|stell)\b"
        r"|\b(\d+)\s*(?:minuten?|sekunden?|stunden?)\s+(?:timer|alarm)\b"
        r"|\bstell(?:e)?\s+(?:mir\s+)?(?:einen?\s+)?(?:timer|alarm|wecker)\b"
        r"|\b(?:setz[e]?|start[e]?)\s+(?:einen?\s+)?timer\b",
        re.IGNORECASE,
    )
    _TIMER_CANCEL_PATTERN = re.compile(
        r"\b(?:stopp?|abbr[eü]ch?|beend[e]?|lösch[e]?|cancel|reset|abschalten)\s+(?:den\s+|alle\s+)?(?:timer|alarm|wecker)\b"
        r"|\b(?:timer|alarm|wecker)\s+(?:stopp?|abbr[eü]ch?|beend[e]?|lösch[e]?|aus|weg)\b"
        r"|\b(?:timer|alarm|wecker)\s+(?:nicht\s+mehr|deaktivieren)\b"
        r"|\balle\s+(?:timer|alarme?|wecker)\b",
        re.IGNORECASE,
    )
    _TIMER_DISMISS_PATTERN = re.compile(
        r"^(?:stopp?|stop|aus|ok(?:ay)?|fertig|danke|ruhe|genug|hör\s+auf)$",
        re.IGNORECASE,
    )
    _TIMER_LABEL_RE = re.compile(
        r'\bmit\s+namen?\s+([A-Za-zÄÖÜäöüß]{2,}(?:\s+[A-Za-zÄÖÜäöüß]{2,})?)'
        r'|\bnamens\s+([A-Za-zÄÖÜäöüß]{2,}(?:\s+[A-Za-zÄÖÜäöüß]{2,})?)'
        r'|\bfür\s+(?:die\s+|den\s+|das\s+|dem\s+|einen?\s+|einem\s+)?([A-Za-zÄÖÜäöüß]{2,})',
        re.IGNORECASE,
    )
    _TIMER_REMAINING_PATTERN = re.compile(
        r"\bwie\s+lang[e]?\s+(?:noch|dauert)\b"
        r"|\bnoch\s+wie\s+lang[e]?\b"
        r"|\bwie\s+viel\s+zeit\b"
        r"|\bnoch\s+(?:wie\s+lang[e]?|viel\s+zeit)\b"
        r"|\b(?:rest(?:zeit)?|verbleibend[e]?)\s+(?:beim?\s+)?timer\b"
        r"|\btimer\s+(?:status|rest|wie\s+lang[e]?)\b",
        re.IGNORECASE,
    )
    _TIMER_LIST_PATTERN = re.compile(
        r"\bwelch[e]?\s+timer\b"
        r"|\bwie\s+viele?\s+timer\b"
        r"|\bzeig[e]?\s+(?:mir\s+)?(?:alle?\s+)?timer\b"
        r"|\bwas\s+(?:für\s+)?timer\s+(?:laufen?|sind|l[aä]uft|aktiv)\b",
        re.IGNORECASE,
    )
    _TIMER_RENAME_PATTERN = re.compile(
        r"\b(?:nenn[e]?|benenn[e]?|umbenennen?|umbenenn[e]?|umtaufen?)\b.{0,60}\btimer\b"
        r"|\btimer\b.{0,60}\b(?:nenn[e]?|benenn[e]?|heißt?|soll\s+heißen?|umbenennen?)\b",
        re.IGNORECASE,
    )
    _TIMER_LABEL_BLACKLIST = frozenset([
        "timer", "alarm", "wecker", "mich", "dich", "uns", "euch", "ihn", "sie", "es",
        "minuten", "sekunden", "stunden", "minute", "sekunde", "stunde", "mal",
    ])
    _DURATION_RE = re.compile(
        r"(eine?|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|fünfzehn|zwanzig|dreißig|vierzig|fünfzig|sechzig|\d+(?:[.,]\d+)?)"
        r"\s*(stunde[n]?|std?|h(?:our)?|minute[n]?|min?|sekunde[n]?|sek?|s(?:ec)?)\b",
        re.IGNORECASE,
    )
    _WORD_NUMBERS = {
        "eine": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
        "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
        "elf": 11, "zwölf": 12, "fünfzehn": 15, "zwanzig": 20,
        "dreißig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60,
    }

    _CALENDAR_PATTERN = re.compile(
        r"\bkalendereintrag\b"
        r"|\b(trag[e]?|erstell[e]?|anlegen?|notier[e]?|füg[e]?\s+ein|merk[e]?\s+(?:dir|vor)|speicher[e]?).{0,60}\b(termin|eintrag|event|kalender|appointment|verabredung|besprechung|meeting)\b"
        r"|\b(termin|event|besprechung|meeting|verabredung).{0,40}\b(tragen?|erstellen?|anlegen?|eintragen?|einplanen?|merken?|speichern?)\b"
        r"|\b(kalender|terminkalender).{0,40}\b(eintragen?|erstellen?|anlegen?|notieren?|hinzufügen?|ergänzen?)\b"
        r"|\btrag[e]?\s+(?:bitte\s+)?(?:für\s+)?(?:mich\s+)?.{0,60}\b(?:ein|im\s+kalender)\b",
        re.IGNORECASE,
    )

    def _try_calendar_command(self, captured: str, person_name: str | None) -> str | None:
        if not self._CALENDAR_PATTERN.search(captured):
            return None
        try:
            from app.services.calendar_write_service import CalendarWriteService
            svc = CalendarWriteService()
            entity_id = svc.resolve_entity(person_name)
            if not entity_id:
                return "Kein Kalender konfiguriert. Bitte im Admin unter Personen oder Kalender einen Schreibkalender festlegen."

            # LLM für strukturierte Extraktion von Datum/Zeit/Titel
            from datetime import datetime, timezone
            from app.brain.llm_client import LLMRouter
            today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            weekday_de = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
            today_label = weekday_de[datetime.now().weekday()] + ", " + today
            extraction_prompt = (
                f"Heute ist {today_label}. Extrahiere aus folgendem Text einen Kalendereintrag und antworte NUR mit gültigem JSON.\n"
                f"Format: {{\"title\": \"...\", \"date\": \"YYYY-MM-DD\", \"time\": \"HH:MM\", \"duration_min\": 60}}\n"
                f"Wenn kein Datum/Zeit erkennbar: date=heute, time=\"12:00\". Dauer Standard 60 Min.\n"
                f"Text: \"{captured}\""
            )
            router = LLMRouter()
            result = router.generate({
                "messages": [
                    {"role": "system", "content": "Du extrahierst strukturierte Kalendereinträge aus natürlicher Sprache. Antworte nur mit JSON."},
                    {"role": "user", "content": extraction_prompt},
                ],
            }, timeout_seconds=10)
            reply_text = (result.get("reply") or "").strip()

            # JSON aus Antwort extrahieren
            import json, re as _re
            m = _re.search(r'\{[^}]+\}', reply_text, _re.DOTALL)
            if not m:
                return "Ich konnte den Termin nicht verstehen. Bitte genauer formulieren."
            data = json.loads(m.group(0))
            title       = str(data.get("title") or "Termin").strip()
            date_str    = str(data.get("date") or today)
            time_str    = str(data.get("time") or "12:00")
            duration_m  = int(data.get("duration_min") or 60)

            from datetime import timedelta
            start_dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
            end_dt   = start_dt + timedelta(minutes=duration_m)
            ok = svc.create_event(entity_id, title, start_dt, end_dt)
            if not ok:
                return "Fehler beim Anlegen des Termins in Home Assistant."

            # Bestätigung formatieren
            weekday = weekday_de[start_dt.weekday()]
            return f"Termin '{title}' wurde für {weekday}, {start_dt.strftime('%d.%m.%Y')} um {start_dt.strftime('%H:%M')} Uhr eingetragen."
        except Exception:
            return None

    def _try_scene_command(self, captured: str) -> str | None:
        import re, json
        q = captured.lower()
        if not re.search(r'\bszene\b', q):
            return None
        m = re.search(r'szene[n]?\s+[»„"\']?([^\'"»"]+?)[\'\"«"»]?\s*(?:aktivieren?|starten?|einschalten?|laden?|abspielen?|an)?$', q)
        if not m:
            m = re.search(r'(?:aktiviere?|starte?|spiele?|lade?)\s+(?:die\s+)?szene[n]?\s+[»„"\']?(.+?)[\'\"«"»]?\s*$', q)
        if not m:
            return None
        scene_name = m.group(1).strip().rstrip('.')
        if not scene_name:
            return None
        try:
            from app.database.db import get_connection
            with get_connection() as conn:
                rows = conn.execute("SELECT id, name FROM light_scenes").fetchall()
            best_id, best_name = None, None
            name_lower = scene_name.lower()
            for row in rows:
                if row["name"].lower() == name_lower:
                    best_id, best_name = row["id"], row["name"]
                    break
                if name_lower in row["name"].lower() or row["name"].lower() in name_lower:
                    best_id, best_name = row["id"], row["name"]
            if not best_id:
                return f"Szene '{scene_name}' nicht gefunden."
            from app.services.light_service import LightService
            from app.database.db import get_connection
            with get_connection() as conn:
                row = conn.execute("SELECT light_states FROM light_scenes WHERE id = ?", (best_id,)).fetchone()
            if not row:
                return "Szene konnte nicht geladen werden."
            states = json.loads(row["light_states"])
            svc = LightService()
            for light in states:
                eid = light.get("entity_id", "")
                if not eid:
                    continue
                if light.get("state") == "off":
                    svc.control_light({"entity_id": eid, "service": "turn_off"})
                else:
                    cmd: dict = {"entity_id": eid, "service": "turn_on"}
                    if light.get("brightness_pct") is not None:
                        cmd["brightness_pct"] = light["brightness_pct"]
                    if light.get("hs_color"):
                        cmd["hs_color"] = light["hs_color"]
                    elif light.get("color_temp_kelvin"):
                        cmd["color_temp_kelvin"] = light["color_temp_kelvin"]
                    elif light.get("rgb_color"):
                        cmd["rgb_color"] = light["rgb_color"]
                    svc.control_light(cmd)
            return f"Szene '{best_name}' aktiviert."
        except Exception:
            return None

    _VEHICLE_QUERY_PATTERN = re.compile(
        r"\b(?:"
        # Zustandsfragen mit Fahrzeugnamen
        r"wie\s+(?:ist|viel|weit|hoch|lang|sieht|steht)\b.{0,50}\b(?:akku|ladestand|tank|tankstand|reichweite|laden|ladung|batterie|auto|fahrzeug|dacia|spring|wagen|elektro)"
        r"|(?:akku|ladestand|tank|tankstand|reichweite|ladung|batterie)\b.{0,40}\b(?:auto|fahrzeug|dacia|spring|wagen|vom|des|mein)"
        r"|\b(?:wie\s+viel|wieviel)\s+(?:akku|reichweite|strom|prozent|kilometer|km)\b"
        # Ladefragen in verschiedenen Wortstellungen
        r"|wird\b.{0,40}\b(?:auto|fahrzeug|dacia|spring|wagen|es)\b.{0,20}\b(?:geladen|aufgeladen|laden)"
        r"|(?:auto|fahrzeug|dacia|spring|wagen)\b.{0,30}\b(?:gerade\s+)?(?:am\s+laden|geladen|lädt|aufgeladen)"
        r"|(?:lädt|laden|geladen)\b.{0,30}\b(?:auto|fahrzeug|dacia|spring|wagen|es|gerade)"
        r"|\b(?:ist|wird)\b.{0,20}\b(?:dacia|spring|auto|fahrzeug|wagen)\b.{0,20}\b(?:geladen|laden|am\s+laden|am\s+strom|angesteckt|verbunden)"
        r"|\bam\s+laden\b"
        r"|\b(?:lädt|geladen|ladevorgang|ladestand)\b"
        # Reichweite / Allgemein
        r"|(?:alle?\s+)?(?:autos?|fahrzeuge)\b"
        r"|(?:wie\s+weit|weit)\s+komm(?:e|st)?\s+(?:ich|du|man)\s+noch\b"
        r"|(?:reicht|langt)\s+(?:der\s+akku|die\s+ladung|der\s+tank)\b"
        r")",
        re.IGNORECASE,
    )

    def _try_vehicle_query(self, captured: str) -> str | None:
        if not self._VEHICLE_QUERY_PATTERN.search(captured):
            return None
        try:
            from app.services.vehicle_service import VehicleService
            from app.services.integration_config_service import IntegrationConfigService
            svc = VehicleService()
            cfg = IntegrationConfigService().get_config()
            data = svc.list_vehicles(cfg)
            vehicles = data.get("vehicles") or []
            if not vehicles:
                return "Ich habe keine Fahrzeuge konfiguriert."

            q = captured.lower()

            # Gezieltes Fahrzeug suchen (nach Label/Name)
            target = None
            for v in vehicles:
                label = (v.get("label") or v.get("id") or "").lower()
                if any(word in q for word in label.split()):
                    target = v
                    break

            # Alle Fahrzeuge wenn explizit gefragt oder nur eines vorhanden
            if target is None and ("alle" in q or "fahrzeuge" in q or len(vehicles) == 1):
                return self._format_vehicles_reply(vehicles)

            if target is None:
                target = vehicles[0]

            return self._format_vehicle_reply(target)
        except Exception:
            return None

    @staticmethod
    def _fmt_minutes(mins: int) -> str:
        if mins <= 0:
            return "vollständig geladen"
        if mins < 60:
            return f"noch etwa {mins} Minuten"
        h = mins // 60
        m = mins % 60
        if m == 0:
            return f"noch etwa {h} {'Stunde' if h == 1 else 'Stunden'}"
        return f"noch etwa {h} {'Stunde' if h == 1 else 'Stunden'} und {m} Minuten"

    @staticmethod
    def _pct(state: Any) -> str:
        try:
            return f"{round(float(state))} Prozent"
        except (TypeError, ValueError):
            return str(state)

    @staticmethod
    def _km(state: Any, unit: str = "km") -> str:
        try:
            val = round(float(state))
            return f"{val} Kilometer"
        except (TypeError, ValueError):
            return f"{state} {unit}"

    def _format_vehicle_reply(self, v: dict) -> str:
        label = v.get("label") or v.get("id") or "Fahrzeug"
        parts: list[str] = []

        # ── E-Auto ────────────────────────────────────────────
        battery = v.get("battery")
        if battery:
            pct = self._pct(battery.get("state"))
            parts.append(f"Der {label} hat gerade {pct} Akku.")

            rng = v.get("range")
            if rng:
                km = self._km(rng.get("state"), rng.get("unit", "km"))
                parts.append(f"Damit kommst du noch etwa {km} weit.")

            plug = v.get("plug")
            charging = v.get("charging")
            rct = v.get("remaining_charge_time")

            _CHARGING_STATES = {
                "on", "charging", "in_charge", "charge_in_progress",
                "plugged_in", "connected", "true", "1",
                "laden", "lädt", "active", "start",
            }
            # Explizit kein Laden — überschreibt rct-Fallback
            _NOT_CHARGING_STATES = {
                "not_charging", "not charging", "charge_error", "charge error",
                "stopped", "stop", "error", "off", "false", "0",
                "nicht am laden", "nicht_am_laden", "no_charging",
            }
            _PLUGGED_STATES = _CHARGING_STATES | {"plugged", "plug_in", "angeschlossen"}

            charge_state = (charging.get("state") or "").lower() if charging else ""
            plug_state   = (plug.get("state")    or "").lower() if plug    else ""

            rct_mins = 0
            try:
                rct_mins = int(float((rct or {}).get("state", 0) or 0))
            except (TypeError, ValueError):
                pass

            # rct > 0 nur als Fallback wenn der Ladestatus nicht explizit "kein Laden" meldet
            explicitly_not_charging = charge_state in _NOT_CHARGING_STATES
            is_charging = (
                charge_state in _CHARGING_STATES
                or plug_state in _CHARGING_STATES
                or (rct_mins > 0 and not explicitly_not_charging)
            )

            if is_charging:
                if rct_mins > 0:
                    parts.append(f"Das Auto lädt gerade — {self._fmt_minutes(rct_mins)}.")
                else:
                    parts.append("Das Auto lädt gerade.")
            elif plug_state in _PLUGGED_STATES or explicitly_not_charging:
                parts.append("Das Auto ist angesteckt, aber nicht am Laden.")
            else:
                parts.append("Das Auto ist aktuell nicht angesteckt.")

        # ── Verbrenner ────────────────────────────────────────
        fuel = v.get("fuel_level")
        if fuel:
            pct = self._pct(fuel.get("state"))
            parts.append(f"Der Tank vom {label} ist zu {pct} gefüllt.")
            rng = v.get("range")
            if rng:
                km = self._km(rng.get("state"), rng.get("unit", "km"))
                parts.append(f"Damit kommst du noch etwa {km} weit.")

        return " ".join(parts) if parts else f"Ich habe keine aktuellen Daten für {label}."

    def _format_vehicles_reply(self, vehicles: list) -> str:
        if len(vehicles) == 1:
            return self._format_vehicle_reply(vehicles[0])
        count = len(vehicles)
        intro = f"Du hast {count} Fahrzeuge. "
        return intro + " ".join(self._format_vehicle_reply(v) for v in vehicles)

    def _try_summary_command(self, captured: str, person_name: str | None) -> str | None:
        if not person_name:
            return None
        try:
            from app.services.summary_service import get_config, build_summary
            person = self.profile.get_person(person_name)
            if not person:
                return None
            cfg = get_config(person["id"])
            phrases = [p.strip().lower() for p in (cfg.get("trigger_phrases") or []) if p.strip()]
            q = captured.strip().lower().rstrip('.,!?')
            if not any(q == phrase or q.startswith(phrase) for phrase in phrases):
                return None
            return build_summary(person["id"], person_name)
        except Exception:
            return None

    _CONVERSATION_SUMMARY_PATTERN = re.compile(
        r"\b(?:was\s+haben\s+wir\s+(?:heute|bisher|gerade)\s+(?:so\s+)?(?:besprochen|geredet|gemacht|diskutiert)"
        r"|fass(?:e|t)?\s+(?:unser(?:e|n)?|das)\s+(?:gespräch|unterhaltung|session)\s+zusammen"
        r"|worüber\s+haben\s+wir\s+(?:heute|gerade)\s+(?:gesprochen|geredet)"
        r"|was\s+war\s+(?:das\s+)?thema\s+(?:heute|unserer\s+unterhaltung)"
        r"|zusammenfassung\s+(?:unserer|des)\s+(?:heutig(?:en)?\s+)?(?:gespräch|unterhaltung))\b",
        re.IGNORECASE,
    )

    _NOTE_SAVE_PATTERN = re.compile(
        r"\b(?:merk(?:e|)\s+dir|notier(?:e|)|speicher(?:e|)\s+(?:die\s+)?notiz|leg(?:e|)\s+(?:eine?\s+)?notiz\s+an"
        r"|erinner(?:e|)\s+dich\s+an|denk\s+daran\s+dass?|behalte?\s+(?:im\s+kopf|in\s+erinnerung))"
        r"\s*[:\-–]?\s*(.+)",
        re.IGNORECASE,
    )
    _NOTE_QUERY_PATTERN = re.compile(
        r"\b(?:was\s+(?:hast\s+du\s+dir\s+gemerkt|ist|sind|weißt\s+du)\s+(?:über|zu|bei|vom?|der|die|das)\s+(.+?)"
        r"|was\s+(?:ist|war|sind)\s+(?:der|die|das|mein(?:e)?)?\s*(.+?)\s*\?"
        r"|zeig(?:e?)\s+mir\s+(?:die\s+)?notiz(?:en)?\s+(?:zu|über|von)\s+(.+)"
        r"|(?:meine?\s+)?notiz(?:en)?\s+(?:zu|über|von)\s+(.+)"
        r"|hast\s+du\s+(?:eine?\s+)?notiz\s+(?:zu|über|von)\s+(.+))\b",
        re.IGNORECASE,
    )
    _NOTE_LIST_PATTERN = re.compile(
        r"\b(?:zeig(?:e?)\s+(?:mir\s+)?(?:alle\s+)?(?:meine\s+)?notizen"
        r"|was\s+hast\s+du\s+(?:dir\s+)?(?:alles\s+)?(?:gemerkt|notiert|gespeichert)"
        r"|welche\s+notizen\s+(?:hast\s+du|gibt\s+es))\b",
        re.IGNORECASE,
    )
    _NOTE_DELETE_PATTERN = re.compile(
        r"\b(?:lösch(?:e?)|entfern(?:e?)|vergiss)\s+(?:die\s+)?notiz\s+(?:zu|über|von|mit\s+dem\s+titel)?\s*(.+)",
        re.IGNORECASE,
    )

    def _try_conversation_summary(self, captured: str, person_name: str | None) -> str | None:
        if not self._CONVERSATION_SUMMARY_PATTERN.search(captured):
            return None
        try:
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT message FROM conversation_messages
                    WHERE role = 'user' AND created_at >= ?
                      AND (? IS NULL OR lower(coalesce(person_name,'')) = lower(?))
                    ORDER BY id ASC
                    """,
                    (today_start, person_name, person_name),
                ).fetchall()
            if not rows:
                return "Wir haben heute noch nicht miteinander gesprochen."
            all_topics: list[str] = []
            seen: set[str] = set()
            for row in rows:
                for topic in self.conversation.extract_topics(row["message"]):
                    if topic not in seen:
                        seen.add(topic)
                        all_topics.append(topic)
            count = len(rows)
            if not all_topics:
                return f"Heute haben wir {count} Mal miteinander gesprochen, aber ich konnte keine klaren Themen erkennen."
            topic_labels = [t.capitalize() for t in all_topics[:6]]
            if len(topic_labels) > 1:
                topic_str = ", ".join(topic_labels[:-1]) + " und " + topic_labels[-1]
            else:
                topic_str = topic_labels[0]
            return f"Heute haben wir {count} Mal miteinander gesprochen. Themen waren unter anderem: {topic_str}."
        except Exception:
            return None

    def _save_evening_recap_response(self, captured: str, person_name: str | None) -> None:
        """Erkennt Antwort auf Abend-Recap-Frage und speichert sie als Tagesfazit-Notiz."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT message FROM conversation_messages WHERE role='assistant' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            if not row:
                return
            if "wie war dein tag heute" not in (row["message"] or "").lower():
                return
            from app.services.note_service import NoteService
            from datetime import date
            person_id = None
            if person_name:
                p = self.profile.get_person(person_name)
                if p:
                    person_id = p["id"]
            today_str = date.today().strftime("%d.%m.%Y")
            NoteService().create(
                title=f"Tagesfazit {today_str}",
                content=captured,
                person_id=person_id,
            )
        except Exception:
            pass

    def _try_note_command(self, captured: str, person_name: str | None) -> str | None:
        from app.services.note_service import NoteService
        svc = NoteService()

        person_id: int | None = None
        if person_name:
            p = self.profile.get_person(person_name)
            if p:
                person_id = p["id"]

        # Notiz speichern
        m = self._NOTE_SAVE_PATTERN.search(captured)
        if m:
            raw = m.group(1).strip().rstrip(".,!?")
            # Titel: erstes Wort / Phrase bis zum Doppelpunkt oder erstem Satzzeichen
            # Inhalt: der Rest (oder alles wenn kein klarer Split)
            if ":" in raw:
                parts = raw.split(":", 1)
                title, content = parts[0].strip(), parts[1].strip()
            elif " ist " in raw.lower():
                idx = raw.lower().index(" ist ")
                title, content = raw[:idx].strip(), raw[idx + 5:].strip()
            else:
                title = raw[:40].rsplit(" ", 1)[0] if len(raw) > 40 else raw
                content = raw
            if title and content:
                svc.create(title=title, content=content, person_id=person_id)
                return f"Notiert: {title} — {content}"
            return None

        # Alle Notizen auflisten
        if self._NOTE_LIST_PATTERN.search(captured):
            notes = svc.list_notes(person_id=person_id)
            if not notes:
                return "Ich habe noch keine Notizen gespeichert."
            lines = [f"• {n['title']}: {n['content']}" for n in notes[:8]]
            return "Meine Notizen: " + ". ".join(lines)

        # Notiz löschen
        m = self._NOTE_DELETE_PATTERN.search(captured)
        if m:
            query = m.group(1).strip()
            hits = svc.search(query, person_id=person_id)
            if not hits:
                return f"Ich habe keine Notiz zu '{query}' gefunden."
            svc.delete(hits[0]["id"])
            return f"Notiz '{hits[0]['title']}' gelöscht."

        # Notiz abfragen
        m = self._NOTE_QUERY_PATTERN.search(captured)
        if m:
            query = next(g for g in m.groups() if g)
            hits = svc.search(query.strip(), person_id=person_id)
            if not hits:
                return None  # kein Treffer → LLM übernimmt
            n = hits[0]
            self._set_notes_display_intent()
            return f"{n['title']}: {n['content']}"

        return None

    _REMINDER_PATTERN = re.compile(
        r"\b(?:erinner[e]?\s+(?:mich|uns)|setz[e]?\s+(?:eine?\s+)?erinnerung|stell[e]?\s+(?:eine?\s+)?erinnerung|leg[e]?\s+(?:eine?\s+)?erinnerung)\b"
        r"|\b(?:ich\s+soll\b.{0,30}nicht\s+vergessen\b)"
        r"|\b(?:vergiss?\s+nicht\b.{0,30}\bin\s+\d)",
        re.IGNORECASE,
    )
    _REMINDER_LIST_PATTERN = re.compile(
        r"\b(?:welche|was\s+für|zeig[e]?\s+(?:mir\s+)?(?:alle\s+)?|alle\s+)erinnerungen?\b"
        r"|\berinnerungen?\s+(?:anzeigen|auflisten|zeigen|habe\s+ich)\b"
        r"|\bhabe\s+ich\s+(?:noch\s+)?erinnerungen?\b",
        re.IGNORECASE,
    )
    _REMINDER_CANCEL_PATTERN = re.compile(
        r"\b(?:lösch[e]?|abbr[eü]ch?|beend[e]?|cancel|stopp?)\s+(?:die\s+|alle\s+)?erinnerung(?:en)?\b"
        r"|\berinnerung(?:en)?\s+(?:lösch[e]?|abbr[eü]ch?|aus|weg|löschen)\b",
        re.IGNORECASE,
    )
    _CLOCK_TIME_RE = re.compile(
        r"\bum\s+(\d{1,2})(?::(\d{2}))?\s*Uhr\b"
        r"|\b(\d{1,2}):(\d{2})\s*(?:Uhr)?\b",
        re.IGNORECASE,
    )

    def _try_reminder_command(self, captured: str, person_name: str | None) -> str | None:
        from app.database.db import get_connection
        # Erinnerungen auflisten
        if self._REMINDER_LIST_PATTERN.search(captured):
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT text, fire_at FROM reminders WHERE dismissed=0 ORDER BY fire_at ASC"
                ).fetchall()
            if not rows:
                return "Du hast keine aktiven Erinnerungen."
            from datetime import datetime, timezone
            parts = []
            for r in rows:
                try:
                    fire = datetime.fromisoformat(r["fire_at"]).astimezone()
                    parts.append(f"{r['text']} um {fire.strftime('%H:%M')} Uhr")
                except Exception:
                    parts.append(r["text"])
            return "Deine Erinnerungen: " + ", ".join(parts) + "."
        # Erinnerungen löschen
        if self._REMINDER_CANCEL_PATTERN.search(captured):
            with get_connection() as conn:
                conn.execute("UPDATE reminders SET dismissed=1 WHERE dismissed=0")
            return "Alle Erinnerungen gelöscht."
        if not self._REMINDER_PATTERN.search(captured):
            return None
        try:
            from datetime import datetime, timezone, timedelta

            # Erinnerungstext extrahieren — alles nach "an" oder "dass"
            text_match = re.search(
                r'\b(?:erinner[e]?\s+mich|erinnerung)\b.{0,40}?\b(?:an|dass)\s+(.+?)(?:\.|,|$)',
                captured, re.IGNORECASE
            )
            reminder_text = text_match.group(1).strip().rstrip('.,!?') if text_match else "Erinnerung"
            if not reminder_text:
                reminder_text = "Erinnerung"

            # Uhrzeitangabe ("um 14:15 Uhr") hat Vorrang vor Dauer
            tm = self._CLOCK_TIME_RE.search(captured)
            if tm:
                hour = int(tm.group(1) if tm.group(1) is not None else tm.group(3))
                minute = int(tm.group(2) if tm.group(2) is not None else (tm.group(4) or 0))
                now_local = datetime.now(timezone.utc).astimezone()
                target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now_local:
                    target += timedelta(days=1)
                fire_at = target.astimezone(timezone.utc).isoformat()
                confirm = f"um {hour:02d}:{minute:02d} Uhr"
            else:
                # Fallback: relative Dauer ("in 30 Minuten")
                m = self._DURATION_RE.search(captured.lower())
                if not m:
                    return None
                raw = m.group(1).lower()
                amount = float(self._WORD_NUMBERS.get(raw, raw.replace(",", ".")))
                unit = m.group(2).lower()
                if unit.startswith("s"):
                    seconds = int(amount)
                elif unit.startswith("m"):
                    seconds = int(amount * 60)
                else:
                    seconds = int(amount * 3600)
                if seconds <= 0 or seconds > 86400:
                    return "Ungültige Dauer für die Erinnerung."
                fire_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
                if seconds < 60:
                    confirm = f"in {seconds} Sekunden"
                elif seconds < 3600:
                    mins = seconds // 60
                    confirm = f"in {mins} Minute{'n' if mins != 1 else ''}"
                else:
                    hours = seconds // 3600
                    confirm = f"in {hours} Stunde{'n' if hours != 1 else ''}"

            from app.database.db import get_connection
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO reminders(text, fire_at, person_name, notified, dismissed, created_at) VALUES (?,?,?,0,0,?)",
                    (reminder_text, fire_at, person_name, datetime.now(timezone.utc).isoformat()),
                )
            return f"Ich erinnere dich {confirm} an: {reminder_text}."
        except Exception:
            return None

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds <= 0:
            return "0 Sekunden"
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        parts = []
        if h:
            parts.append(f"{h} Stunde{'n' if h != 1 else ''}")
        if m:
            parts.append(f"{m} Minute{'n' if m != 1 else ''}")
        if s and not h:
            parts.append(f"{s} Sekunde{'n' if s != 1 else ''}")
        return " und ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " und " + parts[-1]

    def _extract_timer_label(self, text: str) -> str | None:
        m = self._TIMER_LABEL_RE.search(text)
        if not m:
            return None
        candidate = next((g for g in m.groups() if g), None)
        if not candidate:
            return None
        candidate = candidate.strip().rstrip(".,!?")
        if candidate.lower() in self._TIMER_LABEL_BLACKLIST:
            return None
        return candidate.capitalize()

    _TIMER_ORDINALS = {"ersten": 0, "erste": 0, "zweiten": 1, "zweite": 1, "dritten": 2, "dritte": 2}

    def _try_timer_command(self, captured: str) -> str | None:
        try:
            return self._try_timer_command_inner(captured)
        except Exception:
            return None

    def _try_timer_command_inner(self, captured: str) -> str | None:
        q = captured.lower().strip()

        if self._TIMER_LIST_PATTERN.search(q):
            from app.api.routers.timer import get_timer_status
            status = get_timer_status()
            timers = [t for t in (status.get("timers") or []) if not t.get("finished")]
            if not timers:
                return "Es läuft gerade kein Timer."
            if len(timers) == 1:
                t = timers[0]
                return f"Ein Timer läuft: {t.get('label') or 'Timer'}, noch {self._format_duration(int(t.get('remaining_seconds') or 0))}."
            parts = [f"{t.get('label') or 'Timer'} ({self._format_duration(int(t.get('remaining_seconds') or 0))})" for t in timers]
            return f"{len(timers)} Timer laufen: " + ", ".join(parts) + "."

        if self._TIMER_REMAINING_PATTERN.search(q):
            from app.api.routers.timer import get_timer_status
            status = get_timer_status()
            timers = [t for t in (status.get("timers") or []) if not t.get("finished")]
            if not timers:
                return "Es läuft gerade kein Timer."
            label_m = self._TIMER_LABEL_RE.search(captured)
            query_label = next((g for g in label_m.groups() if g), None) if label_m else None
            if query_label:
                ql = query_label.lower()
                match = next((t for t in timers if ql in (t.get("label") or "").lower()), None)
                if not match:
                    return f"Ich habe keinen Timer mit dem Namen '{query_label.capitalize()}' gefunden."
                return f"Beim {match.get('label') or 'Timer'}-Timer noch {self._format_duration(int(match.get('remaining_seconds') or 0))}."
            if len(timers) == 1:
                t = timers[0]
                return f"Beim {t.get('label') or 'Timer'}-Timer noch {self._format_duration(int(t.get('remaining_seconds') or 0))}."
            parts = [f"{t.get('label') or 'Timer'}: noch {self._format_duration(int(t.get('remaining_seconds') or 0))}" for t in timers]
            return "Laufende Timer — " + ", ".join(parts) + "."

        if self._TIMER_RENAME_PATTERN.search(q):
            from app.api.routers.timer import get_timer_status, rename_timer
            status = get_timer_status()
            timers = [t for t in (status.get("timers") or []) if not t.get("finished")]
            if not timers:
                return "Es läuft gerade kein Timer."
            target = None
            for word, idx in self._TIMER_ORDINALS.items():
                if word in q and idx < len(timers):
                    target = timers[idx]
                    break
            if not target and len(timers) == 1:
                target = timers[0]
            if not target:
                label_m = self._TIMER_LABEL_RE.search(captured)
                ql = (next((g for g in label_m.groups() if g), None) or "").lower() if label_m else ""
                if ql:
                    target = next((t for t in timers if ql in (t.get("label") or "").lower()), None)
            if not target:
                return "Ich konnte nicht erkennen welchen Timer du umbenennen möchtest."
            new_name_m = re.search(
                r'\b(?:in|als|auf|heißt?|namen?)\s+([A-Za-zÄÖÜäöüß]{2,}(?:\s+[A-Za-zÄÖÜäöüß]{2,})?)\b',
                captured, re.IGNORECASE,
            )
            if not new_name_m:
                new_name_m = re.search(
                    r'\btimer\b\s*(?:\w+\s*){0,4}([A-Za-zÄÖÜäöüß]{3,})[\s.,!?]*$',
                    captured, re.IGNORECASE,
                )
            if not new_name_m:
                return "Ich konnte den neuen Namen nicht erkennen."
            new_label = new_name_m.group(1).strip().capitalize()
            old_label = target.get("label") or "Timer"
            rename_timer(target["id"], new_label)
            return f"Timer '{old_label}' wurde in '{new_label}' umbenannt."

        if self._TIMER_CANCEL_PATTERN.search(q):
            from app.api.routers.timer import cancel_timer
            cancel_timer()
            return "Timer gestoppt."

        if self._TIMER_DISMISS_PATTERN.match(q):
            from app.api.routers.timer import get_timer_status, dismiss_timer
            status = get_timer_status()
            if any(t.get("finished") for t in status.get("timers", [])):
                dismiss_timer()
                return "Timer quittiert."

        if not self._TIMER_PATTERN.search(q):
            return None
        m = self._DURATION_RE.search(q)
        if not m:
            return None
        raw = m.group(1).lower()
        amount = float(self._WORD_NUMBERS.get(raw, raw.replace(",", ".")))
        unit   = m.group(2).lower()
        if unit.startswith("s"):
            seconds = int(amount)
            duration_label = f"{seconds} Sekunden"
        elif unit.startswith("m") or unit == "min":
            seconds = int(amount * 60)
            duration_label = f"{int(amount)} Minuten" if amount == int(amount) else f"{amount} Minuten"
        else:
            seconds = int(amount * 3600)
            duration_label = f"{int(amount)} Stunde{'n' if amount != 1 else ''}"
        if seconds <= 0 or seconds > 86400:
            return None
        subject = self._extract_timer_label(captured)
        label = subject or duration_label
        from app.api.routers.timer import set_timer
        set_timer({"duration_seconds": seconds, "label": label})
        if subject:
            return f"Timer für {subject} auf {duration_label} gestellt. Ich melde mich wenn die Zeit um ist."
        return f"Timer auf {duration_label} gestellt. Ich melde mich wenn die Zeit um ist."

    _LIGHT_SCHEDULE_PATTERN = re.compile(
        # verb → um Uhr → licht  (z.B. "Schalte um 19 Uhr das Licht ein")
        r"\b(?:schalte?|mach[e]?|stell[e]?|dimm[e]?|dreh[e]?)\b.{0,60}"
        r"\bum\s+\d{1,2}(?::\d{2})?\s*Uhr\b.{0,80}\b(?:licht(?:er)?|lampe[n]?|beleuchtung)\b"
        # verb → licht → um Uhr  (z.B. "Schalte das Licht um 19 Uhr ein")
        r"|\b(?:schalte?|mach[e]?|stell[e]?|dimm[e]?|dreh[e]?)\b.{0,80}"
        r"\b(?:licht(?:er)?|lampe[n]?|beleuchtung)\b.{0,60}\bum\s+\d{1,2}(?::\d{2})?\s*Uhr\b"
        # licht → um Uhr  (ohne explizites Verb, z.B. "Licht im Wohnzimmer um 19 Uhr einschalten")
        r"|\b(?:licht(?:er)?|lampe[n]?|beleuchtung)\b.{0,80}\bum\s+\d{1,2}(?::\d{2})?\s*Uhr\b",
        re.IGNORECASE | re.DOTALL,
    )

    def _try_light_schedule_command(self, captured: str, person_name: str | None) -> str | None:
        """Erkennt zeitgesteuerte Lichtbefehle ('Schalte um 19 Uhr das Licht X auf 50% ein')."""
        if not self._LIGHT_SCHEDULE_PATTERN.search(captured):
            return None
        tm = self._CLOCK_TIME_RE.search(captured)
        if not tm:
            return None
        try:
            from datetime import timedelta
            hour = int(tm.group(1) if tm.group(1) is not None else tm.group(3))
            minute = int(tm.group(2) if tm.group(2) is not None else (tm.group(4) or 0))
            now_local = datetime.now(timezone.utc).astimezone()
            target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now_local:
                target += timedelta(days=1)
            fire_at = target.astimezone(timezone.utc).isoformat()
            # Zeit-Angabe aus dem Befehl entfernen, damit execute_light_command sauber parsen kann
            clean_cmd = re.sub(r'\bum\s+\d{1,2}(?::\d{2})?\s*Uhr\b', '', captured, flags=re.IGNORECASE)
            clean_cmd = re.sub(r'\s{2,}', ' ', clean_cmd).strip()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO reminders(text, fire_at, person_name, light_command, notified, dismissed, created_at) "
                    "VALUES (?,?,?,?,0,0,?)",
                    (
                        f"Lichtbefehl um {hour:02d}:{minute:02d} Uhr",
                        fire_at,
                        person_name,
                        clean_cmd,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            return f"Okay, ich führe den Lichtbefehl um {hour:02d}:{minute:02d} Uhr aus."
        except Exception:
            return None

    def _try_light_command(self, captured: str) -> str | None:
        """Führt Lichtbefehl via HA aus und gibt Bestätigungstext zurück oder None."""
        if not self.LIGHT_COMMAND_PATTERN.search(captured):
            return None
        from app.search.providers.homeassistant import HomeAssistantProvider
        return HomeAssistantProvider().execute_light_command(captured)

    def _set_notes_display_intent(self) -> None:
        from datetime import timedelta
        import json as _json
        expires = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
        try:
            with get_connection() as conn:
                write_state(conn, "display_intent", _json.dumps(
                    {"mode": "notes", "expires_at": expires}
                ))
        except Exception:
            pass

    def _set_lights_display_intent(self) -> None:
        from datetime import timedelta
        import json as _json
        expires = (datetime.now(timezone.utc) + timedelta(seconds=8)).isoformat()
        try:
            with get_connection() as conn:
                write_state(conn, "display_intent", _json.dumps(
                    {"mode": "lights", "expires_at": expires}
                ))
        except Exception:
            pass

    def _store_reply_text(self, text: str, done: bool = True) -> None:
        """Speichert den aktuellen LLM-Reply-Text für das Display-Panel."""
        import re as _re
        from datetime import timedelta

        # Thinking-Blöcke entfernen (Qwen3 / DeepSeek-style)
        clean = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()

        # Denken noch im Gange (kein </think> → nur Thinking-Content) → nichts speichern
        if not clean and not done:
            return
        if "<think>" in text and "</think>" not in text:
            return

        display_text = clean if clean else text
        ttl = 60 if done else 20
        expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        try:
            with get_connection() as conn:
                write_state(conn, "last_reply_text", {"text": display_text, "done": done, "expires_at": expires})
        except Exception:
            pass

    def _update_display_intent(self, search_result: Any, person_name: str | None = None) -> None:
        """Setzt display_intent in system_state nach einer Suchanfrage."""
        import json as _json
        import re as _re
        from datetime import datetime, timedelta, timezone
        if not search_result:
            return
        q = getattr(search_result, "query", "").lower()
        meta = getattr(search_result, "meta", None) or {}
        expires = (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat()
        if any(w in q for w in ("tabellenplatz", "spielergebnis", "gespielt", "tabellenstand",
                                "bundesliga", "hat gewonnen", "hat verloren", "letztes spiel",
                                "wie hat", "wie hatte", "ergebnis", "platz", "punkte",
                                "tabelle")):
            from app.search.providers.football import FootballProvider
            fp = FootballProvider()

            # 1. Team aus Suchergebnis-Meta (direkt vom Search-Provider)
            team_name = meta.get("team_name", "")

            # 2. Fallback: Team-Cache nach Keywords durchsuchen
            if not team_name:
                team_info = fp.detect_team_in_query(q)
                if team_info:
                    team_name = team_info.get("name", "")

            # 3. Kein Team im Query → Lieblingsverein aus Nutzerprofil
            if not team_name and person_name:
                try:
                    facts = self.profile.get_facts(person_name)
                    interests = [f["value"] for f in facts
                                 if f.get("trait_type") == "interest"]
                    for interest in interests:
                        match = fp.detect_team_in_query(interest)
                        if match:
                            team_name = match.get("name", "")
                            break
                except Exception:
                    pass

            # Submode: Spielergebnis vs. Tabelle
            _MATCH_WORDS = {"gespielt", "hat gewonnen", "hat verloren", "letztes spiel",
                            "wie hat", "wie hatte", "ergebnis", "spielergebnis", "tore"}
            is_match = any(w in q for w in _MATCH_WORDS)

            if team_name:
                intent = {"mode": "football", "team": team_name,
                          "submode": "match" if is_match else "table",
                          "expires_at": expires}
            else:
                # Nur Liga — kein Verein bekannt
                league_id, _ = fp._detect_league(q)
                intent = {"mode": "football", "team": None,
                          "submode": "league_table", "league_id": league_id,
                          "expires_at": expires}
        elif any(w in q for w in ("wetter", "temperatur", "regen", "wind", "grad", "schnee", "sonnig")):
            import re as _re
            _future_words = ("morgen", "übermorgen", "montag", "dienstag", "mittwoch",
                             "donnerstag", "freitag", "samstag", "sonntag", "wochenende")
            submode = "tomorrow" if any(w in q for w in _future_words) else "current"
            weather_location = meta.get("resolved_name") or None
            coat_url = meta.get("coat_of_arms_url") or None
            intent = {"mode": "weather_detail", "submode": submode,
                      "location": weather_location, "coat_of_arms_url": coat_url,
                      "expires_at": expires}
        elif meta.get("provider") == "calendar" or any(
            w in q for w in ("termin", "kalender", "verabredung", "geburtstag")
        ) or _re.search(r"\b(ansteh\w+|liegt\s+\w+\s*an|steht\s+\w+\s*an)\b", q):
            focus = meta.get("focus") or (
                "tomorrow" if _re.search(r"\bmorgen\b", q) else
                "week" if _re.search(r"\bwoche\b|\bwochenende\b", q) else
                "today"
            )
            intent = {"mode": "calendar", "focus": focus, "expires_at": expires}
        else:
            return
        with get_connection() as conn:
            write_state(conn, "display_intent", _json.dumps(intent))

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

