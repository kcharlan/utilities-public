from __future__ import annotations

import sys
from pathlib import Path

import pytest

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
import tools.check_uv_headers as guard


@pytest.fixture
def empty_registry(tmp_path, monkeypatch):
    registry = tmp_path / "registry.toml"
    registry.write_text("[projects]\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REGISTRY_PATH", registry)


def test_retired_python_colophon_has_no_launcher_or_manifest_policy() -> None:
    assert "colophon/colophon" not in LAUNCHERS
    assert "colophon/colophon" not in DEPENDENCY_MANIFESTS


def test_unregistered_uv_launcher_is_discovered_and_rejected(tmp_path, monkeypatch, capsys, empty_registry) -> None:
    launcher = tmp_path / "synthetic_probe"
    launcher.write_text(guard.CANONICAL_SHEBANG + "\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: [launcher])
    monkeypatch.setattr(guard, "LAUNCHERS", [])

    assert guard.discover_launchers() == {"synthetic_probe"}
    assert guard.main() == 1
    assert "uv launcher is not registered in LAUNCHERS" in capsys.readouterr().out


def test_unlisted_python_shebang_is_rejected(tmp_path, monkeypatch, capsys, empty_registry) -> None:
    launcher = tmp_path / "synthetic_probe"
    launcher.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: [launcher])
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    assert guard.main() == 1
    assert "not a uv launcher" in capsys.readouterr().out


@pytest.mark.parametrize("quote", ['\"', "'"])
def test_unlisted_entrypoint_is_rejected(tmp_path, monkeypatch, capsys, quote, empty_registry) -> None:
    launcher = tmp_path / "synthetic_tool.py"
    launcher.write_text(f"if __name__ == {quote}__main__{quote}:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: [launcher])
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    assert guard.main() == 1
    assert "Python entry point is not a uv launcher" in capsys.readouterr().out


def test_entrypoint_under_test_paths_is_skipped(tmp_path, monkeypatch, empty_registry) -> None:
    paths = [tmp_path / "tests/helper.py", tmp_path / "test/helper.py",
             tmp_path / "test_probe.py", tmp_path / "conftest.py"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("if __name__ == '__main__':\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: paths)
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    assert guard.main() == 0


def test_module_without_main_guard_is_skipped(tmp_path, monkeypatch, empty_registry) -> None:
    module = tmp_path / "module.py"
    module.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: [module])
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    assert guard.main() == 0


def test_allowlisted_entrypoint_is_skipped(tmp_path, monkeypatch, empty_registry) -> None:
    paths = [tmp_path / "allowed.py", tmp_path / "examples/probe.py"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("if __name__ == '__main__':\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: paths)
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    monkeypatch.setattr(guard, "NON_UV_ENTRYPOINT_ALLOWLIST", ("allowed.py", "examples/"))
    assert guard.main() == 0


def test_binary_python_file_is_skipped(tmp_path, monkeypatch, empty_registry) -> None:
    binary = tmp_path / "binary.py"
    binary.write_bytes(b"\xff\xfe\x00")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: [binary])
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    assert guard.main() == 0


def test_binary_file_is_skipped(tmp_path, monkeypatch, capsys, empty_registry) -> None:
    binary = tmp_path / "synthetic_binary"
    binary.write_bytes(b"\xff\xfe\x00")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: [binary])
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    assert guard.main() == 0
    assert "FAILED" not in capsys.readouterr().out


def test_allowlist_matches_exact_files_and_directory_prefixes(tmp_path, monkeypatch, capsys, empty_registry) -> None:
    exact = tmp_path / "allowed.py"
    inside = tmp_path / "workers" / "probe"
    near_miss = tmp_path / "workers-extra" / "probe"
    for path in (exact, inside, near_miss):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "git_repository_files", lambda: [exact, inside, near_miss])
    monkeypatch.setattr(guard, "LAUNCHERS", [])
    monkeypatch.setattr(guard, "NON_UV_PYTHON_ALLOWLIST", ("allowed.py", "workers/"))
    assert guard.main() == 1
    output = capsys.readouterr().out
    assert "workers-extra/probe" in output
    assert "FAIL allowed.py" not in output
    assert "FAIL workers/probe" not in output


def test_registered_missing_file_still_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    assert guard.check_launcher("probe") == ["file not found: probe"]


@pytest.mark.parametrize("dependencies, expected", [
    ([], []),
    (["pyyaml"], ["stdlib-only launcher declares dependencies: pyyaml"]),
])
def test_stdlib_policy(tmp_path, monkeypatch, dependencies, expected) -> None:
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setitem(guard.DEPENDENCY_MANIFESTS, "probe", ("stdlib", "", frozenset()))
    assert guard.check_dependency_manifest("probe", {"dependencies": dependencies}) == expected


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


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_each_remaining_launcher_manifest_is_checked(launcher: str) -> None:
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


def test_git_fleet_browser_test_dependencies_are_manifest_only() -> None:
    manifest_type, manifest_path, allowed_extras = DEPENDENCY_MANIFESTS[
        "git-multirepo-dashboard/git_dashboard.py"
    ]

    assert manifest_type == "requirements"
    assert manifest_path == "git-multirepo-dashboard/tests/requirements-test.txt"
    assert {"playwright", "pytest-playwright"} <= allowed_extras


def test_vid_compiler_has_stdlib_runtime_and_pytest_only_dev_policy() -> None:
    launcher = "vid-compiler/video_compiler.py"

    assert launcher in LAUNCHERS
    assert DEPENDENCY_MANIFESTS[launcher] == (
        "requirements",
        "vid-compiler/requirements-dev.txt",
        frozenset({"pytest"}),
    )
    assert check_dependency_manifest(launcher) == []


def test_target_missing_import_is_reported(tmp_path, monkeypatch) -> None:
    target = tmp_path / "target.py"
    target.write_text("def load():\n    import librosa\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "LAUNCHER_TARGETS", {"launcher": ("target.py",)}, raising=False)
    problems = guard.check_launcher_targets("launcher", [])
    assert any("target.py" in p and "librosa" in p for p in problems)


def test_whisper_alias_satisfies_import(tmp_path) -> None:
    assert missing_declared_imports(tmp_path / "target.py", "import whisper\n", ["openai-whisper==20250625"]) == []


def test_missing_target_is_reported(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "LAUNCHER_TARGETS", {"launcher": ("missing.py",)}, raising=False)
    assert guard.check_launcher_targets("launcher", []) == ["registered target not found: missing.py"]


def test_target_syntax_error_is_reported(tmp_path, monkeypatch) -> None:
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "LAUNCHER_TARGETS", {"launcher": ("bad.py",)}, raising=False)
    assert guard.check_launcher_targets("launcher", [])


def test_targets_belong_to_registered_launchers() -> None:
    assert set(guard.LAUNCHER_TARGETS) <= set(LAUNCHERS)


def test_transcription_app_is_not_entrypoint_allowlisted() -> None:
    assert "transcription/app.py" not in guard.NON_UV_ENTRYPOINT_ALLOWLIST


def test_transcription_policy_reconciles_manifests() -> None:
    launcher = "transcription/transcription"
    assert DEPENDENCY_MANIFESTS[launcher] == (
        "requirements", "transcription/requirements-dev.txt", frozenset({"httpx", "pip", "pytest"})
    )
    assert check_dependency_manifest(launcher) == []


def test_attached_requirement_includes_and_constraints(tmp_path):
    (tmp_path / 'nested.txt').write_text('Demo_Package[extra]>=1; python_version >= "3.12"\n')
    (tmp_path / 'constraints.txt').write_text('only-constraint<2\n')
    (tmp_path / 'dev.txt').write_text('-rnested.txt\n--requirement=nested.txt\n-c constraints.txt\n')
    assert [normalize_distribution(x) for x in parse_requirements_file(tmp_path / 'dev.txt')] == ['demo-package']


def test_requirement_parser_rejects_unknown_directive(tmp_path):
    path = tmp_path / 'dev.txt'
    path.write_text('--editable ./local\n')
    with pytest.raises(ValueError, match='unsupported'):
        parse_requirements_file(path)


def test_header_policy_needs_no_sidecar(monkeypatch):
    monkeypatch.setitem(guard.DEPENDENCY_MANIFESTS, 'example', ('header', '', frozenset()))
    assert guard.check_dependency_manifest('example', {'dependencies': ['demo']}) == []


def test_test_requirements_rejects_runtime_dependencies(tmp_path, monkeypatch):
    launcher = tmp_path / 'launcher'
    launcher.write_text('# /// script\n# requires-python = ">=3.12"\n# dependencies = ["demo_package>=1"]\n# ///\n')
    (tmp_path / 'test.txt').write_text('Demo.Package[extra]>=1; python_version >= "3.12"\npytest\n')
    monkeypatch.setattr(guard, 'REPO_ROOT', tmp_path)
    assert 'demo-package' in ' '.join(guard.check_test_requirements('fake', {'launcher': 'launcher', 'test_requirements': 'test.txt'}))


@pytest.mark.parametrize('line', ['--index-url https://example.invalid/simple', '-e ./local', 'not a requirement'])
def test_requirement_parser_rejects_invalid_entries(tmp_path, line):
    path = tmp_path / 'dev.txt'
    path.write_text(line + '\n')
    with pytest.raises(ValueError):
        parse_requirements_file(path)


def test_constraint_does_not_hide_later_requirement(tmp_path):
    (tmp_path / 'shared.txt').write_text('demo-package<2\n')
    (tmp_path / 'dev.txt').write_text('-c shared.txt\n-r shared.txt\n')
    assert [normalize_distribution(item) for item in parse_requirements_file(tmp_path / 'dev.txt')] == ['demo-package']


def test_missing_requirement_include_fails_closed(tmp_path):
    (tmp_path / 'dev.txt').write_text('--requirement=missing.txt\n')
    with pytest.raises(FileNotFoundError):
        parse_requirements_file(tmp_path / 'dev.txt')


def test_guard_rejects_invalid_registry(tmp_path, monkeypatch, capsys):
    registry = tmp_path / 'registry.toml'
    registry.write_text('[projects.bad]\nproject = "missing"\n')
    monkeypatch.setattr(guard, 'REGISTRY_PATH', registry)
    monkeypatch.setattr(guard, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(guard, 'git_repository_files', lambda: [])
    monkeypatch.setattr(guard, 'LAUNCHERS', [])
    assert guard.main() == 1
    assert 'test registry' in capsys.readouterr().out


@pytest.mark.parametrize('requirement', [
    'demo-package=>1',
    'demo-package==not-a-version',
    'demo-package; definitely_not_a_marker',
    'demo-package>=1; python_version => "3.12"',
    'demo-package; python_version == 3.12',
    'demo-package; bogus == "x"',
    'demo-package>=1; python_version == "3.12" and',
    'demo-package>=1; (python_version == "3.12"',
    "demo-package; python_version == '3.' '12'",
    "demo-package; python_version == '''3.12'''",
    "demo-package; python_version == r'3.12'",
    "demo-package; python_version == '3.12'#ignored",
])
def test_requirement_parser_rejects_invalid_specifiers_and_markers(tmp_path, requirement):
    path = tmp_path / 'dev.txt'
    path.write_text(requirement + '\n')
    with pytest.raises(ValueError, match='invalid requirement'):
        parse_requirements_file(path)


@pytest.mark.parametrize('requirement', [
    'demo_package[extra-one,extra_two]>=1.2,<3',
    'demo-package==1.2.*; python_version >= "3.12"',
    'demo-package!=1.2; (sys_platform == "darwin" or os_name == "posix") and python_version >= "3.12"',
    'demo-package; "darwin" == sys_platform',
    'demo-package; platform_machine not in "aarch64,x86_64"',
    'demo-package~=1.2rc1',
])
def test_requirement_parser_accepts_supported_specifiers_and_markers(tmp_path, requirement):
    path = tmp_path / 'dev.txt'
    path.write_text(requirement + '\n')
    assert parse_requirements_file(path) == [requirement]
