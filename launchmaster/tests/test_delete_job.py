from __future__ import annotations

import asyncio
import plistlib
import sys
from pathlib import Path

import pytest


UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.testkit import load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "launchmaster"
LABEL = "com.example.fake-job"
DOMAIN = "user-agent"


@pytest.fixture
def lm_module(tmp_path, monkeypatch):
    """Import the launcher without starting its server or creating runtime files."""
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("UTILITIES_TESTING", "1")
    return load_launcher(SCRIPT_PATH)


def _write_synthetic_plist(path: Path) -> None:
    path.write_bytes(plistlib.dumps({"Label": LABEL, "Program": "/usr/bin/true"}))


def test_delete_job_backs_up_unloads_and_removes_plist(
    lm_module, tmp_path, monkeypatch
):
    plist_path = tmp_path / f"{LABEL}.plist"
    _write_synthetic_plist(plist_path)
    unload_calls = []

    async def fake_unload(label, domain, path):
        unload_calls.append((label, domain, path))
        return {"success": True, "message": "unloaded"}

    monkeypatch.setattr(lm_module, "unload_job", fake_unload)

    result = asyncio.run(
        lm_module.delete_job(LABEL, DOMAIN, str(plist_path))
    )

    assert result["success"] is True
    assert not plist_path.exists()
    backups = list(Path(lm_module.BACKUP_DIR).glob(f"{LABEL}.*.plist"))
    assert len(backups) == 1
    assert plistlib.loads(backups[0].read_bytes())["Label"] == LABEL
    assert unload_calls == [(LABEL, DOMAIN, str(plist_path))]


def test_delete_job_unloads_when_plist_is_already_absent(
    lm_module, tmp_path, monkeypatch
):
    plist_path = tmp_path / f"{LABEL}.plist"
    unload_calls = []

    async def fake_unload(label, domain, path):
        unload_calls.append((label, domain, path))
        return {"success": True, "message": "unloaded"}

    monkeypatch.setattr(lm_module, "unload_job", fake_unload)

    result = asyncio.run(
        lm_module.delete_job(LABEL, DOMAIN, str(plist_path))
    )

    assert result["success"] is True
    assert "already absent" in result["message"]
    assert unload_calls == [(LABEL, DOMAIN, str(plist_path))]
    assert not Path(lm_module.BACKUP_DIR).exists()


def test_delete_job_propagates_unload_failure_when_plist_is_absent(
    lm_module, monkeypatch
):
    unload_calls = []
    failure = {"success": False, "message": "boot-out failed"}

    async def fake_unload(label, domain, path):
        unload_calls.append((label, domain, path))
        return failure

    monkeypatch.setattr(lm_module, "unload_job", fake_unload)

    result = asyncio.run(lm_module.delete_job(LABEL, "unknown", None))

    assert result == failure
    assert unload_calls == [(LABEL, "unknown", None)]


def test_delete_job_reports_permission_denied_removing_plist(
    lm_module, tmp_path, monkeypatch
):
    plist_dir = tmp_path / "read-only"
    plist_dir.mkdir()
    plist_path = plist_dir / f"{LABEL}.plist"
    _write_synthetic_plist(plist_path)

    async def fake_unload(label, domain, path):
        return {"success": True, "message": "unloaded"}

    monkeypatch.setattr(lm_module, "unload_job", fake_unload)
    plist_dir.chmod(0o500)
    try:
        result = asyncio.run(
            lm_module.delete_job(LABEL, DOMAIN, str(plist_path))
        )
    finally:
        plist_dir.chmod(0o700)

    assert result["success"] is False
    assert "Permission denied" in result["message"]
    assert plist_path.exists()


def test_api_delete_job_delegates_when_plist_path_is_missing(
    lm_module, monkeypatch
):
    delete_calls = []
    expected = {"success": True, "message": "ok"}
    job = {"label": LABEL, "plist_path": None, "domain": "unknown"}

    async def fake_delete(label, domain, plist_path):
        delete_calls.append((label, domain, plist_path))
        return expected

    async def fake_refresh():
        return None

    monkeypatch.setattr(lm_module, "_find_job", lambda label: job)
    monkeypatch.setattr(lm_module, "delete_job", fake_delete)
    monkeypatch.setattr(lm_module, "_refresh_jobs", fake_refresh)

    result = asyncio.run(lm_module.api_delete_job(LABEL))

    assert result == expected
    assert delete_calls == [(LABEL, "unknown", None)]
