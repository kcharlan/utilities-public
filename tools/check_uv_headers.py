#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fleet drift guard for the uv-managed PEP 723 launchers.

This replaces the per-tool ``test_bootstrap*.py`` copies deleted during the uv
migration. It verifies that every migrated launcher:

  * begins with the canonical ``uv run --script`` shebang,
  * carries a valid PEP 723 ``# /// script`` block whose TOML declares
    ``requires-python`` and a ``dependencies`` list, and
  * declares every third-party import, including imports inside functions,
  * matches its tracked project dependency manifest in both directions,
  * is registered even when newly added but not yet staged, and
  * contains none of the old hand-rolled bootstrap patterns.

If anyone pastes venv/bootstrap code back into a launcher, this fails.

Run it directly (it is itself a uv PEP 723 script with no dependencies):

    ./tools/check_uv_headers.py
    uv run --script tools/check_uv_headers.py
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL_SHEBANG = "#!/usr/bin/env -S uv run --script"

NON_UV_ENTRYPOINT_ALLOWLIST: tuple[str, ...] = (
    "benchmark-llm/benchmark_llm/__main__.py",
    "benchmark-llm/examples/",
    "cognitive_switchyard/cognitive_switchyard/__main__.py",
    "colophon/tools/gen_unicode.py",
    "docker/llm_collector/collector/collector.py",
    "docker/llm_proxy/src/llm_proxy/main.py",
    "model_sentinel/model_sentinel/__main__.py",
)

IMPORT_DISTRIBUTION_ALIASES = {
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "fitz": "pymupdf",
    "pptx": "python-pptx",
    "readability": "readability-lxml",
    "whisper": "openai-whisper",
    "yaml": "pyyaml",
}

# The migrated launchers (repo-relative). model_sentinel's own entry point is
# intentionally excluded: it is the zipapp-form reference and has no bootstrap
# layer. Its standalone build step is a uv script and is verified here.
LAUNCHERS = [
    "editdb/editdb",
    "jtree/jtree",
    "harscope/harscope",
    "mls-tracker/mls_tracker",
    "docpipe/docpipe",
    "storage_monitor/storage_monitor",
    "tax2/tax2",
    "routerview/routerview",
    "expense_dock/expense_dock",
    "git-multirepo-dashboard/git_dashboard.py",
    "launchmaster/launchmaster",
    "router-log-analyzer/router_log_analyze.py",
    "hysa-excel/hysa_vs_cd_model.py",
    "div_conv/div_conv",
    "etf_montecarlo/etf_montecarlo",
    "benchmark-llm/bench",
    "cognitive_switchyard/switchyard",
    "vid-compiler/video_compiler.py",
    "model_sentinel/build_standalone.py",
    "abacus usage/de-abacus.py",
    "anduril_steps/anduril_steps.py",
    "dloc/dloc",
    "worktree-helper/worktree",
    "md-json/md_converter.py",
    "Claude_plugin_converter/to_gemini_cli/migrate_skills.py",
    "doc_linearizer/linearize.py",
    "data_format_converter/src/data_convert.py",
    "reversible-skew/rs.py",
    "reversible-skew/rs-big.py",
    "video-scenes/video-scenes",
    "apple-health-extract/extract_workout_stats.py",
    "apple-health-extract/exercise_bouts.py",
    "transcription/transcription",
]

# Explicit targets per launcher; do not scan sibling modules implicitly.
LAUNCHER_TARGETS: dict[str, tuple[str, ...]] = {
    "transcription/transcription": ("transcription/app.py", "transcription/transcribe.py", "transcription/transcription_state.py"),
}

NON_UV_PYTHON_ALLOWLIST: tuple[str, ...] = (
    "Calculation tools/backtest/data/compile_market_data.py",
    "benchmark-llm/examples/shared/demo_prompt_executor.py",
    "coding/design_orch/scripts/codex_json_progress.py",
    "cognitive_switchyard/cognitive_switchyard/scripts/plan_commit_msg.py",
    "cognitive_switchyard/scripts/codex_json_progress.py",
    "cognitive_switchyard/tests/fixtures/workers/",
    "docker/llm_collector/snapshots/rollup_snapshots.py",
    "harscope/tests/verify_redaction.py",
    "model_sentinel/__main__.py",
    "model_sentinel/model-sentinel",
)

# Each tracked manifest must contain every launcher dependency and may contain
# only the explicitly listed test/CLI extras. This catches drift in both
# directions without pretending test-only packages belong in PEP 723 metadata.
# Values are: (format, repo-relative manifest path, allowed manifest-only deps).
DEPENDENCY_MANIFESTS: dict[str, tuple[str, str, frozenset[str]]] = {
    "transcription/transcription": ("requirements", "transcription/requirements-dev.txt", frozenset({"httpx", "pip", "pytest"})),
    "abacus usage/de-abacus.py": ("stdlib", "", frozenset()),
    "anduril_steps/anduril_steps.py": ("stdlib", "", frozenset()),
    "dloc/dloc": ("stdlib", "", frozenset()),
    "worktree-helper/worktree": ("stdlib", "", frozenset()),
    "md-json/md_converter.py": ("stdlib", "", frozenset()),
    "Claude_plugin_converter/to_gemini_cli/migrate_skills.py": ("stdlib", "", frozenset()),
    "doc_linearizer/linearize.py": ("requirements", "doc_linearizer/requirements.txt", frozenset()),
    "data_format_converter/src/data_convert.py": ("requirements", "data_format_converter/requirements.txt", frozenset({"pytest"})),
    "reversible-skew/rs.py": ("requirements", "reversible-skew/requirements.txt", frozenset({"numba"})),
    "reversible-skew/rs-big.py": ("requirements", "reversible-skew/requirements.txt", frozenset()),
    "video-scenes/video-scenes": ("requirements", "video-scenes/requirements.txt", frozenset()),
    "apple-health-extract/extract_workout_stats.py": ("requirements", "apple-health-extract/requirements-dev.txt", frozenset()),
    "apple-health-extract/exercise_bouts.py": ("requirements", "apple-health-extract/requirements-dev.txt", frozenset()),
    "editdb/editdb": (
        "requirements",
        "editdb/requirements-dev.txt",
        frozenset({"httpx", "playwright", "pytest", "pytest-playwright"}),
    ),
    "jtree/jtree": (
        "requirements",
        "jtree/requirements-dev.txt",
        frozenset({"httpx", "playwright", "pytest", "pytest-playwright"}),
    ),
    "harscope/harscope": (
        "requirements",
        "harscope/requirements-dev.txt",
        frozenset(
            {"anyio", "httpx", "playwright", "pytest", "pytest-playwright"}
        ),
    ),
    "mls-tracker/mls_tracker": (
        "requirements",
        "mls-tracker/requirements-dev.txt",
        frozenset({"httpx", "playwright", "pytest"}),
    ),
    "docpipe/docpipe": (
        "requirements",
        "docpipe/requirements-dev.txt",
        frozenset({"pytest"}),
    ),
    "storage_monitor/storage_monitor": (
        "requirements",
        "storage_monitor/requirements-dev.txt",
        frozenset({"playwright", "pytest"}),
    ),
    "tax2/tax2": (
        "requirements",
        "tax2/requirements-dev.txt",
        frozenset({"playwright", "pytest"}),
    ),
    "routerview/routerview": (
        "requirements",
        "routerview/requirements-dev.txt",
        frozenset({"httpx", "playwright", "pytest"}),
    ),
    "expense_dock/expense_dock": (
        "requirements",
        "expense_dock/requirements-dev.txt",
        frozenset({"playwright", "pytest", "pytest-playwright"}),
    ),
    "git-multirepo-dashboard/git_dashboard.py": (
        "requirements",
        "git-multirepo-dashboard/tests/requirements-test.txt",
        frozenset({"httpx", "playwright", "pytest", "pytest-playwright"}),
    ),
    "launchmaster/launchmaster": (
        "requirements",
        "launchmaster/requirements-dev.txt",
        frozenset({"playwright", "pytest", "pytest-playwright"}),
    ),
    "router-log-analyzer/router_log_analyze.py": (
        "requirements",
        "router-log-analyzer/requirements-dev.txt",
        frozenset({"pytest"}),
    ),
    "hysa-excel/hysa_vs_cd_model.py": (
        "requirements",
        "hysa-excel/requirements-dev.txt",
        frozenset({"openpyxl", "pytest"}),
    ),
    "div_conv/div_conv": (
        "requirements",
        "div_conv/requirements-dev.txt",
        frozenset({"pytest"}),
    ),
    "etf_montecarlo/etf_montecarlo": (
        "requirements",
        "etf_montecarlo/requirements-dev.txt",
        frozenset({"pandas", "pytest"}),
    ),
    "benchmark-llm/bench": (
        "pyproject",
        "benchmark-llm/pyproject.toml",
        frozenset(),
    ),
    "cognitive_switchyard/switchyard": (
        "requirements",
        "cognitive_switchyard/requirements.txt",
        frozenset(),
    ),
    "vid-compiler/video_compiler.py": (
        "requirements",
        "vid-compiler/requirements-dev.txt",
        frozenset({"pytest"}),
    ),
    "model_sentinel/build_standalone.py": (
        "requirements",
        "model_sentinel/requirements-dev.txt",
        frozenset({"playwright", "pytest"}),
    ),
}

# Substrings that must never reappear in a migrated launcher.
FORBIDDEN_PATTERNS = [
    "BOOTSTRAP_VERSION",
    "bootstrap_state",
    "os.execv",
    "venv.EnvBuilder",
    "venv.create",
    "ensure_private_venv",
]

# PEP 723 block extraction (from the specification).
PEP723_BLOCK = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)


def extract_pep723(text: str) -> dict | None:
    """Return the parsed ``script`` PEP 723 metadata, or None if absent/invalid."""
    for match in PEP723_BLOCK.finditer(text):
        if match.group("type") != "script":
            continue
        lines = []
        for line in match.group("content").splitlines():
            if line.startswith("# "):
                lines.append(line[2:])
            elif line == "#":
                lines.append("")
        try:
            return tomllib.loads("\n".join(lines))
        except tomllib.TOMLDecodeError:
            return None
    return None


def normalize_distribution(requirement: str) -> str:
    """Return a PEP 503-style name from a requirement or distribution name."""
    name = re.split(r"[\s<>=!~\[;@]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements_file(path: Path, _seen: set[Path] | None = None) -> list[str]:
    """Read requirement entries recursively, following local ``-r`` includes."""
    resolved = path.resolve()
    seen = _seen if _seen is not None else set()
    if resolved in seen:
        return []
    seen.add(resolved)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)

    requirements: list[str] = []
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        if line.startswith("-r "):
            requirements.extend(parse_requirements_file(resolved.parent / line[3:].strip(), seen))
            continue
        if line.startswith("--requirement "):
            requirements.extend(
                parse_requirements_file(resolved.parent / line.removeprefix("--requirement ").strip(), seen)
            )
            continue
        if line.startswith("-"):
            continue
        requirements.append(line)
    return requirements


def compare_dependency_sets(
    declared: list[str],
    manifest: list[str],
    allowed_manifest_only: frozenset[str],
) -> tuple[list[str], list[str]]:
    """Return dependencies missing from the manifest and unexpected manifest entries."""
    declared_names = {normalize_distribution(item) for item in declared}
    manifest_names = {normalize_distribution(item) for item in manifest}
    allowed_names = {normalize_distribution(item) for item in allowed_manifest_only}
    return (
        sorted(declared_names - manifest_names),
        sorted(manifest_names - declared_names - allowed_names),
    )


def check_dependency_manifest(rel_path: str, metadata: dict | None = None) -> list[str]:
    """Check one launcher's tracked dependency sidecar in both directions."""
    launcher_path = REPO_ROOT / rel_path
    policy = DEPENDENCY_MANIFESTS.get(rel_path)
    if policy is None:
        return ["no dependency manifest policy registered"]

    if metadata is None:
        metadata = extract_pep723(launcher_path.read_text(encoding="utf-8"))
    if metadata is None or not isinstance(metadata.get("dependencies"), list):
        return []  # Header validation reports the actionable metadata error.

    manifest_format, manifest_rel_path, allowed_extras = policy
    if manifest_format == "stdlib":
        if metadata["dependencies"]:
            return ["stdlib-only launcher declares dependencies: " + ", ".join(metadata["dependencies"])]
        return []
    manifest_path = REPO_ROOT / manifest_rel_path
    if not manifest_path.is_file():
        return [f"dependency manifest not found: {manifest_rel_path}"]

    problems: list[str] = []
    try:
        if manifest_format == "requirements":
            manifest_dependencies = parse_requirements_file(manifest_path)
        elif manifest_format == "pyproject":
            project = tomllib.loads(manifest_path.read_text(encoding="utf-8"))["project"]
            manifest_dependencies = list(project.get("dependencies", []))
            if metadata.get("requires-python") != project.get("requires-python"):
                problems.append(
                    "requires-python differs from "
                    f"{manifest_rel_path}: {metadata.get('requires-python')!r} != "
                    f"{project.get('requires-python')!r}"
                )
        else:  # pragma: no cover - policies are constants validated by review/tests.
            return [f"unsupported dependency manifest format: {manifest_format}"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        return [f"could not read dependency manifest {manifest_rel_path}: {exc}"]

    missing, unexpected = compare_dependency_sets(
        metadata["dependencies"],
        manifest_dependencies,
        allowed_extras,
    )
    if missing:
        problems.append(
            f"dependencies missing from {manifest_rel_path}: {', '.join(missing)}"
        )
    if unexpected:
        problems.append(
            f"unexpected dependencies in {manifest_rel_path}: {', '.join(unexpected)}"
        )
    return problems


def _is_local_import(path: Path, import_name: str) -> bool:
    return (path.parent / f"{import_name}.py").is_file() or (path.parent / import_name).is_dir()


def missing_declared_imports(path: Path, text: str, dependencies: list[str]) -> list[str]:
    """Return third-party imports at any scope absent from PEP 723 dependencies."""
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    declared = {normalize_distribution(dependency) for dependency in dependencies}
    missing: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            import_names = [alias.name.partition(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            import_names = [node.module.partition(".")[0]]
        else:
            continue

        for import_name in import_names:
            if import_name in sys.stdlib_module_names or _is_local_import(path, import_name):
                continue
            distribution = IMPORT_DISTRIBUTION_ALIASES.get(import_name, import_name)
            if normalize_distribution(distribution) not in declared:
                missing.add(import_name)
    return sorted(missing)


def check_launcher_targets(rel_path: str, dependencies: list[str]) -> list[str]:
    problems = []
    for target in LAUNCHER_TARGETS.get(rel_path, ()):
        path = REPO_ROOT / target
        if not path.is_file():
            problems.append(f"registered target not found: {target}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
            ast.parse(text, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            problems.append(f"could not parse registered target {target}: {exc}")
            continue
        missing = missing_declared_imports(path, text, dependencies)
        if missing:
            problems.append(f"{target}: third-party imports missing from dependencies: {', '.join(missing)}")
    return problems


def git_repository_files() -> list[Path]:
    """List tracked plus non-ignored untracked files without walking ignored trees."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {stderr or 'unknown error'}")
    return [
        REPO_ROOT / raw_path.decode("utf-8", errors="surrogateescape")
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    ]


def read_first_line(path: Path) -> str | None:
    """Read a text file's first line, skipping unreadable and binary files."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.readline().rstrip("\r\n")
    except (OSError, UnicodeDecodeError):
        return None


def is_test_path(relative: str) -> bool:
    path = Path(relative)
    return (any(part in {"test", "tests"} for part in path.parts[:-1])
            or path.name == "conftest.py" or path.name.startswith("test_"))


def is_allowlisted(relative: str, allowlist: tuple[str, ...]) -> bool:
    return any(relative.startswith(item) if item.endswith("/") else relative == item
               for item in allowlist)


def discover_launchers() -> set[str]:
    """Find files in the repository whose first line is the canonical shebang."""
    discovered: set[str] = set()
    for path in git_repository_files():
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if path.suffix not in {"", ".py"}:
            continue
        if read_first_line(path) == CANONICAL_SHEBANG:
            discovered.add(relative.as_posix())
    return discovered


def check_launcher(rel_path: str) -> list[str]:
    """Return a list of violation messages for one launcher (empty == OK)."""
    problems: list[str] = []
    path = REPO_ROOT / rel_path
    if not path.is_file():
        return [f"file not found: {rel_path}"]

    text = path.read_text(encoding="utf-8")
    first_line = text.splitlines()[0] if text else ""
    if first_line != CANONICAL_SHEBANG:
        problems.append(f"first line is not the canonical shebang (got: {first_line!r})")

    meta = extract_pep723(text)
    if meta is None:
        problems.append("missing or invalid PEP 723 '# /// script' block")
    else:
        if "requires-python" not in meta:
            problems.append("PEP 723 block missing 'requires-python'")
        deps = meta.get("dependencies")
        if not isinstance(deps, list):
            problems.append("PEP 723 block missing a 'dependencies' list")
        else:
            missing_imports = missing_declared_imports(path, text, deps)
            if missing_imports:
                problems.append(
                    "third-party imports missing from dependencies: "
                    + ", ".join(missing_imports)
                )
            problems.extend(check_launcher_targets(rel_path, deps))
            problems.extend(check_dependency_manifest(rel_path, meta))

    for pattern in FORBIDDEN_PATTERNS:
        if pattern in text:
            problems.append(f"forbidden bootstrap pattern present: {pattern!r}")

    return problems


def main() -> int:
    any_failures = False
    registered = set(LAUNCHERS)
    try:
        discovered = discover_launchers() - {"tools/check_uv_headers.py"}
        for path in git_repository_files():
            if not path.is_file():
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            first_line = read_first_line(path)
            allowed = is_allowlisted(relative, NON_UV_PYTHON_ALLOWLIST)
            if first_line is not None and re.match(r"^#!.*python", first_line) and not allowed:
                any_failures = True
                print(f"FAIL {relative}\n       - Python shebang is not a uv launcher")
            if (path.suffix == ".py" and first_line is not None
                    and not first_line.startswith("#!") and not is_test_path(relative)
                    and not is_allowlisted(relative, NON_UV_ENTRYPOINT_ALLOWLIST)):
                try:
                    source = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                # Scripts without a main guard remain unseen by this signal.
                if re.search(r"(?m)^if __name__ == [\"']__main__[\"']:", source):
                    any_failures = True
                    print(f"FAIL {relative}\n       - Python entry point is not a uv launcher")
    except RuntimeError as exc:
        print(f"FAIL launcher discovery\n       - {exc}")
        return 1
    for rel_path in sorted(discovered - registered):
        any_failures = True
        print(f"FAIL {rel_path}")
        print("       - uv launcher is not registered in LAUNCHERS")

    for rel_path in LAUNCHERS:
        problems = check_launcher(rel_path)
        if problems:
            any_failures = True
            print(f"FAIL {rel_path}")
            for problem in problems:
                print(f"       - {problem}")

    if any_failures:
        print("\ncheck_uv_headers: FAILED (see violations above)")
        return 1

    print(f"check_uv_headers: OK ({len(LAUNCHERS)} launchers verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
