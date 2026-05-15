from app.conversation.service import ConversationService


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
