from collections import OrderedDict
import datetime
from typing import Any

import yaml
from .temporal import iso_temporal


def load_yaml(text: str) -> Any:
    """
    Parses a YAML string into a Python object using safe_load.
    """
    # Inspect the composed node graph before SafeLoader flattens merge keys.
    # Repeated aliases must be counted repeatedly, including recursive aliases.
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    remaining = 100_000
    nodes = [root] if root is not None else []
    while nodes:
        node = nodes.pop()
        remaining -= 1
        if isinstance(node, yaml.ScalarNode):
            remaining -= len(node.value)
        elif isinstance(node, yaml.SequenceNode):
            nodes.extend(node.value)
        elif isinstance(node, yaml.MappingNode):
            for key, child in node.value:
                nodes.extend((key, child))
        if remaining < 0:
            raise ValueError('YAML expansion limit exceeded')
    value = yaml.safe_load(text)
    # Count every occurrence, including aliases, before a serializer expands it.
    remaining = 100_000
    stack = [value]
    while stack:
        item = stack.pop()
        remaining -= 1 + (len(item) if isinstance(item, (str, bytes)) else 0)
        if remaining < 0:
            raise ValueError('YAML expansion limit exceeded')
        if isinstance(item, dict):
            for key, child in item.items():
                stack.extend((key, child))
        elif isinstance(item, (list, tuple, set)):
            stack.extend(item)
    return value


def _normalize(obj: Any) -> Any:
    if isinstance(obj, datetime.time):
        return iso_temporal(obj)
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
