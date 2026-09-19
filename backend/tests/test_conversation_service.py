from app.conversation.service import ConversationService
from app.database.db import get_connection


def test_single_question_does_not_create_interest_signal(temp_db):
    service = ConversationService()

    signal = service.detect_interest_signal(
        person_name="Dennis",
        text="Wie repariere ich einen Gartenschlauch?",
        threshold=3,
        window_days=14,
    )

    assert signal is None


def test_repeated_topic_creates_interest_signal(temp_db):
    service = ConversationService()

    service.record_user_topics("Dennis", "Ich habe eine Frage zu Anycubic.")
    service.record_user_topics("Dennis", "Kannst du mir bei Anycubic helfen?")

    signal = service.detect_interest_signal(
        person_name="Dennis",
        text="Noch eine Frage zu Anycubic.",
        threshold=3,
        window_days=14,
    )

    assert signal is not None
    assert signal["category"] == "interest_signal"
    assert signal["subject"] == "Dennis"
    assert "Anycubic" in signal["content"]


def test_support_topics_are_weighted_more_cautiously(temp_db):
    service = ConversationService()

    for text in [
        "Ich habe ein Problem mit dem Gartenschlauch.",
        "Der Gartenschlauch ist kaputt.",
        "Ich brauche Hilfe mit dem Gartenschlauch.",
    ]:
        service.record_user_topics("Dennis", text)

    signal = service.detect_interest_signal(
        person_name="Dennis",
        text="Der Gartenschlauch funktioniert nicht.",
        threshold=3,
        window_days=14,
    )

    assert signal is None


def test_knowledge_questions_without_self_reference_are_not_tracked(temp_db):
    """Regression: 'Wie hoch ist der Mount Everest?' o.ä. landete bisher als
    'aktives Thema'/'Interesse' von Dennis, obwohl es eine allgemeine
    Wissensfrage ohne jeden Selbstbezug ist."""
    service = ConversationService()

    for text in [
        "Wie hoch ist der Mount Everest?",
        "Wer ist der amtierende Bundeskanzler?",
        "Was ist die Hauptstadt von Kasachstan?",
    ]:
        service.record_user_topics("Dennis", text)

    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) c FROM topic_mentions WHERE person_name='Dennis'"
        ).fetchone()["c"]
    assert count == 0


def test_knowledge_question_with_self_reference_is_still_tracked(temp_db):
    """'Wie repariere ich meinen Gartenschlauch?' ist trotz W-Frage eine
    persönliche Aussage (Selbstbezug 'ich'/'meinen') und muss weiter erfasst
    werden."""
    service = ConversationService()
    service.record_user_topics("Dennis", "Wie repariere ich meinen Gartenschlauch?")

    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) c FROM topic_mentions WHERE person_name='Dennis'"
        ).fetchone()["c"]
    assert count > 0


def test_repeated_knowledge_questions_do_not_create_interest_signal(temp_db):
    service = ConversationService()
    for text in [
        "Wie hoch ist der Mount Everest?",
        "Wie hoch ist der K2?",
        "Wie hoch ist die Zugspitze?",
    ]:
        service.record_user_topics("Dennis", text)

    signal = service.detect_interest_signal(
        person_name="Dennis",
        text="Wie hoch ist der Mont Blanc?",
        threshold=1,
        window_days=14,
    )
    assert signal is None


def test_singular_and_plural_topic_forms_merge_for_interest_signal(temp_db):
    """Regression: 'Katze' und 'Katzen' wurden bisher als zwei getrennte
    Themen gezählt, wodurch der Schwellwert nie gemeinsam erreicht wurde."""
    service = ConversationService()
    service.record_user_topics("Nela", "Ich habe eine Katze.")
    service.record_user_topics("Nela", "Meine Katzen sind süß.")

    signal = service.detect_interest_signal(
        person_name="Nela",
        text="Ich liebe Katzen so sehr.",
        threshold=3,
        window_days=14,
    )

    assert signal is not None
    assert signal["subject"] == "Nela"
