from app.brain.prompt_builder import PromptBuilder


def test_prompt_builder_creates_system_message_with_identity_and_memories():
    builder = PromptBuilder()

    payload = builder.build_chat_payload(
        message="Hallo",
        person_name="Dennis",
        personality={
            "friendliness": 0.9,
            "humor": 0.65,
            "curiosity": 0.75,
            "talkativeness": 0.45,
            "caution": 0.8,
            "directness": 0.7,
            "sarcasm": 0.15,
            "patience": 0.85,
        },
        approved_memories=["Dennis mag Kaffee.", "Dennis mag Jazz."],
        recent_messages=[
            {"role": "user", "content": "Nenne mir vier Zahlen."},
            {"role": "assistant", "content": "1, 2, 3, 4"},
        ],
        runtime_facts={
            "battery_level": 88,
            "display_status": "ready",
            "device_state": "ready",
        },
        response_style="kurz, freundlich und präzise",
        explain_only_on_request=True,
        person_preference_lines=["Diese Person bevorzugt einen sachlichen, nüchternen Ton."],
    )

    assert payload["messages"][0]["role"] == "system"
    assert "Du bist Erika, ein sozialer KI-Roboter im lokalen Haushalt oder Standort." in payload["system_prompt"]
    assert "Aktuell erkannte oder adressierte Person: Dennis." in payload["system_prompt"]
    assert "battery=88%" in payload["system_prompt"]
    assert "Dennis mag Kaffee." in payload["system_prompt"]
    assert "Diese Person bevorzugt einen sachlichen, nüchternen Ton." in payload["system_prompt"]
    assert payload["context"]["known_person"] == "Dennis"
    assert payload["messages"][1] == {"role": "user", "content": "Nenne mir vier Zahlen."}
    assert payload["messages"][2] == {"role": "assistant", "content": "1, 2, 3, 4"}
    assert payload["messages"][3] == {"role": "user", "content": "Hallo"}


_PERSONALITY = {
    "friendliness": 0.5, "humor": 0.5, "curiosity": 0.5, "talkativeness": 0.5,
    "caution": 0.5, "directness": 0.5, "sarcasm": 0.5, "patience": 0.5,
}
_RUNTIME_FACTS = {"battery_level": 100, "display_status": "ready", "device_state": "ready"}


def test_search_marker_instruction_present_without_search_context():
    """Ohne bereits vorliegendes Recherche-Ergebnis darf das LLM Unsicherheit
    signalisieren (SUCHE:-Marker) — Grundlage für die reaktive Websuche."""
    payload = PromptBuilder().build_chat_payload(
        message="Nenne mir die Hauptstadt von Kasachstan.",
        person_name="Dennis",
        personality=_PERSONALITY,
        approved_memories=[],
        recent_messages=[],
        runtime_facts=_RUNTIME_FACTS,
        response_style="kurz",
        explain_only_on_request=True,
    )
    assert "SUCHE:" in payload["system_prompt"]


def test_search_marker_instruction_absent_with_search_context():
    """Sobald ein Recherche-Ergebnis vorliegt (zweiter, bereits gegroundeter
    Aufruf), darf die Anweisung NICHT mehr auftauchen — sonst Endlos-Schleife."""
    payload = PromptBuilder().build_chat_payload(
        message="Nenne mir die Hauptstadt von Kasachstan.",
        person_name="Dennis",
        personality=_PERSONALITY,
        approved_memories=[],
        recent_messages=[],
        runtime_facts=_RUNTIME_FACTS,
        response_style="kurz",
        explain_only_on_request=True,
        search_context="[Wikipedia]: Astana ist die Hauptstadt von Kasachstan.",
    )
    assert "SUCHE:" not in payload["system_prompt"]
