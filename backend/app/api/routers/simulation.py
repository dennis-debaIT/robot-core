from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import get_core
from app.api.schemas import (
    BatterySimulationRequest,
    DisplaySimulationRequest,
    PersonSimulationRequest,
    SpeechSimulationRequest,
)


router = APIRouter()


@router.post("/simulate/person")
def simulate_person(payload: PersonSimulationRequest) -> dict[str, object]:
    return get_core().simulate_person(payload.person_name)


@router.post("/simulate/battery")
def simulate_battery(payload: BatterySimulationRequest) -> dict[str, object]:
    return get_core().simulate_battery(payload.level)


@router.post("/simulate/speech")
def simulate_speech(payload: SpeechSimulationRequest) -> dict[str, object]:
    return get_core().simulate_speech(payload.text, payload.person_name)


@router.post("/simulate/display")
def simulate_display(payload: DisplaySimulationRequest) -> dict[str, object]:
    return get_core().simulate_display(payload.status)
