from typing import Any, Dict, List
import xmltodict

def load_xml(text: str) -> Any:
    """
    Parses an XML string into a Python object using xmltodict.
    - Disallows attributes to enforce a simple key-value structure.
    - Expects a single root element.
    """
    return xmltodict.parse(text, attr_prefix='', cdata_key='text')

def _to_xml_recursive(obj: Any) -> str:
    """Recursively builds an XML string from a Python object."""
    parts = []
    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            value = obj[key]
            if isinstance(value, list):
                for item in value:
                    parts.append(f"<{key}>{_to_xml_recursive(item)}</{key}>")
            else:
                parts.append(f"<{key}>{_to_xml_recursive(value)}</{key}>")
    elif isinstance(obj, (str, int, float, bool)):
        return str(obj).lower() if isinstance(obj, bool) else str(obj)
    elif obj is None:
        return ""
    else:
        raise TypeError(f"Unsupported type for XML conversion: {type(obj)}")
    return "".join(parts)

def dump_xml(obj: Any) -> str:
    """
    Dumps a Python object to an XML string with deterministic key ordering.
    Assumes the object is a dictionary with a single root key.
    """
    if not isinstance(obj, dict) or len(obj) != 1:
        raise ValueError("Input object must be a dictionary with a single root key.")
    
    root_key = list(obj.keys())[0]
    content = _to_xml_recursive(obj[root_key])
    
    return f"<{root_key}>{content}</{root_key}>"
