from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.db import get_connection


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ConversationService:
    STOPWORDS = {
        # Artikel und Demonstrativpronomen
        "aber", "also", "beim", "dafür", "dann", "dein", "deine", "deinem",
        "deinen", "deiner", "denn", "der", "des", "die", "dir", "doch",
        "ein", "eine", "einem", "einen", "einer", "eines",
        "dieser", "diese", "dieses", "diesem", "diesen",
        "jener", "jene", "jenes", "jenem", "jenen",
        "solche", "solchen", "solcher", "solchem", "solches",
        # Interrogativ- und Relativpronomen
        "welche", "welchen", "welcher", "welches", "welchem",
        "wessen", "woher", "wohin", "womit", "worüber", "wozu",
        "wofür", "worin", "wobei", "wovon", "worauf", "wodurch",
        "wieso", "weshalb", "warum", "wann", "wer", "was", "wie",
        "woran", "worum", "wieviel", "wieviele", "wievieles", "wievielmal",
        # Personalpronomen und Reflexivpronomen
        "sich", "dich", "euch", "ihnen", "ihn", "ihr", "ihre", "ihrem",
        "ihren", "ihrer", "ihres", "mich", "mein", "meine", "meinem",
        "meinen", "meiner", "meines", "uns", "ich",
        # Hilfsverben und häufige Verbformen (alle Personen)
        "habe", "haben", "hast", "hatte", "hatten", "hattest", "hätte", "hätten", "hättest",
        "sein", "sind", "bist", "wäre", "wären", "wärst", "wirst", "wird",
        "wurde", "wurden", "wardst",
        "kann", "kannst", "könnten", "könnte", "konnte", "konnten",
        "soll", "sollte", "sollten", "solltest",
        "darf", "dürfte", "dürften",
        "muss", "müsste", "müssten", "musste",
        "mag", "magst", "möchte", "möchten", "möchtest", "mögen",
        "würde", "würden", "würdest", "werden", "werdet", "werde",
        "will", "wollen", "wollte", "wollten", "wolltest",
        "fragt", "frage", "fragen", "fragst",
        "sagt", "sage", "sagen", "sagst",
        "macht", "mache", "machen", "machst",
        "geht", "gehe", "gehen", "gehst",
        "gibt", "geben", "gibst",
        "weißt", "weiß", "wissen",
        "weißt", "sagst", "kennst", "denkst", "glaubst", "meinst",
        "findest", "siehst", "hörst", "brauchst", "willst", "wollt",
        "kommst", "gehst", "machst", "sagst", "weißt",
        "denke", "denken", "dachte", "dachten", "gedacht",
        "glaube", "glauben", "glaubte", "kenne", "kennen", "kannte",
        "merke", "merken", "merkt", "bemerkt",
        "hoffe", "hoffen", "hofft", "gehört", "gestellt",
        # Zeitwörter — nie Interessen
        "heute", "gestern", "morgen", "jetzt", "dann", "früher",
        "später", "gleich", "bald", "gerade", "damals", "immer",
        "manchmal", "meistens", "selten", "täglich", "wöchentlich",
        # Präpositionen und Adverbien
        "aber", "also", "auch", "außer", "bitte", "dafür", "damit",
        "dort", "doch", "einfach", "erst", "etwas",
        "falls", "für", "gegen", "hier", "indem",
        "irgendwie", "kurz", "lang", "mal", "mehr",
        "nach", "nicht", "nein", "noch", "nun", "obwohl", "oder",
        "ohne", "schon", "sehr", "seit", "sodass", "sofern",
        "über", "und", "unter", "viel", "vielleicht", "weil",
        "wenn", "wieder", "wo", "wohl", "zurück",
        "bereits", "bisher", "dennoch", "jedoch", "trotzdem",
        "außerdem", "ebenfalls", "eigentlich", "natürlich", "übrigens",
        "einmal", "nochmal", "überall", "nirgends", "irgendwo",
        "kein", "keine", "keinem", "keinen", "keiner", "keines",
        "letzten", "letzter", "letztes", "letztem", "letzte",
        "ersten", "erster", "erstes", "erstem", "erste",
        "nächsten", "nächster", "nächstes", "nächstem", "nächste",
        # Verben (Partizip Perfekt & häufige Verbformen) — nie Interessen
        "gespielt", "gemacht", "gesagt", "geworden", "gegeben", "gegangen",
        "gekommen", "gestellt", "gestanden", "gelegen", "gefahren", "geflogen",
        "gesehen", "gehört", "gefunden", "gelesen", "geschrieben", "gedacht",
        "gezeigt", "gehört", "gesucht", "gefragt", "geöffnet", "geschlossen",
        "gestartet", "gestoppt", "geladen", "gesendet", "gespeichert",
        "steht", "stehen", "stand", "stände", "stünde",
        "liegt", "liegen", "läuft", "laufen", "lief",
        "sitzt", "sitzen", "saß", "stellt", "stellt",
        "passiert", "passieren", "existiert", "existieren",
        # Zu generische Einzelnomen — kein sinnvolles Interesse
        "platz", "stelle", "ort", "punkt", "lage", "bereich",
        "fall", "fälle", "schritt", "teil", "teile",
        "art", "weise", "form", "grund", "gründe",
        "tage", "wochen", "monat", "monate", "jahr", "jahre",
        "uhr", "zeit", "stunde", "stunden", "minute", "minuten",
        "zahl", "zahlen", "wert", "werte", "anzahl", "menge",
        "name", "namen", "titel",
        "idee", "ideen", "vorschlag", "vorschläge",
        "beispiel", "beispiele", "ansatz", "ansätze",
        "lösung", "lösungen", "möglichkeit", "möglichkeiten",
        "ergebnis", "ergebnisse", "resultat",
        # Adjektive / Adverbien die keine Interessen sind
        "weitere", "weiteren", "weiterer", "weiteres", "weiterem",
        "aktuell", "aktuelle", "aktuellen", "aktueller", "aktuelles",
        "interessant", "interessante", "interessanten",
        "bestimmte", "bestimmten", "bestimmter",
        "ähnliche", "ähnlichen", "ähnlicher",
        "andere", "anderen", "anderer", "anderes",
        "gleiche", "gleichen", "gleicher",
        "solche", "solchen", "solcher",
        "direkt", "direkte", "direkten",
        "einfach", "einfache", "einfachen",
        "komplex", "komplexe", "komplexen",
        # Partizipien & Adjektive (generisch)
        "geboren", "gestorben", "bekannt", "berühmt", "wichtig",
        "groß", "kleine", "neue", "alten", "letzten", "erste",
        "richtig", "falsch", "möglich", "nötig", "fertig",
        # Testwörter / Meta-Konversation
        "test", "teste", "testen", "probiere", "probier", "ausprobieren",
        "danach", "danke", "okay", "alles", "nochmal", "weisst", "weißt",
        "eigentlich", "genau", "stimmt", "richtig", "falsch", "echt", "wirklich",
        "nochmal", "nochmals", "wieder", "immer", "noch", "schon", "bereits",
        # Erika-spezifisch — System/Roboter-Begriffe sind nie echte Interessen
        "erika", "interessiere",
        "roboter", "system", "backend", "docker", "container", "server",
        "modell", "stimme", "sprache", "ausgabe", "eingabe", "display",
        "bildschirm", "button", "funktion", "feature", "fehler", "problem",
        "version", "update", "code", "daten", "wert", "liste",
        # Smart-Home / Lichtsteuerung (Konfiguration, kein Interesse)
        "licht", "lampe", "lampen", "lichter", "schalter", "gruppe",
        "gruppen", "szene", "automation", "steckdose", "tresenlicht",
        "helligkeit", "dimmer",
        # Web / Suche / Internet (technische Diskussion)
        "internet", "suche", "suchen", "google", "browser", "webseite",
        "seite", "link", "ergebnis", "ergebnisse",
        # Zu generisch — keine sinnvollen Interessen
        "alles", "alle", "viele", "etwas", "ding", "dinge", "sache",
        "sachen", "thema", "themen", "bereich", "punkt", "info", "infos",
        "frage", "antwort", "gerne", "genau", "klar", "bitte",
        # Grüße und Abschiedsformeln
        "guten", "gute", "guter", "gutem", "gutes",
        "morgen", "abend", "nacht", "hallo", "hello",
        "moin", "servus", "ciao", "tschüss", "tschuss",
        "okay", "danke", "super", "prima", "genau",
    }

    # Trifft auf Nachrichten zu, die NUR aus einem Gruß bestehen
    GREETING_ONLY_PATTERN = re.compile(
        r"^\s*(?:"
        r"guten?\s+(?:morgen|tag|abend|nacht)"
        r"|gute\s+nacht"
        r"|hallo(?:\s+zusammen)?"
        r"|hi\b"
        r"|hey\b"
        r"|moin(?:\s+moin)?"
        r"|servus"
        r"|ciao"
        r"|grüß\s+gott"
        r"|grüezi"
        r"|tschüss?"
        r"|tschau"
        r"|auf\s+wiedersehen"
        r"|bis\s+(?:dann|bald|später|morgen|gleich)"
        r")\s*[!.?]*\s*$",
        re.IGNORECASE,
    )

    TOKEN_PATTERN = re.compile(r"[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9._+-]{2,}")
    FOLLOW_UP_PATTERN = re.compile(
        r"\b(nun|noch|mehr|weniger|weiter|danach|ansonsten|außerdem|und dann|davon|wieder|nochmal)\b",
        re.IGNORECASE,
    )
    DIRECT_INTEREST_PATTERN = re.compile(
        r"\bich interessiere mich für\s+(.+)"
        r"|\bmein hobby ist\s+(.+)"
        r"|\bmeine hobbies sind\s+(.+)"
        r"|\bich beschäftige mich gern mit\s+(.+)",
        re.IGNORECASE,
    )
    HOBBY_PATTERN = re.compile(
        r"\b(hobby|hobbies|spiele gern|bastle gern|sammle|gärtnere|koche gern|drucke gern|fotografiere gern)\b",
        re.IGNORECASE,
    )
    SUPPORT_PATTERN = re.compile(
        r"\b(problem|hilfe|fehler|kaputt|reparier|support|störung|geht nicht|funktioniert nicht)\b",
        re.IGNORECASE,
    )

    def is_greeting(self, text: str) -> bool:
        return bool(self.GREETING_ONLY_PATTERN.match(text.strip()))

    def extract_topics(self, text: str) -> list[str]:
        if self.is_greeting(text):
            return []
        seen: set[str] = set()
        topics: list[str] = []
        for token in self.TOKEN_PATTERN.findall(text):
            normalized = token.casefold().strip(".,!?;:")
            if len(normalized) < 4 or normalized in self.STOPWORDS:
                continue
            if normalized not in seen:
                seen.add(normalized)
                topics.append(normalized)
        return topics[:5]

    def is_follow_up(self, text: str) -> bool:
        stripped = " ".join(text.strip().split())
        if not stripped:
            return False
        if len(stripped.split()) <= 4:
            return True
        return bool(self.FOLLOW_UP_PATTERN.search(stripped))

    def record_user_topics(self, person_name: str | None, text: str) -> None:
        topics = self.extract_topics(text)
        if not person_name or not topics:
            return

        topic_kind, score = self.classify_topic_signal(text)
        created_at = now_utc().isoformat()
        with get_connection() as conn:
            for topic in topics:
                conn.execute(
                    """
                    INSERT INTO topic_mentions(person_name, topic, source_role, topic_kind, score, created_at)
                    VALUES (?, ?, 'user', ?, ?, ?)
                    """,
                    (person_name, topic, topic_kind, score, created_at),
                )

    def detect_interest_signal(
        self,
        *,
        person_name: str | None,
        text: str,
        threshold: int,
        window_days: int,
    ) -> dict[str, Any] | None:
        if not person_name:
            return None

        topics = self.extract_topics(text)
        if not topics:
            return None

        cutoff = (now_utc() - timedelta(days=window_days)).isoformat()
        with get_connection() as conn:
            for topic in topics:
                if self._is_known_person_name(conn, topic):
                    continue
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(score), 0) AS total_score
                    FROM topic_mentions
                    WHERE lower(coalesce(person_name, '')) = lower(?)
                      AND topic = ?
                      AND created_at >= ?
                    """,
                    (person_name, topic, cutoff),
                ).fetchone()
                topic_kind, current_score = self.classify_topic_signal(text)
                total_score = float(row["total_score"]) + current_score
                if total_score >= threshold:
                    label = self._format_topic_label(topic)
                    category = "support_signal" if topic_kind == "support" else "interest_signal"
                    summary = (
                        f"{person_name} hat wiederholt Fragen oder Probleme zu '{label}' – wirkt wie ein dauerhaftes Support-Thema."
                        if topic_kind == "support"
                        else f"{person_name} interessiert sich für '{label}' und spricht das Thema regelmäßig an."
                    )
                    return {
                        "subject": person_name,
                        "category": category,
                        "content": summary,
                        "confidence": 0.58 if topic_kind == "support" else 0.74,
                        "reason": "repeated_topic_support" if topic_kind == "support" else "repeated_topic_interest",
                        "topic": topic,
                        "mention_score": round(total_score, 2),
                    }
        return None

    def classify_topic_signal(self, text: str) -> tuple[str, float]:
        if self.is_greeting(text):
            return "greeting", 0.0
        if self.DIRECT_INTEREST_PATTERN.search(text):
            return "direct_interest", 2.0
        if self.HOBBY_PATTERN.search(text):
            return "hobby_interest", 1.35
        if self.SUPPORT_PATTERN.search(text):
            return "support", 0.3
        return "neutral", 1.0

    def select_prompt_messages(
        self,
        *,
        person_name: str | None,
        current_message: str,
        limit: int,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        if limit <= 0:
            return [], {"strategy": "disabled", "focus_topics": []}

        with get_connection() as conn:
            if person_name:
                rows = conn.execute(
                    """
                    SELECT id, role, message
                    FROM conversation_messages
                    WHERE lower(coalesce(person_name, '')) = lower(?)
                    ORDER BY id DESC
                    LIMIT 60
                    """,
                    (person_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, role, message
                    FROM conversation_messages
                    ORDER BY id DESC
                    LIMIT 60
                    """
                ).fetchall()

        items = [dict(row) for row in rows]
        if not items:
            return [], {"strategy": "empty", "focus_topics": self.extract_topics(current_message)}

        focus_topics = self.extract_topics(current_message)
        follow_up = self.is_follow_up(current_message)
        base_recent = min(limit, 8 if follow_up else 6)
        selected_ids = {item["id"] for item in items[:base_recent]}

        if focus_topics:
            for item in items[base_recent:]:
                if len(selected_ids) >= limit:
                    break
                item_topics = set(self.extract_topics(item["message"]))
                if item_topics.intersection(focus_topics):
                    selected_ids.add(item["id"])

        if len(selected_ids) < limit:
            for item in items:
                if len(selected_ids) >= limit:
                    break
                selected_ids.add(item["id"])

        selected = [item for item in reversed(items) if item["id"] in selected_ids and item["role"] in {"user", "assistant"}]
        selected = self._sanitize_prompt_messages(selected)[-limit:]
        return (
            [{"role": item["role"], "content": item["message"]} for item in selected],
            {
                "strategy": "follow_up" if follow_up else "recent_plus_topic",
                "focus_topics": focus_topics,
                "selected_count": len(selected),
            },
        )

    @staticmethod
    def _format_topic_label(topic: str) -> str:
        if "-" in topic or "." in topic or "_" in topic:
            return topic
        return topic.capitalize()

    @staticmethod
    def _is_known_person_name(conn: Any, topic: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM persons WHERE lower(name) = lower(?) LIMIT 1",
            (topic,),
        ).fetchone()
        return bool(row)

    @staticmethod
    def _sanitize_prompt_messages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in items:
            role = item.get("role")
            message = ConversationService._compact_message(item.get("message") or "")
            if role not in {"user", "assistant"} or not message:
                continue
            item = {**item, "message": message}
            if cleaned and cleaned[-1]["role"] == role:
                if role == "user":
                    cleaned[-1] = item
                continue
            cleaned.append(item)
        if cleaned and cleaned[0]["role"] == "assistant":
            cleaned = cleaned[1:]
        return cleaned

    @staticmethod
    def _compact_message(message: str) -> str:
        normalized = re.sub(r"\s+", " ", message).strip()
        if not normalized:
            return ""
        parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]
        unique_parts: list[str] = []
        seen: set[str] = set()
        for part in parts:
            key = part.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique_parts.append(part)
            if len(" ".join(unique_parts)) >= 180:
                break
        compact = " ".join(unique_parts)
        if len(compact) > 180:
            return compact[:177].rstrip() + "..."
        return compact

