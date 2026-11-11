"""Synthetic API-shaped model builders. Every name here is invented."""
import re


def model(name, index=None, cost=None, maker="Example Lab", slug=None, release="2026-01-01", total=None) -> dict:
    slug = slug or re.sub(r"[^a-z0-9]", "-", name.lower())
    return {
        "slug": slug,
        "name": name,
        "release_date": release,
        "model_creator": {"name": maker},
        "evaluations": {"artificial_analysis_intelligence_index": index},
        "artificial_analysis_intelligence_index_cost": None if index is None else {
            "total_cost": total,
            "cost_per_task": {"total_cost": cost} if cost is not None else None,
        },
        "pricing": {},
        "performance": {},
        "performance_v3": {},
    }
