from dataclasses import dataclass


@dataclass
class CameraDetection:
    person_name: str | None
    confidence: float


class CameraAdapter:
    def detect_person(self, person_name: str | None) -> CameraDetection:
        raise NotImplementedError


class MicrophoneAdapter:
    def capture_text(self, text: str) -> str:
        raise NotImplementedError


class BatteryAdapter:
    def update_level(self, level: int) -> int:
        raise NotImplementedError
