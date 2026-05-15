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


def test_decision_engine_extracts_direct_height_statement():
    engine = DecisionEngine()

    result = engine.analyze_chat("Ich bin 1,70 m groß.", "Christin")

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == CandidateKind.PROFILE
    assert candidate.category == "height"
    assert candidate.subject == "Christin"
    assert candidate.content == "Christin ist 1,70 m groß."
    assert candidate.profile_value == "1,70 m"


def test_decision_engine_extracts_reported_self_height_statement_for_other_person():
    engine = DecisionEngine()

    result = engine.analyze_chat("Christin hat gesagt, dass sie 1,70m groß ist.", "Dennis")

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == CandidateKind.PROFILE
    assert candidate.category == "height"
    assert candidate.subject == "Christin"
    assert candidate.content == "Christin ist 1,70 m groß."
    assert candidate.reason == "reported_self_height_statement"


def test_decision_engine_extracts_color_preference_and_eye_color():
    engine = DecisionEngine()

    result = engine.analyze_chat("Ich mag die Farbe blau. Meine Augenfarbe ist grün.", "Dennis")

    assert len(result.candidates) == 2
    assert result.candidates[0].category == "favorite_color"
    assert result.candidates[0].content == "Dennis mag die Farbe blau."
    assert result.candidates[1].category == "eye_color"
    assert result.candidates[1].content == "Dennis hat grün Augen."


def test_decision_engine_extracts_age_job_location_and_family_relation():
    engine = DecisionEngine()

    result = engine.analyze_chat(
        "Ich bin 34 Jahre alt. Ich arbeite als Entwickler. Ich komme aus Hamburg. Ich wohne in Kiel. Meine Schwester heißt Anna.",
        "Dennis",
    )

    categories = [candidate.category for candidate in result.candidates]
    assert categories == ["age", "occupation", "hometown", "residence", "family_relation"]
    assert result.candidates[0].content == "Dennis ist 34 Jahre alt."
    assert result.candidates[1].content == "Dennis arbeitet als Entwickler."
    assert result.candidates[2].content == "Dennis kommt aus Hamburg."
    assert result.candidates[3].content == "Dennis wohnt in Kiel."
    assert result.candidates[4].content == "Dennis' schwester heißt Anna."


def test_decision_engine_extracts_language_food_drink_pet_and_relationship():
    engine = DecisionEngine()

    result = engine.analyze_chat(
        "Ich spreche Deutsch. Mein Lieblingsessen ist Pizza. Mein Lieblingsgetränk ist Tee. Mein Hund heißt Bruno. Anna ist meine Freundin.",
        "Dennis",
    )

    categories = [candidate.category for candidate in result.candidates]
    assert categories == ["language", "favorite_food", "favorite_drink", "pet", "person_relationship"]
    assert result.candidates[0].content == "Dennis spricht Deutsch."
    assert result.candidates[1].content == "Dennis isst am liebsten Pizza."
    assert result.candidates[2].content == "Dennis trinkt am liebsten Tee."
    assert result.candidates[3].content == "Dennis hat einen hund namens Bruno."
    assert result.candidates[4].content == "Anna ist Dennis' freundin."


def test_decision_engine_extracts_response_preferences():
    engine = DecisionEngine()

    result = engine.analyze_chat(
        "Ich mag es sachlich. Sei ruhig witziger. Antworte bitte kürzer.",
        "Dennis",
    )

    categories = [candidate.category for candidate in result.candidates]
    assert categories == [
        "response_style_preference",
        "response_humor_preference",
        "response_length_preference",
    ]
    values = {candidate.category: candidate.profile_value for candidate in result.candidates}
    assert values["response_style_preference"] == "sachlich"
    assert values["response_humor_preference"] == "higher"
    assert values["response_length_preference"] == "short"
