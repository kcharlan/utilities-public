from __future__ import annotations

import sys
import threading
import time
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "storage_monitor"


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    return load_launcher(SCRIPT_PATH)


def reference(root, path_str):
    try:
        return len(PurePosixPath(path_str).relative_to(PurePosixPath(root)).parts)
    except ValueError:
        return 0


def test_unreadable_report_caps_items_and_rebuild_preserves_it(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    unreadable = [(f"/synthetic/denied-{i}", 13) for i in range(205)]
    section = module.format_unreadable(unreadable, {})
    assert section["count"] == 205
    assert len(section["items"]) == 200
    assert section["items"][0] == {"path": "/synthetic/denied-0", "errno": 13, "reason": "Permission denied"}
    monkeypatch.setattr(module, "build_breakdowns_from_db", lambda scan_id: {key: {"total_bytes": 0} for key in ("data_root", "home_root", "applications_root")})
    monkeypatch.setattr(module, "fetch_large_files_from_db", lambda scan_id: {"items": []})
    monkeypatch.setattr(module, "build_findings_section", lambda *args: {"items": []})
    metadata = dict.fromkeys(("container_size_bytes", "container_used_bytes", "container_free_bytes", "data_volume_used_bytes", "system_volume_used_bytes"))
    rebuilt = module.build_updated_report(1, {"unreadable": section}, metadata, [], {"items": []})
    assert rebuilt["unreadable"] == section


def test_path_depth_matches_pathlib(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    cases = [
        ("/r", "/r"), ("/r", "/r/"), ("/r", "/r/a"),
        ("/r", "/r/a/b/c"), ("/r", "/r//a///b"),
        ("/r", "/r/./a"), ("/r", "/r/a/"), ("/r", "/rx/a"),
        ("/r", "/other"), ("/r/", "/r/a"), ("/", "/a/b"),
        ("/r", "/r/../a"),
    ]
    for root, path_str in cases:
        assert module.path_depth(Path(root), path_str) == reference(root, path_str)


def test_path_depth_is_fast(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = Path("/synthetic/root")
    paths = [f"/synthetic/root/a{i}/b/c/d" for i in range(300_000)]
    started = time.perf_counter()
    for item in paths:
        module.path_depth(root, item)
    fast_duration = time.perf_counter() - started
    started = time.perf_counter()
    for item in paths:
        reference(root, item)
    reference_duration = time.perf_counter() - started
    assert fast_duration < reference_duration / 2


def test_provider_probes_start_before_walk(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    module.ensure_runtime_home(module.RUNTIME_PATHS)
    module.initialize_scan_db(module.RUNTIME_PATHS)
    scan_id = module.create_scan_run(module.iso_now())
    started = {slug: threading.Event() for slug in module.PROVIDER_SPECS}
    release = threading.Event()
    walk_raised = threading.Event()
    returned = threading.Event()
    probe_threads = []
    probe_times = {}
    finished = set()
    outcome = []
    times = {}
    sentinel = RuntimeError("synthetic walk failure")
    existing_threads = set(threading.enumerate())

    def run_command(command, *, timeout):
        slug = next((key for key, spec in module.PROVIDER_SPECS.items()
                     if command == spec["probe"]), None)
        if slug is not None:
            assert timeout == module.PROVIDER_SPECS[slug]["probe_timeout"]
            probe_threads.append(threading.current_thread())
            probe_times[slug] = time.monotonic()
            started[slug].set()
            assert release.wait(10), "test did not release provider probes"
            finished.add(slug)
        return {"command": command, "ok": True, "stdout": "", "stderr": "", "duration_ms": 1}

    def walk_tree(*args, **kwargs):
        times["walk"] = time.monotonic()
        for event in started.values():
            if not event.wait(5):
                break
        times["sentinel"] = time.monotonic()
        walk_raised.set()
        raise sentinel

    def collect():
        try:
            module.collect_scan_report(scan_id)
        except BaseException as error:
            outcome.append((error, set(finished)))
        finally:
            returned.set()

    monkeypatch.setattr(module.shutil, "which", lambda binary: f"/synthetic/bin/{binary}")
    monkeypatch.setattr(module, "run_command", run_command)
    monkeypatch.setattr(module, "collect_snapshot_section", lambda: {"items": []})
    monkeypatch.setattr(module, "walk_tree", walk_tree)
    collector = threading.Thread(target=collect, name="synthetic-scan-collector")
    collector.start()
    try:
        assert walk_raised.wait(10), "volume walk did not reach the sentinel"
        assert all(event.is_set() for event in started.values()), "provider probes did not overlap the walk"
        assert all(timestamp <= times["sentinel"] for timestamp in probe_times.values())
        assert not returned.is_set()
    finally:
        release.set()
        collector.join(10)
    assert not collector.is_alive()
    assert outcome == [(sentinel, set(module.PROVIDER_SPECS))]
    assert all(not thread.is_alive() for thread in probe_threads)
    assert not [thread for thread in threading.enumerate()
                if thread not in existing_threads and thread.name.startswith("ThreadPoolExecutor-")]
