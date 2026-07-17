from __future__ import annotations

import sys
from pathlib import Path


UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.check_uv_headers import check_dependency_manifest


def test_launcher_dependencies_are_declared_for_project_tests() -> None:
    assert check_dependency_manifest("cognitive_switchyard/switchyard") == []
