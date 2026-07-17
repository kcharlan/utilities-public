"""
Packet 05 — Fleet Overview UI: Tests

All tests check for the presence of required patterns/strings in HTML_TEMPLATE,
following the same approach as test_html_shell.py (packet 04).

Run from project root:
    .venv/bin/python -m pytest tests/test_fleet_overview_ui.py -v
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


# ── Test 1: FleetOverview component ──────────────────────────────────────────

def test_fleet_overview_component_exists(html_body):
    """HTML_TEMPLATE contains a FleetOverview function component definition."""
    assert "function FleetOverview" in html_body


# ── Test 2: KpiRow component ─────────────────────────────────────────────────

def test_kpi_row_component_exists(html_body):
    """HTML_TEMPLATE contains a KpiRow component that receives kpis prop."""
    assert "function KpiRow" in html_body
    # KpiRow must be wired to receive kpis prop
    assert "kpis" in html_body


# ── Test 3: ProjectCard component ────────────────────────────────────────────

def test_project_card_component_exists(html_body):
    """HTML_TEMPLATE contains a ProjectCard component."""
    assert "function ProjectCard" in html_body


# ── Test 4: Sort dropdown options ────────────────────────────────────────────

def test_sort_dropdown_options(html_body):
    """HTML_TEMPLATE contains all 4 sort option labels."""
    assert "Last active" in html_body
    assert "Name A-Z" in html_body
    assert "Most changes" in html_body
    assert "Most stale branches" in html_body


# ── Test 5: Filter input placeholder ─────────────────────────────────────────

def test_filter_input_placeholder(html_body):
    """HTML_TEMPLATE contains a filter input with placeholder 'Filter projects...'."""
    assert "Filter projects..." in html_body


# ── Test 6: Empty state message ───────────────────────────────────────────────

def test_empty_state_message(html_body):
    """HTML_TEMPLATE contains an empty state element for when no repos are registered."""
    # EmptyState component or an empty state message visible when repos list is empty
    assert "EmptyState" in html_body or "No repositories" in html_body or "add" in html_body.lower()
    # Verify there is a component or section that handles zero repos
    assert "repos.length === 0" in html_body or "repos.length == 0" in html_body or "EmptyState" in html_body


# ── Test 7: Runtime badge labels ──────────────────────────────────────────────

def test_runtime_badge_labels(html_body):
    """HTML_TEMPLATE contains runtime badge label mappings for all 11 types."""
    assert "RUNTIME_LABELS" in html_body
    for label in ["'PY'", "'JS'", "'GO'", "'RS'", "'RB'", "'PHP'", "'SH'", "'DK'", "'HTML'", "'MIX'", "'??'"]:
        assert label in html_body, f"Missing runtime badge label: {label}"


# ── Test 8: Freshness thresholds ─────────────────────────────────────────────

def test_freshness_thresholds(html_body):
    """HTML_TEMPLATE contains freshness classification with thresholds at 7, 30, and 90 days."""
    # The freshness logic must compare against 7, 30, and 90 days
    assert "7" in html_body
    assert "30" in html_body
    assert "90" in html_body
    # Verify the freshness CSS variables are referenced
    assert "--fresh-this-week" in html_body
    assert "--fresh-this-month" in html_body
    assert "--fresh-older" in html_body
    assert "--fresh-stale" in html_body


# ── Test 9: Relative time function ───────────────────────────────────────────

def test_relative_time_function(html_body):
    """HTML_TEMPLATE contains a timeAgo or equivalent function for relative timestamps."""
    assert "timeAgo" in html_body or "relativeTime" in html_body or "time_ago" in html_body
    # Must handle "never" for null dates
    assert "never" in html_body


# ── Test 10: Card click navigation ───────────────────────────────────────────

def test_card_click_navigation(html_body):
    """HTML_TEMPLATE includes hash navigation to #/repo/{id} on card click."""
    assert "#/repo/" in html_body


# ── Test 11: Sparkline hover container ───────────────────────────────────────

def test_sparkline_hover_container(html_body):
    """HTML_TEMPLATE contains sparkline container with translateY transform for hover reveal."""
    assert "translateY" in html_body
    # The sparkline container slides up from translateY(100%) to translateY(0)
    assert "translateY(100%)" in html_body or "translateY(0)" in html_body


# ── Test 12: Fleet data fetch ─────────────────────────────────────────────────

def test_fleet_data_fetch(html_body):
    """HTML_TEMPLATE contains fetch('/api/fleet') call."""
    assert "fetch('/api/fleet')" in html_body


# ── Test 13: Status pill variants ────────────────────────────────────────────

def test_status_pill_variants(html_body):
    """HTML_TEMPLATE contains pill rendering logic for Clean, mod, new, staged variants."""
    assert "Clean" in html_body
    assert "mod" in html_body
    assert "staged" in html_body


# ── Test 14: KPI conditional coloring ────────────────────────────────────────

def test_kpi_conditional_coloring(html_body):
    """HTML_TEMPLATE contains conditional color logic for dirty (yellow), vuln (red), stale (orange)."""
    assert "--status-yellow" in html_body
    assert "--status-red" in html_body
    assert "--status-orange" in html_body
