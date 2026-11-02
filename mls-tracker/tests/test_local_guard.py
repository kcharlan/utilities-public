from concurrent.futures import ThreadPoolExecutor

from tools.testkit import ASGISyncClient, assert_local_server_guard

import mls_tracker


def test_shared_guard_contract():
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(assert_local_server_guard, mls_tracker.app,
                        post_path='/api/refresh').result()


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
