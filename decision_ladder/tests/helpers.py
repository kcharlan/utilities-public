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


def many_systems(n):
    return [system(key=f'synthetic-{i:03}', name=f'Synthetic system {i:03}',
                   capability={'score': 100 - (i % 40), 'eligible': True, 'within_caps': True},
                   price={'kind': 'estimate', 'usd_per_1000_decisions': 1 + i / 1000},
                   latency={'p50_s_adjusted': 1 + i / 1000}) for i in range(1, n + 1)]
