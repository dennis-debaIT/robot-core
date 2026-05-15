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
