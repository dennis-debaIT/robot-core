from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum


class CandidateKind(StrEnum):
    MEMORY = "memory"
    PROFILE = "profile"


@dataclass
class CandidateDecision:
    kind: CandidateKind
    category: str
    subject: str | None
    content: str
    profile_value: str | None
    reason: str
    confidence: float
    requires_approval: bool = True

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return payload


@dataclass
class ChatDecisionResult:
    should_respond: bool
    response_reason: str
    candidates: list[CandidateDecision]

    def to_dict(self) -> dict[str, object]:
        return {
            "should_respond": self.should_respond,
            "response_reason": self.response_reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class DecisionEngine:
    PERSON_TOKEN = r"(?!ich\b|du\b|er\b|sie\b|es\b|wir\b|ihr\b|man\b|mein\b|meine\b|meiner\b|meinem\b|meinen\b)([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]*)"
    NAME_PATTERN = re.compile(
        r"\b(?:ich hei(?:ss|ß)e|mein name ist)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]*)",
        re.IGNORECASE,
    )
    LIKE_PATTERN = re.compile(r"\b(?:ich mag|ich liebe)\s+(.+?)(?:[.!?]|$)", re.IGNORECASE)
    RESPONSE_STYLE_PREFERENCE_PATTERN = re.compile(
        r"\b(?:ich mag es|ich hätte es gern|bitte)\s+(sachlich|locker|nüchtern|direkt)(?:e?r?)?\b"
        r"|\bsei(?:\s+ruhig)?\s+(sachlicher|lockerer|nüchterner|direkter)\b",
        re.IGNORECASE,
    )
    RESPONSE_HUMOR_PREFERENCE_PATTERN = re.compile(
        r"\b(?:sei(?:\s+ruhig)?|antworte)\s+(?:gern\s+)?(witziger|ernster)\b"
        r"|\bich mag\s+(witzige|humorvolle|ernste)\s+antworten\b",
        re.IGNORECASE,
    )
    RESPONSE_LENGTH_PREFERENCE_PATTERN = re.compile(
        r"\b(?:antworte|sei)\b.*?\b(kürzer|kurz|ausführlicher|detaillierter)\b"
        r"|\bich mag\s+(kurze|knappe|ausführliche|detaillierte)\s+antworten\b",
        re.IGNORECASE,
    )
    INTEREST_PATTERN = re.compile(
        r"\bich interessiere mich für\s+(.+?)(?:[.!?]|$)"
        r"|\bmein hobby ist\s+(.+?)(?:[.!?]|$)"
        r"|\bmeine hobbies sind\s+(.+?)(?:[.!?]|$)"
        r"|\bich beschäftige mich gern mit\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    HEIGHT_PATTERN = re.compile(
        r"\bich bin\s+(\d(?:[.,]\d{1,2})?)\s*(?:m|meter)\s+gro(?:ß|ss)\b",
        re.IGNORECASE,
    )
    AGE_PATTERN = re.compile(
        r"\bich bin\s+(\d{1,3})\s+jahre?\s+alt\b",
        re.IGNORECASE,
    )
    COLOR_PREFERENCE_PATTERN = re.compile(
        r"\bich mag\s+die farbe\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)"
        r"|\b([A-Za-zÄÖÜäöüß-]+)\s+ist\s+toll(?:[.!?]|$)"
        r"|\bmeine lieblingsfarbe ist\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    LANGUAGE_PATTERN = re.compile(
        r"\bich spreche\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)"
        r"|\bmeine sprache ist\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    FAVORITE_FOOD_PATTERN = re.compile(
        r"\bmein lieblingsessen ist\s+(.+?)(?:[.!?]|$)"
        r"|\bich esse am liebsten\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    FAVORITE_DRINK_PATTERN = re.compile(
        r"\bmein lieblingsgetränk ist\s+(.+?)(?:[.!?]|$)"
        r"|\bich trinke am liebsten\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    EYE_COLOR_PATTERN = re.compile(
        r"\bmeine augenfarbe ist\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)"
        r"|\bich habe\s+([A-Za-zÄÖÜäöüß-]+)\s+augen(?:[.!?]|$)",
        re.IGNORECASE,
    )
    JOB_PATTERN = re.compile(
        r"\bich arbeite als\s+([A-Za-zÄÖÜäöüß0-9 /_-]+?)(?:[.!?]|$)"
        r"|\bich bin von beruf\s+([A-Za-zÄÖÜäöüß0-9 /_-]+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    HOMETOWN_PATTERN = re.compile(
        r"\bich komme aus\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .-]+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    RESIDENCE_PATTERN = re.compile(
        r"\bich wohne in\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .-]+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    FAMILY_SELF_PATTERN = re.compile(
        r"\bmein(?:e|)\s+(mutter|vater|schwester|bruder|tochter|sohn|frau|mann|partnerin|partner)\s+hei(?:ß|ss)t\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    PET_PATTERN = re.compile(
        r"\bich habe\s+ein(?:en|e)?\s+(hund|katze|kater|hamster|kaninchen|papagei|vogel|fisch)\b"
        r"|\bmein(?:e|)\s+(hund|katze|kater|hamster|kaninchen|papagei|vogel|fisch)\s+hei(?:ß|ss)t\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    RELATIONSHIP_TO_PERSON_PATTERN = re.compile(
        r"\b([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)\s+ist\s+mein(?:e|)\s+(freundin|freund|partnerin|partner|kollegin|kollege|nachbarin|nachbar)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    DISLIKE_PATTERN = re.compile(
        r"\bich mag\s+keine[nrms]?\s+(.+?)(?:[.!?]|$)"
        r"|\bich mag\s+(.+?)\s+nicht(?:[.!?]|$)"
        r"|\bich hasse\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_HEIGHT_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+(\d(?:[.,]\d{{1,2}})?)\s*(?:m|meter)\s+gro(?:ß|ss)\s+ist\b",
        re.IGNORECASE,
    )
    REPORTED_AGE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+(\d{{1,3}})\s+jahre?\s+alt\s+ist\b",
        re.IGNORECASE,
    )
    REPORTED_COLOR_PREFERENCE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+die farbe\s+([A-Za-zÄÖÜäöüß-]+)\s+mag(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+([A-Za-zÄÖÜäöüß-]+)\s+toll\s+findet(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:seine|ihre)\s+lieblingsfarbe\s+([A-Za-zÄÖÜäöüß-]+)\s+ist(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_LANGUAGE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+([A-Za-zÄÖÜäöüß-]+)\s+spricht(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_FAVORITE_FOOD_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:sein|ihr)\s+lieblingsessen\s+(.+?)\s+ist(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_FAVORITE_DRINK_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:sein|ihr)\s+lieblingsgetränk\s+(.+?)\s+ist(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_EYE_COLOR_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:seine|ihre)\s+augenfarbe\s+([A-Za-zÄÖÜäöüß-]+)\s+ist(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+([A-Za-zÄÖÜäöüß-]+)\s+augen\s+hat(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_JOB_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+als\s+([A-Za-zÄÖÜäöüß0-9 /_-]+?)\s+arbeitet(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+von beruf\s+([A-Za-zÄÖÜäöüß0-9 /_-]+?)\s+ist(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_HOMETOWN_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+aus\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .-]+?)\s+kommt(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_RESIDENCE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+in\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .-]+?)\s+wohnt(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_FAMILY_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:seine|ihre)\s+(mutter|vater|schwester|bruder|tochter|sohn|frau|mann|partnerin|partner)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)\s+hei(?:ß|ss)t(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_PET_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:er|sie)\s+ein(?:en|e)?\s+(hund|katze|kater|hamster|kaninchen|papagei|vogel|fisch)\s+hat(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+(?:sein|ihr)\s+(hund|katze|kater|hamster|kaninchen|papagei|vogel|fisch)\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)\s+hei(?:ß|ss)t(?:[.!?]|$)",
        re.IGNORECASE,
    )
    REPORTED_RELATIONSHIP_TO_PERSON_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+gesagt,?\s+dass\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)\s+(?:sein|ihr)\s+(freundin|freund|partnerin|partner|kollegin|kollege|nachbarin|nachbar)\s+ist(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_HEIGHT_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+ist\s+(\d(?:[.,]\d{{1,2}})?)\s*(?:m|meter)\s+gro(?:ß|ss)\b",
        re.IGNORECASE,
    )
    THIRD_PERSON_AGE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+ist\s+(\d{{1,3}})\s+jahre?\s+alt\b",
        re.IGNORECASE,
    )
    THIRD_PERSON_COLOR_PREFERENCE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+mag\s+die farbe\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+findet\s+([A-Za-zÄÖÜäöüß-]+)\s+toll(?:[.!?]|$)"
        rf"|\b(?:die lieblingsfarbe von\s+{PERSON_TOKEN}\s+ist|{PERSON_TOKEN}\s+lieblingsfarbe ist)\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_LANGUAGE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+spricht\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_FAVORITE_FOOD_PATTERN = re.compile(
        rf"\b(?:das lieblingsessen von\s+{PERSON_TOKEN}\s+ist|{PERSON_TOKEN}\s+lieblingsessen ist)\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_FAVORITE_DRINK_PATTERN = re.compile(
        rf"\b(?:das lieblingsgetränk von\s+{PERSON_TOKEN}\s+ist|{PERSON_TOKEN}\s+lieblingsgetränk ist)\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_EYE_COLOR_PATTERN = re.compile(
        rf"\b(?:die augenfarbe von\s+{PERSON_TOKEN}\s+ist|{PERSON_TOKEN}\s+augenfarbe ist)\s+([A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+hat\s+([A-Za-zÄÖÜäöüß-]+)\s+augen(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_JOB_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+arbeitet\s+als\s+([A-Za-zÄÖÜäöüß0-9 /_-]+?)(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+ist\s+von beruf\s+([A-Za-zÄÖÜäöüß0-9 /_-]+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_HOMETOWN_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+kommt\s+aus\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .-]+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_RESIDENCE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+wohnt\s+in\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .-]+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_FAMILY_PATTERN = re.compile(
        rf"\b(?:die|der)\s+(mutter|vater|schwester|bruder|tochter|sohn|frau|mann|partnerin|partner)\s+von\s+{PERSON_TOKEN}\s+hei(?:ß|ss)t\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+(?:mutter|vater|schwester|bruder|tochter|sohn|frau|mann|partnerin|partner)\s+hei(?:ß|ss)t\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_PET_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+hat\s+ein(?:en|e)?\s+(hund|katze|kater|hamster|kaninchen|papagei|vogel|fisch)(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+(hund|katze|kater|hamster|kaninchen|papagei|vogel|fisch)\s+hei(?:ß|ss)t\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_RELATIONSHIP_TO_PERSON_PATTERN = re.compile(
        rf"\b([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]+)\s+ist\s+(?:der|die)\s+(freundin|freund|partnerin|partner|kollegin|kollege|nachbarin|nachbar)\s+von\s+{PERSON_TOKEN}(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_LIKE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+(?:mag|liebt)\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )
    THIRD_PERSON_DISLIKE_PATTERN = re.compile(
        rf"\b{PERSON_TOKEN}\s+mag\s+keine[nrms]?\s+(.+?)(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+mag\s+(.+?)\s+nicht(?:[.!?]|$)"
        rf"|\b{PERSON_TOKEN}\s+hasst\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    )

    def analyze_chat(self, message: str, person_name: str | None = None) -> ChatDecisionResult:
        normalized = message.strip()
        candidates: list[CandidateDecision] = []

        if not normalized:
            return ChatDecisionResult(
                should_respond=False,
                response_reason="empty_message",
                candidates=[],
            )

        extracted_name = None
        name_match = self.NAME_PATTERN.search(normalized)
        if name_match:
            extracted_name = name_match.group(1).strip()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="person_profile",
                    subject=extracted_name,
                    content=f"Der Nutzer heißt {extracted_name}.",
                    profile_value=extracted_name,
                    reason="explicit_self_identification",
                    confidence=0.98,
                )
            )

        subject = person_name or extracted_name or "unknown_user"

        style_preference_match = self.RESPONSE_STYLE_PREFERENCE_PATTERN.search(normalized)
        if style_preference_match:
            style_token = next(group for group in style_preference_match.groups() if group).strip().casefold()
            style_value = self._normalize_style_preference(style_token)
            if style_value:
                candidates.append(
                    CandidateDecision(
                        kind=CandidateKind.PROFILE,
                        category="response_style_preference",
                        subject=subject,
                        content=f"{subject} bevorzugt einen {style_value}en Antwortstil.",
                        profile_value=style_value,
                        reason="explicit_response_style_preference",
                        confidence=0.9,
                    )
                )

        humor_preference_match = self.RESPONSE_HUMOR_PREFERENCE_PATTERN.search(normalized)
        if humor_preference_match:
            humor_token = next(group for group in humor_preference_match.groups() if group).strip().casefold()
            humor_value = self._normalize_humor_preference(humor_token)
            if humor_value:
                wording = "eher humorvolle Antworten" if humor_value == "higher" else "eher nüchterne Antworten"
                candidates.append(
                    CandidateDecision(
                        kind=CandidateKind.PROFILE,
                        category="response_humor_preference",
                        subject=subject,
                        content=f"{subject} mag {wording}.",
                        profile_value=humor_value,
                        reason="explicit_response_humor_preference",
                        confidence=0.9,
                    )
                )

        length_preference_match = self.RESPONSE_LENGTH_PREFERENCE_PATTERN.search(normalized)
        if length_preference_match:
            length_token = next(group for group in length_preference_match.groups() if group).strip().casefold()
            length_value = self._normalize_length_preference(length_token)
            if length_value:
                wording = "eher kurze Antworten" if length_value == "short" else "auch ausführlichere Antworten"
                candidates.append(
                    CandidateDecision(
                        kind=CandidateKind.PROFILE,
                        category="response_length_preference",
                        subject=subject,
                        content=f"{subject} mag {wording}.",
                        profile_value=length_value,
                        reason="explicit_response_length_preference",
                        confidence=0.89,
                    )
                )

        height_match = self.HEIGHT_PATTERN.search(normalized)
        if height_match:
            height_value = self._normalize_height(height_match.group(1))
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="height",
                    subject=subject,
                    content=f"{subject} ist {height_value} groß.",
                    profile_value=height_value,
                    reason="explicit_height_statement",
                    confidence=0.96,
                )
            )
        age_match = self.AGE_PATTERN.search(normalized)
        if age_match:
            age_value = age_match.group(1).strip()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="age",
                    subject=subject,
                    content=f"{subject} ist {age_value} Jahre alt.",
                    profile_value=age_value,
                    reason="explicit_age_statement",
                    confidence=0.95,
                )
            )

        color_preference_match = self.COLOR_PREFERENCE_PATTERN.search(normalized)
        if color_preference_match:
            color_value = next(group for group in color_preference_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_color",
                    subject=subject,
                    content=f"{subject} mag die Farbe {color_value}.",
                    profile_value=color_value,
                    reason="explicit_color_preference_statement",
                    confidence=0.93,
                )
            )

        language_match = self.LANGUAGE_PATTERN.search(normalized)
        if language_match:
            language_value = next(group for group in language_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="language",
                    subject=subject,
                    content=f"{subject} spricht {language_value}.",
                    profile_value=language_value,
                    reason="explicit_language_statement",
                    confidence=0.92,
                )
            )

        favorite_food_match = self.FAVORITE_FOOD_PATTERN.search(normalized)
        if favorite_food_match:
            food_value = next(group for group in favorite_food_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_food",
                    subject=subject,
                    content=f"{subject} isst am liebsten {food_value}.",
                    profile_value=food_value,
                    reason="explicit_favorite_food_statement",
                    confidence=0.92,
                )
            )

        favorite_drink_match = self.FAVORITE_DRINK_PATTERN.search(normalized)
        if favorite_drink_match:
            drink_value = next(group for group in favorite_drink_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_drink",
                    subject=subject,
                    content=f"{subject} trinkt am liebsten {drink_value}.",
                    profile_value=drink_value,
                    reason="explicit_favorite_drink_statement",
                    confidence=0.92,
                )
            )

        eye_color_match = self.EYE_COLOR_PATTERN.search(normalized)
        if eye_color_match:
            color_value = next(group for group in eye_color_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="eye_color",
                    subject=subject,
                    content=f"{subject} hat {color_value} Augen.",
                    profile_value=color_value,
                    reason="explicit_eye_color_statement",
                    confidence=0.95,
                )
            )
        job_match = self.JOB_PATTERN.search(normalized)
        if job_match:
            job_value = next(group for group in job_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="occupation",
                    subject=subject,
                    content=f"{subject} arbeitet als {job_value}.",
                    profile_value=job_value,
                    reason="explicit_job_statement",
                    confidence=0.92,
                )
            )
        hometown_match = self.HOMETOWN_PATTERN.search(normalized)
        if hometown_match:
            place = hometown_match.group(1).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="hometown",
                    subject=subject,
                    content=f"{subject} kommt aus {place}.",
                    profile_value=place,
                    reason="explicit_hometown_statement",
                    confidence=0.92,
                )
            )
        residence_match = self.RESIDENCE_PATTERN.search(normalized)
        if residence_match:
            place = residence_match.group(1).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="residence",
                    subject=subject,
                    content=f"{subject} wohnt in {place}.",
                    profile_value=place,
                    reason="explicit_residence_statement",
                    confidence=0.92,
                )
            )
        family_match = self.FAMILY_SELF_PATTERN.search(normalized)
        if family_match:
            relation = family_match.group(1).strip().lower()
            relation_name = family_match.group(2).strip()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="family_relation",
                    subject=subject,
                    content=f"{self._possessive_form(subject)} {relation} heißt {relation_name}.",
                    profile_value=f"{relation}:{relation_name}",
                    reason="explicit_family_relation_statement",
                    confidence=0.91,
                )
            )
        pet_match = self.PET_PATTERN.search(normalized)
        if pet_match:
            if pet_match.group(1):
                pet_type = pet_match.group(1).strip().lower()
                pet_value = pet_type
                content = f"{subject} hat einen {pet_type}."
            else:
                pet_type = pet_match.group(2).strip().lower()
                pet_name = pet_match.group(3).strip()
                pet_value = f"{pet_type}:{pet_name}"
                content = f"{subject} hat einen {pet_type} namens {pet_name}."
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="pet",
                    subject=subject,
                    content=content,
                    profile_value=pet_value,
                    reason="explicit_pet_statement",
                    confidence=0.9,
                )
            )
        relationship_match = self.RELATIONSHIP_TO_PERSON_PATTERN.search(normalized)
        if relationship_match:
            other_person = relationship_match.group(1).strip()
            relation = relationship_match.group(2).strip().lower()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="person_relationship",
                    subject=subject,
                    content=f"{other_person} ist {self._possessive_form(subject)} {relation}.",
                    profile_value=f"{relation}:{other_person}",
                    reason="explicit_person_relationship_statement",
                    confidence=0.9,
                )
            )

        interest_match = self.INTEREST_PATTERN.search(normalized)
        if interest_match:
            interest_value = next(group for group in interest_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="interest",
                    subject=subject,
                    content=f"{subject} interessiert sich für {interest_value}.",
                    profile_value=interest_value,
                    reason="explicit_interest_statement",
                    confidence=0.95,
                )
            )

        reported_height_match = self.REPORTED_HEIGHT_PATTERN.search(normalized)
        if reported_height_match:
            matched_subject = reported_height_match.group(1).strip()
            height_value = self._normalize_height(reported_height_match.group(2))
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="height",
                    subject=matched_subject,
                    content=f"{matched_subject} ist {height_value} groß.",
                    profile_value=height_value,
                    reason="reported_self_height_statement",
                    confidence=0.86,
                )
            )
        reported_age_match = self.REPORTED_AGE_PATTERN.search(normalized)
        if reported_age_match:
            matched_subject = reported_age_match.group(1).strip()
            age_value = reported_age_match.group(2).strip()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="age",
                    subject=matched_subject,
                    content=f"{matched_subject} ist {age_value} Jahre alt.",
                    profile_value=age_value,
                    reason="reported_self_age_statement",
                    confidence=0.84,
                )
            )

        reported_color_match = self.REPORTED_COLOR_PREFERENCE_PATTERN.search(normalized)
        if reported_color_match:
            groups = reported_color_match.groups()
            matched_subject = next(groups[index] for index in (0, 2, 4) if groups[index]).strip()
            color_value = next(groups[index] for index in (1, 3, 5) if groups[index]).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_color",
                    subject=matched_subject,
                    content=f"{matched_subject} mag die Farbe {color_value}.",
                    profile_value=color_value,
                    reason="reported_self_color_preference_statement",
                    confidence=0.84,
                )
            )
        reported_language_match = self.REPORTED_LANGUAGE_PATTERN.search(normalized)
        if reported_language_match:
            matched_subject = reported_language_match.group(1).strip()
            language_value = reported_language_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="language",
                    subject=matched_subject,
                    content=f"{matched_subject} spricht {language_value}.",
                    profile_value=language_value,
                    reason="reported_self_language_statement",
                    confidence=0.83,
                )
            )
        reported_food_match = self.REPORTED_FAVORITE_FOOD_PATTERN.search(normalized)
        if reported_food_match:
            matched_subject = reported_food_match.group(1).strip()
            food_value = reported_food_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_food",
                    subject=matched_subject,
                    content=f"{matched_subject} isst am liebsten {food_value}.",
                    profile_value=food_value,
                    reason="reported_self_favorite_food_statement",
                    confidence=0.82,
                )
            )
        reported_drink_match = self.REPORTED_FAVORITE_DRINK_PATTERN.search(normalized)
        if reported_drink_match:
            matched_subject = reported_drink_match.group(1).strip()
            drink_value = reported_drink_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_drink",
                    subject=matched_subject,
                    content=f"{matched_subject} trinkt am liebsten {drink_value}.",
                    profile_value=drink_value,
                    reason="reported_self_favorite_drink_statement",
                    confidence=0.82,
                )
            )

        reported_eye_color_match = self.REPORTED_EYE_COLOR_PATTERN.search(normalized)
        if reported_eye_color_match:
            groups = reported_eye_color_match.groups()
            matched_subject = next(groups[index] for index in (0, 2) if groups[index]).strip()
            color_value = next(groups[index] for index in (1, 3) if groups[index]).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="eye_color",
                    subject=matched_subject,
                    content=f"{matched_subject} hat {color_value} Augen.",
                    profile_value=color_value,
                    reason="reported_self_eye_color_statement",
                    confidence=0.86,
                )
            )
        reported_job_match = self.REPORTED_JOB_PATTERN.search(normalized)
        if reported_job_match:
            groups = reported_job_match.groups()
            matched_subject = next(groups[index] for index in (0, 2) if groups[index]).strip()
            job_value = next(groups[index] for index in (1, 3) if groups[index]).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="occupation",
                    subject=matched_subject,
                    content=f"{matched_subject} arbeitet als {job_value}.",
                    profile_value=job_value,
                    reason="reported_self_job_statement",
                    confidence=0.83,
                )
            )
        reported_hometown_match = self.REPORTED_HOMETOWN_PATTERN.search(normalized)
        if reported_hometown_match:
            matched_subject = reported_hometown_match.group(1).strip()
            place = reported_hometown_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="hometown",
                    subject=matched_subject,
                    content=f"{matched_subject} kommt aus {place}.",
                    profile_value=place,
                    reason="reported_self_hometown_statement",
                    confidence=0.83,
                )
            )
        reported_residence_match = self.REPORTED_RESIDENCE_PATTERN.search(normalized)
        if reported_residence_match:
            matched_subject = reported_residence_match.group(1).strip()
            place = reported_residence_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="residence",
                    subject=matched_subject,
                    content=f"{matched_subject} wohnt in {place}.",
                    profile_value=place,
                    reason="reported_self_residence_statement",
                    confidence=0.83,
                )
            )
        reported_family_match = self.REPORTED_FAMILY_PATTERN.search(normalized)
        if reported_family_match:
            matched_subject = reported_family_match.group(1).strip()
            relation = reported_family_match.group(2).strip().lower()
            relation_name = reported_family_match.group(3).strip()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="family_relation",
                    subject=matched_subject,
                    content=f"{self._possessive_form(matched_subject)} {relation} heißt {relation_name}.",
                    profile_value=f"{relation}:{relation_name}",
                    reason="reported_self_family_relation_statement",
                    confidence=0.82,
                )
            )
        reported_pet_match = self.REPORTED_PET_PATTERN.search(normalized)
        if reported_pet_match:
            groups = reported_pet_match.groups()
            matched_subject = next(groups[index] for index in (0, 2) if groups[index]).strip()
            if groups[1]:
                pet_type = groups[1].strip().lower()
                pet_value = pet_type
                content = f"{matched_subject} hat einen {pet_type}."
            else:
                pet_type = groups[3].strip().lower()
                pet_name = groups[4].strip()
                pet_value = f"{pet_type}:{pet_name}"
                content = f"{matched_subject} hat einen {pet_type} namens {pet_name}."
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="pet",
                    subject=matched_subject,
                    content=content,
                    profile_value=pet_value,
                    reason="reported_self_pet_statement",
                    confidence=0.81,
                )
            )
        reported_relationship_match = self.REPORTED_RELATIONSHIP_TO_PERSON_PATTERN.search(normalized)
        if reported_relationship_match:
            matched_subject = reported_relationship_match.group(1).strip()
            other_person = reported_relationship_match.group(2).strip()
            relation = reported_relationship_match.group(3).strip().lower()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="person_relationship",
                    subject=matched_subject,
                    content=f"{other_person} ist {self._possessive_form(matched_subject)} {relation}.",
                    profile_value=f"{relation}:{other_person}",
                    reason="reported_self_person_relationship_statement",
                    confidence=0.8,
                )
            )

        third_person_height_match = self.THIRD_PERSON_HEIGHT_PATTERN.search(normalized)
        if third_person_height_match:
            matched_subject = third_person_height_match.group(1).strip()
            height_value = self._normalize_height(third_person_height_match.group(2))
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="height",
                    subject=matched_subject,
                    content=f"{matched_subject} ist {height_value} groß.",
                    profile_value=height_value,
                    reason="explicit_height_statement_third_person",
                    confidence=0.8,
                )
            )
        third_person_age_match = self.THIRD_PERSON_AGE_PATTERN.search(normalized)
        if third_person_age_match:
            matched_subject = third_person_age_match.group(1).strip()
            age_value = third_person_age_match.group(2).strip()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="age",
                    subject=matched_subject,
                    content=f"{matched_subject} ist {age_value} Jahre alt.",
                    profile_value=age_value,
                    reason="explicit_age_statement_third_person",
                    confidence=0.78,
                )
            )

        third_person_color_match = self.THIRD_PERSON_COLOR_PREFERENCE_PATTERN.search(normalized)
        if third_person_color_match:
            groups = third_person_color_match.groups()
            matched_subject = next(groups[index] for index in (0, 2, 4) if groups[index]).strip()
            color_value = next(groups[index] for index in (1, 3, 5) if groups[index]).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_color",
                    subject=matched_subject,
                    content=f"{matched_subject} mag die Farbe {color_value}.",
                    profile_value=color_value,
                    reason="explicit_color_preference_statement_third_person",
                    confidence=0.79,
                )
            )
        third_person_language_match = self.THIRD_PERSON_LANGUAGE_PATTERN.search(normalized)
        if third_person_language_match:
            matched_subject = third_person_language_match.group(1).strip()
            language_value = third_person_language_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="language",
                    subject=matched_subject,
                    content=f"{matched_subject} spricht {language_value}.",
                    profile_value=language_value,
                    reason="explicit_language_statement_third_person",
                    confidence=0.76,
                )
            )
        third_person_food_match = self.THIRD_PERSON_FAVORITE_FOOD_PATTERN.search(normalized)
        if third_person_food_match:
            matched_subject = third_person_food_match.group(1).strip()
            food_value = third_person_food_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_food",
                    subject=matched_subject,
                    content=f"{matched_subject} isst am liebsten {food_value}.",
                    profile_value=food_value,
                    reason="explicit_favorite_food_statement_third_person",
                    confidence=0.75,
                )
            )
        third_person_drink_match = self.THIRD_PERSON_FAVORITE_DRINK_PATTERN.search(normalized)
        if third_person_drink_match:
            matched_subject = third_person_drink_match.group(1).strip()
            drink_value = third_person_drink_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="favorite_drink",
                    subject=matched_subject,
                    content=f"{matched_subject} trinkt am liebsten {drink_value}.",
                    profile_value=drink_value,
                    reason="explicit_favorite_drink_statement_third_person",
                    confidence=0.75,
                )
            )

        third_person_eye_color_match = self.THIRD_PERSON_EYE_COLOR_PATTERN.search(normalized)
        if third_person_eye_color_match:
            groups = third_person_eye_color_match.groups()
            matched_subject = next(groups[index] for index in (0, 2) if groups[index]).strip()
            color_value = next(groups[index] for index in (1, 3) if groups[index]).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="eye_color",
                    subject=matched_subject,
                    content=f"{matched_subject} hat {color_value} Augen.",
                    profile_value=color_value,
                    reason="explicit_eye_color_statement_third_person",
                    confidence=0.83,
                )
            )
        third_person_job_match = self.THIRD_PERSON_JOB_PATTERN.search(normalized)
        if third_person_job_match:
            groups = third_person_job_match.groups()
            matched_subject = next(groups[index] for index in (0, 2) if groups[index]).strip()
            job_value = next(groups[index] for index in (1, 3) if groups[index]).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="occupation",
                    subject=matched_subject,
                    content=f"{matched_subject} arbeitet als {job_value}.",
                    profile_value=job_value,
                    reason="explicit_job_statement_third_person",
                    confidence=0.77,
                )
            )
        third_person_hometown_match = self.THIRD_PERSON_HOMETOWN_PATTERN.search(normalized)
        if third_person_hometown_match:
            matched_subject = third_person_hometown_match.group(1).strip()
            place = third_person_hometown_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="hometown",
                    subject=matched_subject,
                    content=f"{matched_subject} kommt aus {place}.",
                    profile_value=place,
                    reason="explicit_hometown_statement_third_person",
                    confidence=0.77,
                )
            )
        third_person_residence_match = self.THIRD_PERSON_RESIDENCE_PATTERN.search(normalized)
        if third_person_residence_match:
            matched_subject = third_person_residence_match.group(1).strip()
            place = third_person_residence_match.group(2).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="residence",
                    subject=matched_subject,
                    content=f"{matched_subject} wohnt in {place}.",
                    profile_value=place,
                    reason="explicit_residence_statement_third_person",
                    confidence=0.77,
                )
            )
        third_person_family_match = self.THIRD_PERSON_FAMILY_PATTERN.search(normalized)
        if third_person_family_match:
            groups = third_person_family_match.groups()
            if groups[0] and groups[1] and groups[2]:
                relation = groups[0].strip().lower()
                matched_subject = groups[1].strip()
                relation_name = groups[2].strip()
            else:
                matched_subject = groups[3].strip()
                relation_name = groups[4].strip()
                relation = self._extract_inline_relation(normalized, matched_subject)
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="family_relation",
                    subject=matched_subject,
                    content=f"{self._possessive_form(matched_subject)} {relation} heißt {relation_name}.",
                    profile_value=f"{relation}:{relation_name}",
                    reason="explicit_family_relation_statement_third_person",
                    confidence=0.76,
                )
            )
        third_person_pet_match = self.THIRD_PERSON_PET_PATTERN.search(normalized)
        if third_person_pet_match:
            groups = third_person_pet_match.groups()
            matched_subject = next(groups[index] for index in (0, 2) if groups[index]).strip()
            if groups[1]:
                pet_type = groups[1].strip().lower()
                pet_value = pet_type
                content = f"{matched_subject} hat einen {pet_type}."
            else:
                pet_type = groups[3].strip().lower()
                pet_name = groups[4].strip()
                pet_value = f"{pet_type}:{pet_name}"
                content = f"{matched_subject} hat einen {pet_type} namens {pet_name}."
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="pet",
                    subject=matched_subject,
                    content=content,
                    profile_value=pet_value,
                    reason="explicit_pet_statement_third_person",
                    confidence=0.74,
                )
            )
        third_person_relationship_match = self.THIRD_PERSON_RELATIONSHIP_TO_PERSON_PATTERN.search(normalized)
        if third_person_relationship_match:
            other_person = third_person_relationship_match.group(1).strip()
            relation = third_person_relationship_match.group(2).strip().lower()
            matched_subject = third_person_relationship_match.group(3).strip()
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="person_relationship",
                    subject=matched_subject,
                    content=f"{other_person} ist {self._possessive_form(matched_subject)} {relation}.",
                    profile_value=f"{relation}:{other_person}",
                    reason="explicit_person_relationship_statement_third_person",
                    confidence=0.73,
                )
            )

        third_person_dislike_match = self.THIRD_PERSON_DISLIKE_PATTERN.search(normalized)
        if third_person_dislike_match:
            groups = third_person_dislike_match.groups()
            matched_subject = next(groups[index] for index in (0, 2, 4) if groups[index]).strip()
            disliked = next(groups[index] for index in (1, 3, 5) if groups[index]).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.MEMORY,
                    category="dislike",
                    subject=matched_subject,
                    content=f"{matched_subject} mag {disliked} nicht.",
                    profile_value=disliked,
                    reason="explicit_dislike_statement_third_person",
                    confidence=0.74,
                )
            )
            return ChatDecisionResult(True, "chat_message", candidates)

        dislike_match = self.DISLIKE_PATTERN.search(normalized)
        if dislike_match:
            disliked = next(group for group in dislike_match.groups() if group).strip().rstrip(".!?")
            candidates.append(
                CandidateDecision(
                    kind=CandidateKind.PROFILE,
                    category="dislike",
                    subject=subject,
                    content=f"{subject} mag {disliked} nicht.",
                    profile_value=disliked,
                    reason="explicit_dislike_statement",
                    confidence=0.92,
                )
            )
        else:
            third_person_like_match = self.THIRD_PERSON_LIKE_PATTERN.search(normalized)
            if third_person_like_match:
                matched_subject = third_person_like_match.group(1).strip()
                preference = third_person_like_match.group(2).strip().rstrip(".!?")
                candidates.append(
                    CandidateDecision(
                        kind=CandidateKind.MEMORY,
                        category="preference",
                        subject=matched_subject,
                        content=f"{matched_subject} mag {preference}.",
                        profile_value=preference,
                        reason="explicit_preference_statement_third_person",
                        confidence=0.76,
                    )
                )
                return ChatDecisionResult(True, "chat_message", candidates)

            likes_match = self.LIKE_PATTERN.search(normalized)
            if likes_match:
                preference = likes_match.group(1).strip().rstrip(".!?")
                lowered_preference = preference.casefold()
                if (
                    not lowered_preference.startswith("die farbe ")
                    and lowered_preference not in {"es sachlich", "es locker", "es nüchtern", "es direkt"}
                ):
                    candidates.append(
                        CandidateDecision(
                            kind=CandidateKind.PROFILE,
                            category="preference",
                            subject=subject,
                            content=f"{subject} mag {preference}.",
                            profile_value=preference,
                            reason="explicit_preference_statement",
                            confidence=0.93,
                        )
                    )

        candidates = self._dedupe_candidates(candidates)
        return ChatDecisionResult(
            should_respond=True,
            response_reason="chat_message",
            candidates=candidates,
        )

    @staticmethod
    def _normalize_height(raw_value: str) -> str:
        value = raw_value.replace(".", ",").strip()
        if "," not in value:
            value = f"{value},00"
        return f"{value} m"

    @staticmethod
    def _extract_inline_relation(message: str, subject: str) -> str:
        lowered = message.casefold()
        subject_lower = subject.casefold()
        for relation in ("mutter", "vater", "schwester", "bruder", "tochter", "sohn", "frau", "mann", "partnerin", "partner"):
            if f"{subject_lower} {relation}".casefold() in lowered:
                return relation
        return "familienmitglied"

    @staticmethod
    def _possessive_form(name: str) -> str:
        if name.casefold().endswith(("s", "ß", "x", "z")):
            return f"{name}'"
        return f"{name}s"

    @staticmethod
    def _dedupe_candidates(candidates: list[CandidateDecision]) -> list[CandidateDecision]:
        deduped: list[CandidateDecision] = []
        seen: set[tuple[str, str | None, str]] = set()
        for candidate in candidates:
            key = (candidate.category, candidate.subject, candidate.content)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    @staticmethod
    def _normalize_style_preference(token: str) -> str | None:
        token = token.casefold()
        if "sach" in token or "nüchter" in token:
            return "sachlich"
        if "locker" in token:
            return "locker"
        if "direkt" in token:
            return "sachlich"
        return None

    @staticmethod
    def _normalize_humor_preference(token: str) -> str | None:
        token = token.casefold()
        if "witz" in token or "humor" in token:
            return "higher"
        if "ernst" in token:
            return "lower"
        return None

    @staticmethod
    def _normalize_length_preference(token: str) -> str | None:
        token = token.casefold()
        if "kurz" in token or "kürz" in token or "knapp" in token:
            return "short"
        if "ausführ" in token or "detail" in token:
            return "detailed"
        return None
