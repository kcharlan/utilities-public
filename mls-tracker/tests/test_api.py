"""Tests for the MLS Tracker backend API and helper functions.

Strategy:
- Helper/computation functions are tested directly (unit tests).
- API endpoints are tested via FastAPI's TestClient with mocked ESPN calls.
- No real network calls; all external HTTP is mocked.
"""
import subprocess
import threading
import time
from concurrent.futures import Future
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
from tools.testkit import ASGISyncClient

import mls_tracker

REAL_FETCH_LOGO_DATA = mls_tracker.fetch_logo_data
SYNTHETIC_PNG = b"\x89PNG\r\n\x1a\nsynthetic"
SYNTHETIC_PNG_URL = "data:image/png;base64,iVBORw0KGgpzeW50aGV0aWM="


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
                _make_team_entry(1, "Team Alpha", "ALP", "C8102E", "1D428A", "https://a.espncdn.com/i/teamlogos/soccer/500/alpha.png"),
                _make_team_entry(2, "Team Bravo", "BRV", "000000", "80FF00", "https://a.espncdn.com/i/teamlogos/soccer/500/bravo.png"),
                _make_team_entry(3, "Team Charlie", "CHR", "ffffff", "FF5733", "https://a.espncdn.com/i/teamlogos/soccer/500/charlie.png"),
                _make_team_entry(4, "Team Delta", "DLT", "1D428A", "", "https://a.espncdn.com/i/teamlogos/soccer/500/delta.png"),
                _make_team_entry(5, "Team Echo", "ECH", "", "", ""),
                _make_team_entry(6, "Team Foxtrot", "FOX", "3366CC", "AABBCC", "https://a.espncdn.com/i/teamlogos/soccer/500/foxtrot.png"),
                _make_team_entry(7, "Team Golf", "GLF", "228B22", "FFD700", "https://a.espncdn.com/i/teamlogos/soccer/500/golf.png"),
                _make_team_entry(8, "Team Hotel", "HTL", "8B0000", "DC143C", "https://a.espncdn.com/i/teamlogos/soccer/500/hotel.png"),
                _make_team_entry(9, "Team India", "IND", "4B0082", "EE82EE", "https://a.espncdn.com/i/teamlogos/soccer/500/india.png"),
                _make_team_entry(10, "Team Juliet", "JUL", "DAA520", "B8860B", "https://a.espncdn.com/i/teamlogos/soccer/500/juliet.png"),
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
    if url.startswith("https://a.espncdn.com/i/teamlogos/soccer/"):
        resp.status_code = 200
        resp.headers = {"Content-Type": "image/png"}
        resp.__enter__.return_value = resp
        resp.raw.read1.side_effect = [SYNTHETIC_PNG, b""]
    elif "teams" in url:
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
    mls_tracker.logo_cache.clear()
    with patch("mls_tracker.requests.get", side_effect=_mock_requests_get), patch(
        "mls_tracker.fetch_logo_data", side_effect=mls_tracker._fetch_logo_data
    ):
        yield


@pytest.fixture
def client():
    """Synchronous HTTPX client for the FastAPI app."""
    return ASGISyncClient(mls_tracker.app)


# ============================================================
# Unit tests — safe_int
# ============================================================

@pytest.mark.parametrize("value,expected", [
    (42, 42), ("7", 7), (3.9, 3), ("3.9", 3),
    (None, 0), ("abc", 0), ("", 0), (-10, -10), (0, 0),
])
def test_safe_int(value, expected):
    assert mls_tracker.safe_int(value) == expected


def test_safe_int_explicit_default():
    assert mls_tracker.safe_int(None, 5) == 5


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

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_strings(self, value):
        result = mls_tracker.process_team_colors(value, value)
        assert result["primary"] == "#6366f1"  # fallback indigo
        assert result["secondary"] == "#1f2937"
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

    def test_teams_are_refetched_after_ttl(self, monkeypatch):
        cache = mls_tracker.DataCache(ttl=1)
        now = time.time()
        monkeypatch.setattr(mls_tracker.time, "time", lambda: now)
        first = cache.get_teams()
        monkeypatch.setattr(mls_tracker.time, "time", lambda: now + 2)
        second = cache.get_teams()
        assert second is not first
        team_requests = [call for call in mls_tracker.requests.get.call_args_list
                         if "teams" in call.args[0]]
        assert len(team_requests) == 2

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
    def test_contention_numbers_match_hand_calculation(self):
        target = _make_team("Target", pts=30, gp=20, position=10)
        cutoff = _make_team("Cutoff", pts=40, gp=20, position=9)
        result = mls_tracker.compute_scenarios(target, cutoff)
        assert result["status"] == "contention"
        assert result["cutoff"]["projected"] == 68.0
        assert result["worst_case"] == {
            "wins": 13, "ties": 0, "losses": 1, "final_pts": 69, "possible": True,
        }
        assert result["easiest_path"] == {
            "wins": 13, "ties": 1, "losses": 0, "final_pts": 70, "possible": True,
        }
        assert result["points_to_safety"] == 39
        assert result["ppg_required"] == 2.79
        assert result["target"]["max_possible"] == 72
        assert result["cutoff"]["max_possible"] == 82

    def test_equal_max_is_not_clinched(self):
        target = _make_team("Target", pts=50, gp=30, position=1)
        cutoff = _make_team("Cutoff", pts=41, gp=31, position=9)
        assert mls_tracker.compute_scenarios(target, cutoff)["status"] == "contention"

    def test_equal_max_is_not_eliminated(self):
        target = _make_team("Target", pts=20, gp=30, position=10)
        cutoff = _make_team("Cutoff", pts=32, gp=30, position=9)
        assert mls_tracker.compute_scenarios(target, cutoff)["status"] == "need_help"

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
# Unit tests — fetch_standings_from_espn
# ============================================================

class TestFetchStandings:
    def test_maps_fixture_team(self):
        standings = mls_tracker.fetch_standings_from_espn(2025)
        assert standings["Eastern Conference"][0] == {
            "position": 1, "name": "Team Alpha", "id": "1", "gp": 20,
            "w": 14, "l": 2, "t": 4, "pts": 46, "gf": 35, "ga": 15,
            "gd": 20, "ppg": 2.3,
        }

    def test_string_stats_and_missing_rank(self):
        ranked = _make_standing_entry(
            1, "Team Alpha", "1.0", "20.0", "14.0", "2.0", "4.0", "46.0", "35.0", "15.0"
        )
        rankless = _make_standing_entry(2, "Team Bravo", 2, 20, 12, 4, 4, 40, 30, 18)
        rankless["stats"] = [stat for stat in rankless["stats"] if stat["name"] != "rank"]
        response = MagicMock()
        response.json.return_value = {"children": [{
            "name": "Synthetic Conference", "standings": {"entries": [rankless, ranked]},
        }]}
        with patch("mls_tracker.requests.get", return_value=response):
            teams = mls_tracker.fetch_standings_from_espn(2025)["Synthetic Conference"]
        assert teams[0] == {
            "position": 1, "name": "Team Alpha", "id": "1", "gp": 20,
            "w": 14, "l": 2, "t": 4, "pts": 46, "gf": 35, "ga": 15,
            "gd": 20, "ppg": 2.3,
        }
        assert teams[1]["name"] == "Team Bravo"
        assert teams[1]["position"] == 99


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

    def test_espn_failure_returns_error(self, client):
        """An unavailable upstream is not a successful empty response."""
        import requests as req_lib
        with patch("mls_tracker.requests.get", side_effect=req_lib.exceptions.ConnectionError("timeout")):
            mls_tracker.cache.invalidate()
            resp = client.get("/api/data")
            assert resp.status_code == 500
            assert resp.json() == {"detail": "Internal server error"}


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

    def test_espn_failure_returns_error(self, client):
        """An unavailable upstream cannot establish whether a team exists."""
        import requests as req_lib
        with patch("mls_tracker.requests.get", side_effect=req_lib.exceptions.ConnectionError("timeout")):
            mls_tracker.cache.invalidate()
            resp = client.get("/api/scenarios?team=Team+Alpha&season=2025&cutoff=9")
            assert resp.status_code == 500


# ============================================================
# API endpoint tests — POST /api/refresh
# ============================================================

class TestApiRefresh:
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
        assert alpha["logo"] == SYNTHETIC_PNG_URL

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

    def test_empty_standings_include_warnings(self, client):
        with patch("mls_tracker.fetch_standings_from_espn", return_value={}):
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


def test_logo_is_embedded_and_network_request_is_bounded():
    logo = b'\x89PNG\r\n\x1a\nsynthetic'
    response = MagicMock(status_code=200, headers={'Content-Type': 'image/png'})
    response.__enter__.return_value = response
    response.raw.read1.side_effect = [logo, b""]
    with patch('mls_tracker.requests.get', return_value=response) as get:
        result = mls_tracker._fetch_logo_data('https://a.espncdn.com/i/teamlogos/soccer/500/123.png')
    assert result == 'data:image/png;base64,iVBORw0KGgpzeW50aGV0aWM='
    assert get.call_args.kwargs['allow_redirects'] is False
    assert get.call_args.kwargs['stream'] is True
    assert get.call_args.kwargs['timeout'] == (3, 5)


def test_logo_rejects_untrusted_redirects_oversize_and_errors():
    with patch('mls_tracker.requests.get') as get:
        for url in ('http://a.espncdn.com/i/teamlogos/soccer/500/x.png',
                    'https://a.espncdn.com.example.invalid/i/teamlogos/soccer/500/x.png',
                    'https://a.espncdn.com:443/i/teamlogos/soccer/500/x.png',
                    'https://a.espncdn.com/other/x.png'):
            assert mls_tracker._fetch_logo_data(url) == ''
        get.assert_not_called()
        response = MagicMock(status_code=302, headers={'Content-Type': 'image/png'})
        response.__enter__.return_value = response
        get.return_value = response
        url = 'https://a.espncdn.com/i/teamlogos/soccer/500/x.png'
        assert mls_tracker._fetch_logo_data(url) == ''
        response.status_code = 200
        response.headers['Content-Encoding'] = 'gzip'
        assert mls_tracker._fetch_logo_data(url) == ''
        del response.headers['Content-Encoding']
        response.raw.read1.side_effect = [b'x' * (mls_tracker.MAX_LOGO_BYTES + 1)]
        assert mls_tracker._fetch_logo_data(url) == ''
        get.side_effect = mls_tracker.requests.exceptions.Timeout('synthetic timeout')
        assert mls_tracker._fetch_logo_data(url) == ''


def test_team_fetch_embeds_logo_using_cached_metadata():
    payload = {'sports': [{'leagues': [{'teams': [_make_team_entry(
        1, 'Synthetic Team', 'SYN', '123456', 'abcdef',
        'https://a.espncdn.com/i/teamlogos/soccer/500/123.png')]}]}]}
    response = MagicMock()
    response.json.return_value = payload
    with patch('mls_tracker.requests.get', return_value=response), patch(
        'mls_tracker.fetch_logo_data', return_value='data:image/png;base64,c3ludGhldGlj'
    ) as embed:
        cache = mls_tracker.DataCache()
        assert cache.get_teams()[0]['logo'] == 'data:image/png;base64,c3ludGhldGlj'
        cache.get_teams()
        embed.assert_called_once()


def test_logo_rejects_normalized_and_encoded_path_escape():
    base = 'https://a.espncdn.com/i/teamlogos/soccer/'
    with patch('mls_tracker.requests.get') as get:
        for path in ('../../../other.png', '%2e%2e/%2e%2e/%2e%2e/other.png',
                     '%2e%2e%2fother.png', '500/%2e%2e/../../other.png'):
            assert mls_tracker._fetch_logo_data(base + path) == ''
        get.assert_not_called()


def test_logo_slow_trickle_exceeds_total_deadline_and_closes(caplog):
    response = MagicMock(status_code=200, headers={'Content-Type': 'image/png'})
    response.__enter__.return_value = response
    clock = [0.0]
    def trickle(*args, **kwargs):
        clock[0] += 2
        return b'x'
    response.raw.read1.side_effect = trickle
    response.iter_content.side_effect = lambda **kwargs: (trickle() for _ in range(6))
    with patch('mls_tracker.requests.get', return_value=response), patch(
        'mls_tracker.time.monotonic', side_effect=lambda: clock[0]
    ):
        assert mls_tracker._fetch_logo_data('https://a.espncdn.com/i/teamlogos/soccer/500/123.png') == ''
    response.__exit__.assert_called_once()
    assert 'deadline' in caplog.text.lower()


def test_logo_worker_deadline_kills_and_reaps_real_sleeping_child(tmp_path, monkeypatch, caplog):
    import os
    pid_file = tmp_path / 'synthetic-worker.pid'
    code = (f"import os,time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); "
            "time.sleep(30)")
    monkeypatch.setattr(mls_tracker, 'LOGO_WORKER_CODE', code)
    monkeypatch.setattr(mls_tracker, 'LOGO_DEADLINE_SECONDS', 1)
    start = time.monotonic()
    assert REAL_FETCH_LOGO_DATA('https://a.espncdn.com/i/teamlogos/soccer/500/123.png') == ''
    assert time.monotonic() - start < 5
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert 'deadline' in caplog.text.lower()


def test_logo_worker_returns_successful_result(monkeypatch):
    monkeypatch.setattr(mls_tracker, 'LOGO_WORKER_CODE', "print('data:image/png;base64,c3ludGhldGlj', end='')")
    assert REAL_FETCH_LOGO_DATA('https://a.espncdn.com/i/teamlogos/soccer/500/123.png') == 'data:image/png;base64,c3ludGhldGlj'


def test_logo_worker_runs_transport_on_synthetic_response(monkeypatch):
    code = (
        "import runpy,sys; from unittest.mock import MagicMock; "
        "m=runpy.run_path(sys.argv[1], run_name='mls_logo_worker'); "
        "r=MagicMock(status_code=200, headers={'Content-Type':'image/png'}); "
        "r.__enter__.return_value=r; r.raw.read1.side_effect=[b'\\x89PNG\\r\\n\\x1a\\nsynthetic',b'']; "
        "m['_fetch_logo_data'].__globals__['requests'].get=lambda *a,**k:r; "
        "print(m['_fetch_logo_data'](sys.argv[2]),end='')"
    )
    monkeypatch.setattr(mls_tracker, 'LOGO_WORKER_CODE', code)
    assert REAL_FETCH_LOGO_DATA('https://a.espncdn.com/i/teamlogos/soccer/500/123.png') == SYNTHETIC_PNG_URL


def test_parent_rejects_unsafe_logo_before_worker():
    with patch('mls_tracker.subprocess.run') as run:
        assert REAL_FETCH_LOGO_DATA('https://a.espncdn.com/i/teamlogos/soccer/../../../other.png') == ''
        run.assert_not_called()


def test_logo_worker_ignores_a_shadowing_module_in_the_launch_directory(tmp_path):
    marker = tmp_path / "shadow-ran"
    (tmp_path / "requests.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    with patch("mls_tracker.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        REAL_FETCH_LOGO_DATA("https://a.espncdn.com/i/teamlogos/soccer/500/123.png")
    argv = run.call_args.args[0]
    # The worker rejects this address before any request, so nothing reaches the network.
    argv[-1] = "https://not-espn.invalid/i/teamlogos/soccer/500/123.png"

    result = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=30)

    assert not marker.exists()
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


class TestLogoContent:
    URL = "https://a.espncdn.com/i/teamlogos/soccer/500/123.png"

    @staticmethod
    def _fetch(body, media_type):
        response = MagicMock(status_code=200, headers={"Content-Type": media_type})
        response.__enter__.return_value = response
        response.raw.read1.side_effect = [body, b""]
        with patch("mls_tracker.requests.get", return_value=response):
            return mls_tracker._fetch_logo_data(TestLogoContent.URL)

    @pytest.mark.parametrize(
        ("body", "media_type"),
        [
            (SYNTHETIC_PNG, "image/png"),
            (b"\xff\xd8\xff\xe0synthetic", "image/jpeg"),
            (b"RIFF\x10\x00\x00\x00WEBPsynthetic", "image/webp"),
        ],
    )
    def test_accepts_bytes_matching_the_declared_type(self, body, media_type):
        assert self._fetch(body, media_type).startswith(f"data:{media_type};base64,")

    @pytest.mark.parametrize(
        ("body", "media_type"),
        [
            (b"<html>synthetic</html>", "image/png"),
            (b"\xff\xd8\xff\xe0synthetic", "image/png"),
            (SYNTHETIC_PNG, "image/jpeg"),
            (b"RIFF\x10\x00\x00\x00WAVEsynthetic", "image/webp"),
            (b"", "image/png"),
        ],
    )
    def test_rejects_bytes_not_matching_the_declared_type(self, body, media_type):
        assert self._fetch(body, media_type) == ""


class TestLogoHref:
    @pytest.mark.parametrize("href", [5, None, ["synthetic"], {"synthetic": 1}, b"synthetic"])
    def test_non_string_href_is_invalid(self, href):
        assert mls_tracker._valid_logo_url(href) is False
        assert REAL_FETCH_LOGO_DATA(href) == ""

    @pytest.mark.parametrize("href", [5, ["synthetic"]])
    def test_non_string_href_leaves_a_blank_logo_in_the_response(self, client, href):
        payload = {"sports": [{"leagues": [{"teams": [_make_team_entry(
            1, "Team Alpha", "ALP", "123456", "abcdef", href)]}]}]}

        def espn(url, **kwargs):
            if "teams" not in url:
                return _mock_requests_get(url, **kwargs)
            response = MagicMock()
            response.json.return_value = payload
            return response

        with patch("mls_tracker.requests.get", side_effect=espn):
            resp = client.get("/api/data?season=2025")

        assert resp.status_code == 200
        assert resp.json()["conferences"]["Eastern Conference"][0]["logo"] == ""


class TestLogoCache:
    URL_A = "https://a.espncdn.com/i/teamlogos/soccer/500/a.png"
    URL_B = "https://a.espncdn.com/i/teamlogos/soccer/500/b.png"
    URL_C = "https://a.espncdn.com/i/teamlogos/soccer/500/c.png"

    def test_good_logos_survive_data_expiry_and_manual_refresh(self, client):
        with patch("mls_tracker.fetch_logo_data", return_value=SYNTHETIC_PNG_URL) as fetch:
            client.get("/api/data?season=2025")
            downloads = fetch.call_count
            assert downloads > 0
            client.post("/api/refresh")
            mls_tracker.cache._teams_ts = 0
            resp = client.get("/api/data?season=2025")

        assert fetch.call_count == downloads
        assert resp.json()["conferences"]["Eastern Conference"][0]["logo"] == SYNTHETIC_PNG_URL

    def test_downloads_each_distinct_url_once(self):
        logos = mls_tracker.LogoCache()
        with patch("mls_tracker.fetch_logo_data", return_value="data:one") as fetch:
            assert logos.resolve([self.URL_A, self.URL_A, ""]) == ["data:one", "data:one", ""]
        fetch.assert_called_once_with(self.URL_A)

    def test_expired_logo_is_replaced_by_a_good_download(self):
        logos = mls_tracker.LogoCache(ttl=100)
        with patch("mls_tracker.time.time", return_value=1000.0), patch(
            "mls_tracker.fetch_logo_data", return_value="data:old"
        ):
            logos.resolve([self.URL_A])
        with patch("mls_tracker.time.time", return_value=1050.0), patch(
            "mls_tracker.fetch_logo_data", return_value="data:new"
        ) as within_lifetime:
            assert logos.resolve([self.URL_A]) == ["data:old"]
        within_lifetime.assert_not_called()
        with patch("mls_tracker.time.time", return_value=1101.0), patch(
            "mls_tracker.fetch_logo_data", return_value="data:new"
        ):
            assert logos.resolve([self.URL_A]) == ["data:new"]

    def test_failed_refresh_keeps_a_good_logo_and_retries(self):
        logos = mls_tracker.LogoCache(ttl=100)
        with patch("mls_tracker.time.time", return_value=1000.0), patch(
            "mls_tracker.fetch_logo_data", return_value="data:good"
        ):
            logos.resolve([self.URL_A])
        with patch("mls_tracker.time.time", return_value=2000.0), patch(
            "mls_tracker.fetch_logo_data", return_value=""
        ):
            assert logos.resolve([self.URL_A]) == ["data:good"]
        with patch("mls_tracker.time.time", return_value=2001.0), patch(
            "mls_tracker.fetch_logo_data", return_value="data:later"
        ):
            assert logos.resolve([self.URL_A]) == ["data:later"]

    def test_failed_first_download_stays_blank_and_retries(self):
        logos = mls_tracker.LogoCache()
        with patch("mls_tracker.fetch_logo_data", return_value=""):
            assert logos.resolve([self.URL_A]) == [""]
        with patch("mls_tracker.fetch_logo_data", return_value="data:good"):
            assert logos.resolve([self.URL_A]) == ["data:good"]

    def test_total_payload_is_capped_and_only_kept_logos_are_stored(self, monkeypatch):
        monkeypatch.setattr(mls_tracker, "MAX_LOGO_PAYLOAD_CHARS", 10)
        sizes = {self.URL_A: "a" * 6, self.URL_B: "b" * 6, self.URL_C: "c" * 4}
        logos = mls_tracker.LogoCache()

        with patch("mls_tracker.fetch_logo_data", side_effect=sizes.get) as fetch:
            assert logos.resolve(list(sizes)) == [sizes[self.URL_A], "", sizes[self.URL_C]]
            assert logos.resolve(list(sizes)) == [sizes[self.URL_A], "", sizes[self.URL_C]]

        assert fetch.call_args_list.count(((self.URL_A,),)) == 1
        assert fetch.call_args_list.count(((self.URL_B,),)) == 2

    def test_partial_list_keeps_a_good_logo_until_it_expires(self):
        logos = mls_tracker.LogoCache(ttl=100)
        with patch("mls_tracker.time.time", return_value=1000.0), patch(
            "mls_tracker.fetch_logo_data", return_value="data:good"
        ):
            logos.resolve([self.URL_A, self.URL_B])
        with patch("mls_tracker.time.time", return_value=1050.0), patch(
            "mls_tracker.fetch_logo_data", return_value=""
        ) as fetch:
            logos.resolve([self.URL_B])
            assert logos.resolve([self.URL_A]) == ["data:good"]
        fetch.assert_not_called()

        with patch("mls_tracker.time.time", return_value=1101.0), patch(
            "mls_tracker.fetch_logo_data", side_effect=lambda url: "data:later" if url == self.URL_B else ""
        ):
            logos.resolve([self.URL_B])
            # Unlisted past its lifetime, so it was pruned and a failed download finds nothing.
            assert logos.resolve([self.URL_A]) == [""]

    def test_older_overlapping_resolve_keeps_a_newer_logo(self):
        logos = mls_tracker.LogoCache()

        def fetch(url):
            if url == self.URL_A:
                logos.resolve([self.URL_B])
                return "data:a"
            return "data:b"

        with patch("mls_tracker.fetch_logo_data", side_effect=fetch):
            assert logos.resolve([self.URL_A]) == ["data:a"]
        with patch("mls_tracker.fetch_logo_data", return_value="") as later:
            assert logos.resolve([self.URL_A, self.URL_B]) == ["data:a", "data:b"]
        later.assert_not_called()

    def test_older_failed_refresh_cannot_replace_a_newer_download(self):
        logos = mls_tracker.LogoCache(ttl=100)
        with patch("mls_tracker.time.time", return_value=1000.0), patch(
            "mls_tracker.fetch_logo_data", return_value="data:old"
        ):
            logos.resolve([self.URL_A])
        answers = iter(["", "data:new"])

        def fetch(url):
            answer = next(answers)
            if not answer:
                logos.resolve([self.URL_A])
            return answer

        with patch("mls_tracker.time.time", return_value=2000.0), patch(
            "mls_tracker.fetch_logo_data", side_effect=fetch
        ):
            assert logos.resolve([self.URL_A]) == ["data:old"]
        with patch("mls_tracker.time.time", return_value=2001.0), patch(
            "mls_tracker.fetch_logo_data", return_value=""
        ) as later:
            assert logos.resolve([self.URL_A]) == ["data:new"]
        later.assert_not_called()


class TestDataCacheFetchOutsideLock:
    @staticmethod
    def _blocking_fetch(values):
        started = threading.Event()
        release = threading.Event()
        remaining = iter(values)

        def fetch():
            started.set()
            assert release.wait(10)
            return next(remaining)

        return fetch, started, release

    @staticmethod
    @contextmanager
    def _parked_followers():
        """Count followers as they reach the shared flight, before it can resolve."""
        parked = threading.Semaphore(0)

        class ParkedFuture(Future):
            def result(self, timeout=None):
                parked.release()
                return super().result(timeout)

        with patch("mls_tracker.Future", ParkedFuture):
            yield parked

    def test_invalidate_does_not_wait_and_discards_the_running_fetch(self):
        cache = mls_tracker.DataCache()
        fetch, started, release = self._blocking_fetch([["before"], ["after"]])
        results = []
        with patch("mls_tracker.fetch_teams_from_espn", side_effect=fetch):
            reader = threading.Thread(target=lambda: results.append(cache.get_teams()))
            reader.start()
            assert started.wait(10)

            invalidator = threading.Thread(target=cache.invalidate)
            invalidator.start()
            invalidator.join(2)
            assert not invalidator.is_alive(), "invalidate waited for the network"

            release.set()
            reader.join(10)
            assert results == [["before"]]
            assert cache._teams is None
            assert cache.get_teams() == ["after"]

    def test_reader_after_invalidate_starts_its_own_fetch(self):
        cache = mls_tracker.DataCache()
        fetch, started, release = self._blocking_fetch([["before"], ["after"]])
        results = {}
        with patch("mls_tracker.fetch_teams_from_espn", side_effect=fetch) as teams:
            first = threading.Thread(target=lambda: results.update(first=cache.get_teams()))
            first.start()
            assert started.wait(10)
            cache.invalidate()
            second = threading.Thread(target=lambda: results.update(second=cache.get_teams()))
            second.start()
            deadline = time.monotonic() + 10
            while teams.call_count < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert teams.call_count == 2
            release.set()
            first.join(10)
            second.join(10)
        assert sorted(results.values()) == [["after"], ["before"]]

    def test_concurrent_readers_share_one_fetch(self):
        cache = mls_tracker.DataCache()
        fetch, started, release = self._blocking_fetch([{"season": "synthetic"}])
        results = []
        with self._parked_followers() as parked, patch(
            "mls_tracker.fetch_standings_from_espn", side_effect=lambda season: fetch()
        ) as standings:
            readers = [
                threading.Thread(target=lambda: results.append(cache.get_standings(2025)), daemon=True)
                for _ in range(4)
            ]
            readers[0].start()
            assert started.wait(10)
            for reader in readers[1:]:
                reader.start()
            # Every follower is waiting on the flight while its fetch is still held open.
            for _ in readers[1:]:
                assert parked.acquire(timeout=10)
            release.set()
            for reader in readers:
                reader.join(10)
                assert not reader.is_alive()
        assert standings.call_count == 1
        assert results == [{"season": "synthetic"}] * 4

    def _load_with_a_waiting_follower(self, cache, fetch, store):
        """Run a leader and one parked follower; return each one's outcome."""
        outcomes = {}

        def load(name):
            try:
                outcomes[name] = cache._load("synthetic", lambda: None, fetch, store)
            except RuntimeError as exc:
                outcomes[name] = exc

        return load, outcomes

    def test_waiting_follower_receives_the_leaders_fetch_failure(self):
        cache = mls_tracker.DataCache()
        started = threading.Event()
        release = threading.Event()
        fetches = []

        def fetch():
            fetches.append(1)
            started.set()
            assert release.wait(10)
            raise RuntimeError("synthetic fetch failure")

        load, outcomes = self._load_with_a_waiting_follower(cache, fetch, lambda value: None)
        with self._parked_followers() as parked:
            leader = threading.Thread(target=load, args=("leader",), daemon=True)
            follower = threading.Thread(target=load, args=("follower",), daemon=True)
            leader.start()
            assert started.wait(10)
            follower.start()
            assert parked.acquire(timeout=10)
            release.set()
            leader.join(10)
            follower.join(10)
            assert not leader.is_alive() and not follower.is_alive()

        assert len(fetches) == 1
        assert outcomes["follower"] is outcomes["leader"]
        assert str(outcomes["follower"]) == "synthetic fetch failure"
        assert not cache._flights

    def test_waiting_follower_is_resolved_when_store_raises(self):
        cache = mls_tracker.DataCache()
        fetch, started, release = self._blocking_fetch([["synthetic"]])

        def store(value):
            raise RuntimeError("synthetic store failure")

        load, outcomes = self._load_with_a_waiting_follower(cache, fetch, store)
        with self._parked_followers() as parked:
            leader = threading.Thread(target=load, args=("leader",), daemon=True)
            follower = threading.Thread(target=load, args=("follower",), daemon=True)
            leader.start()
            assert started.wait(10)
            follower.start()
            assert parked.acquire(timeout=10)
            release.set()
            leader.join(10)
            follower.join(10)
            assert not leader.is_alive() and not follower.is_alive(), "a follower waited forever"

        assert str(outcomes["leader"]) == "synthetic store failure"
        assert outcomes["follower"] is outcomes["leader"]
        assert not cache._flights

    def test_failed_fetch_is_not_cached(self):
        cache = mls_tracker.DataCache()
        calls = []

        def fail_once():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("synthetic fetch failure")
            return ["recovered"]

        with patch("mls_tracker.fetch_teams_from_espn", side_effect=fail_once):
            with pytest.raises(RuntimeError, match="synthetic fetch failure"):
                cache.get_teams()
            assert cache.get_teams() == ["recovered"]
