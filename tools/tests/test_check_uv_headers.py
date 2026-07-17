from __future__ import annotations

import sys
from pathlib import Path

UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.check_uv_headers import (
    DEPENDENCY_MANIFESTS,
    LAUNCHERS,
    REPO_ROOT,
    check_dependency_manifest,
    compare_dependency_sets,
    extract_pep723,
    git_repository_files,
    missing_declared_imports,
    normalize_distribution,
    parse_requirements_file,
)


def test_requirement_normalization_handles_extras_versions_and_case() -> None:
    assert normalize_distribution("uvicorn[standard]>=0.30") == "uvicorn"
    assert normalize_distribution("PyMuPDF>=1.24,<2") == "pymupdf"
    assert normalize_distribution("pytest_playwright") == "pytest-playwright"
    assert normalize_distribution("httpx; python_version >= '3.12'") == "httpx"
    assert normalize_distribution("demo @ https://example.test/demo.whl") == "demo"


def test_requirements_parser_follows_includes(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.txt"
    runtime.write_text("fastapi\nuvicorn[standard]\n", encoding="utf-8")
    dev = tmp_path / "dev.txt"
    dev.write_text("-r runtime.txt\npytest>=8 # test runner\n", encoding="utf-8")

    assert parse_requirements_file(dev) == [
        "fastapi",
        "uvicorn[standard]",
        "pytest>=8",
    ]


def test_manifest_error_reports_missing_recursive_include(tmp_path: Path, monkeypatch) -> None:
    launcher = tmp_path / "launcher"
    launcher.write_text(
        "#!/usr/bin/env -S uv run --script\n"
        "# /// script\n"
        '# requires-python = \">=3.12\"\n'
        '# dependencies = [\"fastapi\"]\n'
        "# ///\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "requirements-dev.txt"
    manifest.write_text("-r missing.txt\nfastapi\n", encoding="utf-8")
    monkeypatch.setitem(
        DEPENDENCY_MANIFESTS,
        "probe/launcher",
        ("requirements", str(manifest), frozenset()),
    )
    monkeypatch.setattr("tools.check_uv_headers.REPO_ROOT", tmp_path)

    problems = check_dependency_manifest(
        "probe/launcher",
        {"requires-python": ">=3.12", "dependencies": ["fastapi"]},
    )

    assert len(problems) == 1
    assert "could not read dependency manifest" in problems[0]
    assert "missing.txt" in problems[0]


def test_lazy_imports_are_checked(tmp_path: Path) -> None:
    launcher = tmp_path / "launcher"
    source = "def load_pdf():\n    import fitz\n    import pypdf\n"

    assert missing_declared_imports(launcher, source, ["pypdf"]) == ["fitz"]
    assert missing_declared_imports(
        launcher,
        source,
        ["PyMuPDF>=1.24,<2", "pypdf>=5,<7"],
    ) == []


def test_reverse_manifest_check_rejects_unapproved_extras() -> None:
    missing, unexpected = compare_dependency_sets(
        ["fastapi", "uvicorn"],
        ["fastapi", "uvicorn[standard]", "pytest", "httpx2"],
        frozenset({"pytest"}),
    )

    assert missing == []
    assert unexpected == ["httpx2"]


def test_every_launcher_has_a_clean_dependency_manifest_policy() -> None:
    assert set(DEPENDENCY_MANIFESTS) == set(LAUNCHERS)
    for launcher in LAUNCHERS:
        assert check_dependency_manifest(launcher) == []


def test_git_file_listing_excludes_ignored_environment_trees() -> None:
    relative_paths = [path.relative_to(REPO_ROOT) for path in git_repository_files()]

    assert relative_paths
    assert not any(
        part in {".tax2_venv", ".venv", "node_modules", "venv"}
        for path in relative_paths
        for part in path.parts
    )


def test_router_log_lazy_dependencies_are_covered() -> None:
    path = REPO_ROOT / "router-log-analyzer/router_log_analyze.py"
    text = path.read_text(encoding="utf-8")
    metadata = extract_pep723(text)

    assert metadata is not None
    assert missing_declared_imports(path, text, metadata["dependencies"]) == []
