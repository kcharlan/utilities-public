# Cron Expression Dialect

This is the authoritative spec for the cron dialect this benchmark uses. The grading suite enforces it exactly. Do not assume any other dialect.

## Function

```python
def next_fires(
    expr: str,
    after: datetime,
    n: int = 1,
    tz: str = "UTC",
) -> list[datetime]:
    ...
```

- `expr`: a five-field cron expression (see "Fields" below).
- `after`: a timezone-aware `datetime`. A naive datetime raises `InvalidCronExpr`.
- `n`: number of fire times to return; must be `>= 1`. Otherwise `InvalidCronExpr`.
- `tz`: an IANA timezone name (string). Default `"UTC"`.

Returns a list of `n` timezone-aware `datetime` objects in `tz`, in ascending order, all strictly after `after`. The list is exactly length `n` (the schedule is assumed to keep firing indefinitely; you do not need to handle "no more fires ever").

## Error class

```python
class InvalidCronExpr(ValueError):
    """Raised for any malformed expression or invalid argument."""
```

This is the only exception type the function may raise. Any malformed input, invalid argument, unknown timezone, or other usage error must raise `InvalidCronExpr`.

## Fields

Five space-separated fields, in this order:

| Field | Range | Notes |
| --- | --- | --- |
| minute | 0–59 | |
| hour | 0–23 | |
| dom (day of month) | 1–31 | |
| month | 1–12 | Numeric only. Names like `JAN` are NOT accepted. |
| dow (day of week) | 0–6 | 0 = Sunday. `7` is NOT accepted as Sunday. Names like `MON` are NOT accepted. |

A wrong number of fields raises `InvalidCronExpr`.

## Field grammar

Each field is one of:

- `*` — any value in range.
- A literal integer in range.
- A range `a-b` where `a <= b`, both in range.
- A list of any of the above, comma-separated, e.g. `1,5,10-15`.
- A step expression `<base>/<step>` where:
  - `<base>` is `*`, a single integer, or a range `a-b`.
  - `<step>` is a positive integer.
  - When `<base>` is a single integer `n`, the resulting set is `{n, n+step, n+2*step, ...}` ∩ `[n, field_max]`.
  - When `<base>` is `*`, the set is `{field_min, field_min+step, field_min+2*step, ...}` ∩ `[field_min, field_max]`.
  - When `<base>` is a range `a-b`, the set is `{a, a+step, a+2*step, ...}` ∩ `[a, b]`.
- `?` — only valid in `dom` and `dow`. Means "no opinion." See "DOM/DOW interaction" below.
- `L` — only valid in `dom`. Means "last day of the given month."
- `W` — only valid in `dom`, immediately following an integer `n`, e.g. `15W`. Means "weekday (Mon–Fri) nearest to day `n` of the month, without crossing month boundaries." If `n` falls on a weekday, that's the day. If on Saturday, use the Friday before it (unless that would land in the previous month, in which case use the Monday after). If on Sunday, use the Monday after (unless that would land in the next month, in which case use the Friday before).

The following are invalid and raise `InvalidCronExpr`:
- Steps with non-positive values.
- Ranges with `a > b`.
- Out-of-range literals.
- Unknown characters.
- `L` or `W` in fields other than `dom`.
- `?` in fields other than `dom`/`dow`.
- A `?` in both `dom` and `dow` simultaneously.

## DOM/DOW interaction (POSIX OR-rule)

This is the most-violated rule in cron implementations. Be precise:

- If **both** `dom` and `dow` are restricted (neither is `*` and neither is `?`), a date matches if it satisfies **either** field. (POSIX semantics.)
- If `dom` is `*` or `?`, only `dow` matters.
- If `dow` is `*` or `?`, only `dom` matters.
- If both are `*`, both effectively any.
- `?` is identical in match semantics to `*` for these purposes; it exists only to make "the other field is the one I care about" intent explicit. `?` may not be used in both DOM and DOW simultaneously.

## Timezone & DST

The schedule is wall-clock in `tz`. Fire times are returned as timezone-aware datetimes in `tz`.

During DST transitions:

- **Spring-forward (skipped hour):** if a scheduled fire falls in the skipped local interval, the fire is silently skipped. Do not retro-fire and do not slide it forward.
- **Fall-back (duplicated hour):** if a scheduled fire falls during the duplicated hour, fire **once** at the first occurrence (the pre-transition wall-clock instant, `fold=0`) and not again at the second occurrence (`fold=1`).

For schedules that fire every minute or every few minutes, the duplicated hour appears once in the result list and the skipped hour appears not at all.

An unknown timezone name (`zoneinfo.ZoneInfoNotFoundError` or equivalent) raises `InvalidCronExpr`.

## Strictly-after semantics

`after` is exclusive. If `after` is itself a fire time, it is not included in the result; the result starts at the next subsequent fire time.

## Out of scope

These are NOT part of this dialect:

- Year field (six-field cron).
- Seconds field (six-field cron).
- Jenkins `H` (hash) operator.
- Quartz `#` operator (Nth weekday of month).
- Quartz `L-N` (last day minus N).
- Month names (`JAN`–`DEC`) or day names (`SUN`–`SAT`).
- `@yearly` / `@monthly` / `@weekly` / `@daily` / `@hourly` / `@reboot` macros.

The grading suite does not test these. Do not implement them.
