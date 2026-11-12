"""Conspicuously invented feed fixtures."""


def system(**overrides):
    return {"key": "synthetic", "name": "Synthetic", "board": "api", "ranked": True,
            "capability": {"within_caps": True, "eligible": True}, **overrides}


def feed(**overrides):
    return {"schema_version": 2, "revision": "synthetic", "method": {"label": "Synthetic"},
            "capability_policy": {"cost_cap_usd_per_1000": 5, "median_latency_cap_s": 10},
            "systems": [system()], **overrides}


def snapshot(data=None, when="2026-01-01T00:00:00+00:00"):
    return {"schema": 1, "fetched_at": when, "last_checked": when, "sha256": "synthetic",
            "feed": feed() if data is None else data}
