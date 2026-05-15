from __future__ import annotations

from typing import Any


class PromptBuilder:
    def build_chat_payload(
        self,
        *,
        message: str,
        person_name: str | None,
        personality: dict[str, Any],
        approved_memories: list[str],
        recent_messages: list[dict[str, str]],
        runtime_facts: dict[str, Any],
        response_style: str,
        explain_only_on_request: bool,
        person_preference_lines: list[str] | None = None,
    ) -> dict[str, Any]:
        context = self._build_context(
            person_name=person_name,
            personality=personality,
            approved_memories=approved_memories,
            recent_messages=recent_messages,
            runtime_facts=runtime_facts,
            response_style=response_style,
            explain_only_on_request=explain_only_on_request,
            person_preference_lines=person_preference_lines or [],
        )
        system_prompt = self._build_system_prompt(context=context)
        return {
            "system_prompt": system_prompt,
            "messages": [
                {"role": "system", "content": system_prompt},
                *recent_messages,
                {"role": "user", "content": message},
            ],
            "context": context,
            "message": message,
            "person_name": person_name,
            "personality": personality,
            "approved_memories": approved_memories,
            "response_style": response_style,
            "explain_only_on_request": explain_only_on_request,
            "person_preference_lines": person_preference_lines or [],
        }

    @staticmethod
    def _build_context(
        *,
        person_name: str | None,
        personality: dict[str, Any],
        approved_memories: list[str],
        recent_messages: list[dict[str, str]],
        runtime_facts: dict[str, Any],
        response_style: str,
        explain_only_on_request: bool,
        person_preference_lines: list[str],
    ) -> dict[str, Any]:
        return {
            "known_person": person_name or "unbekannt",
            "response_style": response_style,
            "explain_rule": (
                "Erkläre nur dann ausführlicher, wenn der Nutzer ausdrücklich danach fragt."
                if explain_only_on_request
                else "Kurze Erklärungen sind erlaubt, wenn sie konkret helfen."
            ),
            "approved_memories": approved_memories or ["Keine freigegebenen Erinnerungen vorhanden."],
            "recent_messages": recent_messages,
            "runtime_facts": runtime_facts,
            "history_strategy": "topic_weighted_recent_context",
            "person_preference_lines": person_preference_lines,
            "personality_lines": [
                f"- friendliness: {personality['friendliness']:.2f}",
                f"- humor: {personality['humor']:.2f}",
                f"- curiosity: {personality['curiosity']:.2f}",
                f"- talkativeness: {personality['talkativeness']:.2f}",
                f"- caution: {personality['caution']:.2f}",
                f"- directness: {personality['directness']:.2f}",
                f"- sarcasm: {personality['sarcasm']:.2f}",
                f"- patience: {personality['patience']:.2f}",
            ],
        }

    @staticmethod
    def _build_system_prompt(*, context: dict[str, Any]) -> str:
        personality_block = "; ".join(line[2:] for line in context["personality_lines"])
        memory_block = " | ".join(context["approved_memories"])
        preference_block = " ".join(context["person_preference_lines"]).strip()
        runtime_block = (
            f"battery={context['runtime_facts']['battery_level']}%, "
            f"display={context['runtime_facts']['display_status']}, "
            f"device={context['runtime_facts']['device_state']}"
        )
        preference_sentence = f"{preference_block} " if preference_block else ""
        return (
            "Du bist Erika, ein sozialer KI-Roboter im lokalen Haushalt oder Standort. "
            "Du sprichst als physisches Gerät, nicht als abstrakter Online-Chatbot. "
            f"Antworte standardmäßig auf Deutsch, {context['response_style']}. "
            f"{context['explain_rule']} "
            "Keine Hardware direkt steuern. Keine Wahrnehmungen oder Fakten erfinden. "
            "Wenn Informationen fehlen, frage kurz und konkret nach. "
            f"Aktuell erkannte oder adressierte Person: {context['known_person']}. "
            f"{preference_sentence}"
            "Nutze den ausgewählten Gesprächsverlauf für Anschlussfragen und offene Aufgaben. "
            f"Live-Gerätestatus: {runtime_block}. "
            "Wenn der Nutzer nach Akkustand, Display-Status oder Gerätezustand fragt, nutze diese Werte direkt. "
            f"Persönlichkeit: {personality_block}. "
            f"Freigegebene Erinnerungen: {memory_block}. "
            "Nutze Erinnerungen nur, wenn sie für die aktuelle Antwort wirklich relevant sind. "
            "Kein Markdown und keine Listen, wenn ein kurzer Fließtext reicht. "
            "Antworte kurz: meist 1 bis 3 Sätze. Keine Wiederholungen. Keine unnötigen Emojis, Witze oder Meta-Erklärungen."
        )
