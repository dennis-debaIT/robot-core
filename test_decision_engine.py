from app.brain.decision_engine import CandidateKind, DecisionEngine


def test_decision_engine_extracts_profile_candidates():
    engine = DecisionEngine()

    result = engine.analyze_chat("Ich heiße Dennis und ich mag Kaffee.", "Dennis")

    assert result.should_respond is True
    assert result.response_reason == "chat_message"
    assert len(result.candidates) == 2
    assert result.candidates[0].kind == CandidateKind.PROFILE
    assert result.candidates[0].content == "Der Nutzer heißt Dennis."
    assert result.candidates[0].profile_value == "Dennis"
    assert result.candidates[1].content == "Dennis mag Kaffee."
    assert result.candidates[1].profile_value == "Kaffee"


def test_decision_engine_ignores_plain_greeting_for_memory_candidates():
    engine = DecisionEngine()

    result = engine.analyze_chat("Hallo zusammen", None)

    assert result.should_respond is True
    assert result.candidates == []


def test_decision_engine_classifies_negated_preference_as_dislike():
    engine = DecisionEngine()

    result = engine.analyze_chat("Ich mag keine Blutwurst.", "Dennis")

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == CandidateKind.PROFILE
    assert candidate.category == "dislike"
    assert candidate.content == "Dennis mag Blutwurst nicht."
    assert candidate.profile_value == "Blutwurst"


def test_decision_engine_extracts_third_person_preference_for_new_person():
    engine = DecisionEngine()

    result = engine.analyze_chat("Anna mag Kaffee.", None)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.subject == "Anna"
    assert candidate.category == "preference"
    assert candidate.kind == CandidateKind.MEMORY
    assert candidate.content == "Anna mag Kaffee."


def test_decision_engine_uses_explicit_person_name_for_new_person_preferences():
    engine = DecisionEngine()

    result = engine.analyze_chat("Ich liebe Lasagne.", "Mira")

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.subject == "Mira"
    assert candidate.category == "preference"
    assert candidate.content == "Mira mag Lasagne."


def test_decision_engine_extracts_explicit_interest_statement():
    engine = DecisionEngine()

    result = engine.analyze_chat("Ich interessiere mich für 3D-Druck.", "Dennis")

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == CandidateKind.PROFILE
    assert candidate.category == "interest"
    assert candidate.subject == "Dennis"
    assert candidate.content == "Dennis interessiert sich für 3D-Druck."
