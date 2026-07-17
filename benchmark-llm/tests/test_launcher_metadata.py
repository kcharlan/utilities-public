from __future__ import annotations

import sys
from pathlib import Path


UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.check_uv_headers import check_dependency_manifest


def test_launcher_metadata_matches_project_metadata() -> None:
    assert check_dependency_manifest("benchmark-llm/bench") == []
