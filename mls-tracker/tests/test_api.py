"""Tests for the MLS Tracker backend API and helper functions.

Strategy:
- Helper/computation functions are tested directly (unit tests).
- API endpoints are tested via FastAPI's TestClient with mocked ESPN calls.
- No real network calls; all external HTTP is mocked.
"""
import time
from unittest.mock import patch, MagicMock

import pytest
from tools.testkit import ASGISyncClient

import mls_tracker


# ============================================================
# Fixtures — mock ESPN data
# ============================================================

def _make_team_entry(tid, name, abbr, color, alt_color, logo_url):
    """Build a single team dict matching ESPN /teams shape."""
    return {
        "team": {
            "id": str(tid),
            "displayName": name,
            "abbreviation": abbr,
            "shortDisplayName": abbr,
            "color": color,
            "alternateColor": alt_color,
            "logos": [{"href": logo_url}],
        }
    }


def _make_standing_entry(tid, name, rank, gp, w, l, t, pts, gf, ga):
    """Build a single standings entry matching ESPN /standings shape."""
    return {
        "team": {"id": str(tid), "displayName": name},
        "stats": [
            {"name": "rank", "value": rank},
            {"name": "gamesPlayed", "value": gp},
            {"name": "wins", "value": w},
            {"name": "losses", "value": l},
            {"name": "ties", "value": t},
            {"name": "points", "value": pts},
            {"name": "pointsFor", "value": gf},
            {"name": "pointsAgainst", "value": ga},
        ],
    }


MOCK_TEAMS_RESPONSE = {
    "sports": [{
        "leagues": [{
            "teams": [
                _make_team_entry(1, "Team Alpha", "ALP", "C8102E", "1D428A", "https://cdn/alpha.png"),
                _make_team_entry(2, "Team Bravo", "BRV", "000000", "80FF00", "https://cdn/bravo.png"),
                _make_team_entry(3, "Team Charlie", "CHR", "ffffff", "FF5733", "https://cdn/charlie.png"),
                _make_team_entry(4, "Team Delta", "DLT", "1D428A", "", "https://cdn/delta.png"),
                _make_team_entry(5, "Team Echo", "ECH", "", "", ""),
                _make_team_entry(6, "Team Foxtrot", "FOX", "3366CC", "AABBCC", "https://cdn/foxtrot.png"),
                _make_team_entry(7, "Team Golf", "GLF", "228B22", "FFD700", "https://cdn/golf.png"),
                _make_team_entry(8, "Team Hotel", "HTL", "8B0000", "DC143C", "https://cdn/hotel.png"),
                _make_team_entry(9, "Team India", "IND", "4B0082", "EE82EE", "https://cdn/india.png"),
                _make_team_entry(10, "Team Juliet", "JUL", "DAA520", "B8860B", "https://cdn/juliet.png"),
            ]
        }]
    }]
}


def _east_entries():
    """10-team Eastern Conference standings (mid-season, 20 GP each)."""
    return [
        _make_standing_entry(1,  "Team Alpha",   1,  20, 14, 2, 4, 46, 35, 15),
        _make_standing_entry(2,  "Team Bravo",   2,  20, 12, 4, 4, 40, 30, 18),
        _make_standing_entry(3,  "Team Charlie",  3,  20, 11, 5, 4, 37, 28, 20),
        _make_standing_entry(4,  "Team Delta",   4,  20, 10, 6, 4, 34, 25, 22),
        _make_standing_entry(5,  "Team Echo",    5,  20, 9,  7, 4, 31, 22, 24),
        _make_standing_entry(6,  "Team Foxtrot", 6,  20, 8,  8, 4, 28, 20, 20),
        _make_standing_entry(7,  "Team Golf",    7,  20, 7,  9, 4, 25, 18, 25),
        _make_standing_entry(8,  "Team Hotel",   8,  20, 6, 10, 4, 22, 16, 28),
        _make_standing_entry(9,  "Team India",   9,  20, 5, 11, 4, 19, 14, 30),
        _make_standing_entry(10, "Team Juliet",  10, 20, 3, 14, 3, 12, 10, 40),
    ]


MOCK_STANDINGS_RESPONSE = {
    "children": [
        {
            "name": "Eastern Conference",
            "standings": {"entries": _east_entries()},
        },
    ]
}


def _mock_requests_get(url, **kwargs):
    """Route mocked requests.get to the right fixture."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if "teams" in url:
        resp.json.return_value = MOCK_TEAMS_RESPONSE
    elif "standings" in url:
        resp.json.return_value = MOCK_STANDINGS_RESPONSE
    else:
        resp.json.return_value = {}
    return resp


@pytest.fixture(autouse=True)
def _patch_espn_and_reset_cache():
    """Patch external HTTP calls and reset the global cache for every test."""
    mls_tracker.cache.invalidate()
    with patch("mls_tracker.requests.get", side_effect=_mock_requests_get):
        yield


@pytest.fixture
def client():
    """Synchronous HTTPX client for the FastAPI app."""
    return ASGISyncClient(mls_tracker.app)


# ============================================================
# Unit tests — safe_int
# ============================================================

class TestSafeInt:
    def test_normal_int(self):
        assert mls_tracker.safe_int(42) == 42

    def test_string_int(self):
        assert mls_tracker.safe_int("7") == 7

    def test_float_value(self):
        assert mls_tracker.safe_int(3.9) == 3

    def test_string_float(self):
        assert mls_tracker.safe_int("3.9") == 3

    def test_none_returns_default(self):
        assert mls_tracker.safe_int(None) == 0
        assert mls_tracker.safe_int(None, 5) == 5

    def test_non_numeric_string(self):
        assert mls_tracker.safe_int("abc") == 0

    def test_empty_string(self):
        assert mls_tracker.safe_int("") == 0

    def test_negative(self):
        assert mls_tracker.safe_int(-10) == -10

    def test_zero(self):
        assert mls_tracker.safe_int(0) == 0


# ============================================================
# Unit tests — process_team_colors
# ============================================================

class TestProcessTeamColors:
    def test_normal_colors(self):
        result = mls_tracker.process_team_colors("C8102E", "1D428A")
        assert result["primary"] == "#C8102E"
        assert result["secondary"] == "#1D428A"

    def test_black_primary_swaps_to_alt(self):
        result = mls_tracker.process_team_colors("000000", "80FF00")
        assert result["primary"] == "#80FF00"
        assert result["secondary"] == "#000000"

    def test_white_primary_swaps_to_alt(self):
        result = mls_tracker.process_team_colors("ffffff", "FF5733")
        assert result["primary"] == "#FF5733"
        assert result["secondary"] == "#ffffff"

    def test_both_low_contrast_no_swap(self):
        result = mls_tracker.process_team_colors("000000", "ffffff")
        # Both low-contrast: alt is also low-contrast, so no swap
        assert result["primary"] == "#000000"

    def test_empty_strings(self):
        result = mls_tracker.process_team_colors("", "")
        assert result["primary"] == "#6366f1"  # fallback indigo
        assert result["secondary"] == "#1f2937"

    def test_none_inputs(self):
        result = mls_tracker.process_team_colors(None, None)
        assert "primary" in result
        assert "secondary" in result
        assert "accent" in result

    def test_hash_stripped(self):
        result = mls_tracker.process_team_colors("#C8102E", "#1D428A")
        assert result["primary"] == "#C8102E"

    def test_accent_white_for_dark_primary(self):
        result = mls_tracker.process_team_colors("1D428A", "FFFFFF")
        assert result["accent"] == "#ffffff"

    def test_accent_dark_for_light_primary(self):
        result = mls_tracker.process_team_colors("FFFF00", "000000")
        assert result["accent"] == "#1f2937"


# ============================================================
# Unit tests — DataCache
# ============================================================

class TestDataCache:
    def test_invalidate_clears_data(self):
        cache = mls_tracker.DataCache(ttl=300)
        # Populate cache
        cache.get_teams()
        cache.get_standings(2025)
        assert cache._teams is not None
        assert 2025 in cache._standings

        cache.invalidate()
        assert cache._teams is None
        assert len(cache._standings) == 0

    def test_expired_returns_true_after_ttl(self):
        cache = mls_tracker.DataCache(ttl=1)
        past = time.time() - 2
        assert cache._expired(past) is True

    def test_not_expired_within_ttl(self):
        cache = mls_tracker.DataCache(ttl=300)
        assert cache._expired(time.time()) is False

    def test_cache_reuses_data_within_ttl(self):
        """Second call should not re-fetch (mock call count stays at 1)."""
        cache = mls_tracker.DataCache(ttl=300)
        t1 = cache.get_teams()
        t2 = cache.get_teams()
        assert t1 is t2  # Same object, not re-fetched


# ============================================================
# Unit tests — compute_scenarios and sub-functions
# ============================================================

def _make_team(name, pts, gp, position, ppg=None):
    """Helper to build a team dict for compute_scenarios."""
    if ppg is None:
        ppg = round(pts / gp, 3) if gp > 0 else 0.0
    return {
        "name": name, "pts": pts, "gp": gp, "position": position,
        "ppg": ppg, "colors": {}, "logo": "",
    }


class TestComputeWorstCase:
    def test_needs_wins(self):
        result = mls_tracker._compute_worst_case(pts_target=30, gr_target=10, must_beat=50)
        assert result["possible"] is True
        assert result["wins"] == 7  # need 20 pts → ceil(20/3) = 7
        assert result["losses"] == 3
        assert result["final_pts"] == 51

    def test_already_above(self):
        result = mls_tracker._compute_worst_case(pts_target=55, gr_target=5, must_beat=50)
        assert result["possible"] is True
        assert result["wins"] == 0
        assert result["losses"] == 5

    def test_impossible(self):
        result = mls_tracker._compute_worst_case(pts_target=10, gr_target=2, must_beat=20)
        assert result["possible"] is False

    def test_zero_games_remaining(self):
        result = mls_tracker._compute_worst_case(pts_target=50, gr_target=0, must_beat=55)
        assert result["possible"] is False


class TestComputeEasiestPath:
    def test_maximises_ties(self):
        result = mls_tracker._compute_easiest_path(pts_target=30, gr_target=14, must_beat=50)
        assert result["possible"] is True
        # Should have fewer wins than worst_case equivalent
        assert result["ties"] > 0
        assert result["wins"] + result["ties"] + result["losses"] == 14
        assert result["final_pts"] >= 50

    def test_impossible_returns_possible_false(self):
        result = mls_tracker._compute_easiest_path(pts_target=10, gr_target=2, must_beat=20)
        assert result["possible"] is False


class TestComputeNeedHelp:
    def test_produces_message(self):
        cutoff = _make_team("Rival", pts=40, gp=20, position=9)
        result = mls_tracker._compute_need_help(cutoff, season_games=34, max_possible_target=55)
        assert "Rival" in result["message"]
        assert result["cutoff_gr"] == 14
        assert "max_wins" in result
        assert "max_ties" in result

    def test_cutoff_must_lose_all(self):
        cutoff = _make_team("Rival", pts=55, gp=30, position=9)
        result = mls_tracker._compute_need_help(cutoff, season_games=34, max_possible_target=55)
        assert result["max_wins"] == 0
        assert result["max_ties"] == 0
        assert "lose all" in result["message"]


class TestComputeScenarios:
    def test_clinched(self):
        target = _make_team("Top", pts=60, gp=30, position=1)
        cutoff = _make_team("Ninth", pts=15, gp=30, position=9)
        result = mls_tracker.compute_scenarios(target, cutoff)
        assert result["status"] == "clinched"

    def test_eliminated(self):
        target = _make_team("Bottom", pts=5, gp=30, position=10)
        cutoff = _make_team("Ninth", pts=50, gp=20, position=9)
        result = mls_tracker.compute_scenarios(target, cutoff)
        assert result["status"] == "eliminated"

    def test_contention(self):
        target = _make_team("Mid", pts=35, gp=20, position=5)
        cutoff = _make_team("Ninth", pts=19, gp=20, position=9)
        result = mls_tracker.compute_scenarios(target, cutoff)
        assert result["status"] == "contention"
        assert "worst_case" in result
        assert "easiest_path" in result

    def test_need_help(self):
        # Target can win out to 46+42=88 total? No, let's calibrate:
        # target: 30 pts, 20 gp → 14 remaining → max 30+42=72
        # cutoff: 40 pts, 20 gp → 14 remaining → projected = 40 + 14*(40/20) = 40+28=68
        # max_possible_target (72) >= projected (68) → not need_help? Actually need_help requires
        # max_possible_target < projected. So let's make projected > max_possible:
        # target: 20 pts, 20 gp → max = 20+42 = 62
        # cutoff: 45 pts, 20 gp → projected = 45 + 14*(45/20) = 45+31.5 = 76.5
        # 62 < 76.5 → need_help, and not eliminated since 62 >= 45
        target = _make_team("Struggling", pts=20, gp=20, position=7)
        cutoff = _make_team("Strong9", pts=45, gp=20, position=9)
        result = mls_tracker.compute_scenarios(target, cutoff)
        assert result["status"] == "need_help"
        assert result["need_help_info"] is not None

    def test_response_shape(self):
        target = _make_team("Any", pts=30, gp=20, position=5)
        cutoff = _make_team("CutTeam", pts=25, gp=20, position=9)
        result = mls_tracker.compute_scenarios(target, cutoff)
        assert "status" in result
        assert "target" in result
        assert "cutoff" in result
        assert "worst_case" in result
        assert "easiest_path" in result
        assert "points_to_safety" in result
        assert "ppg_required" in result
        assert result["target"]["name"] == "Any"
        assert result["cutoff"]["name"] == "CutTeam"


# ============================================================
# Unit tests — merge_team_metadata
# ============================================================

class TestMergeTeamMetadata:
    def test_merges_by_id(self):
        standings = {"East": [{"id": "1", "name": "Team Alpha", "position": 1}]}
        teams = [{"id": "1", "name": "Team Alpha", "colors": {"primary": "#red"}, "logo": "x.png", "abbreviation": "ALP"}]
        result = mls_tracker.merge_team_metadata(standings, teams)
        assert result["East"][0]["colors"]["primary"] == "#red"
        assert result["East"][0]["logo"] == "x.png"

    def test_merges_by_name_fallback(self):
        standings = {"East": [{"id": "999", "name": "Team Alpha", "position": 1}]}
        teams = [{"id": "1", "name": "Team Alpha", "colors": {"primary": "#red"}, "logo": "x.png", "abbreviation": "ALP"}]
        result = mls_tracker.merge_team_metadata(standings, teams)
        assert result["East"][0]["colors"]["primary"] == "#red"

    def test_missing_metadata_gets_defaults(self):
        standings = {"East": [{"id": "999", "name": "Unknown FC", "position": 1}]}
        teams = []
        result = mls_tracker.merge_team_metadata(standings, teams)
        # Should get default colors (from process_team_colors("", ""))
        assert "primary" in result["East"][0]["colors"]

    def test_does_not_mutate_original(self):
        original = {"id": "1", "name": "Team Alpha", "position": 1}
        standings = {"East": [original]}
        teams = [{"id": "1", "name": "Team Alpha", "colors": {"primary": "#red"}, "logo": "x.png", "abbreviation": "ALP"}]
        mls_tracker.merge_team_metadata(standings, teams)
        assert "colors" not in original  # Should not mutate


# ============================================================
# API endpoint tests — GET /
# ============================================================

class TestIndexEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_returns_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_contains_app_markers(self, client):
        resp = client.get("/")
        assert "MLS Playoff Tracker" in resp.text
        assert "<div id=" in resp.text


# ============================================================
# API endpoint tests — GET /api/data
# ============================================================

class TestApiData:
    def test_success_default_season(self, client):
        resp = client.get("/api/data")
        assert resp.status_code == 200
        data = resp.json()
        assert "season" in data
        assert "conferences" in data

    def test_explicit_season(self, client):
        resp = client.get("/api/data?season=2024")
        assert resp.status_code == 200
        data = resp.json()
        assert data["season"] == 2024

    def test_conference_structure(self, client):
        resp = client.get("/api/data")
        data = resp.json()
        confs = data["conferences"]
        assert len(confs) >= 1
        for conf_name, teams in confs.items():
            assert isinstance(teams, list)
            assert len(teams) > 0
            team = teams[0]
            for key in ("position", "name", "id", "gp", "w", "l", "t", "pts", "gf", "ga", "gd", "ppg"):
                assert key in team, f"Missing key {key} in team"
            assert "colors" in team
            assert "logo" in team

    def test_teams_sorted_by_position(self, client):
        resp = client.get("/api/data")
        data = resp.json()
        for _, teams in data["conferences"].items():
            positions = [t["position"] for t in teams]
            assert positions == sorted(positions)

    def test_espn_failure_returns_empty_conferences(self, client):
        """When ESPN is unreachable, fetch helpers return empty data; endpoint still returns 200."""
        import requests as req_lib
        with patch("mls_tracker.requests.get", side_effect=req_lib.exceptions.ConnectionError("timeout")):
            mls_tracker.cache.invalidate()
            resp = client.get("/api/data")
            assert resp.status_code == 200
            data = resp.json()
            assert data["conferences"] == {}


# ============================================================
# API endpoint tests — GET /api/scenarios
# ============================================================

class TestApiScenarios:
    def test_success(self, client):
        resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=9")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("clinched", "eliminated", "contention", "need_help")
        assert "conference" in data

    def test_team_not_found(self, client):
        resp = client.get("/api/scenarios?team=Nonexistent+FC&season=2025&cutoff=9")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_cutoff_too_high(self, client):
        resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=99")
        assert resp.status_code == 400
        assert "out of range" in resp.json()["detail"].lower()

    def test_cutoff_too_low(self, client):
        resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=0")
        assert resp.status_code == 400

    def test_default_parameters(self, client):
        """Endpoint works with defaults (team defaults to 'Atlanta United FC' which won't be in mock data)."""
        resp = client.get("/api/scenarios")
        # Default team 'Atlanta United FC' won't exist in mock → 404
        assert resp.status_code == 404

    def test_scenarios_response_shape(self, client):
        resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=9")
        data = resp.json()
        assert "target" in data
        assert "cutoff" in data
        assert "worst_case" in data
        assert "easiest_path" in data
        assert "points_to_safety" in data
        assert "ppg_required" in data
        # Target info
        assert data["target"]["name"] == "Team Alpha"
        # Cutoff should be 9th place team
        assert data["cutoff"]["position"] == 9

    def test_team_at_cutoff_position(self, client):
        """Team at exactly the cutoff position should still get valid scenarios."""
        resp = client.get("/api/scenarios?team=Team+India&season=2025&cutoff=9")
        assert resp.status_code == 200
        data = resp.json()
        # Comparing against itself
        assert data["target"]["name"] == "Team India"
        assert data["cutoff"]["name"] == "Team India"

    def test_espn_failure_returns_404(self, client):
        """When ESPN is unreachable, standings are empty, so the team is not found → 404."""
        import requests as req_lib
        with patch("mls_tracker.requests.get", side_effect=req_lib.exceptions.ConnectionError("timeout")):
            mls_tracker.cache.invalidate()
            resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=9")
            assert resp.status_code == 404


# ============================================================
# API endpoint tests — POST /api/refresh
# ============================================================

class TestApiRefresh:
    def test_returns_ok(self, client):
        resp = client.post("/api/refresh")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_actually_clears_cache(self, client):
        # Populate cache
        client.get("/api/data?season=2025")
        assert mls_tracker.cache._teams is not None
        assert 2025 in mls_tracker.cache._standings

        # Refresh
        resp = client.post("/api/refresh")
        assert resp.status_code == 200
        assert mls_tracker.cache._teams is None
        assert len(mls_tracker.cache._standings) == 0

    def test_get_method_not_allowed(self, client):
        resp = client.get("/api/refresh")
        assert resp.status_code == 405


# ============================================================
# API edge cases — invalid methods, unknown routes
# ============================================================

class TestEdgeCases:
    def test_unknown_route_returns_404(self, client):
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404

    def test_post_to_data_not_allowed(self, client):
        resp = client.post("/api/data")
        assert resp.status_code == 405

    def test_post_to_scenarios_not_allowed(self, client):
        resp = client.post("/api/scenarios")
        assert resp.status_code == 405

    def test_season_as_string_param(self, client):
        """FastAPI should reject non-integer season."""
        resp = client.get("/api/data?season=abc")
        assert resp.status_code == 422

    def test_cutoff_as_string_param(self, client):
        resp = client.get("/api/scenarios?team=Team+Alpha&cutoff=abc")
        assert resp.status_code == 422


# ============================================================
# Integration-style: data flow through cache → merge → response
# ============================================================

class TestDataFlow:
    def test_data_endpoint_returns_merged_colors(self, client):
        """Verify that /api/data returns teams with merged color metadata from the teams endpoint."""
        resp = client.get("/api/data?season=2025")
        data = resp.json()
        east = data["conferences"].get("Eastern Conference", [])
        alpha = next((t for t in east if t["name"] == "Team Alpha"), None)
        assert alpha is not None
        # Team Alpha has color=C8102E which is not low-contrast → should be primary
        assert alpha["colors"]["primary"] == "#C8102E"
        assert alpha["logo"] == "https://cdn/alpha.png"

    def test_black_primary_team_gets_swapped_colors(self, client):
        """Team Bravo has black primary → should swap to alt color."""
        resp = client.get("/api/data?season=2025")
        data = resp.json()
        east = data["conferences"].get("Eastern Conference", [])
        bravo = next((t for t in east if t["name"] == "Team Bravo"), None)
        assert bravo is not None
        assert bravo["colors"]["primary"] == "#80FF00"

    def test_scenarios_uses_correct_conference(self, client):
        """Verify scenarios are computed within the correct conference."""
        resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=9")
        data = resp.json()
        assert data["conference"] == "Eastern Conference"

    def test_cache_serves_same_data_on_repeat(self, client):
        """Two calls should return identical data (cache hit)."""
        r1 = client.get("/api/data?season=2025").json()
        r2 = client.get("/api/data?season=2025").json()
        assert r1 == r2


# ============================================================
# Audit regression tests
# ============================================================

class TestAuditFinding2_CacheBound:
    """Finding #2: Cache should evict oldest season when exceeding max."""

    def test_cache_does_not_grow_unbounded(self):
        cache = mls_tracker.DataCache(ttl=300)
        for yr in range(2020, 2025):
            cache.get_standings(yr)
        assert len(cache._standings) <= 3, (
            f"Cache holds {len(cache._standings)} seasons; expected <= 3"
        )


class TestAuditFinding4_ErrorDetailLeak:
    """Finding #4: 500 responses must not leak internal exception text."""

    def test_data_500_does_not_leak_exception(self, client):
        sentinel = "INTERNAL_SECRET_PATH_42"
        with patch("mls_tracker.merge_team_metadata", side_effect=RuntimeError(sentinel)):
            mls_tracker.cache.invalidate()
            resp = client.get("/api/data?season=2025")
            assert resp.status_code == 500
            assert sentinel not in resp.text, "Internal exception text leaked in 500 response"

    def test_scenarios_500_does_not_leak_exception(self, client):
        sentinel = "INTERNAL_SECRET_PATH_99"
        with patch("mls_tracker.compute_scenarios", side_effect=RuntimeError(sentinel)):
            mls_tracker.cache.invalidate()
            resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=9")
            assert resp.status_code == 500
            assert sentinel not in resp.text, "Internal exception text leaked in 500 response"


class TestAuditFinding6_NeedHelpClamped:
    """Finding #6: max_wins + max_ties must not exceed games remaining."""

    def test_max_wins_capped_by_games_remaining(self):
        # Cutoff: 10 pts, 30 gp → 4 games remaining
        # max_possible_target large enough to produce delta >> gr_cutoff
        cutoff = {"name": "Rival", "pts": 10, "gp": 30, "position": 9, "ppg": 0.333}
        result = mls_tracker._compute_need_help(cutoff, season_games=34, max_possible_target=80)
        gr_cutoff = 4
        assert result["max_wins"] + result["max_ties"] <= gr_cutoff, (
            f"max_wins ({result['max_wins']}) + max_ties ({result['max_ties']}) = "
            f"{result['max_wins'] + result['max_ties']}; exceeds games remaining ({gr_cutoff})"
        )

    def test_max_wins_does_not_exceed_games_remaining(self):
        # Cutoff: 5 pts, 32 gp → 2 games remaining, limit_pts = 99
        cutoff = {"name": "Underdog", "pts": 5, "gp": 32, "position": 9, "ppg": 0.156}
        result = mls_tracker._compute_need_help(cutoff, season_games=34, max_possible_target=100)
        gr_cutoff = 2
        assert result["max_wins"] <= gr_cutoff, (
            f"max_wins ({result['max_wins']}) exceeds games remaining ({gr_cutoff})"
        )


class TestAuditFinding8_WarningsField:
    """Finding #8: /api/data should include warnings when ESPN data is empty."""

    def test_espn_failure_includes_warnings(self, client):
        import requests as req_lib
        with patch("mls_tracker.requests.get", side_effect=req_lib.exceptions.ConnectionError("timeout")):
            mls_tracker.cache.invalidate()
            resp = client.get("/api/data")
            data = resp.json()
            assert "warnings" in data, "Response missing 'warnings' field"
            assert len(data["warnings"]) > 0, "Expected non-empty warnings when ESPN is unreachable"

    def test_success_has_empty_warnings(self, client):
        resp = client.get("/api/data?season=2025")
        data = resp.json()
        assert "warnings" in data, "Response missing 'warnings' field"
        assert data["warnings"] == []
