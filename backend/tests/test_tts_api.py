import importlib

from fastapi.testclient import TestClient


def test_tts_status_reports_disabled_by_default(temp_db, monkeypatch):
    monkeypatch.setenv("ROBOT_TTS_PROVIDER", "disabled")
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.get("/tts/status")
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "disabled"
        assert data["ready"] is False


def test_mock_tts_synthesize_returns_wav(temp_db, monkeypatch):
    monkeypatch.setenv("ROBOT_TTS_PROVIDER", "mock")

    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        status = client.get("/tts/status")
        assert status.status_code == 200
        assert status.json()["provider"] == "mock"
        assert status.json()["ready"] is True

        response = client.post("/tts/synthesize", json={"text": "Hallo Dennis"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.content[:4] == b"RIFF"
