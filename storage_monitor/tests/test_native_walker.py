"""Acceptance tests using exclusively synthetic filesystem fixtures."""
from collections import Counter
import os
import re
import subprocess
import unicodedata


FIELD_COUNTS = {b"D": 2, b"H": 6, b"L": 4, b"P": 1, b"S": 4}


def run_walk(binary, root, *extra, stdin=None):
    result = subprocess.run([binary, "walk", "--root", root, "--workers", "4", "--large-file-bytes", "1", "--progress-every", "2000", *extra], input=stdin, capture_output=True, timeout=90)
    assert b"Sanitizer" not in result.stderr and b"runtime error" not in result.stderr, result.stderr
    fields = result.stdout.split(b"\0")
    assert fields.pop() == b""
    records = []
    while fields:
        kind = fields.pop(0)
        count = FIELD_COUNTS[kind]
        assert len(fields) >= count
        records.append((kind, *fields[:count]))
        del fields[:count]
    if result.returncode == 0:
        assert records[-1][0] == b"S"
        assert sum(r[0] == b"S" for r in records) == 1
    return records, result


def good_walk(binary, root, *extra, **kwargs):
    records, result = run_walk(binary, root, *extra, **kwargs)
    assert result.returncode == 0, result.stderr
    return records


def mixed_tree(root):
    nested, leaf = root / "nested", root / "leaf"
    nested.mkdir(parents=True)
    leaf.mkdir()
    original = nested / "payload"
    original.write_bytes(b"x" * 8192)
    os.link(original, leaf / "linked")
    (leaf / "plain").write_bytes(b"y" * 4096)
    (root / "symlink").symlink_to(nested, target_is_directory=True)


def allocated_total(records):
    links = {(r[1], r[2]): int(r[4]) for r in records if r[0] == b"H"}
    return sum(int(r[2]) for r in records if r[0] == b"D") + sum(links.values())


def test_version_reports_protocol(walker_binary):
    result = subprocess.run([walker_binary, "--version"], capture_output=True)
    assert result.returncode == 0 and not result.stderr
    assert re.fullmatch(rb"storage_monitor_walk \d+\.\d+\.\d+ protocol 1\n", result.stdout)


def test_matches_du_on_nested_tree_with_hardlinks_and_symlinks(walker_binary, tmp_path):
    mixed_tree(tmp_path / "tree")
    records = good_walk(walker_binary, tmp_path / "tree")
    expected = int(subprocess.check_output(["du", "-xsk", tmp_path / "tree"]).split()[0]) * 1024
    assert allocated_total(records) == expected
    assert sum(r[0] == b"H" for r in records) == 2


def test_names_with_control_characters_round_trip(walker_binary, tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    for name in ["new\nline", "tab\tname", "sp ace", "é", unicodedata.normalize("NFD", "é") + "-nfd"]:
        child = root / name
        child.mkdir()
        (child / name).write_bytes(b"synthetic")
        os.link(child / name, child / (name + "-link"))
    raw = os.fsencode(root) + b"/raw-\xe2\x98\x83"
    os.mkdir(raw)
    with open(raw + b"/raw-\xe2\x98\x82", "wb") as handle:
        handle.write(b"synthetic")
    expected_dirs, expected_names = {os.fsencode(root)}, set()
    for directory in os.scandir(root):
        expected_dirs.add(os.fsencode(directory.path))
        for entry in os.scandir(directory.path):
            expected_names.add((os.fsencode(directory.path), os.fsencode(entry.name)))
    records = good_walk(walker_binary, root)
    assert {r[1] for r in records if r[0] == b"D"} == expected_dirs
    assert {(r[3], r[4]) for r in records if r[0] == b"L"} == expected_names
    assert {(r[5], r[6]) for r in records if r[0] == b"H"} == {x for x in expected_names if not x[1].startswith(b"raw-")}


def test_directory_larger_than_one_bulk_buffer(walker_binary, tmp_path):
    for i in range(20000):
        (tmp_path / f"empty-{i}").touch()
    for i in range(50):
        (tmp_path / f"data-{i}").write_bytes(b"x" * 4096)
    expected = os.lstat(tmp_path).st_blocks * 512 + sum(e.stat(follow_symlinks=False).st_blocks * 512 for e in os.scandir(tmp_path))
    records = good_walk(walker_binary, tmp_path)
    assert int(records[-1][2]) == 20050
    assert allocated_total(records) == expected


def test_mounted_volume_is_skipped(walker_binary, tmp_path):
    root = tmp_path / "tree"
    mount = root / "mnt"
    mount.mkdir(parents=True)
    image = tmp_path / "img.dmg"
    subprocess.run(["hdiutil", "create", "-size", "8m", "-fs", "APFS", "-volname", "SMWSynthetic", str(image)], check=True, capture_output=True)
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(image)], check=True, capture_output=True)
    try:
        (mount / "payload").write_bytes(b"x" * 1024 * 1024)
        records = good_walk(walker_binary, root)
        assert not any(r[0] == b"D" and r[1].startswith(os.fsencode(mount)) for r in records)
        assert allocated_total(records) == os.lstat(root).st_blocks * 512
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True, capture_output=True)


def test_excluded_path_and_registered_inodes(walker_binary, tmp_path):
    excluded = tmp_path / "excluded"
    excluded.mkdir()
    (excluded / "hidden").write_bytes(b"synthetic")
    tracked = tmp_path / "tracked"
    tracked.write_bytes(b"synthetic")
    records = good_walk(walker_binary, tmp_path, "--exclude", str(excluded), "--registered-inodes-stdin", stdin=f"{tracked.stat().st_ino}\n".encode())
    assert {r[1] for r in records if r[0] == b"D"} == {os.fsencode(tmp_path)}
    links = [r for r in records if r[0] == b"H"]
    assert len(links) == 1 and links[0][3] == b"1" and links[0][6] == b"tracked"
    assert int(records[-1][2]) == 1


def test_unreadable_directory_counts_error_and_keeps_own_bytes(walker_binary, tmp_path):
    child = tmp_path / "unreadable"
    child.mkdir()
    expected = child.stat().st_blocks * 512
    child.chmod(0)
    try:
        records = good_walk(walker_binary, tmp_path)
        assert (b"D", os.fsencode(child), str(expected).encode()) in records
        assert int(records[-1][3]) >= 1
    finally:
        child.chmod(0o700)


def test_large_file_threshold_uses_apparent_size(walker_binary, tmp_path):
    with (tmp_path / "sparse").open("wb") as handle:
        handle.truncate(1048577)
    records = good_walk(walker_binary, tmp_path, "--large-file-bytes", "1048576")
    large = [r for r in records if r[0] == b"L"]
    assert len(large) == 1 and int(large[0][1]) == 1048577
    assert int(large[0][2]) < 1048577


def test_progress_records_every_k_directories(walker_binary, tmp_path):
    for i in range(24):
        (tmp_path / str(i)).mkdir()
    records = good_walk(walker_binary, tmp_path, "--progress-every", "10")
    assert [int(r[1]) for r in records if r[0] == b"P"] == [10, 20]
    assert int(records[-1][1]) == 25


def test_missing_root_exits_3_with_errno(walker_binary, tmp_path):
    records, result = run_walk(walker_binary, tmp_path / "missing")
    assert not records and result.returncode == 3
    assert result.stdout == b"" and result.stderr.splitlines()[0] == b"errno=2"


def test_stat_mode_matches_bulk_mode(walker_binary, tmp_path):
    mixed_tree(tmp_path / "tree")
    bulk = good_walk(walker_binary, tmp_path / "tree")
    stat = good_walk(walker_binary, tmp_path / "tree", "--stat-mode")
    assert Counter(r for r in bulk if r[0] in (b"D", b"H", b"L")) == Counter(r for r in stat if r[0] in (b"D", b"H", b"L"))


def test_deep_tree(walker_binary, tmp_path):
    child = tmp_path
    for _ in range(300):
        child = child / "d"
        child.mkdir()
    records = good_walk(walker_binary, tmp_path)
    assert int(records[-1][1]) == 301
    assert sum(r[0] == b"D" for r in records) == 301


def test_root_symlink_is_followed_but_owns_link_bytes(walker_binary, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "payload").write_bytes(b"synthetic" * 1024)
    root = tmp_path / "root-link"
    root.symlink_to(target, target_is_directory=True)
    records = good_walk(walker_binary, root)
    expected = root.lstat().st_blocks * 512 + (target / "payload").stat().st_blocks * 512
    assert (b"D", os.fsencode(root), str(expected).encode()) in records
    assert int(records[-1][1]) == 1 and int(records[-1][2]) == 1


def test_workers_flush_whole_records_under_contention(walker_binary, tmp_path):
    expected = set()
    for i in range(24):
        child = tmp_path / f"directory-{i}"
        child.mkdir()
        for j in range(100):
            name = f"payload-{j}\n"
            (child / name).write_bytes(b"synthetic")
            expected.add((os.fsencode(child), os.fsencode(name)))
    for workers in (1, 16):
        records = good_walk(walker_binary, tmp_path, "--workers", str(workers), "--progress-every", "5")
        assert {(r[3], r[4]) for r in records if r[0] == b"L"} == expected
        assert sum(r[0] == b"L" for r in records) == 2400
        assert int(records[-1][1]) == 25 and int(records[-1][2]) == 2400
        assert [int(r[1]) for r in records if r[0] == b"P"] == [5, 10, 15, 20, 25]


def test_missing_attributes_and_unsupported_bulk_fall_back(walker_binary, tmp_path, monkeypatch, bulk_fault_library):
    mixed_tree(tmp_path / "tree")
    baseline = good_walk(walker_binary, tmp_path / "tree", "--stat-mode")
    expected = Counter(r for r in baseline if r[0] in (b"D", b"H", b"L"))
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", str(bulk_fault_library))
    for mode in ("missing", "unsupported", "invalid"):
        monkeypatch.setenv("SMW_TEST_BULK_MODE", mode)
        records = good_walk(walker_binary, tmp_path / "tree")
        assert Counter(r for r in records if r[0] in (b"D", b"H", b"L")) == expected
        assert records[-1][1:4] == baseline[-1][1:4]


def test_opened_directory_mount_is_rechecked(walker_binary, tmp_path, monkeypatch, bulk_fault_library):
    child = tmp_path / "changed-mount"
    child.mkdir()
    (child / "payload").write_bytes(b"synthetic")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", str(bulk_fault_library))
    monkeypatch.setenv("SMW_TEST_BULK_MODE", "mount-race")
    records = good_walk(walker_binary, tmp_path)
    assert [r[1] for r in records if r[0] == b"D"] == [os.fsencode(tmp_path)]
    assert records[-1][1:4] == (b"1", b"0", b"0")


def test_usage_errors_have_no_protocol_output(walker_binary, tmp_path):
    for extra in [("--workers", "0"), ("--workers", "17"), ("--progress-every", "0"), ("--large-file-bytes", "-1"), ("--unknown", "value")]:
        records, result = run_walk(walker_binary, tmp_path, *extra)
        assert result.returncode == 2 and result.stderr and not records


def test_registered_stdin_is_read_before_output(walker_binary, tmp_path):
    import select
    command = [walker_binary, "walk", "--root", tmp_path, "--workers", "1", "--large-file-bytes", "1", "--progress-every", "1", "--registered-inodes-stdin"]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        try:
            assert not select.select([child.stdout], [], [], 0.2)[0]
            stdout, stderr = child.communicate(b"1\n", timeout=10)
            assert child.returncode == 0 and stdout.endswith(b"\0") and not stderr
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()


def test_output_failure_is_fatal(walker_binary, tmp_path):
    output = tmp_path / "readonly"
    output.touch()
    with output.open("rb") as handle:
        result = subprocess.run([walker_binary, "walk", "--root", tmp_path, "--workers", "1", "--large-file-bytes", "1", "--progress-every", "1"], stdout=handle, stderr=subprocess.PIPE)
    assert result.returncode == 1
    assert b"Sanitizer" not in result.stderr and b"runtime error" not in result.stderr
