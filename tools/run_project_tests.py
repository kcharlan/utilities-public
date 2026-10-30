#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run registered project suites using their launcher's declared dependencies."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
from check_uv_headers import LAUNCHERS, extract_pep723


@dataclass(frozen=True)
class ProjectTests:
    project: str
    launcher: str
    test_requirements: str | None
    test_commands: tuple[tuple[str, ...], ...]
    smoke_args: tuple[str, ...] | None
    smoke_skip_reason: str | None


def load_project_tests(path: Path) -> dict[str, ProjectTests]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read registry {path}: {exc}") from exc
    if set(data) != {"projects"} or not isinstance(data["projects"], dict):
        raise ValueError("registry must contain only a projects table")
    result = {}
    for key, value in data["projects"].items():
        try:
            if not isinstance(value, dict) or set(value) - {"project", "launcher", "test_requirements", "test_commands", "smoke_args", "smoke_skip_reason"}:
                raise ValueError("unknown fields or invalid table")
            project, launcher = value["project"], value["launcher"]
            req = value.get("test_requirements")
            def check_path(item, directory=False):
                if not isinstance(item, str) or not item or Path(item).is_absolute():
                    raise ValueError("paths must be nonempty relative strings")
                candidate = (REPO_ROOT / item).resolve()
                if not candidate.is_relative_to(REPO_ROOT) or not (candidate.is_dir() if directory else candidate.is_file()):
                    raise ValueError(f"invalid {'directory' if directory else 'file'}: {item}")
            check_path(project, True)
            check_path(launcher)
            if launcher not in LAUNCHERS:
                raise ValueError(f"unknown launcher: {launcher}")
            if req is not None:
                check_path(req)
            commands = value["test_commands"]
            def strings(items):
                return isinstance(items, list) and bool(items) and all(isinstance(x, str) and x for x in items)
            if not isinstance(commands, list) or not commands or not all(strings(c) for c in commands):
                raise ValueError("test_commands must be nonempty arrays of nonempty strings")
            smoke, reason = value.get("smoke_args"), value.get("smoke_skip_reason")
            if (smoke is None) == (reason is None) or (smoke is not None and smoke != ["--help"]) or (reason is not None and (not isinstance(reason, str) or not reason.strip())):
                raise ValueError("specify smoke_args = [\"--help\"] or a nonempty smoke_skip_reason")
            result[key] = ProjectTests(project, launcher, req, tuple(tuple(c) for c in commands), tuple(smoke) if smoke is not None else None, reason)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"project {key}: {exc}") from exc
    return result


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    venv = env.pop("VIRTUAL_ENV", None)
    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "UV_SYSTEM_PYTHON", "UV_BREAK_SYSTEM_PACKAGES"):
        env.pop(key, None)
    paths = env.get("PATH", "").split(os.pathsep)
    def is_venv_bin(path: str) -> bool:
        resolved = Path(path).resolve()
        return bool((venv and resolved == (Path(venv) / "bin").resolve()) or
                    (resolved.name == "bin" and (resolved.parent / "pyvenv.cfg").is_file()))
    paths = [p for p in paths if p and not is_venv_bin(p)]
    env["PATH"] = os.pathsep.join(paths)
    env["UV_PYTHON_DOWNLOADS"] = "never"
    return env


def is_approved_interpreter(path: Path, homebrew_root: Path = Path("/opt/homebrew")) -> bool:
    return (path.is_absolute() and path.is_file() and path.is_relative_to(homebrew_root)
            and path.resolve().is_relative_to(homebrew_root.resolve())
            and not (path.parent.parent / "pyvenv.cfg").exists())


def resolve_interpreter(launcher: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="project-tests-discovery-") as scratch:
        env = clean_environment()
        env["TMPDIR"] = scratch
        result = subprocess.run(["uv", "python", "find", "--no-python-downloads", "--no-cache", "--script", str(launcher)], cwd=scratch, env=env, capture_output=True, text=True, check=True)
    interpreter = result.stdout.strip()
    if not is_approved_interpreter(Path(interpreter)):
        raise ValueError(f"uv selected an unapproved interpreter: {interpreter}; install or select an approved Homebrew interpreter")
    return interpreter


def build_test_command(entry: ProjectTests, interpreter: str, command: tuple[str, ...], extra: list[str]) -> list[str]:
    args = ["uv", "run", "--no-project", "--isolated", "--no-python-downloads", "--python", interpreter, "--with-requirements", str(REPO_ROOT / entry.launcher)]
    if entry.test_requirements:
        args.extend(["--with-requirements", str(REPO_ROOT / entry.test_requirements)])
    return args + ["python", "-m", *command, *extra]


def verify_interpreter(entry: ProjectTests, interpreter: str, env: dict[str, str], *, suite: bool = True) -> None:
    metadata = extract_pep723((REPO_ROOT / entry.launcher).read_text(encoding="utf-8"))
    if not metadata or not isinstance(metadata.get("requires-python"), str):
        raise ValueError("launcher has invalid requires-python metadata")
    code = "import sys; print(sys._base_executable); print(sys.version.split()[0])"
    with tempfile.TemporaryDirectory(prefix="project-tests-probe-") as scratch:
        script = Path(scratch) / "probe.py"
        script.write_text('# /// script\n# requires-python = ' + json.dumps(metadata['requires-python']) + '\n# dependencies = []\n# ///\n' + code + '\n', encoding="utf-8")
        reference = subprocess.run(["uv", "run", "--no-python-downloads", "--python", interpreter, "--script", str(script)], cwd=scratch, env=env, capture_output=True, text=True, check=True)
        expected = reference.stdout.strip().splitlines()
        if len(expected) != 2:
            raise ValueError(f"invalid interpreter probe output: {reference.stdout!r}")
        # An explicit --python overrides script metadata in uv. Ask uv to find
        # an installation matching both the metadata and the observed version,
        # without the explicit selection override, to validate the intersection.
        constraint = metadata['requires-python'] + ',==' + expected[1]
        script.write_text('# /// script\n# requires-python = ' + json.dumps(constraint) + '\n# dependencies = []\n# ///\n', encoding="utf-8")
        validation_env = env.copy()
        validation_env.pop("UV_PYTHON", None)
        subprocess.run(["uv", "python", "find", "--no-python-downloads", "--script", str(script)], cwd=scratch, env=validation_env, capture_output=True, text=True, check=True)
    if len(expected) != 2 or Path(expected[0]).resolve() != Path(interpreter).resolve():
        raise ValueError(f"interpreter mismatch: requested {interpreter}, actual {reference.stdout.strip()!r}")
    if not suite:
        print(f"Actual base interpreter: {expected[0]}; Python {expected[1]}", flush=True)
        return
    template = build_test_command(entry, interpreter, ("placeholder",), [])
    probe = template[:-2] + ["-c", code]
    result = subprocess.run(probe, cwd=REPO_ROOT / entry.project, env=env, capture_output=True, text=True, check=True)
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2 or Path(lines[0]).resolve() != Path(expected[0]).resolve() or lines[1] != expected[1]:
        raise ValueError(f"interpreter mismatch: requested {interpreter}, actual {result.stdout.strip()!r}")
    print(f"Actual base interpreter: {lines[0]}; Python {lines[1]}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--install-browsers", action="store_true")
    parser.add_argument("--print-command", action="store_true")
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw_args:
        separator = raw_args.index("--")
        runner_args, extra = raw_args[:separator], raw_args[separator + 1:]
    else:
        runner_args, extra = raw_args, []
    args, unknown = parser.parse_known_args(runner_args)
    if unknown:
        parser.error("extra arguments must follow --")
    if (args.smoke_only and (args.install_browsers or extra)) or (args.install_browsers and extra):
        parser.error("--smoke-only and --install-browsers cannot be combined with other actions or extra arguments")
    try:
        entries = load_project_tests(REPO_ROOT / "tools/project_tests.toml")
        if args.key not in entries:
            raise ValueError(f"unknown project {args.key!r}; available: {', '.join(sorted(entries)) or '(none)'}")
        entry = entries[args.key]
        commands = [("playwright", "install", "chromium")] if args.install_browsers else entry.test_commands
        if args.print_command:
            if entry.smoke_args and not args.install_browsers:
                print(shlex.join([str(REPO_ROOT / entry.launcher), *entry.smoke_args]))
            elif not args.install_browsers:
                print(f"Smoke skipped: {entry.smoke_skip_reason}")
            if not args.smoke_only:
                for cmd in commands:
                    print(shlex.join(build_test_command(entry, "<resolved-interpreter>", cmd, extra)))
            return 0
        env = clean_environment()
        interpreter = resolve_interpreter(REPO_ROOT / entry.launcher)
        print(f"Resolved interpreter: {interpreter}", flush=True)
        verify_interpreter(entry, interpreter, env, suite=False)
        env["UV_PYTHON"] = interpreter
        if not args.install_browsers:
            if entry.smoke_args:
                with tempfile.TemporaryDirectory(prefix="project-tests-smoke-") as scratch:
                    result = subprocess.run([str(REPO_ROOT / entry.launcher), *entry.smoke_args], cwd=scratch, env=env)
                if result.returncode:
                    return result.returncode
            else:
                print(f"Smoke skipped: {entry.smoke_skip_reason}")
        if not args.smoke_only:
            verify_interpreter(entry, interpreter, env)
            for command in commands:
                result = subprocess.run(build_test_command(entry, interpreter, command, extra), cwd=REPO_ROOT / entry.project, env=env)
                if result.returncode:
                    return result.returncode
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"project tests: command failed: {exc}; {exc.stderr or ''}", file=sys.stderr)
        return exc.returncode
    except (ValueError, OSError) as exc:
        print(f"project tests: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
