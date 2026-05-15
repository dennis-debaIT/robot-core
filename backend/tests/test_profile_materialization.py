import importlib

from fastapi.testclient import TestClient


def test_profile_candidate_is_materialized_on_approval(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={"message": "Ich heiße Dennis. Ich mag Kaffee. Ich interessiere mich für 3D-Druck.", "person_name": "Dennis"},
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert len(payload["proposed_memories"]) == 3

        for item in payload["proposed_memories"]:
            approve = client.post(f"/memory/approve/{item['id']}")
            assert approve.status_code == 200
            assert approve.json()["materialization"]["action"] == "profile_fact"

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        items = profiles.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Dennis"
        assert {fact["trait_type"] for fact in items[0]["facts"]} == {"person_profile", "preference", "interest"}
        facts_by_type = {fact["trait_type"]: fact["value"] for fact in items[0]["facts"]}
        assert facts_by_type["person_profile"] == "Dennis"
        assert facts_by_type["preference"] == "Kaffee"
        assert facts_by_type["interest"] == "3D-Druck"


def test_rejecting_approved_profile_memory_removes_profile_fact(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={"message": "Ich mag Lasagne.", "person_name": "Dennis"},
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert len(payload["proposed_memories"]) == 1

        memory_id = payload["proposed_memories"][0]["id"]

        approve = client.post(f"/memory/approve/{memory_id}")
        assert approve.status_code == 200
        assert approve.json()["profile_update"]["name"] == "Dennis"

        profiles_before = client.get("/profiles")
        assert profiles_before.status_code == 200
        assert profiles_before.json()["items"][0]["facts"][0]["value"] == "Lasagne"

        reject = client.post(f"/memory/reject/{memory_id}")
        assert reject.status_code == 200
        assert reject.json()["profile_update"]["facts"] == []

        profiles_after = client.get("/profiles")
        assert profiles_after.status_code == 200
        assert profiles_after.json()["items"][0]["facts"] == []


def test_negated_preference_is_materialized_as_dislike(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={"message": "Ich mag keine Blutwurst.", "person_name": "Dennis"},
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert len(payload["proposed_memories"]) == 1
        assert payload["proposed_memories"][0]["category"] == "dislike"
        assert payload["proposed_memories"][0]["content"] == "Dennis mag Blutwurst nicht."

        memory_id = payload["proposed_memories"][0]["id"]
        approve = client.post(f"/memory/approve/{memory_id}")
        assert approve.status_code == 200

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        facts = profiles.json()["items"][0]["facts"]
        assert facts[0]["trait_type"] == "dislike"
        assert facts[0]["value"] == "Blutwurst"


def test_deleting_person_removes_profile_memories_and_messages(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={"message": "Ich heiße Dennis. Ich mag Kaffee.", "person_name": "Dennis"},
        )
        assert chat.status_code == 200
        memory_ids = [item["id"] for item in chat.json()["proposed_memories"]]

        for memory_id in memory_ids:
            approve = client.post(f"/memory/approve/{memory_id}")
            assert approve.status_code == 200

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        person_id = profiles.json()["items"][0]["id"]

        deleted = client.delete(f"/profiles/{person_id}")
        assert deleted.status_code == 200
        payload = deleted.json()
        assert payload["deleted_person"]["name"] == "Dennis"
        assert payload["deleted_memory_count"] == 2
        assert payload["deleted_message_count"] == 2

        profiles_after = client.get("/profiles")
        assert profiles_after.status_code == 200
        assert profiles_after.json()["items"] == []

        memories_after = client.get("/memory?status=approved")
        assert memories_after.status_code == 200
        assert memories_after.json()["items"] == []


def test_approving_third_person_memory_creates_person_without_profile_facts(temp_db):
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
        assert memory["candidate_kind"] == "memory"

        approve = client.post(f"/memory/approve/{memory['id']}")
        assert approve.status_code == 200
        profile_update = approve.json()["profile_update"]
        assert approve.json()["materialization"]["action"] == "person_stub"
        assert profile_update["name"] == "Christin"
        assert profile_update["facts"] == []

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        items = profiles.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Christin"
        assert items[0]["facts"] == []


def test_reported_height_statement_is_materialized_as_profile_fact(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={"message": "Christin hat gesagt, dass sie 1,70m groß ist.", "person_name": "Dennis"},
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert len(payload["proposed_memories"]) == 1
        memory = payload["proposed_memories"][0]
        assert memory["subject"] == "Christin"
        assert memory["category"] == "height"
        assert memory["candidate_kind"] == "profile"

        approve = client.post(f"/memory/approve/{memory['id']}")
        assert approve.status_code == 200
        assert approve.json()["materialization"]["action"] == "profile_fact"

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        items = {item["name"]: item for item in profiles.json()["items"]}
        assert items["Christin"]["facts"][0]["trait_type"] == "height"
        assert items["Christin"]["facts"][0]["value"] == "1,70 m"


def test_multiple_stable_profile_traits_are_materialized(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={
                "message": (
                    "Ich mag die Farbe blau. "
                    "Meine Augenfarbe ist grün. "
                    "Ich bin 34 Jahre alt. "
                    "Ich arbeite als Entwickler. "
                    "Ich komme aus Hamburg. "
                    "Ich wohne in Kiel. "
                    "Meine Schwester heißt Anna."
                ),
                "person_name": "Dennis",
            },
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert len(payload["proposed_memories"]) == 7

        for item in payload["proposed_memories"]:
            approve = client.post(f"/memory/approve/{item['id']}")
            assert approve.status_code == 200

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        person = profiles.json()["items"][0]
        facts = {fact["trait_type"]: fact["value"] for fact in person["facts"]}
        assert facts["favorite_color"] == "blau"
        assert facts["eye_color"] == "grün"
        assert facts["age"] == "34"
        assert facts["occupation"] == "Entwickler"
        assert facts["hometown"] == "Hamburg"
        assert facts["residence"] == "Kiel"
        assert facts["family_relation"] == "schwester:Anna"


def test_language_food_drink_pet_and_relationship_are_materialized(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={
                "message": (
                    "Ich spreche Deutsch. "
                    "Mein Lieblingsessen ist Pizza. "
                    "Mein Lieblingsgetränk ist Tee. "
                    "Mein Hund heißt Bruno. "
                    "Anna ist meine Freundin."
                ),
                "person_name": "Dennis",
            },
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert len(payload["proposed_memories"]) == 5

        for item in payload["proposed_memories"]:
            approve = client.post(f"/memory/approve/{item['id']}")
            assert approve.status_code == 200

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        person = next(item for item in profiles.json()["items"] if item["name"] == "Dennis")
        facts = {fact["trait_type"]: fact["value"] for fact in person["facts"]}
        assert facts["language"] == "Deutsch"
        assert facts["favorite_food"] == "Pizza"
        assert facts["favorite_drink"] == "Tee"
        assert facts["pet"] == "hund:Bruno"
        assert facts["person_relationship"] == "freundin:Anna"


def test_response_preferences_are_proposed_and_materialized(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={
                "message": "Ich mag es sachlich. Sei ruhig witziger. Antworte bitte kürzer.",
                "person_name": "Dennis",
            },
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert len(payload["proposed_memories"]) == 3

        for item in payload["proposed_memories"]:
            approve = client.post(f"/memory/approve/{item['id']}")
            assert approve.status_code == 200
            assert approve.json()["materialization"]["action"] == "profile_fact"

        profiles = client.get("/profiles")
        person = next(item for item in profiles.json()["items"] if item["name"] == "Dennis")
        facts = {fact["trait_type"]: fact["value"] for fact in person["facts"]}
        assert facts["response_style_preference"] == "sachlich"
        assert facts["response_humor_preference"] == "higher"
        assert facts["response_length_preference"] == "short"


def test_profile_conflict_replaces_previous_single_value_and_reports_conflict(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        first = client.post(
            "/chat",
            json={"message": "Ich wohne in Kiel.", "person_name": "Dennis"},
        ).json()["proposed_memories"][0]
        client.post(f"/memory/approve/{first['id']}")

        second = client.post(
            "/chat",
            json={"message": "Ich wohne in Hamburg.", "person_name": "Dennis"},
        ).json()["proposed_memories"][0]
        approve = client.post(f"/memory/approve/{second['id']}")
        assert approve.status_code == 200
        assert approve.json()["conflict"]["type"] == "single_value_replaced"

        profiles = client.get("/profiles")
        person = next(item for item in profiles.json()["items"] if item["name"] == "Dennis")
        facts = {fact["trait_type"]: fact["value"] for fact in person["facts"]}
        assert facts["residence"] == "Hamburg"
