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

def test_html_includes_svg_charts(html_body):
    assert 'svgCharts.CartesianChart' in html_body


# ── Test 4: Fonts ─────────────────────────────────────────────────────────────

def test_html_includes_fonts(html_body):
    assert "JetBrains Mono" in html_body
    assert "Geist" in html_body


# ── Test 5: CSS custom properties ────────────────────────────────────────────

def test_html_includes_css_custom_properties(html_body):
    assert "--bg-primary" in html_body
    assert "--text-primary" in html_body
    assert "--accent-blue" in html_body
    assert "--font-heading" in html_body
    assert "--radius-md" in html_body
    assert "--transition-normal" in html_body


# ── Test 6: Root mount point ─────────────────────────────────────────────────

def test_html_includes_root_div(html_body):
    assert 'id="root"' in html_body


# ── Test 7: Hash routing ──────────────────────────────────────────────────────

def test_html_includes_hash_routing(html_body):
    # Either addEventListener('hashchange') or window.onhashchange
    assert "hashchange" in html_body
    assert "#/fleet" in html_body
    assert "#/analytics" in html_body


# ── Test 8: Navigation tabs ───────────────────────────────────────────────────

def test_html_includes_nav_tabs(html_body):
    assert "Fleet Overview" in html_body
    assert "Analytics" in html_body
    assert "Dependencies" in html_body


# ── Test 9: Header ────────────────────────────────────────────────────────────

def test_html_includes_header(html_body):
    assert "Git Fleet" in html_body
    assert "Scan Dir" in html_body
    assert "Full Scan" in html_body


# ── Test 10: ErrorBoundary ────────────────────────────────────────────────────

def test_html_includes_error_boundary(html_body):
    assert "ErrorBoundary" in html_body
