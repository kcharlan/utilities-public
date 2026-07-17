import logging

import yaml

from taxkit.config import config_path, default_config, load_config, save_config


def test_config_defaults_created_in_tax2_home(monkeypatch, tmp_path):
    runtime_home = tmp_path / "runtime"
    monkeypatch.setenv("TAX2_HOME", str(runtime_home))

    cfg = load_config()

    assert cfg == default_config()
    assert config_path() == runtime_home / "config.yaml"
    assert yaml.safe_load(config_path().read_text(encoding="utf-8")) == default_config()


def test_config_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))

    saved = save_config(
        {
            "default_states": ["pa"],
            "legacy_combined_alias": "pa",
            "qif_overrides": {"PA": {"state_transfer": "[Custom PA]"}},
        }
    )

    assert saved["default_states"] == ["PA"]
    assert load_config() == saved


def test_corrupt_config_warns_and_uses_defaults_without_overwrite(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(": : bad yaml", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        cfg = load_config()

    assert cfg == default_config()
    assert "Unable to read" in caplog.text
    assert path.read_text(encoding="utf-8") == ": : bad yaml"
