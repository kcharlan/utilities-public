# Worked Examples

Each example shows the input arguments to `next_fires` and the expected return value. Times are shown in the requested timezone. All examples assume the dialect in `spec.md`.

## Example 1 — every minute, UTC

```python
next_fires("* * * * *", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns:
# [datetime(2026, 1, 1, 0, 1, tzinfo=ZoneInfo("UTC")),
#  datetime(2026, 1, 1, 0, 2, tzinfo=ZoneInfo("UTC")),
#  datetime(2026, 1, 1, 0, 3, tzinfo=ZoneInfo("UTC"))]
```

`after` is exclusive, so `00:00` is not included.

## Example 2 — every 15 minutes, alignment from `*`

```python
next_fires("*/15 * * * *", datetime(2026, 1, 1, 0, 7, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns: 00:15, 00:30, 00:45 on 2026-01-01
```

Step from `*` aligns to `field_min` (here, minute 0).

## Example 3 — list expression in hour

```python
next_fires("0 8,12,17 * * *", datetime(2026, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns: 12:00 and 17:00 on 2026-01-01, then 08:00 on 2026-01-02
```

## Example 4 — DOM/DOW OR-rule

```python
next_fires("0 12 1 * 1", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=3, tz="UTC")
# returns: noon on the 1st of the month OR any Monday
```

When both `dom` (1) and `dow` (Monday) are restricted, a date matches if EITHER condition is true. The first three fires after midnight on 2026-01-01 (a Thursday) are: noon on 2026-01-01 (matches "1st"), then the next two Mondays at noon.

## Example 5 — last day of month with `L`

```python
next_fires("0 12 L * *", datetime(2026, 2, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=2, tz="UTC")
# returns: noon on the last day of February 2026, then noon on the last day of March 2026
```

`L` resolves to the actual last day of each month, accounting for leap years for February.

## Example 6 — weekday-nearest with `W`

```python
next_fires("0 9 15W * *", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")), n=2, tz="UTC")
# returns: 09:00 on the weekday closest to the 15th of January 2026, then the same in February
```

If the 15th is Saturday, fire on Friday the 14th. If Sunday, fire on Monday the 16th. Without crossing month boundaries.

## Example 7 — DST fall-back, fires once during duplicated hour

```python
next_fires(
    "30 * * * *",
    datetime(2026, 11, 1, 5, 0, tzinfo=ZoneInfo("UTC")),
    n=5,
    tz="America/Los_Angeles",
)
# returns 5 times, with the duplicated 01:30 local appearing exactly once.
```

On 2026-11-01, Los Angeles falls back from 01:59:59 PDT to 01:00:00 PST. The schedule fires at minute 30 of each local hour. The 01:30 instant occurs twice in wall-clock time; the function fires exactly once for it (at the first occurrence, `fold=0`). The skipped hour on the spring-forward equivalent would not appear in the result at all.

## Example 8 — invalid expression raises `InvalidCronExpr`

```python
next_fires("*/0 * * * *", datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")))
# raises InvalidCronExpr (step must be a positive integer)
```

A step of zero is not a valid expression. Any malformed input raises `InvalidCronExpr` (a subclass of `ValueError`), not `ValueError` directly, not `TypeError`, not a generic crash.
