from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService


class CameraStreamService:
    _ffmpeg_procs: dict[str, subprocess.Popen] = {}
    _ffmpeg_last: dict[str, float] = {}
    _HLS_DIR = Path("/tmp/hls")
    _HLS_DIR.mkdir(exist_ok=True)

    _RTSP_USER = os.environ.get("ROBOT_RING_RTSP_USER", "erika")
    _RTSP_PASS = os.environ.get("ROBOT_RING_RTSP_PASS", "erika123")

    RING_DEVICE_MAP: dict[str, str] = {
        "camera.haustur_live_ansicht": "343ea4dd0896",
        "camera.garten_live_ansicht": "649a63f0d054",
        "camera.terrasse_live_ansicht": "649a63eef039",
    }
    LIVE_TIMEOUT = 300
    _watchdog_started = False

    @classmethod
    def ensure_started(cls) -> None:
        if cls._watchdog_started:
            return
        cls._watchdog_started = True
        threading.Thread(target=cls._ffmpeg_watchdog, daemon=True).start()

    @classmethod
    def ring_ids(cls) -> set[str]:
        return set(cls.RING_DEVICE_MAP.keys())

    @classmethod
    def rtsp_url(cls, entity_id: str) -> str:
        ha_host = HomeAssistantRuntimeConfigService.get_config()["host"]
        device_id = cls.RING_DEVICE_MAP.get(entity_id)
        if device_id:
            return f"rtsp://{cls._RTSP_USER}:{cls._RTSP_PASS}@{ha_host}:8554/{device_id}_live"
        return f"rtsp://{cls._RTSP_USER}:{cls._RTSP_PASS}@{ha_host}:8554/{entity_id}"

    @classmethod
    def live_switch(cls, entity_id: str) -> str | None:
        for key in cls.RING_DEVICE_MAP:
            cam_part = key.replace("camera.", "").replace("_live_ansicht", "")
            if entity_id == key or cam_part in entity_id:
                return f"switch.{cam_part}_live_stream"
        return None

    @classmethod
    def ha_switch(cls, switch_eid: str, turn_on: bool) -> None:
        try:
            from app.search.providers.homeassistant import HomeAssistantProvider

            HomeAssistantProvider().call_service(
                "switch", "turn_on" if turn_on else "turn_off", {"entity_id": switch_eid}
            )
            print(f"[CAMERA] switch {switch_eid} -> {'ON' if turn_on else 'OFF'}")
        except Exception as exc:
            print(f"[CAMERA] switch {switch_eid} failed: {exc}")

    @classmethod
    def kill_ffmpeg(cls, entity_id: str) -> None:
        proc = cls._ffmpeg_procs.pop(entity_id, None)
        cls._ffmpeg_last.pop(entity_id, None)
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
        print(f"[CAMERA] stopped {entity_id}")

    @classmethod
    def start_ffmpeg(cls, entity_id: str) -> None:
        out_dir = cls._HLS_DIR / entity_id.replace(".", "_")
        out_dir.mkdir(exist_ok=True)
        m3u8 = out_dir / "stream.m3u8"
        cmd = [
            "ffmpeg",
            "-y",
            "-rtsp_transport",
            "tcp",
            "-i",
            cls.rtsp_url(entity_id),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ac",
            "1",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "3",
            "-hls_flags",
            "delete_segments+append_list",
            "-hls_segment_filename",
            str(out_dir / "seg%03d.ts"),
            str(m3u8),
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        cls._ffmpeg_procs[entity_id] = proc
        cls._ffmpeg_last[entity_id] = time.time()
        print(f"[CAMERA] started {entity_id} (pid={proc.pid})")

    @classmethod
    def live_start(cls, entity_id: str) -> dict[str, str | int | None]:
        sw = cls.live_switch(entity_id)
        if sw:
            threading.Thread(target=cls.ha_switch, args=(sw, True), daemon=True).start()
            time.sleep(0.5)
        if entity_id in cls._ffmpeg_procs:
            cls.kill_ffmpeg(entity_id)
        cls.start_ffmpeg(entity_id)
        m3u8_path = cls._HLS_DIR / entity_id.replace(".", "_") / "stream.m3u8"
        deadline = time.time() + 8
        while not m3u8_path.exists() and time.time() < deadline:
            time.sleep(0.3)
        if not m3u8_path.exists():
            cls.kill_ffmpeg(entity_id)
            if sw:
                threading.Thread(target=cls.ha_switch, args=(sw, False), daemon=True).start()
            raise RuntimeError("Stream nicht erreichbar (RTSP Timeout)")
        return {
            "m3u8_url": f"/ha/cameras/{entity_id}/hls/stream.m3u8",
            "timeout_seconds": cls.LIVE_TIMEOUT,
            "switch": sw,
        }

    @classmethod
    def live_stop(cls, entity_id: str) -> dict[str, str | None]:
        sw = cls.live_switch(entity_id)
        cls.kill_ffmpeg(entity_id)
        if sw:
            threading.Thread(target=cls.ha_switch, args=(sw, False), daemon=True).start()
        return {"stopped": entity_id, "switch": sw}

    @classmethod
    def stream_playlist(cls, entity_id: str) -> str:
        m3u8_path = cls._HLS_DIR / entity_id.replace(".", "_") / "stream.m3u8"
        if not m3u8_path.exists() or entity_id not in cls._ffmpeg_procs:
            raise RuntimeError("Stream nicht aktiv - POST /live/start aufrufen")
        cls._ffmpeg_last[entity_id] = time.time()
        content = m3u8_path.read_text()
        lines: list[str] = []
        for line in content.splitlines():
            if line.strip().endswith(".ts"):
                seg = line.strip().split("/")[-1]
                lines.append(f"/ha/cameras/{entity_id}/hls/{seg}")
            else:
                lines.append(line)
        return "\n".join(lines)

    @classmethod
    def read_segment(cls, entity_id: str, filename: str) -> bytes:
        cls._ffmpeg_last[entity_id] = time.time()
        seg_path = cls._HLS_DIR / entity_id.replace(".", "_") / filename
        if not seg_path.exists():
            raise FileNotFoundError(filename)
        return seg_path.read_bytes()

    @classmethod
    def stop_all(cls) -> list[str]:
        stopped: list[str] = []
        for eid in list(cls._ffmpeg_procs.keys()):
            sw = cls.live_switch(eid)
            cls.kill_ffmpeg(eid)
            stopped.append(eid)
            if sw:
                threading.Thread(target=cls.ha_switch, args=(sw, False), daemon=True).start()
        print(f"[CAMERA] stop-all: {stopped}")
        return stopped

    @classmethod
    def _ffmpeg_watchdog(cls) -> None:
        while True:
            time.sleep(10)
            now = time.time()
            for eid, last in list(cls._ffmpeg_last.items()):
                if now - last > cls.LIVE_TIMEOUT:
                    print(f"[CAMERA] timeout {eid} - stopping")
                    sw = cls.live_switch(eid)
                    cls.kill_ffmpeg(eid)
                    if sw:
                        threading.Thread(target=cls.ha_switch, args=(sw, False), daemon=True).start()
