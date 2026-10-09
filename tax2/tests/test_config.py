import logging

import yaml
import os
import pytest
from pathlib import Path

from taxkit.config import config_path, default_config, load_config
from tests.helpers import tree_snapshot, unreadable_config_chain, warning_count


@pytest.fixture(autouse=True)
def private_scratch(tmp_path):
    assert not tmp_path.resolve().is_relative_to(Path(__file__).resolve().parents[2])
    tmp_path.chmod(0o700)


def test_config_helpers_tolerate_permission_errors(monkeypatch, tmp_path, caplog):
    from taxkit.config import create_config_if_missing
    home = tmp_path / 'runtime'
    monkeypatch.setenv('TAX2_HOME', str(home))
    with unreadable_config_chain(tmp_path, home):
        create_config_if_missing(default_config())
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert load_config() == default_config()
        assert warning_count(caplog) == 1
    assert sorted(path.name for path in home.iterdir()) == ['config.yaml']


def test_load_config_tolerates_raising_exists(monkeypatch, tmp_path, caplog):
    """Pin Python 3.12/3.13 Path.exists semantics (raising) on any interpreter.

    The config file genuinely exists and is unreadable (mode 000), and
    Path.exists raises PermissionError for that path only, as 3.12/3.13 do for
    an inaccessible chain. A correct fix may or may not call exists(); either
    way it must warn once, return defaults and create or rewrite nothing.
    """
    if os.geteuid() == 0:
        pytest.skip('root bypasses file permissions')
    home = tmp_path / 'runtime'
    monkeypatch.setenv('TAX2_HOME', str(home))
    home.mkdir(mode=0o700)
    config = home / 'config.yaml'
    config.write_bytes(b'default_states: [XF]\n')
    before = tree_snapshot(home)
    original_exists = Path.exists

    def raising_exists(self, *args, **kwargs):
        if self == config:
            raise PermissionError('synthetic inaccessible config chain')
        return original_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'exists', raising_exists)
    config.chmod(0)
    try:
        with caplog.at_level(logging.WARNING):
            assert load_config() == default_config()
        assert warning_count(caplog) == 1
    finally:
        config.chmod(0o600)
    assert tree_snapshot(home) == before


def test_private_atomic_helpers(monkeypatch, tmp_path):
    from taxkit.config import ensure_runtime_home, atomic_write_bytes
    assert not tmp_path.resolve().is_relative_to(Path(__file__).resolve().parents[2])
    home = ensure_runtime_home(tmp_path / "runtime")
    home.chmod(0o755)
    assert ensure_runtime_home(home).stat().st_mode & 0o777 == 0o700
    page = home / "tax2.html"
    atomic_write_bytes(page, b"synthetic old")
    assert page.stat().st_mode & 0o777 == 0o600
    def fail(*args): raise OSError("synthetic replace failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="synthetic replace failure"):
        atomic_write_bytes(page, b"synthetic new")
    assert page.read_bytes() == b"synthetic old"
    assert list(home.iterdir()) == [page]


def test_create_config_race_no_clobber(monkeypatch, tmp_path):
    from taxkit.config import create_config_if_missing
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    original_link = os.link
    winner = b"default_states: [XF]\nlegacy_combined_alias: XF\n"
    def race(source, dest):
        Path(dest).write_bytes(winner)
        return original_link(source, dest)
    monkeypatch.setattr(os, "link", race)
    assert load_config()["default_states"] == ["XF"]
    path = config_path()
    before = path.stat().st_mtime_ns
    create_config_if_missing(default_config())
    assert path.read_bytes() == winner
    assert path.stat().st_mtime_ns == before
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("raw", [None, [], "synthetic", 1, True])
def test_malformed_override_container(raw, caplog):
    from taxkit.config import normalize_qif_overrides
    assert normalize_qif_overrides(raw) == {}
    assert "qif_overrides" in caplog.text


def test_override_projection_collision_and_safe_warnings(caplog):
    from taxkit.config import normalize_qif_overrides
    raw = {" xtest ": {"state_expense": "synthetic", "state_transfer": "", "secret-key": {"secret": "value"}},
           "XTEST": {"state_expense": 4, "state_transfer": "synthetic later"},
           "anything": {"state_expense": ""}, " ": {}, 4: {}, "invalid-state": [],
           "XF": {"state_expense": None, "state_transfer": False},
           "XG": {"state_expense": [], "state_transfer": {}}, "XH": {}}
    assert normalize_qif_overrides(raw) == {"XTEST": {"state_expense": "synthetic", "state_transfer": "synthetic later"}, "ANYTHING": {"state_expense": ""}, "XF": {}, "XG": {}, "XH": {}}
    assert "secret-key" not in caplog.text
    assert "invalid-state" not in caplog.text
    assert "synthetic later" not in caplog.text


def test_missing_config_private(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    load_config()
    assert config_path().stat().st_mode & 0o777 == 0o600
    assert config_path().parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('text', ['- GA\n', 'just text\n', '42\n', ''])
def test_non_mapping_config_warns(monkeypatch, tmp_path, caplog, text):
    monkeypatch.setenv('TAX2_HOME', str(tmp_path / 'runtime'))
    path = config_path()
    path.parent.mkdir()
    path.write_text(text)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with caplog.at_level(logging.WARNING):
        assert load_config() == default_config()
    assert [(record.levelname, record.message) for record in caplog.records] == [
        ('WARNING', 'config.yaml is not a mapping; using defaults')]
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_entry_matches_unicode_missing_and_existing_identity(tmp_path, monkeypatch):
    from taxkit.config import entry_matches
    assert entry_matches(tmp_path / 'Straße.yaml', tmp_path / 'STRASSE.yaml')
    assert entry_matches(tmp_path / 'é.yaml', tmp_path / 'e\u0301.yaml')
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.write_bytes(b'synthetic')
    os.link(first, second)
    assert entry_matches(first, second)
    # Synthetic identities model distinct existing entries on a case-sensitive volume.
    original = os.lstat
    def identities(path, *args, **kwargs):
        if Path(path).name in {'config.yaml', 'CONFIG.yaml'}:
            return type('Identity', (), {'st_dev': 1, 'st_ino': 1 if Path(path).name == 'config.yaml' else 2})()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(os, 'lstat', identities)
    assert not entry_matches(tmp_path / 'config.yaml', tmp_path / 'CONFIG.yaml')


def test_config_resolution_preserves_link_dotdot_and_missing_tail(tmp_path):
    from taxkit.config import config_resolution_entries
    physical = tmp_path / 'physical/nested'
    physical.mkdir(parents=True)
    alias = tmp_path / 'alias'
    alias.symlink_to(physical, target_is_directory=True)
    config = tmp_path / 'config.yaml'
    config.symlink_to('alias/../missing/deep.yaml')
    entries = config_resolution_entries(config)
    assert config in entries and alias in entries
    assert entries[-1] == tmp_path / 'physical/missing/deep.yaml'


def test_config_resolution_bounded_and_read_errors(tmp_path, monkeypatch):
    from taxkit.config import config_resolution_entries, entry_matches
    for index in range(42):
        (tmp_path / f'link{index}').symlink_to(f'link{index + 1}')
    entries = config_resolution_entries(tmp_path / 'link0')
    assert tmp_path / 'link40' in entries
    assert tmp_path / 'link41' not in entries
    def unreadable(*args, **kwargs):
        raise PermissionError('synthetic inaccessible entry')
    monkeypatch.setattr(os, 'readlink', unreadable)
    assert config_resolution_entries(tmp_path / 'link0')[-1] == tmp_path / 'link0'
    monkeypatch.setattr(os, 'lstat', unreadable)
    assert config_resolution_entries(tmp_path / 'absent/deep/config.yaml')[-1] == tmp_path / 'absent/deep/config.yaml'
    monkeypatch.setattr(os.path, 'realpath', unreadable)
    assert not entry_matches(tmp_path / 'missing/a', tmp_path / 'MISSING/A')


def test_missing_config_does_not_warn(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv('TAX2_HOME', str(tmp_path / 'runtime'))
    assert load_config() == default_config()
    assert caplog.records == []


def test_atomic_fsync_failure_preserves_page(monkeypatch, tmp_path):
    from taxkit.config import atomic_write_bytes
    path = tmp_path / "synthetic.html"
    atomic_write_bytes(path, b"synthetic old")
    def fail(fd): raise OSError("synthetic fsync failure")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="synthetic fsync failure"):
        atomic_write_bytes(path, b"synthetic new")
    assert path.read_bytes() == b"synthetic old"
    assert list(tmp_path.iterdir()) == [path]


def test_config_defaults_created_in_tax2_home(monkeypatch, tmp_path):
    runtime_home = tmp_path / "runtime"
    monkeypatch.setenv("TAX2_HOME", str(runtime_home))

    cfg = load_config()

    assert cfg == default_config()
    assert config_path() == runtime_home / "config.yaml"
    assert yaml.safe_load(config_path().read_text(encoding="utf-8")) == default_config()


def test_hand_edited_config_is_loaded_without_rewrite(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))

    path = config_path()
    path.parent.mkdir(mode=0o700)
    text = b'default_states: [pa]\nlegacy_combined_alias: ignored\nqif_overrides:\n  pa:\n    state_transfer: "[Synthetic PA]"\n'
    path.write_bytes(text)
    path.chmod(0o600)
    before = path.stat().st_mtime_ns
    assert load_config() == {'default_states': ['PA'], 'qif_overrides': {'PA': {'state_transfer': '[Synthetic PA]'}}}
    assert path.read_bytes() == text
    assert path.stat().st_mtime_ns == before


def test_corrupt_config_warns_and_uses_defaults_without_overwrite(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(": : bad yaml", encoding="utf-8")
    path.chmod(0o600)
    original_mtime = path.stat().st_mtime_ns

    with caplog.at_level(logging.WARNING):
        cfg = load_config()

    assert cfg == default_config()
    assert "Unable to read" in caplog.text
    assert path.read_text(encoding="utf-8") == ": : bad yaml"
    assert path.stat().st_mtime_ns == original_mtime
