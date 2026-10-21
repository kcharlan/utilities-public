"""JSON projections shared by the browse API handlers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any, Mapping

from ..change_render import RenderedChange, absent_side_display


def rendered_change_to_json(rendered: RenderedChange) -> dict[str, Any]:
    return {
        **asdict(rendered),
        "old_display": absent_side_display(rendered.old_display, rendered.old_raw),
        "new_display": absent_side_display(rendered.new_display, rendered.new_raw),
    }


def json_scrape(scrape: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in scrape.items()
    }
