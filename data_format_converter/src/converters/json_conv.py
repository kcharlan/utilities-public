import json
from typing import Any

def load_json(text: str) -> Any:
    """
    Strictly parses a JSON string into a Python object.
    """
    return json.loads(text)

def dump_pretty(obj: Any) -> str:
    """
    Dumps a Python object to a pretty-printed JSON string with 2-space indents
    and sorted keys.
    """
    return json.dumps(obj, sort_keys=True, indent=2)

def dump_compact(obj: Any) -> str:
    """
    Dumps a Python object to a compact JSON string with sorted keys and no
    extra whitespace.
    """
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))
