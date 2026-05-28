import importlib

from fastapi.testclient import TestClient


def test_chat_preview_returns_system_prompt_and_messages(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/chat/preview",
            json={"message": "Hallo", "person_name": "Dennis"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][1] == {"role": "user", "content": "Hallo"}
        assert data["context"]["known_person"] == "Dennis"


def test_chat_response_includes_llm_context(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/chat",
            json={"message": "Hallo, ich heiße Dennis", "person_name": "Dennis"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "llm_context" in data
        assert data["llm_context"]["messages"][0]["role"] == "system"
        assert data["llm_context"]["messages"][1]["content"] == "Hallo, ich heiße Dennis"


def test_chat_stream_returns_sse_events(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/chat/stream",
            json={"message": "Hallo, ich heiße Dennis", "person_name": "Dennis"},
        )
        assert response.status_code == 200
        assert "event: delta" in response.text
        assert "event: done" in response.text


def test_chat_answers_battery_question_from_core(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        battery = client.post("/simulate/battery", json={"level": 88})
        assert battery.status_code == 200

        response = client.post(
            "/chat",
            json={"message": "Wie viel Prozent hat dein Akku?", "person_name": "Dennis"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["llm_provider"] == "core"
        assert data["reply"] == "Mein Akkustand liegt gerade bei 88 %."


def test_chat_answers_update_question_from_core(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        device = client.patch(
            "/device",
            json={
                "device_name": "Erika",
                "site_label": "Mein Haushalt",
                "device_state": "updating",
                "network_connected": True,
                "server_connected": True,
                "update_status": "idle",
            },
        )
        assert device.status_code == 200

        response = client.post(
            "/chat",
            json={"message": "Hast du ein Update ausstehend?", "person_name": "Dennis"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["llm_provider"] == "core"
        assert "Nein, aktuell läuft alles normal." in data["reply"]


def test_status_marks_active_known_person_for_chat_context(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        propose = client.post(
            "/memory/propose",
            json={
                "content": "Der Nutzer heißt Dennis.",
                "category": "person_profile",
                "subject": "Dennis",
                "source": "test",
            },
        )
        assert propose.status_code == 200
        memory_id = propose.json()["memory"]["id"]
        approved = client.post(f"/memory/approve/{memory_id}")
        assert approved.status_code == 200

        response = client.post(
            "/chat",
            json={"message": "Hallo", "person_name": "Dennis"},
        )
        assert response.status_code == 200
        status = response.json()["status"]
        assert status["active_person_name"] == "Dennis"
        assert status["known_person_detected"] is True


def test_chat_preview_includes_recent_conversation_history(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        first = client.post(
            "/chat",
            json={"message": "Nenne mir vier Zahlen.", "person_name": "Dennis"},
        )
        assert first.status_code == 200

        preview = client.post(
            "/chat/preview",
            json={"message": "nun 2 mehr", "person_name": "Dennis"},
        )
        assert preview.status_code == 200
        data = preview.json()
        assert data["messages"][1]["role"] == "user"
        assert data["messages"][1]["content"] == "Nenne mir vier Zahlen."
        assert data["messages"][2]["role"] == "assistant"
        assert data["context"]["selection"]["selected_count"] >= 2


def test_chat_preview_omits_irrelevant_memories_without_query_overlap(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        for content in [
            "Dennis mag die Farbe blau.",
            "Dennis ist 34 Jahre alt.",
        ]:
            proposed = client.post(
                "/memory/propose",
                json={"content": content, "category": "recherche", "subject": "Dennis", "source": "test"},
            )
            assert proposed.status_code == 200
            memory_id = proposed.json()["memory"]["id"]
            approved = client.post(f"/memory/approve/{memory_id}")
            assert approved.status_code == 200

        preview = client.post(
            "/chat/preview",
            json={"message": "Was soll ich heute Abend machen?", "person_name": "Dennis"},
        )
        assert preview.status_code == 200
        assert preview.json()["approved_memories"] == []


def test_chat_preview_sanitizes_recent_messages_for_prompt(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        client.post("/chat", json={"message": "Hallo", "person_name": "Dennis"})
        client.post("/chat", json={"message": "Noch einmal hallo", "person_name": "Dennis"})
        preview = client.post(
            "/chat/preview",
            json={"message": "Was nun?", "person_name": "Dennis"},
        )
        assert preview.status_code == 200
        roles = [item["role"] for item in preview.json()["context"]["recent_messages"]]
        assert roles
        assert roles[0] == "user"
        assert all(a != b for a, b in zip(roles, roles[1:]))


def test_memory_propose_reclassifies_third_person_statement(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/memory/propose",
            json={
                "content": "Christin mag Brot mit Quark und Gurke.",
                "category": "general",
                "subject": "Dennis",
                "source": "web_ui",
            },
        )
        assert response.status_code == 200
        memory = response.json()["memory"]
        assert memory["subject"] == "Christin"
        assert memory["category"] == "preference"
        assert memory["candidate_kind"] == "memory"


def test_repeated_topic_creates_interest_signal_memory(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        for message in [
            "Ich habe eine Frage zu Anycubic.",
            "Kannst du mir bei Anycubic helfen?",
            "Noch eine Frage zu Anycubic.",
        ]:
            response = client.post("/chat", json={"message": message, "person_name": "Dennis"})
            assert response.status_code == 200

        pending = client.get("/memory?status=pending")
        assert pending.status_code == 200
        items = pending.json()["items"]
        assert any(item["category"] == "interest_signal" and item["subject"] == "Dennis" for item in items)


def test_conversation_endpoint_returns_recent_messages(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        first = client.post("/chat", json={"message": "Hallo Erika", "person_name": "Dennis"})
        assert first.status_code == 200
        second = client.post("/chat", json={"message": "Wie geht es dir?", "person_name": "Dennis"})
        assert second.status_code == 200

        conversation = client.get("/conversation?person_name=Dennis&limit=10")
        assert conversation.status_code == 200
        items = conversation.json()["items"]
        assert len(items) >= 4
        assert items[0]["role"] == "user"
        assert items[0]["message"] == "Hallo Erika"


def test_chat_answers_person_knowledge_from_core(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        proposed = client.post(
            "/memory/propose",
            json={
                "content": "Christin mag Brot mit Quark und Gurke.",
                "category": "general",
                "subject": "Dennis",
                "source": "web_ui",
            },
        )
        assert proposed.status_code == 200
        memory_id = proposed.json()["memory"]["id"]
        approved = client.post(f"/memory/approve/{memory_id}")
        assert approved.status_code == 200

        response = client.post(
            "/chat",
            json={"message": "Was weißt du über Christin?", "person_name": "Dennis"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["llm_provider"] == "core"
        assert "noch kein bestätigtes Profilwissen" in data["reply"]
        assert "Christin mag Brot mit Quark und Gurke." in data["reply"]
