"""Shared synthetic config-access helpers for tax2 tests (one definition each)."""
import contextlib
import os
from pathlib import Path

import pytest


UNREADABLE_WARNING = 'Unable to read config.yaml; using defaults'


def tree_snapshot(root):
    """Record every entry's bytes (files) and mtime so creation or rewrites are visible."""
    snapshot = {}
    for directory, directories, files in os.walk(root):
        for name in directories + files:
            path = Path(directory) / name
            snapshot[path.relative_to(root).as_posix()] = (
                None if path.is_dir() else path.read_bytes(), path.lstat().st_mtime_ns)
    snapshot['.'] = (None, root.lstat().st_mtime_ns)
    return snapshot


def warning_count(caplog):
    return [record.getMessage() for record in caplog.records].count(UNREADABLE_WARNING)


@contextlib.contextmanager
def unreadable_config_chain(root, home):
    """Link home/config.yaml through a real chmod-000 directory.

    The synthetic target exists but cannot be resolved or read while the body
    runs. Permissions are always restored, then the blocked tree must be
    byte-for-byte and mtime-for-mtime unchanged (nothing created or rewritten).
    """
    if os.geteuid() == 0:
        pytest.skip('root bypasses directory permissions')
    blocked = root / 'blocked'
    target = blocked / 'dir' / 'config.yaml'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'default_states: [XF]\n')
    home.mkdir(mode=0o700, exist_ok=True)
    (home / 'config.yaml').symlink_to(target)
    before = tree_snapshot(blocked)
    blocked.chmod(0)
    try:
        yield blocked
    finally:
        blocked.chmod(0o700)
    assert tree_snapshot(blocked) == before
    assert (home / 'config.yaml').is_symlink()
