from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def run_timestamp_slug(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H-%M-%S-%fZ")


def elapsed_milliseconds(started: datetime, ended: datetime) -> int:
    return max(0, int(round((ended - started).total_seconds() * 1000)))


def safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip()).strip("_") or "item"


def runtime_home_from_environ(environ: dict[str, str]) -> Path:
    return Path(environ.get("BENCH_RUNTIME_HOME", str(Path.home() / ".benchmark_llm"))).expanduser()


def merge_environ(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    merged.update(extra)
    return merged


_MODEL_ENV_KEYS = {
    "HOME",
    "PATH",
    "SHELL",
    "TERM",
    "LANG",
    "TMPDIR",
    "TMP",
    "TEMP",
    "USER",
    "LOGNAME",
    "SSH_AUTH_SOCK",
}
_MODEL_ENV_PREFIXES = (
    "OPENAI_",
    "OPENROUTER_",
    "ANTHROPIC_",
    "GOOGLE_",
    "GEMINI_",
    "AZURE_",
    "AWS_",
    "VERTEX_",
    "MISTRAL_",
    "XAI_",
    "TOGETHER_",
    "FIREWORKS_",
    "COHERE_",
    "MODEL_",
    "LLM_",
    "CX_",
    "CC_",
    "CLAUDE_",
    "CODEX_",
    "HTTP_",
    "HTTPS_",
)
_MODEL_ENV_SUFFIXES = (
    "_API_KEY",
    "_ACCESS_TOKEN",
    "_TOKEN",
    "_BASE_URL",
    "_ENDPOINT",
    "_URL",
    "_MODEL",
    "_PROFILE",
)


def build_model_command_env(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in base.items():
        if (
            key in _MODEL_ENV_KEYS
            or key.startswith("LC_")
            or key in {"http_proxy", "https_proxy", "no_proxy", "all_proxy"}
            or key.startswith(_MODEL_ENV_PREFIXES)
            or key.endswith(_MODEL_ENV_SUFFIXES)
        ):
            cleaned[key] = value
    cleaned.update(extra)
    return cleaned


def unique_child_name(parent: Path, base_name: str) -> str:
    candidate = base_name
    counter = 2
    while (parent / candidate).exists():
        candidate = f"{base_name}__{counter}"
        counter += 1
    return candidate


_ENV_VAR_PATTERN = re.compile(r"\$(\w+)|\$\{([^}]+)\}")


def expand_env_string(template: str, environ: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        if key not in environ:
            raise KeyError(f"Missing environment variable: {key}")
        return environ[key]

    return _ENV_VAR_PATTERN.sub(replace, template)


def _pyvenv_home(prefix: str) -> str | None:
    """Return the first `home` value in <prefix>/pyvenv.cfg, or None."""
    try:
        text = (Path(prefix) / "pyvenv.cfg").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "home":
            return value.strip() or None
    return None


def _is_executable_file(path: Path) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


_VERSIONED_DIR = re.compile(r"\d+\.\d+\.\d+")


def unstable_python_warning(label: str, path: str) -> str | None:
    """Return a one-line warning if venvs created from `path` may break later, else None.

    A Homebrew Cellar path, or a path under a directory named for a full X.Y.Z
    version (uv-managed, pyenv, asdf), belongs to one installed version.
    """
    if "/Cellar/" in path:
        reason = "is a versioned Homebrew Cellar path"
    else:
        versioned = next(
            (part for part in Path(path).parent.parts if _VERSIONED_DIR.search(part)), None
        )
        if versioned is None:
            return None
        reason = f"is under a versioned directory ({versioned})"
    return (
        f"[bench] warning: {label} {path} {reason}; "
        "venvs created from it may break when that version is upgraded or removed."
    )


def resolve_base_python(
    *,
    executable: str,
    prefix: str,
    base_prefix: str,
    version: tuple[int, int],
    base_executable: str | None,
) -> tuple[str, str | None]:
    """Return (interpreter_path, warning_or_None) for creating durable venvs.

    Prefers a stable (non-Cellar, unversioned) interpreter path. Symlinks are never
    resolved: resolving them is what pins venvs to a versioned Cellar path.
    """
    exe_name = f"python{version[0]}.{version[1]}"
    candidate: Path | None
    if prefix != base_prefix:
        home = _pyvenv_home(prefix)
        candidate = Path(home) / exe_name if home else None
    else:
        candidate = Path(executable)
    if candidate is not None and "/Cellar/" in str(candidate):
        brew_root, rest = str(candidate).split("/Cellar/", 1)
        formula = rest.split("/", 1)[0]
        opt = Path(brew_root) / "opt" / formula / "bin" / exe_name
        if _is_executable_file(opt):
            candidate = opt
    if candidate is not None and _is_executable_file(candidate):
        return str(candidate), unstable_python_warning("base Python", str(candidate))
    fallback = base_executable or executable
    if base_executable is None and prefix != base_prefix:
        return fallback, (
            f"[bench] warning: no stable base Python found; falling back to {fallback}, "
            "which is a venv interpreter, so venvs created from it will be venv-from-venv."
        )
    return fallback, (
        f"[bench] warning: no stable base Python found; falling back to {fallback}, "
        "so venvs created from it may be pinned to that path."
    )
