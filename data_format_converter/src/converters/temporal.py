import datetime
from typing import Any


def iso_temporal(value: Any) -> str:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not serializable")
