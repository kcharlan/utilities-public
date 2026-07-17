from collections import OrderedDict
from typing import Any

import yaml


def load_yaml(text: str) -> Any:
    """
    Parses a YAML string into a Python object using safe_load.
    """
    return yaml.safe_load(text)


def _normalize(obj: Any) -> Any:
    if isinstance(obj, OrderedDict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj

def dump_yaml(obj: Any) -> str:
    """
    Dumps a Python object to a YAML string preserving insertion order.
    """
    normalized = _normalize(obj)
    return yaml.safe_dump(normalized, sort_keys=False, indent=2)
