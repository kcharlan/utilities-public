from unittest.mock import Mock

import pytest
import requests
from tools.testkit import ASGISyncClient

import mls_tracker


@pytest.mark.parametrize("resource", ["teams", "standings"])
def test_failed_fetch_is_not_cached_and_retries(monkeypatch, resource):
    cache = mls_tracker.DataCache()
    good = Mock()
    good.json.return_value = {"sports": []} if resource == "teams" else {"children": []}
    get = Mock(side_effect=[requests.ConnectionError("synthetic outage"), good])
    monkeypatch.setattr(mls_tracker.requests, "get", get)
    load = cache.get_teams if resource == "teams" else lambda: cache.get_standings(2025)
    with pytest.raises(requests.RequestException):
        load()
    assert load() == ([] if resource == "teams" else {})
    assert get.call_count == 2


def test_fetch_failure_reaches_api_as_error_and_next_request_recovers(monkeypatch):
    cache = mls_tracker.DataCache()
    monkeypatch.setattr(mls_tracker, "cache", cache)
    good = Mock()
    good.json.return_value = {"children": []}
    monkeypatch.setattr(mls_tracker.requests, "get", Mock(side_effect=[requests.ConnectionError("synthetic"), good]))
    monkeypatch.setattr(mls_tracker, "fetch_teams_from_espn", lambda: [])
    client = ASGISyncClient(mls_tracker.app)
    assert client.get("/api/data?season=2025").status_code == 500
    assert client.get("/api/data?season=2025").status_code == 200
