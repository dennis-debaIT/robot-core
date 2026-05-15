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
        search_context: str | None = None,
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
            search_context=search_context,
        )
        system_prompt = self._build_system_prompt(context=context)

        # Suchergebnis direkt in die User-Message injizieren — höchste LLM-Aufmerksamkeit
        if search_context:
            user_content = (
                f"[Aktuelles Recherche-Ergebnis — verwende ausschließlich diese Information "
                f"für dieses Thema, dein Trainingswissen kann veraltet sein]:\n"
                f"{search_context}\n\n"
                f"Meine Frage: {message}"
            )
        else:
            user_content = message

        # Bei Mathe-Anfragen Sprachpflicht in die User-Message injizieren (Qwen antwortet sonst auf Chinesisch)
        import re as _re
        if _re.search(
            r"\d+\s*[+\-*/^×÷]\s*\d+|wieviel|wie viel|rechne|berechne|ergebnis|"
            r"\bmal\b|\bdurch\b|\bplus\b|\bminus\b|wurzel|prozent|potenz|\bist \d|\bsind \d",
            user_content, _re.IGNORECASE
        ):
            user_content = f"Antworte auf Deutsch: {user_content}"

        return {
            "system_prompt": system_prompt,
            "messages": [
                {"role": "system", "content": system_prompt},
                *recent_messages,
                {"role": "user", "content": user_content},
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
        search_context: str | None = None,
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
            "search_context": search_context,
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
        search_sentence = (
            f"Aktuelle Recherche: {context['search_context']} "
            if context.get("search_context")
            else ""
        )
        return (
            "Du bist Erika, ein sozialer KI-Roboter im lokalen Haushalt oder Standort. "
            "Du sprichst als physisches Gerät, nicht als abstrakter Online-Chatbot. "
            "WICHTIG: Antworte AUSNAHMSLOS auf Deutsch — egal ob die Frage auf Englisch, Chinesisch oder einer anderen Sprache gestellt wird. Niemals auf Chinesisch, Englisch oder einer anderen Sprache antworten. "
            f"Antworte {context['response_style']}. "
            f"{context['explain_rule']} "
            "Keine Hardware direkt steuern. Keine Wahrnehmungen oder Fakten erfinden. "
            "Für aktuelle Ereignisse, Sportergebnisse oder Tabellenstände: "
            "Nutze ausschließlich bereitgestellte Recherche-Ergebnisse. "
            "Wenn keine Recherche vorliegt, gib offen zu dass du keine aktuellen Daten hast. "
            "Erfinde niemals Tabellenstände, Spielergebnisse oder aktuelle Fakten. "
            f"Aktuell erkannte oder adressierte Person: {context['known_person']}. "
            "Die gespeicherten Erinnerungen beschreiben Wissen und Vorlieben der Person, mit der du sprichst — nicht deine eigenen. "
            "Wenn du nach deinen eigenen Eigenschaften, Interessen oder Vorlieben als Roboter gefragt wirst, antworte aus deiner Rolle als Erika, nicht aus den Erinnerungen der anderen Person. "
            "Wenn du Erinnerungen über die adressierte Person verwendest, sprich sie direkt an: 'du magst', 'dein Interesse', nie 'Dennis mag' oder 'er mag'. "
            f"{preference_sentence}"
            "Nutze den ausgewählten Gesprächsverlauf für Anschlussfragen und offene Aufgaben. "
            f"Live-Gerätestatus: {runtime_block}. "
            "Wenn der Nutzer nach Akkustand, Display-Status oder Gerätezustand fragt, nutze diese Werte direkt. "
            f"Persönlichkeit: {personality_block}. "
            f"Bekannte Fakten über diese Person (nur bei direkter Relevanz verwenden): {memory_block}. "
            "WICHTIGE REGEL – Erinnerungen: Verwende diese Fakten AUSSCHLIESSLICH wenn der Nutzer "
            "direkt nach eigenen Vorlieben fragt (z. B. 'Was esse ich gerne?', 'Was mag ich?'). "
            "Bei allen anderen Fragen – Termine, Feiertage, Wetter, Sport, Geschichte, Ratschläge – "
            "diese Fakten KOMPLETT ignorieren und NICHT erwähnen. "
            "Verboten: Essen, Farben oder Hobbys als Reaktion auf Termine oder Feiertage einbauen. "
            f"{search_sentence}"
            "Du kannst anbieten Wetter oder Kalender nachzuschlagen – der Nutzer muss dann nur 'ja' sagen. "
            "Wenn keine Recherche-Ergebnisse vorliegen: kurz und ehrlich antworten, nichts erfinden. "
            "Kein Markdown und keine Listen, wenn ein kurzer Fließtext reicht. "
            "Antworte kurz: meist 1 bis 3 Sätze. Keine Wiederholungen. Keine unnötigen Emojis, Witze oder Meta-Erklärungen. "
            "SPRACHPFLICHT — ABSOLUT: Antworte auf JEDE Frage — Mathe, Rechnen, Zahlen, Fakten — AUSSCHLIESSLICH auf Deutsch. "
            "Beispiel: Frage 'Was ist 12 mal 12?' → korrekte Antwort: '12 mal 12 ist 144.' "
            "Niemals chinesische Zeichen verwenden. Niemals auf Englisch antworten."
        )
