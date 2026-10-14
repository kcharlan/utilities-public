from __future__ import annotations

import sys
import time
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "storage_monitor"


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    return load_launcher(SCRIPT_PATH)


CASES = [
    ("/r", "/r"), ("/r", "/r/"), ("/r", "/r/a"), ("/r", "/r/a/b/c"),
    ("/r", "/r//a///b"), ("/r", "/r/./a"), ("/r", "/r/a/"),
    ("/r", "/rx/a"), ("/r", "/other"), ("/r/", "/r/a"),
    ("/", "/a/b"), ("/r", "relative/a"),
    # Normalization applies before matching the root; '..' stays lexical.
    ("/r", "/./r/a"), ("/r", "///r/a"), ("/r", "/r/../a"),
    ("/r/a", "/r/a/../b"), ("/r", "/other/../r/a"),
    (".", "a/b"), (".", "./a//b/"), (".", ""), (".", "../a"),
    (".", "/a"), ("r", "./r/a"), ("r", "r//./a"), ("r", "/r/a"),
    ("r/..", "r/../a"),
    # POSIX preserves exactly two leading slashes as a distinct anchor.
    ("/", "//a/b"), ("/", "///a/b"), ("//", "//a/b"),
    ("//", "/a/b"), ("//r", "//r/a"), ("//r", "///r/a"),
    ("/r", "//r/a"), ("//r", "//./r/a"),
]


def reference(root, path_str):
    try:
        return len(PurePosixPath(path_str).relative_to(PurePosixPath(root)).parts)
    except ValueError:
        return 0


@pytest.mark.parametrize("root,path_str", CASES)
def test_path_depth_matches_pathlib(monkeypatch, tmp_path, root, path_str):
    module = load(monkeypatch, tmp_path)
    assert module.path_depth(Path(root), path_str) == reference(root, path_str)


def test_path_depth_is_fast(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = Path("/synthetic/root")
    paths = [f"/synthetic/root/a{i}/b/c/d" for i in range(300_000)]
    started = time.perf_counter()
    for item in paths:
        module.path_depth(root, item)
    assert time.perf_counter() - started < 1.0
