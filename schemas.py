from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    person_name: str | None = None


class MemoryProposalRequest(BaseModel):
    content: str = Field(min_length=1)
    category: str = "general"
    subject: str | None = None
    source: str = "api"


class PersonSimulationRequest(BaseModel):
    person_name: str | None = None


class BatterySimulationRequest(BaseModel):
    level: int = Field(ge=0, le=100)


class SpeechSimulationRequest(BaseModel):
    text: str = Field(min_length=1)
    person_name: str | None = None


class DisplaySimulationRequest(BaseModel):
    status: str = Field(min_length=1)


class PersonalityPatchRequest(BaseModel):
    friendliness: float | None = Field(default=None, ge=0.0, le=1.0)
    humor: float | None = Field(default=None, ge=0.0, le=1.0)
    curiosity: float | None = Field(default=None, ge=0.0, le=1.0)
    talkativeness: float | None = Field(default=None, ge=0.0, le=1.0)
    caution: float | None = Field(default=None, ge=0.0, le=1.0)
    directness: float | None = Field(default=None, ge=0.0, le=1.0)
    sarcasm: float | None = Field(default=None, ge=0.0, le=1.0)
    patience: float | None = Field(default=None, ge=0.0, le=1.0)

    def to_patch(self) -> dict[str, float]:
        return self.model_dump(exclude_none=True)


class ConfigPatchRequest(BaseModel):
    quiet_minutes: int | None = Field(default=None, ge=1, le=120)
    critical_battery_threshold: int | None = Field(default=None, ge=0, le=100)
    greeting_suggestion_template: str | None = None
    response_style: str | None = None
    explain_only_on_request: bool | None = None
    llm_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    llm_max_tokens: int | None = Field(default=None, ge=64, le=2048)
    llm_history_turns: int | None = Field(default=None, ge=0, le=20)
    topic_interest_threshold: int | None = Field(default=None, ge=2, le=10)
    topic_interest_window_days: int | None = Field(default=None, ge=1, le=90)

    def to_patch(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class DevicePatchRequest(BaseModel):
    device_name: str | None = None
    site_label: str | None = None
    device_state: str | None = None
    network_connected: bool | None = None
    server_connected: bool | None = None
    local_ip: str | None = None
    software_version: str | None = None
    update_status: str | None = None
    last_server_contact_at: str | None = None
    maintenance_mode: bool | None = None
    provisioning_status: str | None = None

    def to_patch(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class PersonPreferencePatchRequest(BaseModel):
    response_humor_preference: str | None = Field(default=None, pattern="^(higher|lower)$")
    response_style_preference: str | None = Field(default=None, pattern="^(sachlich|locker)$")
    response_length_preference: str | None = Field(default=None, pattern="^(short|detailed)$")

    def to_patch(self) -> dict[str, str]:
        return self.model_dump(exclude_none=True)
