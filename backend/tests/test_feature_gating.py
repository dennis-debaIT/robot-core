import importlib

from fastapi.testclient import TestClient


def _client():
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)
    return TestClient(main_module.app)


def test_backup_endpoints_blocked_without_license(temp_db):
    with _client() as client:
        assert client.get("/admin/backup/info").status_code == 403
        assert client.post("/admin/backup/create").status_code == 403
        assert client.post("/admin/backup/restore").status_code == 403


def test_backup_endpoints_allowed_with_plus(temp_db, monkeypatch):
    from app.services.feature_service import FeatureService
    monkeypatch.setattr(FeatureService, "has_feature", lambda self, feature_id: True)
    # Backup-Service selbst nicht mocken (kein Sync-Token in Tests) — es reicht
    # zu pruefen, dass die Anfrage ueberhaupt an den Service durchgereicht wird
    # (kein 403 mehr), unabhaengig davon ob sie mangels Konfiguration scheitert.
    with _client() as client:
        assert client.get("/admin/backup/info").status_code != 403


def test_local_first_endpoints_stay_free_at_backend_regardless_of_license(temp_db):
    """waste/liga_plus/camera_events/vehicle_history sind bewusst NICHT im
    Backend gegated (Local-First: Rohdaten/Endpunkte bleiben immer frei, nur
    die Darstellung in display.html/display-liga.js wird per _hasFeature()
    ausgeblendet). Dieser Test haelt genau das fest, damit es nicht versehentlich
    wieder als "Luecke" missverstanden und erneut blockiert wird."""
    with _client() as client:
        assert client.get("/ha/waste").status_code != 403
        assert client.get("/ha/cameras/events").status_code != 403
        assert client.get("/vehicles/veh1/charging-history").status_code != 403
        assert client.get("/liga/team-squad?team_id=1").status_code != 403
