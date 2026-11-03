"""
Packet 04 — HTML Shell & Design System: Tests

Run from the repository root:
    UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard ──────────────────────────────────────────────────────────────
try:
    import fastapi   # noqa: F401
    import aiosqlite # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi/aiosqlite not installed — run from the repository root: "
        "UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402
from tools.testkit import assert_frontend_vendor_current, assert_launcher_compiles_cleanly, assert_offline_page_source  # noqa: E402


# ── Test 1: Basic response ────────────────────────────────────────────────────

def test_get_root_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ── Test 2: Embedded frontend ─────────────────────────────────────────────────

def test_html_embeds_current_offline_frontend(html_body):
    launcher = Path(git_dashboard.__file__)
    assert_frontend_vendor_current(launcher)
    assert_launcher_compiles_cleanly(launcher)
    assert_offline_page_source(html_body)
    assert 'preact.render(' in html_body


# ── Test 3: SVG charts ────────────────────────────────────────────────────────

# ── Test 4: Fonts ─────────────────────────────────────────────────────────────

# ── Test 5: CSS custom properties ────────────────────────────────────────────

# ── Test 6: Root mount point ─────────────────────────────────────────────────

# ── Test 7: Hash routing ──────────────────────────────────────────────────────

# ── Test 8: Navigation tabs ───────────────────────────────────────────────────

# ── Test 9: Header ────────────────────────────────────────────────────────────

# ── Test 10: ErrorBoundary ────────────────────────────────────────────────────
