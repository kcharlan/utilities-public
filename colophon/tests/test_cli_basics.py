"""Task 1 contracts for the CLI and private atomic runtime writes."""

import contextlib
import errno
import json
import os
import stat

import pytest


def test_version(run_cli, home, codex_home):
    result = run_cli("--version", home=home, codex_home=codex_home)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "colophon 0.1.0\n"
    assert not home.exists()


def test_help_documents_environment_and_runtime_without_creating_home(run_cli, home, codex_home):
    result = run_cli("--help", home=home, codex_home=codex_home)
    assert result.returncode == 0, result.stderr
    for marker in ("COLOPHON_HOME", "COLOPHON_PRICING_URL", "price-history.json",
                   "workspaces.json", "priority-turns.json"):
        assert marker in result.stdout
    assert not home.exists()


def test_conflicting_price_flags(run_cli, home, codex_home):
    result = run_cli("--offline", "--refresh-prices", home=home, codex_home=codex_home)
    assert result.returncode == 2
    assert "--offline" in result.stderr
    assert "--refresh-prices" in result.stderr
    assert not home.exists()


def test_unknown_flag(run_cli, home, codex_home):
    result = run_cli("--synthetic-unknown", home=home, codex_home=codex_home)
    assert result.returncode == 2
    assert "--synthetic-unknown" in result.stderr


def test_missing_codex_home(run_cli, home, tmp_path):
    missing = tmp_path / "synthetic-missing-home"
    result = run_cli("--offline", "--no-open", home=home, codex_home=missing)
    assert result.returncode == 1
    assert str(missing) in result.stderr
    assert not home.exists()


def test_unreadable_codex_home(run_cli, home, codex_home):
    prior_mode = stat.S_IMODE(codex_home.stat().st_mode)
    try:
        codex_home.chmod(0)
        result = run_cli("--offline", "--no-open", home=home, codex_home=codex_home)
        assert result.returncode == 1
        assert str(codex_home) in result.stderr
        assert not home.exists()
    finally:
        codex_home.chmod(prior_mode)


def test_first_run_creates_private_files_and_second_run_preserves_them(run_cli, home, codex_home):
    result = run_cli("--offline", "--no-open", home=home, codex_home=codex_home)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    ledger = home / "price-history.json"
    example = home / "workspaces.example.json"
    assert json.loads(ledger.read_text()) == {"schema": 1, "entries": []}
    assert json.loads(example.read_text()) == {
        "schema": 1,
        "aliases": [{"name": "Example Tools",
                     "origins": ["https://example.invalid/synthetic/tools.git"],
                     "paths": ["/synthetic/deployed/tools"]}],
    }
    prior = {}
    for path in (ledger, example):
        info = path.stat()
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert path.read_bytes().endswith(b"\n")
        prior[path] = (info.st_ino, info.st_mtime_ns, path.read_bytes())
    result = run_cli("--offline", "--no-open", home=home, codex_home=codex_home)
    assert result.returncode == 0, result.stderr
    for path, expected in prior.items():
        info = path.stat()
        assert (info.st_ino, info.st_mtime_ns, path.read_bytes()) == expected


def test_runtime_home_expands_override(colophon, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("COLOPHON_HOME", raising=False)
    assert colophon.runtime_home() == tmp_path / ".colophon"
    monkeypatch.setenv("COLOPHON_HOME", "~/synthetic-runtime")
    assert colophon.runtime_home() == tmp_path / "synthetic-runtime"


def test_existing_runtime_home_permissions_are_reapplied(colophon, home):
    home.mkdir(mode=0o755)
    assert colophon.ensure_runtime_home(home) == home
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_atomic_write_private_under_permissive_umask(colophon, tmp_path):
    path = tmp_path / "nested" / "synthetic.bin"
    previous_umask = os.umask(0)
    try:
        colophon.atomic_write_bytes(path, b"Synthetic complete content")
    finally:
        os.umask(previous_umask)
    assert path.read_bytes() == b"Synthetic complete content"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_write_cleanup_on_replace_failure(colophon, tmp_path, monkeypatch):
    path = tmp_path / "synthetic.bin"
    path.write_bytes(b"Synthetic old content")
    old_inode = path.stat().st_ino

    def fail_replace(source, destination):
        raise OSError("Synthetic replace failure")

    monkeypatch.setattr(colophon.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Synthetic replace failure"):
        colophon.atomic_write_bytes(path, b"Synthetic new content")
    assert path.read_bytes() == b"Synthetic old content"
    assert path.stat().st_ino == old_inode
    assert sorted(tmp_path.iterdir()) == [path]


def test_atomic_replacement_is_complete_and_uses_new_inode(colophon, tmp_path):
    path = tmp_path / "synthetic.bin"
    path.write_bytes(b"Synthetic old content")
    old_inode = path.stat().st_ino
    content = b"Synthetic new content\n" * 1000
    colophon.atomic_write_bytes(path, content)
    assert path.read_bytes() == content
    assert path.stat().st_ino != old_inode
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sorted(tmp_path.iterdir()) == [path]


def test_atomic_json_indentation_and_newline(colophon, tmp_path):
    path = tmp_path / "synthetic.json"
    colophon.atomic_write_json(path, {"schema": 1, "entries": []})
    assert path.read_bytes() == b'{\n  "schema": 1,\n  "entries": []\n}\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_json_roundtrips_lone_surrogate_and_unicode(colophon, tmp_path):
    path = tmp_path / "synthetic-unicode.json"
    original = {"synthetic_text": "Synthetic damaged log \ud800",
                "synthetic_unicode": "Synthetic café 雪 🌱"}
    colophon.atomic_write_json(path, original)
    text = path.read_bytes().decode("utf-8")
    assert json.loads(text) == original
    assert text.startswith('{\n  "synthetic_text": ')
    assert text.endswith("\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("failure_stage", ["fchmod", "fdopen"])
def test_atomic_write_closes_untransferred_fd_on_failure(colophon, tmp_path, monkeypatch, failure_stage):
    path = tmp_path / "synthetic.bin"
    old_content = b"Synthetic old content"
    path.write_bytes(old_content)
    old_inode = path.stat().st_ino
    original_error = OSError(f"Synthetic {failure_stage} failure")
    captured_fds = []

    def fail(fd, *args):
        captured_fds.append(fd)
        raise original_error

    monkeypatch.setattr(colophon.os, failure_stage, fail)
    try:
        with pytest.raises(OSError) as raised:
            colophon.atomic_write_bytes(path, b"Synthetic new content")
        assert raised.value is original_error
        assert path.read_bytes() == old_content
        assert path.stat().st_ino == old_inode
        assert sorted(tmp_path.iterdir()) == [path]
        with pytest.raises(OSError) as closed:
            os.fstat(captured_fds[0])
        assert closed.value.errno == errno.EBADF
    finally:
        # Reclaim the descriptor during the expected red run if it leaked.
        for fd in captured_fds:
            with contextlib.suppress(OSError):
                os.close(fd)


def test_atomic_write_does_not_close_fd_after_transfer(colophon, tmp_path, monkeypatch):
    path = tmp_path / "synthetic.bin"
    path.write_bytes(b"Synthetic old content")
    original_error = OSError("Synthetic replace failure after transfer")
    original_fsync = colophon.os.fsync
    original_close = colophon.os.close
    captured_fds = []
    explicit_closes = []

    def fsync(fd):
        captured_fds.append(fd)
        return original_fsync(fd)

    def close(fd):
        explicit_closes.append(fd)
        return original_close(fd)

    def fail_replace(source, destination):
        raise original_error

    monkeypatch.setattr(colophon.os, "fsync", fsync)
    monkeypatch.setattr(colophon.os, "close", close)
    monkeypatch.setattr(colophon.os, "replace", fail_replace)
    with pytest.raises(OSError) as raised:
        colophon.atomic_write_bytes(path, b"Synthetic new content")
    assert raised.value is original_error
    assert not explicit_closes
    with pytest.raises(OSError) as closed:
        os.fstat(captured_fds[0])
    assert closed.value.errno == errno.EBADF
    assert path.read_bytes() == b"Synthetic old content"
    assert sorted(tmp_path.iterdir()) == [path]


def test_now_ms_uses_wall_clock_milliseconds(colophon, monkeypatch):
    monkeypatch.setattr(colophon.time, "time_ns", lambda: 1_234_567_890)
    assert colophon.now_ms() == 1234


def test_parse_rfc3339_ms_preserves_instants_and_rejects_invalid_values(colophon):
    assert colophon.parse_rfc3339_ms("2030-01-15T12:00:00.123Z") == 1_894_708_800_123
    assert colophon.parse_rfc3339_ms("2030-01-15T14:00:00.123+02:00") == 1_894_708_800_123
    assert colophon.parse_rfc3339_ms("1970-01-01T00:00:00Z") == 0
    for invalid in (None, 12, "invalid", "2030-01-15T12:00:00", "2030-02-30T12:00:00Z"):
        assert colophon.parse_rfc3339_ms(invalid) is None


@pytest.mark.parametrize("offset", ["+00:60", "+01:99", "-00:60", "-01:99"])
def test_parse_rfc3339_ms_rejects_invalid_offset_minutes(colophon, offset):
    assert colophon.parse_rfc3339_ms(f"2030-01-15T12:00:00{offset}") is None


@pytest.mark.parametrize("offset,utc", [
    ("+23:59", "2030-01-14T12:01:00Z"),
    ("-23:59", "2030-01-16T11:59:00Z"),
])
def test_parse_rfc3339_ms_accepts_offset_boundaries(colophon, offset, utc):
    assert colophon.parse_rfc3339_ms(f"2030-01-15T12:00:00{offset}") == colophon.parse_rfc3339_ms(utc)


@pytest.mark.parametrize("offset", ["+24:00", "-24:00"])
def test_parse_rfc3339_ms_rejects_invalid_offset_hours(colophon, offset):
    assert colophon.parse_rfc3339_ms(f"2030-01-15T12:00:00{offset}") is None


def test_format_rfc3339_emits_whole_seconds_in_utc(colophon):
    assert colophon.format_rfc3339(1_894_708_800_999) == "2030-01-15T12:00:00Z"
    assert colophon.format_rfc3339(0) == "1970-01-01T00:00:00Z"


def test_epoch_to_ms_distinguishes_seconds_and_milliseconds(colophon):
    assert colophon.epoch_to_ms(1234.567) == 1_234_567
    assert colophon.epoch_to_ms(1_234_567, milliseconds=True) == 1_234_567
    assert colophon.epoch_to_ms(0) == 0
    assert colophon.epoch_to_ms(-0.001) == -1
    for invalid in (None, True, "1234", float("inf"), float("nan")):
        assert colophon.epoch_to_ms(invalid) is None


def test_abbreviate_home_respects_path_component_boundaries(colophon, monkeypatch, tmp_path):
    user_home = tmp_path / "synthetic-user-home"
    monkeypatch.setenv("HOME", str(user_home))
    assert colophon.abbreviate_home(user_home) == "~"
    assert colophon.abbreviate_home(user_home / ".codex") == "~/.codex"
    other = tmp_path / "synthetic-user-home-other" / ".codex"
    assert colophon.abbreviate_home(other) == str(other)
