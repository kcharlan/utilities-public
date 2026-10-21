from __future__ import annotations

import shutil
import stat
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def acceptance_dir() -> Iterator[Path]:
    """A fresh private (0700) directory that the acceptance test owns.

    It is created outside pytest's retained temporary tree and removed when the
    test ends, pass or fail, so no synthetic runtime home, database or browser
    evidence outlives the test.
    """
    path = Path(tempfile.mkdtemp(prefix="model-sentinel-acceptance-"))
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
        yield path
    finally:
        shutil.rmtree(path)
