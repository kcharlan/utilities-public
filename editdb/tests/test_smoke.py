from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import ASGISyncClient, assert_launcher_help, load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "editdb"


def test_help_exits_without_creating_files(tmp_path):
    assert_launcher_help(SCRIPT_PATH, cwd=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_launcher_loads_fastapi_app():
    module = load_launcher(SCRIPT_PATH)

    assert module.app.title == "EditDB API"


def test_status_reports_no_database_before_startup():
    module = load_launcher(SCRIPT_PATH)
    response = ASGISyncClient(module.app).get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "db_path": "",
        "db_name": "No Database Loaded",
    }
