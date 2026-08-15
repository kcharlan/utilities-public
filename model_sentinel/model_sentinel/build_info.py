"""Runtime identity for source checkouts and packaged standalone builds."""

from __future__ import annotations

from pathlib import Path
import sys

try:
    from ._packaged_build import (
        BUILD_KIND,
        BUILD_REVISION,
        BUILD_SOURCE_HASH,
        BUILD_TIME_UTC,
    )
except ImportError:
    BUILD_KIND = "source"
    BUILD_REVISION = "unpackaged"
    BUILD_SOURCE_HASH = "unpackaged"
    BUILD_TIME_UTC = "unpackaged"


def format_build_info(*, full_hash: bool = False) -> str:
    """Return stable, shell-readable provenance for the running code."""
    source_hash = BUILD_SOURCE_HASH
    if not full_hash and len(source_hash) == 64:
        source_hash = source_hash[:12]
    return (
        f"build={BUILD_KIND} revision={BUILD_REVISION} "
        f"source_sha256={source_hash} built={BUILD_TIME_UTC}"
    )


def runtime_entrypoint(argv0: str | None = None) -> str:
    """Return the resolved Model Sentinel command path, not Python's path."""
    value = sys.argv[0] if argv0 is None else argv0
    if not value:
        return "unknown"
    return str(Path(value).expanduser().resolve())
