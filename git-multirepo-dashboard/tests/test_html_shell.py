"""
Packet 04 — HTML Shell & Design System: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_html_shell.py -v
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
        "fastapi/aiosqlite not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402
from tools.testkit import assert_react_19_import_map  # noqa: E402


# ── Test 1: Basic response ────────────────────────────────────────────────────

def test_get_root_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ── Test 2: React CDN tags ────────────────────────────────────────────────────

def test_html_includes_react_19_esm_contract(html_body):
    import_map_match = re.search(
        r'<script type="importmap">\s*(\{.*?\})\s*</script>',
        html_body,
        re.DOTALL,
    )
    assert import_map_match is not None
    import_map = json.loads(import_map_match.group(1))
    assert_react_19_import_map(import_map["imports"])
    assert "react@18.3.1" not in html_body
    assert "react-dom@18.3.1" not in html_body
    assert "@babel/standalone@8.0.5" in html_body
    assert (
        '<script type="text/babel" data-type="module" '
        'data-presets="env,react">'
    ) in html_body
    assert "import * as React from 'react';" in html_body
    assert "import * as ReactDOMClient from 'react-dom/client';" in html_body
    assert "ReactDOMClient.createRoot(" in html_body


# ── Test 3: Recharts CDN graph ───────────────────────────────────────────────

def test_html_includes_recharts_3_esm_with_externalized_react_peers(html_body):
    recharts_url = (
        "https://esm.sh/recharts@3.10.1"
        "?external=react,react-dom,react-is"
    )

    assert html_body.count(recharts_url) == 1
    assert f"import * as Recharts from '{recharts_url}';" in html_body
    assert "umd/Recharts.js" not in html_body
    assert "recharts/2.15.4" not in html_body


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
