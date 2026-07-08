import importlib

from fastapi.testclient import TestClient


def _client():
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)
    return TestClient(main_module.app)


def test_waste_endpoint_blocked_without_license(temp_db):
    with _client() as client:
        response = client.get("/ha/waste")
        assert response.status_code == 403


def test_waste_endpoint_allowed_with_plus(temp_db, monkeypatch):
    from app.services.feature_service import FeatureService
    monkeypatch.setattr(FeatureService, "has_feature", lambda self, feature_id: True)

    with _client() as client:
        response = client.get("/ha/waste")
        assert response.status_code != 403


def test_camera_events_blocked_without_license(temp_db):
    with _client() as client:
        response = client.get("/ha/cameras/events")
        assert response.status_code == 403


def test_camera_events_allowed_with_plus(temp_db, monkeypatch):
    from app.services.feature_service import FeatureService
    monkeypatch.setattr(FeatureService, "has_feature", lambda self, feature_id: True)

    with _client() as client:
        response = client.get("/ha/cameras/events")
        assert response.status_code != 403


def test_vehicle_charging_history_blocked_without_license(temp_db):
    with _client() as client:
        response = client.get("/vehicles/veh1/charging-history")
        assert response.status_code == 403


def test_vehicle_charging_history_allowed_with_plus(temp_db, monkeypatch):
    from app.services.feature_service import FeatureService
    monkeypatch.setattr(FeatureService, "has_feature", lambda self, feature_id: True)

    with _client() as client:
        response = client.get("/vehicles/veh1/charging-history")
        assert response.status_code != 403


def test_liga_plus_endpoints_blocked_without_license(temp_db):
    with _client() as client:
        assert client.get("/liga/tm/profile?team_name=Test").status_code == 403
        assert client.get("/liga/tm/players?team_name=Test").status_code == 403
        assert client.get("/liga/person/123").status_code == 403
        assert client.get("/liga/tm/club-transfers?team_name=Test").status_code == 403
        assert client.get("/liga/tm/player-search?name=Test").status_code == 403
        assert client.get("/liga/tm/player/123").status_code == 403
        assert client.get("/liga/kader-full?team_name=Test").status_code == 403
        assert client.get("/liga/team-squad?team_id=123").status_code == 403


def test_liga_base_endpoints_stay_free_without_license(temp_db):
    with _client() as client:
        # Keine 403 fuer die Basis-Anzeige (Konfigurationsluecke fuehrt hoechstens
        # zu einer leeren Antwort, nie zu einem Lizenz-Fehler).
        assert client.get("/liga/state").status_code == 200
        assert client.get("/liga/standings?code=BL1").status_code == 200
        assert client.get("/liga/teams").status_code == 200


def test_liga_team_detail_blocked_for_foreign_team_without_license(temp_db):
    with _client() as client:
        response = client.get("/liga/team-detail?team_id=999")
        assert response.status_code == 403


def test_liga_team_detail_free_for_own_favorite_team(temp_db, monkeypatch):
    from app.services.integration_config_service import IntegrationConfigService
    from app.services.liga_service import LigaService

    monkeypatch.setattr(
        IntegrationConfigService,
        "get_config",
        lambda self: {"liga": {"api_key": "dummy", "favorite_team_id": 42}},
    )
    monkeypatch.setattr(LigaService, "get_team_focus", lambda self, team_id: {"team_id": team_id})

    with _client() as client:
        response = client.get("/liga/team-detail?team_id=42")
        assert response.status_code == 200
        # Ein fremdes Team ueber denselben Endpoint bleibt weiterhin Plus-gated.
        blocked = client.get("/liga/team-detail?team_id=7")
        assert blocked.status_code == 403
