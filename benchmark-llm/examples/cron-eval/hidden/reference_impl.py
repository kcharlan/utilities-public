import argparse
import calendar
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class InvalidCronExpr(ValueError):
    """Raised for any malformed expression or invalid argument."""


@dataclass(frozen=True)
class ParsedCron:
    minute_set: set[int]
    hour_set: set[int]
    dom_kind: str
    dom_set: set[int]
    dom_special: str | tuple[int, str] | None
    month_set: set[int]
    dow_kind: str
    dow_set: set[int]


_INT_RE = re.compile(r"^[0-9]+$")


def _raise(message: str) -> None:
    raise InvalidCronExpr(message)


def _parse_int(text: str, minimum: int, maximum: int) -> int:
    if not _INT_RE.match(text):
        _raise(f"invalid integer: {text}")
    value = int(text)
    if value < minimum or value > maximum:
        _raise(f"out of range: {text}")
    return value


def _expand_atom(atom: str, minimum: int, maximum: int) -> set[int]:
    if atom == "*":
        return set(range(minimum, maximum + 1))
    if "-" in atom:
        parts = atom.split("-")
        if len(parts) != 2:
            _raise(f"invalid range: {atom}")
        start = _parse_int(parts[0], minimum, maximum)
        end = _parse_int(parts[1], minimum, maximum)
        if start > end:
            _raise(f"reversed range: {atom}")
        return set(range(start, end + 1))
    value = _parse_int(atom, minimum, maximum)
    return {value}


def _expand_step(text: str, minimum: int, maximum: int) -> set[int]:
    base, step_text = text.split("/", 1)
    if "/" in step_text or base == "":
        _raise(f"invalid step: {text}")
    if not _INT_RE.match(step_text):
        _raise(f"invalid step: {text}")
    step = int(step_text)
    if step <= 0:
        _raise(f"invalid step: {text}")
    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        parts = base.split("-")
        if len(parts) != 2:
            _raise(f"invalid step range: {text}")
        start = _parse_int(parts[0], minimum, maximum)
        end = _parse_int(parts[1], minimum, maximum)
        if start > end:
            _raise(f"reversed range: {base}")
    else:
        start = _parse_int(base, minimum, maximum)
        end = maximum
    return set(range(start, end + 1, step))


def _parse_standard_field(text: str, minimum: int, maximum: int) -> tuple[str, set[int], str | tuple[int, str] | None]:
    if text == "":
        _raise("empty field")
    if text == "?":
        return "question", set(range(minimum, maximum + 1)), None
    values: set[int] = set()
    for item in text.split(","):
        if item == "":
            _raise("empty list item")
        if "/" in item:
            values.update(_expand_step(item, minimum, maximum))
        else:
            values.update(_expand_atom(item, minimum, maximum))
    kind = "any" if text == "*" else "restricted"
    return kind, values, None


def _parse_dom(text: str) -> tuple[str, set[int], str | tuple[int, str] | None]:
    if text == "L":
        return "restricted", set(), "L"
    if text.endswith("W"):
        day = _parse_int(text[:-1], 1, 31)
        return "restricted", set(), (day, "W")
    return _parse_standard_field(text, 1, 31)


def _parse_expr(expr: str) -> ParsedCron:
    fields = expr.split()
    if len(fields) != 5:
        _raise("cron expression must have five fields")
    minute_kind, minute_set, _ = _parse_standard_field(fields[0], 0, 59)
    hour_kind, hour_set, _ = _parse_standard_field(fields[1], 0, 23)
    dom_kind, dom_set, dom_special = _parse_dom(fields[2])
    month_kind, month_set, _ = _parse_standard_field(fields[3], 1, 12)
    dow_kind, dow_set, _ = _parse_standard_field(fields[4], 0, 6)

    if minute_kind == "question" or hour_kind == "question" or month_kind == "question":
        _raise("? is only valid in dom and dow")
    if fields[0] == "L" or fields[1] == "L" or fields[3] == "L" or fields[4] == "L":
        _raise("L is only valid in dom")
    if any(field.endswith("W") for field in (fields[0], fields[1], fields[3], fields[4])):
        _raise("W is only valid in dom")
    if dom_kind == "question" and dow_kind == "question":
        _raise("? may not be used in both dom and dow")

    return ParsedCron(
        minute_set=minute_set,
        hour_set=hour_set,
        dom_kind=dom_kind,
        dom_set=dom_set,
        dom_special=dom_special,
        month_set=month_set,
        dow_kind=dow_kind,
        dow_set=dow_set,
    )


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _nearest_weekday(year: int, month: int, day: int) -> int:
    last = _last_day(year, month)
    if day > last:
        _raise("W day exceeds month length")
    weekday = datetime(year, month, day).weekday()
    if weekday < 5:
        return day
    if weekday == 5:
        return day + 2 if day == 1 else day - 1
    return day - 2 if day == last else day + 1


def _cron_dow(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7


def _dom_matches(parsed: ParsedCron, dt: datetime) -> bool:
    if parsed.dom_special == "L":
        return dt.day == _last_day(dt.year, dt.month)
    if isinstance(parsed.dom_special, tuple) and parsed.dom_special[1] == "W":
        return dt.day == _nearest_weekday(dt.year, dt.month, parsed.dom_special[0])
    return dt.day in parsed.dom_set


def _date_matches(parsed: ParsedCron, dt: datetime) -> bool:
    dom_match = _dom_matches(parsed, dt)
    dow_match = _cron_dow(dt) in parsed.dow_set
    dom_restricted = parsed.dom_kind == "restricted"
    dow_restricted = parsed.dow_kind == "restricted"
    if dom_restricted and dow_restricted:
        return dom_match or dow_match
    if dom_restricted:
        return dom_match
    if dow_restricted:
        return dow_match
    return True


def _is_valid_wall_time(candidate: datetime, tzinfo: ZoneInfo) -> bool:
    round_tripped = candidate.astimezone(UTC).astimezone(tzinfo)
    return (
        round_tripped.year,
        round_tripped.month,
        round_tripped.day,
        round_tripped.hour,
        round_tripped.minute,
    ) == (
        candidate.year,
        candidate.month,
        candidate.day,
        candidate.hour,
        candidate.minute,
    )


def next_fires(expr: str, after: datetime, n: int = 1, tz: str = "UTC") -> list[datetime]:
    try:
        if after.tzinfo is None or after.utcoffset() is None:
            _raise("after must be timezone-aware")
        if n < 1:
            _raise("n must be >= 1")
        tzinfo = ZoneInfo(tz)
        parsed = _parse_expr(expr)
    except InvalidCronExpr:
        raise
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise InvalidCronExpr(str(exc)) from exc

    after_utc = after.astimezone(UTC)
    start_year = after.astimezone(tzinfo).year
    results: list[datetime] = []
    year = start_year
    while len(results) < n:
        for month in sorted(parsed.month_set):
            last = _last_day(year, month)
            for day in range(1, last + 1):
                probe_date = datetime(year, month, day)
                if not _date_matches(parsed, probe_date):
                    continue
                for hour in sorted(parsed.hour_set):
                    for minute in sorted(parsed.minute_set):
                        candidate = datetime(year, month, day, hour, minute, tzinfo=tzinfo, fold=0)
                        if not _is_valid_wall_time(candidate, tzinfo):
                            continue
                        if candidate.astimezone(UTC) <= after_utc:
                            continue
                        results.append(candidate)
                        if len(results) == n:
                            return results
        year += 1
        if year > start_year + 50:
            _raise("no fires found within 50 years")
    return results


def _parse_after(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _serialize_fires(fires: list[datetime]) -> list[str]:
    return [item.isoformat() for item in fires]


def evaluate_fixture(fixture: dict) -> tuple[bool, dict]:
    payload = dict(fixture["input"])
    payload["after"] = _parse_after(payload["after"])
    expected = fixture["expected"]
    try:
        actual_fires = next_fires(**payload)
    except Exception as exc:
        actual = {"kind": "raises", "value": type(exc).__name__}
    else:
        actual = {"kind": "fires", "value": _serialize_fires(actual_fires)}
    return actual == expected, actual


def self_check(conformance_dir: str | Path | None = None) -> int:
    base = Path(conformance_dir) if conformance_dir is not None else Path(__file__).resolve().parent / "conformance"
    failures = []
    for path in sorted(base.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        ok, actual = evaluate_fixture(fixture)
        if not ok:
            failures.append({"id": fixture["id"], "expected": fixture["expected"], "actual": actual})
    if failures:
        print(json.dumps(failures, indent=2))
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--conformance-dir", default=None)
    args = parser.parse_args()
    if args.self_check:
        return self_check(args.conformance_dir)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
