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
        "fastapi/aiosqlite not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402
from tools.testkit import ASGISyncClient  # noqa: E402


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
