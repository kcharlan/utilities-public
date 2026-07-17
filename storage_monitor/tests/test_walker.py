from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "storage_monitor"


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    return load_launcher(SCRIPT_PATH)


def test_walk_matches_du_and_deduplicates_hardlinks(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "tree"
    nested = root / "nested"
    leaf = root / "leaf"
    nested.mkdir(parents=True)
    leaf.mkdir()
    original = nested / "payload"
    original.write_bytes(b"x" * 8192)
    os.link(original, leaf / "linked")
    (leaf / "plain").write_bytes(b"y" * 4096)
    (root / "symlink").symlink_to(nested, target_is_directory=True)

    result = module.walk_tree(root, workers=2, excluded_paths=[])
    attributions, _, _ = module.resolve_hardlink_ownership(
        1, result.hardlink_candidates, module.build_walk_translation(), full_scan=True
    )
    for parent, allocated in attributions:
        result.dir_local[parent] += allocated
    totals = module.rollup_subtree_totals(result.dir_local, str(root))
    expected = int(subprocess.check_output(["du", "-xsk", str(root)], text=True).split()[0]) * 1024

    assert totals[str(root)] == expected
    assert len(result.hardlink_candidates) == 2


def test_rollup_is_bottom_up(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    assert module.rollup_subtree_totals({"/r": 0, "/r/a": 2, "/r/a/b": 3}, "/r") == {
        "/r": 5,
        "/r/a": 5,
        "/r/a/b": 3,
    }


def test_symlink_is_not_followed(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "tree"
    target = root / "target"
    target.mkdir(parents=True)
    (target / "payload").write_bytes(b"x" * 4096)
    (root / "link").symlink_to(target, target_is_directory=True)
    result = module.walk_tree(root, workers=2, excluded_paths=[])
    assert str(root / "link") not in result.dir_local
    assert result.dir_count == 2


def test_sparse_large_file_uses_apparent_size(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "tree"
    root.mkdir()
    sparse = root / "sparse"
    with sparse.open("wb") as handle:
        os.ftruncate(handle.fileno(), module.LARGE_FILE_THRESHOLD_BYTES)
    result = module.walk_tree(root, workers=1, excluded_paths=[])
    assert result.large_files[0]["apparent_bytes"] == module.LARGE_FILE_THRESHOLD_BYTES
    assert result.large_files[0]["allocated_bytes"] < module.LARGE_FILE_THRESHOLD_BYTES


def test_regression_guard_has_no_du_or_find_command_literals():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert '"du"' not in source
    assert '"find"' not in source
