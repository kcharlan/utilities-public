from __future__ import annotations

from pathlib import Path


__path__ = [str(Path(__file__).resolve().parent / "model_sentinel")]

# The inner package's __init__ does not run when this checkout shim is the
# imported package, so expose its single version declaration here as well.
from .__init__ import __version__  # noqa: E402
