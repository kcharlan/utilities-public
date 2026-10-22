"""Filesystem isolation shared by synthetic browser acceptance builders."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


_GIT_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _is_within_repository(candidate: Path, repository_root: Path) -> bool:
    resolved = candidate.expanduser().resolve()
    return any(
        ancestor.exists() and os.path.samefile(ancestor, repository_root)
        for ancestor in (resolved, *resolved.parents)
    )


def _prepare_empty_runtime_home(runtime_home: Path) -> Path:
    # The common Git directory belongs to the main checkout when this helper
    # runs in a linked worktree. Both checkout trees are public source trees.
    common_directory = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=_GIT_REPOSITORY_ROOT, text=True,
    ).strip())
    repository_roots = (_GIT_REPOSITORY_ROOT, common_directory.parent)
    resolved = runtime_home.expanduser().resolve()
    if any(_is_within_repository(resolved, root) for root in repository_roots):
        raise ValueError(
            f"Synthetic validation runtime must be outside the git repository: {resolved}"
        )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise ValueError(
                f"Synthetic validation runtime must be a new or empty directory: {resolved}"
            )
    else:
        resolved.mkdir(parents=True)
        resolved = runtime_home.expanduser().resolve()
        if any(_is_within_repository(resolved, root) for root in repository_roots):
            raise ValueError(
                f"Synthetic validation runtime must be outside the git repository: {resolved}"
            )
    return resolved
