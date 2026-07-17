from typing import Any

class ToonUnavailable(Exception):
    """Custom exception raised when the 'toon_format' library is not installed."""
    pass

try:
    from toon_format import encode, decode
    _toon_available = True
except ImportError:
    _toon_available = False

def load_toon(text: str) -> Any:
    """
    Parses a TOON string into a Python object.
    """
    if not _toon_available:
        raise ToonUnavailable("The 'toon-format' library is not installed from GitHub.")
    return decode(text)

def dump_toon(obj: Any) -> str:
    """
    Dumps a Python object to a TOON string.
    """
    if not _toon_available:
        raise ToonUnavailable("The 'toon-format' library is not installed from GitHub.")
    return encode(obj)
