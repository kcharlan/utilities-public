"""
Packet 04 — HTML Shell & Design System: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_html_shell.py -v
"""

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
        "fastapi/aiosqlite not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


# ── Test 1: Basic response ────────────────────────────────────────────────────

def test_get_root_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ── Test 2: React CDN tags ────────────────────────────────────────────────────

def test_html_includes_react_cdn(html_body):
    assert "react/18.2.0" in html_body
    assert "react-dom/18.2.0" in html_body
    assert "babel-standalone/7.23.9" in html_body


# ── Test 3: Recharts CDN tag ─────────────────────────────────────────────────

def test_html_includes_recharts_cdn(html_body):
    assert "recharts/2.12.7" in html_body


# ── Test 4: Font links ────────────────────────────────────────────────────────

def test_html_includes_font_links(html_body):
    assert "JetBrains+Mono" in html_body
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
