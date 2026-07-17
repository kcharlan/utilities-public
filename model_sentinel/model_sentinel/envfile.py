from __future__ import annotations

import ast
from pathlib import Path


class EnvFileError(ValueError):
    """Raised when an env-style file cannot be parsed."""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EnvFileError(f"{path}:{lineno}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise EnvFileError(f"{path}:{lineno}: empty key")
        values[key] = _parse_value(value.strip(), path, lineno)
    return values


def _parse_value(value: str, path: Path, lineno: int) -> str:
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise EnvFileError(f"{path}:{lineno}: invalid quoted value") from exc
        if not isinstance(parsed, str):
            raise EnvFileError(f"{path}:{lineno}: quoted value must be a string")
        return parsed
    return value

