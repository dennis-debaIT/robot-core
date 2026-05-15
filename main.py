from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from app.api.schemas import (
    BatterySimulationRequest,
    ChatRequest,
    ConfigPatchRequest,
    DevicePatchRequest,
    DisplaySimulationRequest,
    MemoryProposalRequest,
    PersonPreferencePatchRequest,
    PersonSimulationRequest,
    PersonalityPatchRequest,
    SpeechSimulationRequest,
)
from app.core.settings import SettingsService
from app.database.db import init_db
from app.integrations.robot_core import RobotCore


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"

core: RobotCore | None = None
settings_service: SettingsService | None = None


def get_core() -> RobotCore:
    if core is None:
        raise RuntimeError("RobotCore not initialized")
    return core


def get_settings_service() -> SettingsService:
    if settings_service is None:
        raise RuntimeError("SettingsService not initialized")
    return settings_service


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    global core, settings_service
    init_db()
    settings_service = SettingsService()
    settings_service.ensure_runtime_state()
    core = RobotCore()
    core.cloud.ensure_state()
    core.device.ensure_state()
    yield


app = FastAPI(title="Robot Core", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=FileResponse)
def index() -> Any:
    return FileResponse(FRONTEND_INDEX)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
def status() -> dict[str, Any]:
    return get_core().get_status()


@app.get("/device/identity")
def get_device_identity() -> dict[str, Any]:
    return get_core().get_device_identity()


@app.get("/sync/contract")
def get_sync_contract() -> dict[str, Any]:
    return get_core().get_sync_contract()


@app.get("/device")
def get_device() -> dict[str, Any]:
    return get_core().get_device()


@app.patch("/device")
def patch_device(payload: DevicePatchRequest) -> dict[str, Any]:
    try:
        return get_core().update_device(payload.to_patch())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/config")
def get_config() -> dict[str, Any]:
    return get_settings_service().describe()


@app.patch("/config")
def patch_config(payload: ConfigPatchRequest) -> dict[str, Any]:
    patch = payload.to_patch()
    effective = get_settings_service().update_runtime_overrides(patch)
    get_core().audit.log(
        action="config.updated",
        target_type="config",
        target_id="runtime_config",
        summary="Laufzeit-Konfiguration wurde geändert.",
        details={"patch": patch},
    )
    return {
        "effective": effective.model_dump(),
        "runtime_overrides": get_settings_service().get_runtime_overrides(),
    }


@app.post("/chat")
def chat(payload: ChatRequest) -> dict[str, Any]:
    return get_core().chat(payload.message, payload.person_name)


@app.post("/chat/preview")
def preview_chat(payload: ChatRequest) -> dict[str, Any]:
    return get_core().preview_chat_prompt(payload.message, payload.person_name)


@app.post("/chat/stream")
def stream_chat(payload: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        get_core().stream_chat(payload.message, payload.person_name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/memory")
def list_memory(status: str | None = Query(default=None)) -> dict[str, Any]:
    return {"items": get_core().memory.list_memories(status=status)}


@app.post("/memory/propose")
def propose_memory(payload: MemoryProposalRequest) -> dict[str, Any]:
    memory = get_core().propose_memory(
        content=payload.content,
        category=payload.category,
        subject=payload.subject,
        source=payload.source,
    )
    return {"memory": memory}


@app.post("/memory/approve/{memory_id}")
def approve_memory(memory_id: int) -> dict[str, Any]:
    result = get_core().approve_memory(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@app.post("/memory/reject/{memory_id}")
def reject_memory(memory_id: int) -> dict[str, Any]:
    result = get_core().reject_memory(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@app.post("/simulate/person")
def simulate_person(payload: PersonSimulationRequest) -> dict[str, Any]:
    return get_core().simulate_person(payload.person_name)


@app.post("/simulate/battery")
def simulate_battery(payload: BatterySimulationRequest) -> dict[str, Any]:
    return get_core().simulate_battery(payload.level)


@app.post("/simulate/speech")
def simulate_speech(payload: SpeechSimulationRequest) -> dict[str, Any]:
    return get_core().simulate_speech(payload.text, payload.person_name)


@app.post("/simulate/display")
def simulate_display(payload: DisplaySimulationRequest) -> dict[str, Any]:
    return get_core().simulate_display(payload.status)


@app.get("/personality")
def get_personality() -> dict[str, Any]:
    return get_core().personality.get()


@app.get("/audit")
def list_audit(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": get_core().list_audit_entries(limit=limit)}


@app.get("/conversation")
def list_conversation(
    person_name: str | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=200),
) -> dict[str, Any]:
    return {"items": get_core().list_conversation_messages(person_name=person_name, limit=limit)}


@app.get("/profiles")
def list_profiles() -> dict[str, Any]:
    return {"items": get_core().profile.list_people()}


@app.get("/profiles/{person_id}/preferences")
def get_profile_preferences(person_id: int) -> dict[str, Any]:
    result = get_core().get_person_preferences(person_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@app.patch("/profiles/{person_id}/preferences")
def patch_profile_preferences(person_id: int, payload: PersonPreferencePatchRequest) -> dict[str, Any]:
    result = get_core().update_person_preferences(person_id, payload.to_patch())
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@app.delete("/profiles/{person_id}")
def delete_profile(person_id: int) -> dict[str, Any]:
    result = get_core().delete_person(person_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@app.patch("/personality")
def patch_personality(payload: PersonalityPatchRequest) -> dict[str, Any]:
    patch = payload.to_patch()
    result = get_core().personality.update(patch)
    get_core().audit.log(
        action="personality.updated",
        target_type="personality",
        target_id="default_personality",
        summary="Persönlichkeit wurde geändert.",
        details={"patch": patch},
    )
    return result
