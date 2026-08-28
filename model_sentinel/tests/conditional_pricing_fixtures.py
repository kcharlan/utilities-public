"""Conspicuously synthetic conditional-pricing policy fixtures.

These values describe only the fake ``synthetic/scheduled-rate-demo`` model.
They are deliberately invented test data, not a provider export or runtime
report. Builders return fresh JSON-compatible metadata dictionaries so later
tests can safely tailor one side of a comparison without cross-test mutation.
"""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any


SYNTHETIC_SCHEDULED_RATE_MODEL_ID = "synthetic/scheduled-rate-demo"
SYNTHETIC_SCHEDULED_RATE_DIMENSIONS = ("prompt", "completion", "request")
SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING = MappingProxyType(
    {
        "policies": 1,
        "source_rules": 6,
        "dimensions": 3,
        "effective_bands": 2,
    }
)

_OLD_BASE_PRICING = {
    "prompt": 0.000001122,
    "completion": 0.0000000374,
    "request": 0.000003366,
}
_LOWER_PRICING = {
    "prompt": 0.00000066,
    "completion": 0.000000022,
    "request": 0.00000198,
}
_HIGHER_PRICING = {
    "prompt": 0.00000132,
    "completion": 0.000000044,
    "request": 0.00000396,
}

_NEW_SCHEDULED_PRICING = {
    **_LOWER_PRICING,
    "overrides": [
        # Weekends inherit completion and request from the lower base.
        {"utc_days": ["saturday", "sunday"], "prompt": _LOWER_PRICING["prompt"]},
        {
            "utc_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "utc_start": 0,
            "utc_end": 100,
            **_LOWER_PRICING,
        },
        {
            "utc_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "utc_start": 100,
            "utc_end": 400,
            **_HIGHER_PRICING,
        },
        {
            "utc_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "utc_start": 400,
            "utc_end": 600,
            # This is the second deliberate omission/inheritance case.
            "prompt": _LOWER_PRICING["prompt"],
        },
        {
            "utc_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "utc_start": 600,
            "utc_end": 1000,
            **_HIGHER_PRICING,
        },
        {
            "utc_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "utc_start": 1000,
            "utc_end": 0,
            **_LOWER_PRICING,
        },
    ],
}

_OLD_MODEL = {
    "id": SYNTHETIC_SCHEDULED_RATE_MODEL_ID,
    "name": "Synthetic Scheduled Rate Demo",
    "pricing": _OLD_BASE_PRICING,
}
_NEW_MODEL = {
    "id": SYNTHETIC_SCHEDULED_RATE_MODEL_ID,
    "name": "Synthetic Scheduled Rate Demo",
    "pricing": _NEW_SCHEDULED_PRICING,
}


def synthetic_scheduled_rate_models() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return fresh old/new metadata for the six-rule synthetic schedule."""
    return deepcopy(_OLD_MODEL), deepcopy(_NEW_MODEL)
