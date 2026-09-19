from app.conversation.service import ConversationService
from app.database.db import get_connection
from app.services.memory_service import MemoryService


def test_ensure_todays_daily_summary_merges_singular_and_plural_topics(temp_db):
    """Regression: 'Katze'/'Katzen' erschienen bisher als zwei getrennte
    Einträge im Tagesrückblick statt einem gemeinsamen."""
    conversation = ConversationService()
    conversation.record_user_topics("Nela", "Ich habe eine Katze.")
    conversation.record_user_topics("Nela", "Meine Katzen sind süß.")

    MemoryService().ensure_todays_daily_summary("Nela")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT topics FROM daily_summaries WHERE person_name='Nela' "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()

    assert row is not None
    topics = [t.strip() for t in row["topics"].split(",")]
    katzen_variants = [t for t in topics if t.lower() in {"katze", "katzen"}]
    assert len(katzen_variants) == 1


def test_refresh_active_topics_merges_singular_and_plural_topics(temp_db):
    conversation = ConversationService()
    conversation.record_user_topics("Nela", "Ich habe eine Katze.")
    conversation.record_user_topics("Nela", "Meine Katzen sind süß.")
    conversation.record_user_topics("Nela", "Katzen schlafen viel.")

    MemoryService().refresh_active_topics("Nela")

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT title, mentions FROM active_topics WHERE person_name='Nela'"
        ).fetchall()

    katzen_rows = [dict(r) for r in rows if r["title"].lower() in {"katze", "katzen"}]
    assert len(katzen_rows) == 1
    assert katzen_rows[0]["mentions"] == 3


def test_group_topics_by_stem_keeps_first_seen_label_as_representative():
    rows = [
        {"topic": "Katze", "topic_stem": "katz", "score": 1.0, "created_at": "2026-01-01T00:00:00"},
        {"topic": "Katzen", "topic_stem": "katz", "score": 1.0, "created_at": "2026-01-01T00:00:01"},
        {"topic": "Hund", "topic_stem": "hund", "score": 1.0, "created_at": "2026-01-01T00:00:02"},
    ]

    grouped = MemoryService._group_topics_by_stem(rows)

    assert set(grouped.keys()) == {"katz", "hund"}
    assert grouped["katz"]["label"] == "Katze"
    assert grouped["katz"]["count"] == 2
    assert grouped["katz"]["total_score"] == 2.0
    assert grouped["hund"]["label"] == "Hund"
