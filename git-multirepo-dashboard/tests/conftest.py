"""Shared test fixtures."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("UTILITIES_TESTING", "1")

PROJECT_ROOT = Path(__file__).parent.parent
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(REPO_ROOT))

try:
    import aiosqlite  # noqa: F401
    import httpx  # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi/aiosqlite not installed — run from the repository root: "
        "UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402
from tools.testkit import ASGISyncClient  # noqa: E402


@pytest.fixture
def dependency_report_seed():
    """One conspicuously synthetic declaration/inventory contract for API and browser tests."""
    import json
    import sqlite3
    rows = []
    for name, severity, outdated, vuln, current, wanted, source, note in [
        ('synthetic-partial-vuln', 'vulnerable', 'unchecked', 'checked', '1.0', None, 'requirements.txt', 'Synthetic registry unavailable'),
        ('synthetic-partial-major', 'major', 'checked', 'unchecked', '1.0', None, 'requirements.txt', 'Synthetic audit unavailable'),
        ('synthetic-partial-outdated', 'outdated', 'checked', 'unchecked', '1.0', None, 'requirements.txt', 'Synthetic audit timeout'),
        ('synthetic-floating', 'outdated', 'floating', 'checked', None, '1.5', 'nested/pyproject.toml', None),
        ('synthetic-clean', 'ok', 'checked', 'checked', '1.0', None, 'requirements.txt', None),
        ('synthetic-direct', 'unchecked', 'unchecked', 'unchecked', 'git:demo', None, 'requirements.txt', git_dashboard.NOTE_DIRECT_REF),
        ('synthetic-clean', 'ok', 'checked', 'checked', '2.0', None, 'nested/pyproject.toml', None),
    ]:
        rows.append(dict(manager='pip', name=name, severity=severity, outdated_state=outdated,
                         vuln_state=vuln, current_version=current, wanted_version=wanted,
                         latest_version='2.0', source_path=source, check_note=note,
                         declared_spec=name + ('>=1,<2' if outdated == 'floating' else '==1.0'),
                         advisory_id='SYNTHETIC-ADVISORY' if severity == 'vulnerable' else None,
                         checked_at='2026-01-02T03:04:05+00:00'))
    manifests = [dict(path=p, kind=k, dependencies=sum(r['source_path'] == p for r in rows), error=e)
                 for p, k, e in [('requirements.txt', 'requirements', None),
                                 ('nested/pyproject.toml', 'pyproject', None),
                                 ('empty.txt', 'requirements', None),
                                 ('broken.txt', 'requirements', 'Synthetic read failure')]]
    summary = dict(declarations=len(rows), manifests=len(manifests),
                   **{s: sum(r['severity'] == s for r in rows) for s in ('ok', 'outdated', 'major', 'vulnerable')})
    summary['fullyChecked'] = sum(r['outdated_state'] in ('checked', 'floating') and r['vuln_state'] == 'checked' for r in rows)
    summary['unchecked'] = len(rows) - summary['fullyChecked']
    missing = [dict(tool='synthetic-audit', description='Synthetic missing audit tool')]

    def seed(db_path, repo_id, path):
        with sqlite3.connect(db_path) as db:
            db.execute('INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)',
                       (repo_id, 'Synthetic coverage repository', str(path), '2026-01-01'))
            db.execute('INSERT INTO working_state (repo_id,dep_check_error,missing_dep_tools,dep_manifests) VALUES (?,1,?,?)',
                       (repo_id, json.dumps(missing), json.dumps(manifests)))
            for row in rows:
                keys = list(row)
                db.execute(f"INSERT INTO dependencies (repo_id,{','.join(keys)}) VALUES ({','.join('?' for _ in range(len(keys)+1))})",
                           [repo_id] + [row[k] for k in keys])
    return dict(rows=rows, manifests=manifests, summary=summary, missing_tools=missing, seed=seed)


@pytest.fixture
def test_app(tmp_path):
    """(ASGI client, db_path) with an isolated database."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    async def override_get_db():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    git_dashboard.app.dependency_overrides[git_dashboard.get_db] = override_get_db
    with ASGISyncClient(git_dashboard.app) as client:
        yield client, db_path
    git_dashboard.app.dependency_overrides.clear()


@pytest.fixture
def test_app_raise(tmp_path):
    """Like test_app but with raise_server_exceptions=True."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    async def override_get_db():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    git_dashboard.app.dependency_overrides[git_dashboard.get_db] = override_get_db
    with ASGISyncClient(git_dashboard.app, raise_server_exceptions=True) as client:
        yield client, db_path
    git_dashboard.app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def client():
    """Module-scoped ASGI client for read-only HTML/static checks ONLY.

    WARNING — do NOT use this fixture for DB-backed API endpoints
    (e.g. /api/fleet, /api/repos/*, /api/analytics/*). This client uses the
    real production database path, not an isolated test DB, so DB-backed calls
    will either fail with missing state or pollute the developer's real database.

    Use the `test_app` fixture (function-scoped, isolated in-memory DB) for any
    endpoint that reads from or writes to the database. (23A gap 9)
    """
    with ASGISyncClient(git_dashboard.app) as c:
        yield c


@pytest.fixture(scope="module")
def html_body(client):
    """The HTML body from GET /, shared across a module."""
    return client.get("/").text
