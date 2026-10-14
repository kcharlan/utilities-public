from __future__ import annotations

import os
import subprocess
import sys
import io
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher, run_launcher


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


def synthetic_helper(monkeypatch, tmp_path, payload, tail=""):
    script = tmp_path / "synthetic-walker"
    script.write_text(f"#!{sys.executable}\nimport os, sys, time\nos.write(1, {payload!r})\n{tail}\n")
    script.chmod(0o700)
    monkeypatch.setenv("STORAGE_MONITOR_WALKER", str(script))
    return script


def test_startup_rejects_missing_or_mismatched_walker(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    for walker in (tmp_path / "absent", synthetic_helper(monkeypatch, tmp_path, b"storage_monitor_walk 9.9.9 protocol 99\n")):
        monkeypatch.setenv("STORAGE_MONITOR_WALKER", str(walker))
        with pytest.raises(module.WalkerUnavailable, match="deploy_storage_monitor.mjs"):
            module.check_walker()
        result = run_launcher(SCRIPT_PATH, "--no-browser")
        assert result.returncode == 2
        assert "deploy_storage_monitor.mjs" in result.stderr
        assert not module.RUNTIME_PATHS.home.exists()
    result = run_launcher(SCRIPT_PATH, "--help", env_overrides={"STORAGE_MONITOR_WALKER": str(tmp_path / "absent")})
    assert result.returncode == 0


def test_truncated_stream_raises_and_persists_nothing(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    synthetic_helper(monkeypatch, tmp_path, b"D\0/synthetic/root\0" + b"0\0")
    with pytest.raises(RuntimeError):
        module.walk_tree(tmp_path, workers=1, excluded_paths=[])
    module.ensure_runtime_dirs()
    previous = module.create_scan_run(module.iso_now())
    with module.open_db_connection() as db:
        db.execute("UPDATE scan_runs SET active=1, status='completed' WHERE id=?", (previous,))
        # Persist a real synthetic walk before attempting the failing scan.
    result = module.WalkResult({"/synthetic/root": 42}, [], [], 1, 0, 0, 0)
    module.persist_full_walk(previous, result, {"/synthetic/root": 42}, [], [])
    with module.open_db_connection() as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM nodes")]
    scan_id = module.create_scan_run(module.iso_now())
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: {"command": command, "ok": False, "stdout": "", "stderr": "synthetic", "duration_ms": 0})
    monkeypatch.setattr(module, "collect_snapshot_section", lambda: {"items": []})
    monkeypatch.setattr(module, "run_provider_probe", lambda slug: {})
    module.run_scan_thread(scan_id)
    with module.open_db_connection() as db:
        assert db.execute("SELECT status FROM scan_runs WHERE id=?", (scan_id,)).fetchone()[0] == "failed"
        assert db.execute("SELECT active FROM scan_runs WHERE id=?", (previous,)).fetchone()[0] == 1
        assert [tuple(row) for row in db.execute("SELECT * FROM nodes")] == before


def test_registered_inodes_reach_helper(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    payload = tmp_path / "payload"
    payload.write_bytes(b"x")
    result = module.walk_tree(tmp_path, workers=1, excluded_paths=[], registered_inodes={payload.stat().st_ino})
    assert [item[2] for item in result.hardlink_candidates] == [str(payload)]


def test_walk_tree_missing_root_raises_oserror(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        module.walk_tree(tmp_path / "absent", workers=1, excluded_paths=[])


def test_progress_callback_receives_counts(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    for index in range(4100):
        (tmp_path / str(index)).mkdir()
    counts = []
    module.walk_tree(tmp_path, workers=2, excluded_paths=[], progress_callback=counts.append)
    assert sorted(counts) == [2000, 4000]


def test_invalid_utf8_protocol_paths_roundtrip(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    parent, name = b"/synthetic/\xff", b"name\xfe\n\t"
    payload = b"\0".join([b"D", parent, b"4", b"H", b"1", b"2", b"2", b"8", parent, name,
                           b"L", b"100", b"8", parent, name, b"S", b"1", b"1", b"0", b"0", b""])
    synthetic_helper(monkeypatch, tmp_path, payload)
    result = module.walk_tree(tmp_path, workers=1)
    assert os.fsencode(next(iter(result.dir_local))) == parent
    assert os.fsencode(result.hardlink_candidates[0][2]) == parent + b"/" + name
    assert os.fsencode(result.large_files[0]["name"]) == name


@pytest.mark.parametrize("payload,tail", [
    (b"X\0", "time.sleep(30)"),
    (b"P\0" + b"2000\0", "time.sleep(30)"),
    (b"D\0/synthetic\0bad\0", "time.sleep(30)"),
    (b"S\0" + b"0\0" * 4 + b"D\0/synthetic\0" + b"0\0", ""),
    (b"S\0" + b"0\0" * 4, "sys.stderr.write('synthetic failure'); sys.exit(7)"),
])
def test_helper_errors_reap_process(monkeypatch, tmp_path, payload, tail):
    module = load(monkeypatch, tmp_path)
    synthetic_helper(monkeypatch, tmp_path, payload, tail)
    original = subprocess.Popen
    children = []
    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    def callback(count):
        raise RuntimeError("synthetic callback failure")
    with pytest.raises((RuntimeError, ValueError)):
        module.walk_tree(tmp_path, workers=1, progress_callback=callback)
    assert len(children) == 1
    assert children[0].poll() is not None


def test_record_parser_handles_chunk_boundaries(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    class TinyReads(io.BytesIO):
        def read(self, size):
            return super().read(1)
    assert list(module._iter_walker_records(TinyReads(b"D\0/synthetic\0" + b"4\0"))) == [(b"D", [b"/synthetic", b"4"])]
    with pytest.raises(RuntimeError, match="truncated"):
        list(module._iter_walker_records(io.BytesIO(b"D\0/synthetic\0")))


def test_parity_tool_compares_synthetic_tree_and_refuses_repo_output(tmp_path):
    import json
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "payload").write_bytes(b"synthetic")
    os.link(tree / "payload", tree / "linked")
    with (tree / "sparse").open("wb") as handle:
        os.ftruncate(handle.fileno(), 1 << 30)
    tool = SCRIPT_PATH.parent / "tests/parity/compare_walkers.py"
    output = tmp_path / "parity.json"
    command = [sys.executable, str(tool), "--baseline-ref", "cc21e50", "--root", str(tree), "--output"]
    completed = subprocess.run([*command, str(output)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text())
    assert all(item["mismatches"] == 0 for item in report.values())
    assert report["large_files"]["baseline"] == 1
    assert report["hardlink_owners"]["baseline"] == 1
    assert output.stat().st_mode & 0o777 == 0o600
    completed = subprocess.run([*command, str(REPO_ROOT / "synthetic-parity.json")], capture_output=True, text=True)
    assert completed.returncode == 2
    assert "outside" in completed.stderr
