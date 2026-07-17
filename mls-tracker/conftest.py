"""Root conftest: make the extensionless mls_tracker script importable."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UTILITIES_TESTING", "1")

UTILITIES_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.testkit import load_launcher


_script = Path(__file__).resolve().parent / "mls_tracker"
load_launcher(_script, "mls_tracker")
