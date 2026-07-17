"""Sanity-check tests for cron_eval.

Run with: pytest -q starter_test.py

These tests are NOT the grading suite. Passing them only confirms that your
module imports, that the function signature is right, and that a handful of
trivial cases work. The hidden conformance suite is much larger and more
demanding.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cron_eval import InvalidCronExpr, next_fires


UTC = ZoneInfo("UTC")


def test_every_minute_returns_n_fires_in_order():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    fires = next_fires("* * * * *", after, n=3, tz="UTC")
    assert fires == [
        datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
    ]


def test_after_is_exclusive():
    after = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fires = next_fires("0 12 * * *", after, n=1, tz="UTC")
    assert fires == [datetime(2026, 1, 2, 12, 0, tzinfo=UTC)]


def test_step_aligns_from_field_min():
    after = datetime(2026, 1, 1, 0, 7, tzinfo=UTC)
    fires = next_fires("*/15 * * * *", after, n=3, tz="UTC")
    assert fires == [
        datetime(2026, 1, 1, 0, 15, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 45, tzinfo=UTC),
    ]


def test_list_in_hour_field():
    after = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    fires = next_fires("0 8,12,17 * * *", after, n=3, tz="UTC")
    assert fires == [
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 17, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 8, 0, tzinfo=UTC),
    ]


def test_returns_tz_aware_datetimes_in_requested_zone():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    fires = next_fires("0 0 * * *", after, n=1, tz="America/Los_Angeles")
    assert fires[0].tzinfo is not None
    assert str(fires[0].tzinfo) == "America/Los_Angeles"


def test_invalid_step_raises_invalid_cron_expr():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    with pytest.raises(InvalidCronExpr):
        next_fires("*/0 * * * *", after, n=1, tz="UTC")


def test_naive_after_raises_invalid_cron_expr():
    naive = datetime(2026, 1, 1, 0, 0)
    with pytest.raises(InvalidCronExpr):
        next_fires("* * * * *", naive, n=1, tz="UTC")


def test_invalid_cron_expr_is_value_error_subclass():
    assert issubclass(InvalidCronExpr, ValueError)
