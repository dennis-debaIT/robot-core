import importlib
import os
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test_robot_core.db"
    monkeypatch.setenv("ROBOT_CORE_DB_PATH", str(db_path))

    import app.database.db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    return db_path
