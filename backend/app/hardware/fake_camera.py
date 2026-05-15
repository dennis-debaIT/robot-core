from app.hardware.base import CameraAdapter, CameraDetection


class FakeCamera(CameraAdapter):
    def detect_person(self, person_name: str | None) -> CameraDetection:
        return CameraDetection(person_name=person_name, confidence=0.92 if person_name else 0.0)
