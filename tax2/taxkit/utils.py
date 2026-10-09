from __future__ import annotations

from pathlib import Path
import re


def discover_year_files(directory: Path) -> dict[int, list[Path]]:
    """Group all ASCII numeric-year YAML entries in filename order, without filtering type."""
    discovered: dict[int, list[Path]] = {}
    if directory.is_dir():
        for path in sorted(directory.iterdir(), key=lambda entry: entry.name):
            if re.fullmatch(r"[0-9]+\.(yaml|yml)", path.name):
                discovered.setdefault(int(path.stem), []).append(path)
    return discovered
