"""Synthetic API-shaped model builders. Every name here is invented."""
import re


def model(name, index=None, cost=None, maker="Example Lab", slug=None, release="2026-01-01", total=None, scores=None) -> dict:
    slug = slug or re.sub(r"[^a-z0-9]", "-", name.lower())
    return {
        "slug": slug,
        "name": name,
        "release_date": release,
        "model_creator": {"name": maker},
        "evaluations": {"artificial_analysis_intelligence_index": index, **{
            "artificial_analysis_" + field + "_index": (scores or {}).get(key)
            for key, field in (("coding", "coding"), ("agentic", "agentic"), ("economics", "economics"),
                               ("engineering", "engineering"), ("finance", "finance_and_accounting"),
                               ("healthcare", "healthcare_and_medical"), ("legal", "legal"),
                               ("strategy", "strategy_and_ops"))}},
        "artificial_analysis_intelligence_index_cost": None if index is None else {
            "total_cost": total,
            "cost_per_task": {"total_cost": cost} if cost is not None else None,
        },
        "pricing": {},
        "performance": {},
        "performance_v3": {},
    }


MAKER = "Example Lab"
OTHER_MAKER = "Sample Works"
RATE = {"limit": 100, "remaining": 95, "reset": 1_800_000_000}

# The Task 4 fixture as API models, plus a rungless family, a family with no
# cost and a pair that collides on family and rung. All invented.
LADDER = [
    ("Alpha Test 1 (Medium)", 40.4, 2.0),
    ("Alpha Test 1 (High)", 45.8, 5.0),
    ("Alpha Test 1 (XHigh)", 46.2, 8.0),
    ("Alpha Test 1 (Max)", 48.6, 14.0),
    ("Beta Test 1 (Medium)", 32.2, 1.0),
    ("Beta Test 1 (High)", 35.8, 1.4),
    ("Beta Test 1 (XHigh)", 41.4, 3.0),
    ("Beta Test 1 (Max)", 43.1, 5.5),
]


def ladder_models() -> list[dict]:
    """Fresh copies of the shared synthetic ladder."""
    return [model(name, index, cost, maker=MAKER) for name, index, cost in LADDER] + [
        model("Gamma Test 1", 20.0, 0.30, maker=OTHER_MAKER),
        model("Delta Test 1 (Low)", 15.0, None, maker=OTHER_MAKER),
        model("Eta Test 1 (High)", 30.0, 0.80, maker=OTHER_MAKER, slug="eta-test-1-high"),
        model("Eta Test 1 (High, Preview)", 31.0, 0.90, maker=OTHER_MAKER, slug="eta-test-1-high-preview"),
    ]


def snapshot(models, *, when="2026-11-05T10:00:00+00:00", checked=None, version=5) -> dict:
    """A snapshot dict shaped like read_snapshot's result."""
    return {"schema": 1, "fetched_at": when, "last_checked": checked or when,
            "index_version": version, "rate_limit": dict(RATE), "models": models}
