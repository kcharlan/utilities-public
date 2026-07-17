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
