from __future__ import annotations

from typing import Any

from app.search.providers.homeassistant import HomeAssistantProvider


class HomeAssistantService:
    def __init__(self, provider: HomeAssistantProvider | None = None) -> None:
        self.provider = provider or HomeAssistantProvider()

    def get_states(self) -> list[dict[str, Any]]:
        states = self.provider._get("/states")
        return states if isinstance(states, list) else []

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        state = self.provider._get(f"/states/{entity_id}")
        return state if isinstance(state, dict) else None

    def get_history(self, path: str) -> Any:
        return self.provider._get(path)

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> bool:
        return self.provider.call_service(domain, service, data)

    def get_lights(self) -> list[dict[str, Any]]:
        return self.provider.get_lights()

    def get_fuel_prices(self) -> dict[str, Any] | None:
        return self.provider.get_fuel_prices()

    def get_doorbell_sensors(self) -> list[dict[str, Any]]:
        return self.provider.get_doorbell_sensors()
