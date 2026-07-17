"""Runtime-environment setup for cognitive_switchyard.

This module owns the runtime *home* lifecycle — resolving the runtime root,
creating the home/packs/sessions directories, ensuring the global config, and
syncing built-in packs. It contains no venv/bootstrap machinery; dependency
management is handled by uv via the launcher's PEP 723 header.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import GlobalConfig, RuntimePaths, build_runtime_paths, ensure_global_config


@dataclass(frozen=True)
class RuntimeSettings:
    repo_root: Path
    runtime_paths: RuntimePaths
    builtin_packs_root: Path


def default_runtime_settings(
    *,
    runtime_root: Path | None = None,
    builtin_packs_root: Path | None = None,
) -> RuntimeSettings:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_paths = build_runtime_paths(home=runtime_root)
    return RuntimeSettings(
        repo_root=repo_root,
        runtime_paths=runtime_paths,
        builtin_packs_root=builtin_packs_root
        or repo_root / "cognitive_switchyard" / "builtin_packs",
    )


def initialize_runtime_environment(settings: RuntimeSettings) -> GlobalConfig:
    from .pack_loader import list_builtin_pack_names, sync_builtin_packs

    runtime_paths = settings.runtime_paths
    runtime_paths.home.mkdir(parents=True, exist_ok=True)
    runtime_paths.packs.mkdir(parents=True, exist_ok=True)
    runtime_paths.sessions.mkdir(parents=True, exist_ok=True)

    builtin_root = settings.builtin_packs_root
    builtin_names = list_builtin_pack_names(builtin_root)
    default_pack = "claude-code" if "claude-code" in builtin_names else (
        builtin_names[0] if builtin_names else "claude-code"
    )
    config = ensure_global_config(runtime_paths.config, default_pack=default_pack)
    sync_builtin_packs(
        builtin_packs_root=builtin_root,
        runtime_packs_dir=runtime_paths.packs,
    )
    return config
