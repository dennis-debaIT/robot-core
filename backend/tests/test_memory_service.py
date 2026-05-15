from app.brain.decision_engine import DecisionEngine
from app.memory.service import MemoryService


def test_propose_deduplicates_pending_and_approved(temp_db):
    service = MemoryService()

    first = service.propose(
        content="Der Nutzer heißt Dennis.",
        category="person_profile",
        subject="Dennis",
        source="chat_auto",
        dedupe_statuses=("pending", "approved"),
    )
    second = service.propose(
        content="Der Nutzer heißt Dennis.",
        category="person_profile",
        subject="Dennis",
        source="chat_auto",
        dedupe_statuses=("pending", "approved"),
    )

    assert first["id"] == second["id"]
    assert len(service.list_memories("pending")) == 1

    approved = service.approve(first["id"])
    third = service.propose(
        content="Der Nutzer heißt Dennis.",
        category="person_profile",
        subject="Dennis",
        source="chat_auto",
        dedupe_statuses=("pending", "approved"),
    )

    assert approved["status"] == "approved"
    assert third["id"] == first["id"]
    assert service.list_memories("pending") == []


def test_extract_proposals_from_chat_creates_name_and_preference_once(temp_db):
    service = MemoryService()
    engine = DecisionEngine()

    first_candidates = engine.analyze_chat("Ich heiße Anna. Ich mag Kaffee.", "Anna").candidates
    repeated_candidates = engine.analyze_chat("Ich heisse Anna. Ich mag Kaffee.", "Anna").candidates

    for candidate in first_candidates:
        service.propose(
            content=candidate.content,
            category=candidate.category,
            subject=candidate.subject,
            source="chat_auto",
            dedupe_statuses=("pending", "approved"),
        )
    for candidate in repeated_candidates:
        service.propose(
            content=candidate.content,
            category=candidate.category,
            subject=candidate.subject,
            source="chat_auto",
            dedupe_statuses=("pending", "approved"),
        )

    all_pending = service.list_memories("pending")
    assert len(all_pending) == 2
    assert {item["category"] for item in all_pending} == {"person_profile", "preference"}
