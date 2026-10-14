"""Keep private scan artifacts outside every registered public checkout."""

import os
from pathlib import Path
import subprocess


def reject_repository_destinations(parser, repository_root, *destinations):
    """Fail closed before scan code loads; resolve symlinked destinations too."""
    # Git selection variables override cwd, potentially hiding this repository's
    # primary checkout. Preserve user configuration and all other environment.
    git_environment = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        git_environment.pop(name, None)
    try:
        inventory = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain", "-z"],
            cwd=repository_root, stderr=subprocess.PIPE, env=git_environment,
        )
    except (OSError, subprocess.CalledProcessError):
        parser.error("cannot establish public checkouts; refusing scan destinations")
    repositories = {Path(repository_root).resolve()}
    repositories.update(
        Path(os.fsdecode(field[len(b"worktree "):])).resolve()
        for field in inventory.split(b"\0") if field.startswith(b"worktree ")
    )
    for destination in destinations:
        if any(destination.expanduser().resolve().is_relative_to(root) for root in repositories):
            parser.error("scan destinations must resolve outside every repository checkout")
