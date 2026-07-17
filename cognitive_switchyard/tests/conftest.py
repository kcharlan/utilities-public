from __future__ import annotations

import importlib.util
import os
import resource
import sys
from pathlib import Path

import pytest

os.environ.setdefault("UTILITIES_TESTING", "1")

# ---------------------------------------------------------------------------
# Validate dev venv dependencies
# ---------------------------------------------------------------------------
# When requirements.txt or requirements-dev.txt gain new packages, the dev
# venv can silently fall behind. Detect missing packages at collection time and
# fail with the exact setup command; tests must never mutate their interpreter.

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_UTILITIES_ROOT))

from tools.check_uv_headers import normalize_distribution, parse_requirements_file

# pip package name → Python import name (only for cases where they differ)
_IMPORT_NAME_OVERRIDES: dict[str, str] = {
    "pyyaml": "yaml",
    "pytest-playwright": "pytest_playwright",
}


def _import_name(package: str) -> str:
    """Derive the importable module name for a pip package."""
    normalized = normalize_distribution(package)
    if normalized in _IMPORT_NAME_OVERRIDES:
        return _IMPORT_NAME_OVERRIDES[normalized]
    return normalized.replace("-", "_")


def _check_dev_dependencies() -> None:
    all_packages: list[str] = []
    all_packages.extend(parse_requirements_file(_REPO_ROOT / "requirements.txt"))
    all_packages.extend(parse_requirements_file(_REPO_ROOT / "requirements-dev.txt"))

    missing = [
        pkg for pkg in all_packages
        if importlib.util.find_spec(_import_name(pkg)) is None
    ]
    if not missing:
        return

    pytest.exit(
        "Cognitive Switchyard test dependencies are missing: "
        f"{', '.join(missing)}.\n"
        "Set up the project interpreter with:\n"
        "  python3 -m venv .venv\n"
        "  .venv/bin/pip install -r requirements.txt -r requirements-dev.txt",
        returncode=1,
    )


_check_dev_dependencies()

# ---------------------------------------------------------------------------
# Raise the soft FD limit so cumulative test resource usage does not
# hit the default macOS cap of 256.
_soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
if _soft < 4096:
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, _hard), _hard))


@pytest.fixture
def repo_root() -> Path:
    return _REPO_ROOT
