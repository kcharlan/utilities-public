"""
Packet 00 — Bootstrap & Schema: Tests

Run from project root after bootstrapping:
    ~/.git_dashboard_venv/bin/python -m pytest tests/test_packet_00.py -v
"""

import os
import sys
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# git_dashboard.py is in the project root (parent of this tests/ directory)
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard: bootstrap() must pass without re-execing in test context ───
# If fastapi is not importable, skip all tests rather than trying to create a
# venv during the test run.
try:
    import fastapi  # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi not installed — run tests inside the app venv: "
        "~/.git_dashboard_venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402  (after path setup and fastapi guard)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Preflight: Python version check
# ─────────────────────────────────────────────────────────────────────────────

def test_python_version_ok(monkeypatch):
    """Python 3.12 should not raise."""
    monkeypatch.setattr(sys, "version_info", (3, 12, 0))
    git_dashboard.check_python_version()  # should not raise


def test_python_version_too_old_exits_1(monkeypatch):
    """Python 3.11 must cause SystemExit(1)."""
    monkeypatch.setattr(sys, "version_info", (3, 11, 0))
    with pytest.raises(SystemExit) as exc_info:
        git_dashboard.check_python_version()
    assert exc_info.value.code == 1


def test_python_version_error_message_mentions_312(monkeypatch, capsys):
    monkeypatch.setattr(sys, "version_info", (3, 11, 0))
    with pytest.raises(SystemExit):
        git_dashboard.check_python_version()
    captured = capsys.readouterr()
    assert "3.12" in captured.err


# ─────────────────────────────────────────────────────────────────────────────
# 2. Preflight: git check
# ─────────────────────────────────────────────────────────────────────────────

def test_git_missing_exits_1(monkeypatch):
    """shutil.which('git') returning None must cause SystemExit(1)."""
    monkeypatch.setattr(git_dashboard.shutil, "which", lambda _cmd: None)
    with pytest.raises(SystemExit) as exc_info:
        git_dashboard.check_git()
    assert exc_info.value.code == 1


def test_git_present_ok(monkeypatch):
    """When git is found, check_git() should not raise."""
    monkeypatch.setattr(git_dashboard.shutil, "which", lambda _cmd: "/usr/bin/git")
    git_dashboard.check_git()  # should not raise


# ─────────────────────────────────────────────────────────────────────────────
# 3. TOOLS dict population
# ─────────────────────────────────────────────────────────────────────────────

def test_tools_dict_npm_present(monkeypatch):
    def mock_which(cmd):
        return "/usr/bin/npm" if cmd == "npm" else None

    monkeypatch.setattr(git_dashboard.shutil, "which", mock_which)
    tools = git_dashboard.build_tools_dict()
    assert tools["npm"] == "/usr/bin/npm"
    assert tools["go"] is None
    assert tools["cargo"] is None
    assert tools["bundle"] is None
    assert tools["composer"] is None


def test_tools_dict_conditional_go_tools(monkeypatch):
    """govulncheck should only be populated when go is found."""
    def mock_which(cmd):
        return "/usr/local/bin/go" if cmd == "go" else (
            "/usr/bin/govulncheck" if cmd == "govulncheck" else None
        )

    monkeypatch.setattr(git_dashboard.shutil, "which", mock_which)
    tools = git_dashboard.build_tools_dict()
    assert tools["go"] == "/usr/local/bin/go"
    assert tools["govulncheck"] == "/usr/bin/govulncheck"
    assert tools["cargo_audit"] is None   # cargo not found
    assert tools["cargo_outdated"] is None


def test_tools_dict_conditional_cargo_tools(monkeypatch):
    """cargo_audit and cargo_outdated should only appear when cargo is found."""
    def mock_which(cmd):
        mapping = {
            "cargo": "/usr/bin/cargo",
            "cargo-audit": "/usr/bin/cargo-audit",
            "cargo-outdated": "/usr/bin/cargo-outdated",
        }
        return mapping.get(cmd)

    monkeypatch.setattr(git_dashboard.shutil, "which", mock_which)
    tools = git_dashboard.build_tools_dict()
    assert tools["cargo"] == "/usr/bin/cargo"
    assert tools["cargo_audit"] == "/usr/bin/cargo-audit"
    assert tools["cargo_outdated"] == "/usr/bin/cargo-outdated"
    assert tools["govulncheck"] is None   # go not found


def test_tools_dict_conditional_bundle_tools(monkeypatch):
    """bundler_audit should only appear when bundle is found."""
    def mock_which(cmd):
        mapping = {
            "bundle": "/usr/bin/bundle",
            "bundler-audit": "/usr/bin/bundler-audit",
        }
        return mapping.get(cmd)

    monkeypatch.setattr(git_dashboard.shutil, "which", mock_which)
    tools = git_dashboard.build_tools_dict()
    assert tools["bundle"] == "/usr/bin/bundle"
    assert tools["bundler_audit"] == "/usr/bin/bundler-audit"


def test_tools_dict_pip_audit_present(monkeypatch):
    """pip_audit is always checked (after venv; here we just verify it appears in dict)."""
    def mock_which(cmd):
        return "/usr/bin/pip-audit" if cmd == "pip-audit" else None

    monkeypatch.setattr(git_dashboard.shutil, "which", mock_which)
    tools = git_dashboard.build_tools_dict()
    assert tools["pip_audit"] == "/usr/bin/pip-audit"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Hard-fail when no ecosystem tools found
# ─────────────────────────────────────────────────────────────────────────────

def test_no_ecosystem_tools_exits_1():
    """All tools missing must cause SystemExit(1)."""
    empty_tools = {k: None for k in [
        "npm", "go", "cargo", "bundle", "composer",
        "pip_audit", "govulncheck", "cargo_audit", "cargo_outdated", "bundler_audit",
    ]}
    with pytest.raises(SystemExit) as exc_info:
        git_dashboard.check_ecosystem_tools(empty_tools)
    assert exc_info.value.code == 1


def test_one_ecosystem_tool_present_does_not_fail():
    """Having at least one ecosystem tool should not raise."""
    tools = {k: None for k in [
        "npm", "go", "cargo", "bundle", "composer",
        "pip_audit", "govulncheck", "cargo_audit", "cargo_outdated", "bundler_audit",
    ]}
    tools["npm"] = "/usr/bin/npm"
    git_dashboard.check_ecosystem_tools(tools)  # must not raise


def test_pip_audit_alone_passes_ecosystem_check():
    """pip_audit alone is enough to pass the ecosystem check."""
    tools = {k: None for k in [
        "npm", "go", "cargo", "bundle", "composer",
        "pip_audit", "govulncheck", "cargo_audit", "cargo_outdated", "bundler_audit",
    ]}
    tools["pip_audit"] = "/usr/bin/pip-audit"
    git_dashboard.check_ecosystem_tools(tools)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# 5. Schema: all 6 tables created
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_TABLES = {
    "repositories",
    "daily_stats",
    "branches",
    "dependencies",
    "working_state",
    "scan_log",
}


def test_schema_creates_all_six_tables():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert tables == EXPECTED_TABLES, f"Tables mismatch: got {tables}"
    finally:
        os.unlink(db_path)


def test_schema_idempotent():
    """Calling init_schema twice must not raise."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        git_dashboard.init_schema(db_path)  # second call — should not raise
    finally:
        os.unlink(db_path)


def test_schema_wal_mode():
    """WAL journal mode must be enabled after init."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert row[0] == "wal", f"Expected WAL mode, got: {row[0]}"
    finally:
        os.unlink(db_path)


def test_schema_repositories_columns():
    """repositories table must have the expected columns."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        info = conn.execute("PRAGMA table_info(repositories)").fetchall()
        conn.close()
        col_names = {row[1] for row in info}
        expected_cols = {
            "id", "name", "path", "default_branch", "runtime",
            "added_at", "last_quick_scan_at", "last_full_scan_at",
        }
        assert expected_cols == col_names, f"Column mismatch: {col_names}"
    finally:
        os.unlink(db_path)


def test_schema_scan_log_columns():
    """scan_log table must have the expected columns."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        info = conn.execute("PRAGMA table_info(scan_log)").fetchall()
        conn.close()
        col_names = {row[1] for row in info}
        expected_cols = {
            "id", "scan_type", "started_at", "finished_at",
            "repos_scanned", "status",
        }
        assert expected_cols == col_names, f"Column mismatch: {col_names}"
    finally:
        os.unlink(db_path)


def test_schema_daily_stats_columns():
    """daily_stats table must have the expected columns."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        info = conn.execute("PRAGMA table_info(daily_stats)").fetchall()
        conn.close()
        col_names = {row[1] for row in info}
        expected_cols = {
            "repo_id", "date", "commits", "insertions",
            "deletions", "files_changed",
        }
        assert expected_cols == col_names, f"Column mismatch: {col_names}"
    finally:
        os.unlink(db_path)


def test_schema_branches_columns():
    """branches table must have the expected columns."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        info = conn.execute("PRAGMA table_info(branches)").fetchall()
        conn.close()
        col_names = {row[1] for row in info}
        expected_cols = {
            "repo_id", "name", "last_commit_date",
            "is_default", "is_stale",
        }
        assert expected_cols == col_names, f"Column mismatch: {col_names}"
    finally:
        os.unlink(db_path)


def test_schema_dependencies_columns():
    """dependencies table must have the expected columns."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        info = conn.execute("PRAGMA table_info(dependencies)").fetchall()
        conn.close()
        col_names = {row[1] for row in info}
        expected_cols = {
            "repo_id", "manager", "name", "current_version",
            "wanted_version", "latest_version", "severity",
            "advisory_id", "checked_at", "source_path",
        }
        assert expected_cols == col_names, f"Column mismatch: {col_names}"
    finally:
        os.unlink(db_path)


def test_schema_working_state_columns():
    """working_state table must have the expected columns."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        info = conn.execute("PRAGMA table_info(working_state)").fetchall()
        conn.close()
        col_names = {row[1] for row in info}
        expected_cols = {
            "repo_id", "has_uncommitted", "modified_count",
            "untracked_count", "staged_count", "current_branch",
            "last_commit_hash", "last_commit_message",
            "last_commit_date", "checked_at",
            # Added in packet 22: error state columns
            "scan_error", "dep_check_error",
        }
        assert expected_cols == col_names, f"Column mismatch: {col_names}"
    finally:
        os.unlink(db_path)


def test_schema_foreign_keys_exist():
    """Tables with FK references to repositories must have them declared."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        git_dashboard.init_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        fk_tables = ["daily_stats", "branches", "dependencies", "working_state"]
        for table in fk_tables:
            fks = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            assert len(fks) > 0, f"{table} has no foreign keys"
            assert fks[0][2] == "repositories", (
                f"{table} FK points to {fks[0][2]}, expected repositories"
            )
        conn.close()
    finally:
        os.unlink(db_path)


# ─────────────────────────────────────────────────────────────────────────────
# 6. CLI argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def test_cli_defaults():
    args = git_dashboard.parse_args([])
    assert args.port == 8300
    assert args.no_browser is False
    assert args.yes is False
    assert args.scan is None


def test_cli_port():
    args = git_dashboard.parse_args(["--port", "9000"])
    assert args.port == 9000


def test_cli_no_browser():
    args = git_dashboard.parse_args(["--no-browser"])
    assert args.no_browser is True


def test_cli_yes_long():
    args = git_dashboard.parse_args(["--yes"])
    assert args.yes is True


def test_cli_yes_short():
    args = git_dashboard.parse_args(["-y"])
    assert args.yes is True


def test_cli_scan():
    args = git_dashboard.parse_args(["--scan", "/some/path"])
    assert args.scan == "/some/path"


def test_cli_all_flags():
    args = git_dashboard.parse_args([
        "--port", "9000", "--no-browser", "--yes", "--scan", "/some/path"
    ])
    assert args.port == 9000
    assert args.no_browser is True
    assert args.yes is True
    assert args.scan == "/some/path"


# ─────────────────────────────────────────────────────────────────────────────
# 7. GET /api/status returns tool info and version
# ─────────────────────────────────────────────────────────────────────────────

def test_api_status_shape(monkeypatch, client):
    monkeypatch.setattr(
        git_dashboard,
        "TOOLS",
        {"npm": "/usr/bin/npm", "go": None},
    )
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data, "Response must include 'tools' key"
    assert "version" in data, "Response must include 'version' key"


def test_api_status_tools_value(monkeypatch, client):
    fake_tools = {"npm": "/usr/bin/npm", "go": None, "cargo": None}
    monkeypatch.setattr(git_dashboard, "TOOLS", fake_tools)
    data = client.get("/api/status").json()
    assert data["tools"] == fake_tools


def test_api_status_version_string(monkeypatch, client):
    monkeypatch.setattr(git_dashboard, "TOOLS", {})
    data = client.get("/api/status").json()
    assert isinstance(data["version"], str)
    assert len(data["version"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. GET / returns HTML with status 200
# ─────────────────────────────────────────────────────────────────────────────

def test_root_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200


def test_root_content_type_html(client):
    response = client.get("/")
    assert "text/html" in response.headers["content-type"]


def test_root_is_html_document(client):
    response = client.get("/")
    body = response.text
    assert "<!DOCTYPE html>" in body or "<html" in body


# ─────────────────────────────────────────────────────────────────────────────
# 9. find_free_port
# ─────────────────────────────────────────────────────────────────────────────

def test_find_free_port_returns_int():
    port = git_dashboard.find_free_port(8300)
    assert isinstance(port, int)
    assert 8300 <= port < 8320


def test_find_free_port_fallback(monkeypatch):
    """When start_port is in use, must return the next free port."""
    import socket as _socket

    original_socket = _socket.socket

    call_count = {"n": 0}

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            self._real = original_socket(*args, **kwargs)
            call_count["n"] += 1
            self._fail = call_count["n"] == 1  # first bind attempt fails

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._real.close()

        def bind(self, addr):
            if self._fail:
                raise OSError("address already in use")
            return self._real.bind(addr)

    monkeypatch.setattr(git_dashboard.socket, "socket", FakeSocket)
    port = git_dashboard.find_free_port(9100)
    assert port == 9101


def test_find_free_port_exhaustion_raises_runtime_error(monkeypatch):
    """When every port in the scan range is occupied, RuntimeError must be raised
    with a message that includes the start and end port numbers. (23A gap 5)
    """
    import socket as _socket

    class AlwaysOccupiedSocket:
        """Fake socket whose bind() always raises OSError (all ports busy)."""
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, addr):
            raise OSError("address already in use")

    monkeypatch.setattr(git_dashboard.socket, "socket", AlwaysOccupiedSocket)

    start = 9200
    max_attempts = 5  # small range to keep test fast
    with pytest.raises(RuntimeError) as exc_info:
        git_dashboard.find_free_port(start, max_attempts=max_attempts)

    msg = str(exc_info.value)
    # Error message must mention the port range so the user knows what to do
    assert str(start) in msg, f"RuntimeError message should mention start port {start}: {msg!r}"
    end = start + max_attempts - 1
    assert str(end) in msg, f"RuntimeError message should mention end port {end}: {msg!r}"
