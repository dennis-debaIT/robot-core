from app.hardware.base import BatteryAdapter


class FakeBattery(BatteryAdapter):
    def update_level(self, level: int) -> int:
        return max(0, min(100, int(level)))
