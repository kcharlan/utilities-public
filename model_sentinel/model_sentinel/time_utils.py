from __future__ import annotations

from datetime import UTC, date, datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_local() -> datetime:
    return datetime.now().astimezone()


def local_today() -> date:
    return now_local().date()


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def to_storage_timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        dt = parse_timestamp(value)
    else:
        dt = value if value.tzinfo is not None else value.astimezone()
    return dt.astimezone(UTC).isoformat()


def to_local_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        dt = parse_timestamp(value)
    else:
        dt = value if value.tzinfo is not None else value.astimezone()
    return dt.astimezone()


def to_local_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return to_local_datetime(value).isoformat()


def to_local_human(value: datetime | str | None) -> str:
    if value is None:
        return "n/a"
    return to_local_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def local_date_for(value: datetime | str) -> date:
    return to_local_datetime(value).date()

