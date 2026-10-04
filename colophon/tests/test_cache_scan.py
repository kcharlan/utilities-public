"""Synthetic cold discovery and transactional per-file parse-cache coverage."""
import hashlib
import json
import os
from pathlib import Path

import pytest


def log_at(codex_home, name="synthetic.jsonl", data=b'{"type":"synthetic"}\n'):
    path = codex_home / "sessions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def path_key(path):
    key = os.path.abspath(path)
    return key[len("/private"):] if key.startswith("/private/var/") else key


def entry(home, path):
    key = path_key(path)
    return home / "cache" / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def scan(colophon, home, codex_home, **kwargs):
    cache = colophon.ParseCache.open(home, rebuild=kwargs.pop("rebuild", False))
    try:
        result = colophon.scan_logs(codex_home, cache, progress=kwargs.pop("progress", None))
        cache.commit(cache._live_paths)
        return result
    except BaseException:
        cache.abort()
        raise


def cache_bytes(home):
    return {p.name: p.read_bytes() for p in (home / "cache").iterdir()}


def test_unchanged_file_hits_cache(colophon, home, codex_home):
    path = log_at(codex_home)
    cold = scan(colophon, home, codex_home)
    warm = scan(colophon, home, codex_home)
    assert (cold.parsed, cold.cached, cold.bytes_parsed) == (1, 0, path.stat().st_size)
    assert (warm.parsed, warm.cached, warm.bytes_parsed) == (0, 1, 0)
    assert cold.records == warm.records
    assert warm.records[0]["token_stream"] == cold.records[0]["token_stream"]


def test_same_size_same_mtime_rewrite_misses(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    before = path.stat()
    path.write_bytes(b'{"type":"rewritten"}\n')
    assert path.stat().st_size == before.st_size
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    result = scan(colophon, home, codex_home)
    assert (result.parsed, result.cached) == (1, 0)
    assert result.records[0]["unknown_types"] == {"rewritten": 1}


def test_grown_file_reparsed_from_zero(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    with path.open("ab") as fh:
        fh.write(b'{"type":"synthetic"}\n')
    result = scan(colophon, home, codex_home)
    assert (result.parsed, result.cached) == (1, 0)
    assert result.records[0]["unknown_types"] == {"synthetic": 2}


def test_archived_move_reparsed_and_old_entry_pruned(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    dest = codex_home / "archived_sessions" / path.name
    dest.parent.mkdir()
    path.rename(dest)
    result = scan(colophon, home, codex_home)
    assert (result.parsed, result.cached) == (1, 0)
    assert result.records[0]["archived"] is True
    assert not entry(home, path).exists()
    assert entry(home, dest).exists()


def test_deleted_entry_pruned(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    path.unlink()
    result = scan(colophon, home, codex_home)
    assert result.records == []
    assert list((home / "cache").iterdir()) == [home / "cache" / "FORMAT"]


def test_format_mismatch_discards_every_entry(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    (home / "cache" / "FORMAT").write_text("999:999")
    colophon.ParseCache.open(home, rebuild=False)
    assert not entry(home, path).exists()
    assert scan(colophon, home, codex_home).parsed == 1


@pytest.mark.parametrize("damage", ["json", "version", "list", "key", "path", "size", "mtime", "tail"])
def test_invalid_entry_reparsed(colophon, home, codex_home, damage):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    target = entry(home, path)
    obj = json.loads(target.read_text())
    if damage == "json":
        target.write_text("{broken")
    elif damage == "list":
        target.write_text("[]")
    else:
        if damage == "version":
            obj["parser_version"] += 1
        elif damage == "key":
            obj["key"] = None
        elif damage == "path":
            obj["key"]["path"] = "/synthetic/wrong.jsonl"
        elif damage == "size":
            obj["key"]["size"] += 1
        elif damage == "mtime":
            obj["key"]["mtime_ns"] += 1
        elif damage == "tail":
            obj["key"]["tail_sha256"] = "invalid"
        target.write_text(json.dumps(obj))
    assert scan(colophon, home, codex_home).parsed == 1


def test_growth_during_scan_retains_start_key(colophon, home, codex_home):
    path = log_at(codex_home)
    before = path.stat()
    def append(done, total):
        assert (done, total) == (before.st_size, before.st_size)
        with path.open("ab") as fh:
            fh.write(b'{"type":"synthetic"}\n')
    result = scan(colophon, home, codex_home, progress=append)
    assert result.records[0]["key"]["size"] == before.st_size
    assert result.records[0]["key"]["mtime_ns"] == before.st_mtime_ns
    assert result.records[0]["unknown_types"] == {"synthetic": 1}
    assert scan(colophon, home, codex_home).parsed == 1


def test_rebuild_success_replaces_cache(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    (home / "cache" / "synthetic-stale.json").write_text("{}")
    result = scan(colophon, home, codex_home, rebuild=True)
    assert (result.parsed, result.cached) == (1, 0)
    assert sorted(p.name for p in (home / "cache").iterdir()) == sorted(["FORMAT", entry(home, path).name])
    assert not list(home.glob("cache.*-*"))


@pytest.mark.parametrize("exc", [KeyboardInterrupt, RuntimeError])
def test_interrupted_rebuild_preserves_old_bytes(colophon, home, codex_home, exc):
    log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    def interrupt(done, total):
        raise exc("synthetic interruption")
    with pytest.raises(exc):
        scan(colophon, home, codex_home, rebuild=True, progress=interrupt)
    assert cache_bytes(home) == before
    assert not (home / f"cache.rebuild-{os.getpid()}").exists()


def test_put_buffers_until_commit_and_abort_discards(colophon, home, codex_home):
    path = log_at(codex_home)
    cache = colophon.ParseCache.open(home, rebuild=False)
    record = colophon.parse_log_file(path, size=path.stat().st_size,
                                    mtime_ns=path.stat().st_mtime_ns, archived=False)
    cache.put(record)
    assert not entry(home, path).exists()
    cache.abort()
    cache.commit({record["key"]["path"]})
    assert not entry(home, path).exists()


def test_dead_pid_cleanup_and_live_pid_preservation(colophon, home, monkeypatch):
    home.mkdir()
    dead = 99999999
    dead_rebuild = home / f"cache.rebuild-{dead}"
    dead_old = home / f"cache.old-{dead}"
    live = home / f"cache.rebuild-{os.getpid()}"
    malformed = home / "cache.rebuild-invalid"
    for path in (dead_rebuild, dead_old, live, malformed):
        path.mkdir()
    def kill(pid, sig):
        if pid == dead:
            raise ProcessLookupError
        assert pid == os.getpid()
    monkeypatch.setattr(colophon.os, "kill", kill)
    colophon.ParseCache.open(home, rebuild=False)
    assert not dead_rebuild.exists() and not dead_old.exists()
    assert live.exists() and malformed.exists()


def test_dead_old_restored_before_open(colophon, home, codex_home, monkeypatch):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    old = home / "cache.old-99999999"
    (home / "cache").rename(old)
    def kill(pid, sig):
        raise ProcessLookupError
    monkeypatch.setattr(colophon.os, "kill", kill)
    cache = colophon.ParseCache.open(home, rebuild=False)
    assert cache_bytes(home) == before
    assert cache.get(colophon.discover_logs(codex_home)[0]) is not None
    assert not old.exists() and entry(home, path).exists()


def test_permission_denied_pid_is_not_dead(colophon, home, monkeypatch):
    home.mkdir()
    path = home / "cache.rebuild-99999999"
    path.mkdir()
    def kill(pid, sig):
        raise PermissionError
    monkeypatch.setattr(colophon.os, "kill", kill)
    colophon.ParseCache.open(home, rebuild=False)
    assert path.exists()


def test_unreadable_file_reported_and_other_files_continue(colophon, home, codex_home, monkeypatch):
    bad = log_at(codex_home, "a.jsonl")
    good = log_at(codex_home, "b.jsonl")
    original = Path.open
    def fail(path, *args, **kwargs):
        if path_key(path) == path_key(bad) and args == ("rb",):
            raise PermissionError("synthetic denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    result = scan(colophon, home, codex_home)
    assert result.unreadable == [(path_key(bad), "synthetic denied")]
    assert result.parsed == 1 and result.records[0]["key"]["path"] == path_key(good)


def test_progress_counts_only_misses(colophon, home, codex_home):
    first = log_at(codex_home, "a.jsonl")
    scan(colophon, home, codex_home)
    second = log_at(codex_home, "b.jsonl")
    events = []
    result = scan(colophon, home, codex_home, progress=lambda *args: events.append(args))
    assert (result.parsed, result.cached) == (1, 1)
    assert events == [(second.stat().st_size, second.stat().st_size)]
    assert entry(home, first).exists()


def test_cache_files_private_and_compact(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "cache").stat().st_mode & 0o777 == 0o700
    for file in (home / "cache").iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
    assert (home / "cache" / "FORMAT").read_text() == "1:1"
    assert entry(home, path).read_bytes().count(b"\n") == 1


def test_discovery_partition_flat_legacy_and_hidden_rules(colophon, codex_home):
    keep = ["2030/01/07/arbitrary.JSONL", "flat.jsonl", "legacy/deeper/old.JsonL", "203x/01/file.jsonl"]
    reject = [".hidden.jsonl", ".hidden/old.jsonl", "2030/1/07/bad.jsonl", "2030/02/30/bad.jsonl", "2030/01/07/deeper/bad.jsonl", "2030/loose.jsonl", "not.txt"]
    for name in keep + reject:
        log_at(codex_home, name)
    archived = codex_home / "archived_sessions" / "archive.jsonl"
    archived.parent.mkdir()
    archived.write_bytes(b"{}\n")
    result = colophon.discover_logs(codex_home)
    assert [p.path for p in result] == [Path(path_key(codex_home / "sessions" / name)) for name in sorted(keep)] + [Path(path_key(archived))]
    assert [p.archived for p in result] == [False] * len(keep) + [True]
    assert all(p.size == p.path.stat().st_size and p.mtime_ns == p.path.stat().st_mtime_ns for p in result)


def test_discovery_file_identity_dedup(colophon, codex_home):
    first = log_at(codex_home, "a.jsonl")
    os.link(first, codex_home / "sessions" / "b.jsonl")
    archive = codex_home / "archived_sessions"
    archive.mkdir()
    os.link(first, archive / "c.jsonl")
    assert [p.path for p in colophon.discover_logs(codex_home)] == [Path(path_key(first))]


def test_path_key_preserves_symlink_spelling(colophon, home, codex_home, tmp_path):
    path = log_at(codex_home)
    alias = tmp_path / "synthetic-alias"
    alias.symlink_to(codex_home, target_is_directory=True)
    result = scan(colophon, home, alias)
    key = path_key(alias / "sessions" / path.name)
    assert result.records[0]["key"]["path"] == key
    assert scan(colophon, home, alias).cached == 1


def test_path_key_only_private_var_alias(colophon):
    assert colophon.codex_path_key(Path("/private/var/synthetic/file.jsonl")) == "/var/synthetic/file.jsonl"
    assert colophon.codex_path_key(Path("/private/variant/synthetic/file.jsonl")) == "/private/variant/synthetic/file.jsonl"


def test_processing_order_uses_milliseconds_then_size_then_path(colophon, home, codex_home):
    paths = [log_at(codex_home, name, data) for name, data in [
        ("a.jsonl", b"{}\n{}\n"), ("b.jsonl", b"{}\n"), ("c.jsonl", b"{}\n"), ("d.jsonl", b"{}\n")]]
    for path, nanos in zip(paths, [1000999999, 1000000000, 1000888888, 1001000000]):
        os.utime(path, ns=(nanos, nanos))
    result = scan(colophon, home, codex_home)
    assert [Path(r["key"]["path"]).name for r in result.records] == ["d.jsonl", "b.jsonl", "c.jsonl", "a.jsonl"]


def test_bool_parser_version_is_not_valid_evidence(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    target = entry(home, path)
    obj = json.loads(target.read_text())
    obj["parser_version"] = True
    target.write_text(json.dumps(obj))
    assert scan(colophon, home, codex_home).parsed == 1


def test_directory_shaped_jsonl_is_discovered_and_reported(colophon, home, codex_home):
    paths = [codex_home / "sessions" / name for name in
             ["flat.jsonl", "2030/01/07/day.jsonl", "legacy/nested.jsonl"]]
    for path in paths:
        path.mkdir(parents=True)
    discovered = colophon.discover_logs(codex_home)
    assert {str(log.path) for log in discovered} == {path_key(p) for p in paths}
    result = scan(colophon, home, codex_home)
    assert {path for path, reason in result.unreadable} == {path_key(p) for p in paths}
    assert all("directory" in reason.lower() for path, reason in result.unreadable)
    assert result.records == []


def test_stat_failure_still_reports_unreadable_candidate(colophon, home, codex_home, monkeypatch):
    path = log_at(codex_home)
    original_stat = Path.stat
    original_open = Path.open
    def fail_stat(target, *args, **kwargs):
        if path_key(target) == path_key(path):
            raise PermissionError("synthetic stat denied")
        return original_stat(target, *args, **kwargs)
    def fail_open(target, *args, **kwargs):
        if path_key(target) == path_key(path):
            raise PermissionError("synthetic read denied")
        return original_open(target, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", fail_stat)
    monkeypatch.setattr(Path, "open", fail_open)
    discovered = colophon.discover_logs(codex_home)
    assert [(log.size, log.mtime_ns) for log in discovered] == [(0, 0)]
    assert scan(colophon, home, codex_home).unreadable == [(path_key(path), "synthetic read denied")]


def test_oversized_pid_is_ambiguous_and_left_alone(colophon, home):
    home.mkdir()
    path = home / ("cache.rebuild-" + "9" * 230)
    path.mkdir()
    colophon.ParseCache.open(home, rebuild=False)
    assert path.exists()


def test_rebuild_failed_install_restores_old_cache(colophon, home, codex_home, monkeypatch):
    log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    original = Path.rename
    def fail(path, target):
        if path.name == f"cache.rebuild-{os.getpid()}":
            raise OSError("synthetic swap failure")
        return original(path, target)
    monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(OSError, match="synthetic swap failure"):
        scan(colophon, home, codex_home, rebuild=True)
    assert cache_bytes(home) == before
    assert not list(home.glob("cache.*-*"))


def test_rebuild_failed_entry_write_preserves_old_cache(colophon, home, codex_home, monkeypatch):
    log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    def fail(*args, **kwargs):
        raise OSError("synthetic full disk")
    monkeypatch.setattr(colophon, "atomic_write_json", fail)
    with pytest.raises(OSError, match="synthetic full disk"):
        scan(colophon, home, codex_home, rebuild=True)
    assert cache_bytes(home) == before
    assert not list(home.glob("cache.*-*"))


def test_cached_tail_read_failure_is_reported(colophon, home, codex_home, monkeypatch):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    original = Path.open
    handles = []
    class BrokenReader:
        def __init__(self, fh):
            self.fh = fh
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.fh.close()
        def seek(self, *args):
            return self.fh.seek(*args)
        def read(self, *args):
            raise OSError("synthetic read failure")
    def fail(target, *args, **kwargs):
        fh = original(target, *args, **kwargs)
        if path_key(target) == path_key(path) and args == ("rb",):
            handles.append(fh)
            return BrokenReader(fh)
        return fh
    monkeypatch.setattr(Path, "open", fail)
    result = scan(colophon, home, codex_home)
    assert result.unreadable == [(path_key(path), "synthetic read failure")]
    assert result.records == [] and result.cached == result.parsed == 0
    assert len(handles) == 1 and handles[0].closed


def test_foundation_package_descendants_and_symlinks(colophon, codex_home):
    names = ["synthetic.app", "synthetic.bundle", "synthetic.pkg", "synthetic.pages",
             "synthetic.framework", "synthetic.xcassets", "synthetic.ordinary"]
    for name in names:
        log_at(codex_home, name + "/synthetic.jsonl")
    root = codex_home / "sessions"
    (root / "alias-ordinary").symlink_to(root / "synthetic.app", target_is_directory=True)
    (root / "alias.app").symlink_to(root / "synthetic.ordinary", target_is_directory=True)
    (root / "alias.jsonl").symlink_to(root / "synthetic.ordinary", target_is_directory=True)
    allowed = names[4:] if colophon.sys.platform == "darwin" else names
    expected = {path_key(root / name / "synthetic.jsonl") for name in allowed}
    expected.add(path_key(root / "alias.jsonl"))
    assert {str(log.path) for log in colophon.discover_logs(codex_home)} == expected


def test_non_darwin_package_option_is_ignored(colophon, monkeypatch):
    monkeypatch.setattr(colophon.sys, "platform", "linux")
    assert colophon._is_package(Path("/synthetic/ordinary.app")) is False


@pytest.mark.parametrize("created,value,error,copy_ok,raise_boolean,expected", [
    (11, 12, 0, True, False, True),
    (11, 0, 13, False, False, False),
    (11, 0, 0, True, False, False),
    (0, 0, 0, False, False, False),
    (11, 12, 13, True, True, None),
])
def test_package_property_releases_every_owned_reference(colophon, monkeypatch,
        created, value, error, copy_ok, raise_boolean, expected):
    import ctypes
    from types import SimpleNamespace
    released = []
    def create(*args):
        return created
    def copy(url, key, value_out, error_out):
        ctypes.cast(value_out, ctypes.POINTER(ctypes.c_void_p))[0] = value
        ctypes.cast(error_out, ctypes.POINTER(ctypes.c_void_p))[0] = error
        return copy_ok
    def boolean(pointer):
        assert pointer.value
        if raise_boolean:
            raise RuntimeError("synthetic native failure")
        return True
    api = SimpleNamespace(CFURLCreateFromFileSystemRepresentation=create,
                          CFURLCopyResourcePropertyForKey=copy,
                          CFBooleanGetValue=boolean,
                          CFRelease=lambda obj: released.append(obj.value if hasattr(obj, "value") else obj))
    monkeypatch.setattr(colophon.sys, "platform", "darwin")
    monkeypatch.setattr(colophon, "_darwin_resource_api",
                        lambda: (api, {"kCFURLIsPackageKey": 99, "kCFURLIsHiddenKey": 98}))
    if raise_boolean:
        with pytest.raises(RuntimeError, match="synthetic native failure"):
            colophon._is_package(Path("/synthetic/ordinary.app"))
    else:
        assert colophon._is_package(Path("/synthetic/ordinary.app")) is expected
    assert released == ([v for v in (value, error, created) if v] if created else [])


def test_hidden_resource_flag_excludes_files_and_descendants(colophon, codex_home):
    import stat
    paths = [log_at(codex_home, "flagged.jsonl"),
             log_at(codex_home, "legacy-flagged/inside.jsonl"),
             log_at(codex_home, "2030/01/07/flagged.jsonl")]
    directory = paths[1].parent
    flagged = [paths[0], directory, paths[2]] if colophon.sys.platform == "darwin" else []
    original_flags = {path: path.stat().st_flags for path in flagged}
    try:
        for path in flagged:
            os.chflags(path, original_flags[path] | stat.UF_HIDDEN)
        result = colophon.discover_logs(codex_home)
        expected = set() if flagged else {path_key(p) for p in paths}
        assert {str(log.path) for log in result} == expected
    finally:
        for path, flags in original_flags.items():
            os.chflags(path, flags)


@pytest.mark.parametrize("ancestor", ["2030", "2030/01", "2030/01/07"])
def test_hidden_partition_ancestor_does_not_hide_visible_day_entry(colophon, codex_home, ancestor):
    import stat
    path = log_at(codex_home, "2030/01/07/visible.jsonl")
    directory = codex_home / "sessions" / ancestor
    original_flags = directory.stat().st_flags if colophon.sys.platform == "darwin" else None
    try:
        if original_flags is not None:
            os.chflags(directory, original_flags | stat.UF_HIDDEN)
        assert [str(log.path) for log in colophon.discover_logs(codex_home)] == [path_key(path)]
    finally:
        if original_flags is not None:
            os.chflags(directory, original_flags)


def test_scan_buffers_until_caller_commit(colophon, home, codex_home):
    path = log_at(codex_home)
    cache = colophon.ParseCache.open(home, rebuild=False)
    result = colophon.scan_logs(codex_home, cache, progress=None)
    assert result.parsed == 1
    assert not entry(home, path).exists()
    cache.commit({record["key"]["path"] for record in result.records})
    assert entry(home, path).exists()


def test_successful_rebuild_scan_can_abort_before_commit(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    cache = colophon.ParseCache.open(home, rebuild=True)
    result = colophon.scan_logs(codex_home, cache, progress=None)
    assert result.parsed == 1
    assert (home / f"cache.rebuild-{os.getpid()}").exists()
    assert cache_bytes(home) == before
    cache.abort()
    assert cache_bytes(home) == before and not list(home.glob("cache.*-*"))


def test_scan_keeps_unreadable_live_paths_for_deferred_pruning(colophon, home, codex_home, monkeypatch):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    cache = colophon.ParseCache.open(home, rebuild=False)
    original = Path.open
    def fail(target, *args, **kwargs):
        if path_key(target) == path_key(path) and args == ("rb",):
            raise PermissionError("synthetic denied")
        return original(target, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    result = colophon.scan_logs(codex_home, cache, progress=None)
    assert result.unreadable == [(path_key(path), "synthetic denied")]
    assert cache._live_paths == {path_key(path)}
    cache.commit(cache._live_paths)
    assert entry(home, path).exists()


@pytest.mark.parametrize("exception", [OSError, KeyboardInterrupt])
def test_post_install_cleanup_preserves_committed_state(colophon, home, codex_home, monkeypatch, exception):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    with path.open("ab") as fh:
        fh.write(b'{"type":"synthetic"}\n')
    cache = colophon.ParseCache.open(home, rebuild=True)
    result = colophon.scan_logs(codex_home, cache, progress=None)
    old = home / f"cache.old-{os.getpid()}"
    original = colophon.shutil.rmtree
    def fail(target, *args, **kwargs):
        if target == old:
            (old / "FORMAT").unlink()
            raise exception("synthetic cleanup failure")
        return original(target, *args, **kwargs)
    monkeypatch.setattr(colophon.shutil, "rmtree", fail)
    if exception is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt, match="synthetic cleanup failure"):
            cache.commit(cache._live_paths)
    else:
        cache.commit(cache._live_paths)
    assert cache.finished is True and cache._committed is True and cache.buffer == {}
    assert json.loads(entry(home, path).read_text())["unknown_types"] == {"synthetic": 2}
    assert old.exists()
    cache.abort()
    assert json.loads(entry(home, path).read_text()) == result.records[0]


@pytest.mark.parametrize("action", ["abort", "commit"])
def test_cache_committed_marker_distinguishes_abort(colophon, home, codex_home, action):
    path = log_at(codex_home)
    cache = colophon.ParseCache.open(home, rebuild=False)
    assert cache._committed is False
    colophon.scan_logs(codex_home, cache, progress=None)
    if action == "abort":
        cache.abort()
        assert cache._committed is False
    else:
        cache.commit(cache._live_paths)
        assert cache._committed is True
        cache.abort()
        assert cache._committed is True
    assert cache.finished is True


def interrupt_commit_boundary(cache, boundary, exception):
    """Deliver one real trace interrupt immediately after a completed rename."""
    import inspect
    import sys
    source, first_line = inspect.getsourcelines(type(cache).commit)
    if boundary.startswith("statement:"):
        statement = boundary.removeprefix("statement:")
        index = next(i for i, line in enumerate(source) if line.strip() == statement)
    elif boundary == "backup":
        index = next(i for i, line in enumerate(source) if "self.installed.rename(old)" in line) + 1
        while not source[index].strip() or source[index].lstrip().startswith("#"):
            index += 1
    else:
        install_index = next(i for i, line in enumerate(source) if "self.directory.rename(self.installed)" in line)
        index = next(i for i, line in enumerate(source)
                     if i > install_index and "self._committed = True" in line)
    target_line = first_line + index
    injected = False
    original_trace = sys.gettrace()
    def trace(frame, event, arg):
        nonlocal injected
        if (event == "line" and frame.f_code is type(cache).commit.__code__
                and frame.f_lineno == target_line and not injected):
            injected = True
            raise exception
        return trace
    try:
        sys.settrace(trace)
        cache.commit(cache._live_paths)
    finally:
        sys.settrace(original_trace)
        assert injected, "Synthetic interrupt boundary was not exercised"


def test_interrupt_immediately_after_backup_rename_restores_old(colophon, home, codex_home):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    with path.open("ab") as fh:
        fh.write(b'{"type":"synthetic"}\n')
    cache = colophon.ParseCache.open(home, rebuild=True)
    colophon.scan_logs(codex_home, cache, progress=None)
    interruption = KeyboardInterrupt("synthetic post-backup interrupt")
    with pytest.raises(KeyboardInterrupt) as caught:
        interrupt_commit_boundary(cache, "backup", interruption)
    assert caught.value is interruption
    cache.abort()
    assert cache_bytes(home) == before
    assert cache._committed is False
    assert not list(home.glob("cache.*-*"))


@pytest.mark.parametrize("existing_cache", [False, True])
def test_interrupt_immediately_after_install_records_commit(colophon, home, codex_home, existing_cache):
    path = log_at(codex_home)
    if existing_cache:
        scan(colophon, home, codex_home)
        before = cache_bytes(home)
        with path.open("ab") as fh:
            fh.write(b'{"type":"synthetic"}\n')
    cache = colophon.ParseCache.open(home, rebuild=True)
    result = colophon.scan_logs(codex_home, cache, progress=None)
    interruption = KeyboardInterrupt("synthetic post-install interrupt")
    with pytest.raises(KeyboardInterrupt) as caught:
        interrupt_commit_boundary(cache, "install", interruption)
    assert caught.value is interruption
    assert cache._committed is True and cache.finished is True and cache.buffer == {}
    cache.abort()
    assert json.loads(entry(home, path).read_text()) == result.records[0]
    old = home / f"cache.old-{os.getpid()}"
    if existing_cache:
        assert {p.name: p.read_bytes() for p in old.iterdir()} == before
    else:
        assert not old.exists()
    assert not (home / f"cache.rebuild-{os.getpid()}").exists()


@pytest.mark.parametrize("statement,installed_new", [
    ("if prior_identity is not None:", False),
    ("self.installed.rename(old)", False),
    ("self.directory.rename(self.installed)", False),
    ("self._committed = True", True),
    ("self.buffer.clear()", True),
    ("self.finished = True", True),
    ("if self.rebuild and prior_identity is not None:", True),
])
def test_rebuild_interrupt_swap_and_bookkeeping_boundaries(colophon, home, codex_home,
                                                          statement, installed_new):
    path = log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    with path.open("ab") as fh:
        fh.write(b'{"type":"synthetic"}\n')
    cache = colophon.ParseCache.open(home, rebuild=True)
    result = colophon.scan_logs(codex_home, cache, progress=None)
    interruption = KeyboardInterrupt("synthetic traced swap interrupt")
    with pytest.raises(KeyboardInterrupt) as caught:
        interrupt_commit_boundary(cache, "statement:" + statement, interruption)
    assert caught.value is interruption
    cache.abort()
    assert cache._committed is installed_new
    if installed_new:
        assert json.loads(entry(home, path).read_text()) == result.records[0]
        old = home / f"cache.old-{os.getpid()}"
        assert {p.name: p.read_bytes() for p in old.iterdir()} == before
    else:
        assert cache_bytes(home) == before
        assert not list(home.glob("cache.*-*"))


@pytest.mark.parametrize("backup_kind", ["directory", "broken_symlink"])
def test_preexisting_backup_is_never_claimed_or_modified(colophon, home, codex_home, backup_kind):
    log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    cache = colophon.ParseCache.open(home, rebuild=True)
    colophon.scan_logs(codex_home, cache, progress=None)
    old = home / f"cache.old-{os.getpid()}"
    if backup_kind == "directory":
        old.mkdir()
        (old / "synthetic-marker").write_bytes(b"synthetic existing backup")
    else:
        old.symlink_to(home / "synthetic-missing-target", target_is_directory=True)
    with pytest.raises(FileExistsError, match="Rebuild backup already exists"):
        cache.commit(cache._live_paths)
    cache.abort()
    assert cache_bytes(home) == before and cache._committed is False
    if backup_kind == "directory":
        assert (old / "synthetic-marker").read_bytes() == b"synthetic existing backup"
    else:
        assert old.is_symlink()


def test_missing_install_path_does_not_prove_backup_ownership(colophon, home, codex_home, monkeypatch):
    log_at(codex_home)
    scan(colophon, home, codex_home)
    before = cache_bytes(home)
    cache = colophon.ParseCache.open(home, rebuild=True)
    colophon.scan_logs(codex_home, cache, progress=None)
    old = home / f"cache.old-{os.getpid()}"
    preserved = home / "synthetic-preserved-original"
    interruption = KeyboardInterrupt("synthetic changed backup ownership")
    original = Path.rename
    def replace_backup(path, target):
        result = original(path, target)
        if path == cache.installed and target == old:
            original(old, preserved)
            old.mkdir()
            (old / "synthetic-marker").write_bytes(b"synthetic foreign directory")
            raise interruption
        return result
    monkeypatch.setattr(Path, "rename", replace_backup)
    with pytest.raises(KeyboardInterrupt) as caught:
        cache.commit(cache._live_paths)
    assert caught.value is interruption
    cache.abort()
    assert cache._committed is False and not cache.installed.exists()
    assert (old / "synthetic-marker").read_bytes() == b"synthetic foreign directory"
    assert {p.name: p.read_bytes() for p in preserved.iterdir()} == before
