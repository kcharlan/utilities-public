from typing import Any

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in 3.10 CI
    import tomli as tomllib  # type: ignore

import tomli_w


def _ensure_toml_compatible(obj: Any, path: str = "root") -> None:
    if obj is None:
        raise ValueError(f"TOML does not support null values (found at {path})")
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}"
            _ensure_toml_compatible(value, child_path)
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            _ensure_toml_compatible(value, f"{path}[{idx}]")


def load_toml(text: str) -> Any:
    """
    Parses a TOML string into a Python object.
    """
    return tomllib.loads(text)


def dump_toml(obj: Any) -> str:
    """
    Dumps a Python object into a TOML string.
    """
    _ensure_toml_compatible(obj)
    return tomli_w.dumps(obj)
