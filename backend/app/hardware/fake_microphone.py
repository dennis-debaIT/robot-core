from app.hardware.base import MicrophoneAdapter


class FakeMicrophone(MicrophoneAdapter):
    def capture_text(self, text: str) -> str:
        return text.strip()
