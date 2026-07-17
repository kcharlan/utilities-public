from pathlib import Path

import pytest

from model_sentinel.config import ConfigError, load_config, missing_credentials, validate_selected_providers


def _write_config_files(root: Path) -> Path:
    runtime_home = root / ".model_sentinel"
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "providers.env").write_text(
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_ENABLED=1\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_LABEL=OpenRouter\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_KIND=openrouter\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_MODELS_PATH=/models\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_API_KEY_ENV=OPENROUTER_AI_CREDS\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_PRICE_MULTIPLIER=1000000\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_PRICE_DIVISOR=1\n"
        "MODEL_SENTINEL_PROVIDER_ABACUS_ENABLED=0\n"
        "MODEL_SENTINEL_PROVIDER_ABACUS_LABEL=Abacus.AI\n"
        "MODEL_SENTINEL_PROVIDER_ABACUS_KIND=abacus\n"
        "MODEL_SENTINEL_PROVIDER_ABACUS_BASE_URL=https://routellm."
        "abacus.ai/v1\n"
        "MODEL_SENTINEL_PROVIDER_ABACUS_MODELS_PATH=/models\n"  # pragma: allowlist secret
        "MODEL_SENTINEL_PROVIDER_ABACUS_API_KEY_ENV=ABACUS_AI_CREDS\n"
        "MODEL_SENTINEL_PROVIDER_ABACUS_PRICE_MULTIPLIER=1\n"
        "MODEL_SENTINEL_PROVIDER_ABACUS_PRICE_DIVISOR=1\n",
        encoding="utf-8",
    )
    (runtime_home / "settings.env").write_text(
        "MODEL_SENTINEL_LOG_MAX_BYTES=10485760\n"
        "MODEL_SENTINEL_LOG_KEEP_FILES=3\n"
        "MODEL_SENTINEL_REPORT_DIR=reports\n"
        "MODEL_SENTINEL_NOTIFY_DEFAULT=1\n"
        "MODEL_SENTINEL_NOTIFY_ON=both\n"
        "MODEL_SENTINEL_NOTIFY_OPEN_TARGET=file\n",
        encoding="utf-8",
    )
    return runtime_home


def test_load_config_parses_providers_and_settings(tmp_path: Path, monkeypatch) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    loaded = load_config(tmp_path)
    assert [provider.provider_id for provider in loaded.providers] == ["abacus", "openrouter"]
    assert loaded.settings.report_dir == (runtime_home / "reports").resolve()
    assert loaded.settings.notify_sound == "default"
    assert loaded.settings.terminal_notifier_path is None
    assert loaded.settings.report_detail == "default"
    assert "pricing.*" in loaded.settings.report_show_fields
    assert loaded.settings.report_squelch_fields == ("benchmarks", "benchmarks.*")
    assert loaded.settings.report_unclassified_limit == 20
    assert loaded.providers[0].price_multiplier == 1
    assert loaded.providers[0].price_divisor == 1
    assert loaded.providers[1].price_multiplier == 1000000
    assert loaded.providers[1].price_divisor == 1


def test_missing_credentials_reports_only_selected_enabled_provider(tmp_path: Path, monkeypatch) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    loaded = load_config(tmp_path)
    selected = validate_selected_providers(loaded.providers, provider_id=None)
    assert [provider.provider_id for provider in selected] == ["openrouter"]
    assert missing_credentials(selected, {}) == ["OPENROUTER_AI_CREDS"]


def test_report_field_patterns_trim_empty_entries(tmp_path: Path, monkeypatch) -> None:
    runtime_home = _write_config_files(tmp_path)
    settings_path = runtime_home / "settings.env"
    settings_path.write_text(
        settings_path.read_text(encoding="utf-8")
        + "MODEL_SENTINEL_REPORT_SHOW_FIELDS= pricing.* , , supported_parameters \n"
        + "MODEL_SENTINEL_REPORT_SQUELCH_FIELDS= benchmarks , benchmarks.* , \n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    loaded = load_config(tmp_path)

    assert loaded.settings.report_show_fields == ("pricing.*", "supported_parameters")
    assert loaded.settings.report_squelch_fields == ("benchmarks", "benchmarks.*")


def test_invalid_report_detail_is_rejected(tmp_path: Path, monkeypatch) -> None:
    runtime_home = _write_config_files(tmp_path)
    settings_path = runtime_home / "settings.env"
    settings_path.write_text(
        settings_path.read_text(encoding="utf-8") + "MODEL_SENTINEL_REPORT_DETAIL=verbose\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    with pytest.raises(ConfigError, match="MODEL_SENTINEL_REPORT_DETAIL"):
        load_config(tmp_path)


def test_invalid_unclassified_limit_is_rejected(tmp_path: Path, monkeypatch) -> None:
    runtime_home = _write_config_files(tmp_path)
    settings_path = runtime_home / "settings.env"
    settings_path.write_text(
        settings_path.read_text(encoding="utf-8") + "MODEL_SENTINEL_REPORT_UNCLASSIFIED_LIMIT=-1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    with pytest.raises(ConfigError, match="MODEL_SENTINEL_REPORT_UNCLASSIFIED_LIMIT"):
        load_config(tmp_path)
