from __future__ import annotations

import ast
import re
from pathlib import Path


class EnvFileError(ValueError):
    """Raised when an env-style file cannot be parsed."""


def parse_env_file(path: Path) -> dict[str, str]:
    return parse_env_text(path.read_text(encoding="utf-8"), source=path)


def parse_env_text(text: str, *, source: Path, strict: bool = False) -> dict[str, str]:
    """Parse assignments without shell expansion; strict mode is a one-line subset."""
    values: dict[str, str] = {}
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EnvFileError(f"{source}:{lineno}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise EnvFileError(f"{source}:{lineno}: empty key")
        value = value.strip()
        if strict:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise EnvFileError(f"{source}:{lineno}: invalid assignment name")
            if key in values:
                raise EnvFileError(f"{source}:{lineno}: duplicate assignment")
            if "\x00" in value or value.endswith("\\"):
                raise EnvFileError(f"{source}:{lineno}: invalid one-line value")
            if value.startswith(("'", '"')):
                if not re.fullmatch(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", value):
                    raise EnvFileError(f"{source}:{lineno}: invalid quoted value")
            elif "'" in value or '"' in value:
                raise EnvFileError(f"{source}:{lineno}: invalid quoted value")
            try:
                values[key] = _parse_value(value, source, lineno)
            except EnvFileError as exc:
                # literal_eval's underlying error can contain the secret source line.
                raise EnvFileError(str(exc)) from None
        else:
            values[key] = _parse_value(value, source, lineno)
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

