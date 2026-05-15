import importlib

from fastapi.testclient import TestClient


def test_device_identity_is_available(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.get("/device/identity")
        assert response.status_code == 200
        payload = response.json()
        assert payload["device_id"].startswith("erika-")
        assert payload["tenant_id"] == "tenant-demo-local"
        assert payload["tenant_binding"] == "factory_assigned"
        assert payload["provisioning_source"] == "factory"


def test_sync_contract_describes_device_cloud_boundary(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.get("/sync/contract")
        assert response.status_code == 200
        payload = response.json()
        assert payload["backend_role"] == "device_runtime"
        assert payload["paired_cloud_backend"] == "future_cloud_platform"
        assert any(domain["name"] == "device_status" for domain in payload["sync_domains"])
        assert "Der lokale Robot-Core bleibt offline arbeitsfähig." in payload["constraints"]
