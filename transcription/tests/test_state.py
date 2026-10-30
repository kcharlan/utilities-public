import json
import getpass
import multiprocessing
import os
import subprocess
from pathlib import Path

import pytest

import transcription_state as state


def test_default_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TRANSCRIPTION_HOME")
    assert state.runtime_home() == tmp_path / ".transcription"


def test_home_override_and_empty_value(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TRANSCRIPTION_HOME", "~/other")
    assert state.runtime_home() == tmp_path / "other"
    monkeypatch.setenv("TRANSCRIPTION_HOME", "")
    assert state.runtime_home() == tmp_path / ".transcription"


def test_file_overrides_win_for_each_counter(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CUMULATIVE_JSON_PATH", "relative/counter.json")
    monkeypatch.setenv("LIFETIME_TXT_PATH", "~/outside/lifetime.txt")
    state.add_duration(3.5)
    assert state.cumulative_path() == Path("relative/counter.json")
    assert state.lifetime_path() == tmp_path / "outside/lifetime.txt"
    assert state.cumulative_path().stat().st_mode & 0o777 == 0o600
    assert state.lifetime_path().stat().st_mode & 0o777 == 0o600


def test_private_modes():
    state.runtime_home().mkdir(mode=0o755)
    state.runtime_home().chmod(0o755)
    state.add_duration(3.5)
    assert state.runtime_home().stat().st_mode & 0o777 == 0o700
    for path in (state.cumulative_path(), state.lifetime_path(), state.runtime_home() / "counters.lock"):
        assert path.stat().st_mode & 0o777 == 0o600


def test_write_formats_are_legacy_compatible():
    state.add_duration(3.5)
    assert json.loads(state.cumulative_path().read_text()) == {"cumulative_seconds": 3.5}
    assert state.lifetime_path().read_text() == "3.5\n"


@pytest.mark.parametrize("text", ["3.5\n", "3.5"], ids=["newline", "no-newline"])
def test_reads_each_legacy_lifetime_form(text):
    state.runtime_home().mkdir()
    state.lifetime_path().write_text(text)
    assert state.read_counters().counters.lifetime_seconds == 3.5


def test_cwd_legacy_counters_are_not_imported():
    Path("session_backup.json").write_text('{"cumulative_seconds": 99}')
    Path("transcription_odometer.txt").write_text("99")
    assert state.read_counters().counters == state.Counters(0.0, 0.0)


@pytest.mark.parametrize("raw", [b"{", b"[]", b"text", b'{"cumulative_seconds": NaN}', b'{"cumulative_seconds": -1}'], ids=["bad-json", "list-json", "text", "nan", "negative"])
def test_corrupt_counter_is_preserved(raw):
    state.runtime_home().mkdir()
    path = state.cumulative_path()
    path.write_bytes(raw)
    result = state.read_counters()
    saved, = path.parent.glob(path.name + ".unreadable-*")
    assert result.counters.cumulative_seconds == 0.0
    assert saved.read_bytes() == raw
    assert any(str(saved) in warning for warning in result.warnings)


def test_unreadable_home_is_a_warning():
    state.runtime_home().write_text("synthetic")
    assert state.read_counters().warnings
    with pytest.raises(OSError):
        state.add_duration(1)


def _add_worker(queue):
    try:
        for _ in range(10):
            state.add_duration(1)
        queue.put(None)
    except BaseException as error:
        queue.put(repr(error))


def test_concurrent_additions_are_not_lost():
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [context.Process(target=_add_worker, args=(queue,)) for _ in range(4)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(30)
            assert worker.exitcode == 0
        assert [queue.get(timeout=2) for _ in workers] == [None] * 4
        assert state.read_counters().counters == state.Counters(40, 40)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        queue.close()


def test_reset_keeps_lifetime():
    state.add_duration(3.5)
    assert state.reset_cumulative() == state.Counters(0, 3.5)


def test_reset_does_not_rewrite_lifetime(monkeypatch):
    state.add_duration(3.5)
    original = state._write
    def fail_lifetime(path, data):
        if path == state.lifetime_path():
            raise OSError("lifetime unavailable")
        original(path, data)
    monkeypatch.setattr(state, "_write", fail_lifetime)
    assert state.reset_cumulative() == state.Counters(0, 3.5)


def test_invalid_utf8_is_preserved():
    state.runtime_home().mkdir()
    state.cumulative_path().write_bytes(b"\xff")
    result = state.read_counters()
    saved, = state.runtime_home().glob("session_backup.json.unreadable-*")
    assert saved.read_bytes() == b"\xff"
    assert str(saved) in result.warnings[0]


@pytest.mark.parametrize("sources", [(True, True), (True, False), (False, True), (False, False)])
@pytest.mark.parametrize("overrides", [False, True])
def test_readme_migration_block(sources, overrides, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TRANSCRIPTION_HOME", "~/new-home")
    if overrides:
        monkeypatch.setenv("CUMULATIVE_JSON_PATH", "relative/counter.json")
        monkeypatch.setenv("LIFETIME_TXT_PATH", "~/outside/lifetime.txt")
        (tmp_path / "outside").mkdir(mode=0o755)
    legacy = tmp_path / "transcription"
    legacy.mkdir()
    names = ("session_backup.json", "transcription_odometer.txt")
    values = (b'{"cumulative_seconds": 3.5}', b"4.5\n")
    for name, value, present in zip(names, values, sources):
        if present:
            (legacy / name).write_bytes(value)
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    section = readme.split("## Manual counter migration", 1)[1]
    script = section.split("```bash\n", 1)[1].split("```", 1)[0]
    for _ in range(2):
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    for name, value, present, destination in zip(names, values, sources, (state.cumulative_path(), state.lifetime_path())):
        if present:
            assert (legacy / name).read_bytes() == value == destination.read_bytes()
            assert destination.stat().st_mode & 0o777 == 0o600
        else:
            assert not destination.exists()
    if overrides:
        assert (tmp_path / "outside").stat().st_mode & 0o777 == 0o755


def test_migration_never_overwrites_existing_or_dangling_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / "transcription"
    legacy.mkdir()
    (legacy / "session_backup.json").write_text("source")
    (legacy / "transcription_odometer.txt").write_text("source")
    state.runtime_home().mkdir()
    state.cumulative_path().write_text("destination")
    state.lifetime_path().symlink_to("missing")
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    script = readme.split("## Manual counter migration", 1)[1].split("```bash\n", 1)[1].split("```", 1)[0]
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert state.cumulative_path().read_text() == "destination"
    assert state.lifetime_path().is_symlink()


def test_migration_expands_named_user_tilde():
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    script = readme.split("## Manual counter migration", 1)[1].split("```bash\n", 1)[1].split("```", 1)[0]
    function = script.split("home=$(expand_path", 1)[0]
    value = "~" + getpass.getuser() + "/synthetic"
    result = subprocess.run(["bash", "-c", function + '\nexpand_path "$1"', "bash", value], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == str(Path(value).expanduser())
