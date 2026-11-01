from tools.testkit import ASGISyncClient

import mls_tracker


def test_guard_rejects_foreign_host_and_origin_before_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(mls_tracker.cache, "invalidate", lambda: calls.append(True))
    client = ASGISyncClient(mls_tracker.app)
    assert client.get("/", headers={"Host": "foreign.example:8000"}).status_code == 403
    assert client.post("/api/refresh", headers={"Origin": "http://foreign.example"}).status_code == 403
    assert client.post("/api/refresh", headers={"Origin": ""}).status_code == 403
    assert calls == []
    assert client.post("/api/refresh").status_code == 200
    assert calls == [True]
