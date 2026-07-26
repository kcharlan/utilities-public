from pathlib import Path

from argparse import Namespace
import os

import model_sentinel.cli as cli
from model_sentinel.config import ProviderConfig
from model_sentinel.models import BaselineInfo
from model_sentinel.storage import Store
from model_sentinel.time_utils import to_local_human


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
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_PRICE_DIVISOR=1\n",
        encoding="utf-8",
    )
    (runtime_home / "settings.env").write_text(
        "MODEL_SENTINEL_LOG_MAX_BYTES=10485760\n"
        "MODEL_SENTINEL_LOG_KEEP_FILES=3\n"
        "MODEL_SENTINEL_REPORT_DIR=reports\n"
        "MODEL_SENTINEL_NOTIFY_DEFAULT=0\n"
        "MODEL_SENTINEL_NOTIFY_ON=never\n"
        "MODEL_SENTINEL_NOTIFY_OPEN_TARGET=file\n",
        encoding="utf-8",
    )
    return runtime_home


def test_default_scan_without_baseline_explains_next_step(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    exit_code = cli.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No saved baseline exists for provider 'openrouter'" in captured.out
    assert "model_sentinel scan --save" in captured.out


def test_save_mode_allows_initial_baseline_without_prior_snapshot(tmp_path: Path) -> None:
    store = Store(tmp_path / ".model_sentinel" / "sentinel.db")
    store.initialize()
    args = Namespace(save=True, baseline="previous", baseline_date=None)
    assert cli._resolve_baseline(store, "openrouter", args) is None


def test_initial_saved_scan_reports_all_models_as_added(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    provider = ProviderConfig(
        provider_id="openrouter",
        label="OpenRouter",
        kind="openrouter",
        base_url="https://openrouter.ai/api/v1",
        models_path="/models",
        credential_env_var="OPENROUTER_AI_CREDS",
        price_multiplier=1000000,
        price_divisor=1,
        enabled=True,
    )

    monkeypatch.setattr(cli, "validate_selected_providers", lambda providers, provider_id=None: (provider,))
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda project_root: type(
            "Loaded",
            (),
            {
                "project_root": tmp_path,
                "runtime_paths": type(
                    "Paths",
                    (),
                    {
                        "database_path": runtime_home / "model_sentinel.db",
                        "runtime_home": runtime_home,
                        "providers_env": runtime_home / "providers.env",
                        "settings_env": runtime_home / "settings.env",
                        "logs_dir": runtime_home / "logs",
                        "log_file": runtime_home / "logs" / "model_sentinel.log",
                        "debug_dir": runtime_home / "debug",
                        "report_dir": runtime_home / "reports",
                        "ensure_directories": lambda self=None: (
                            (runtime_home / "logs").mkdir(parents=True, exist_ok=True),
                            (runtime_home / "debug").mkdir(parents=True, exist_ok=True),
                            (runtime_home / "reports").mkdir(parents=True, exist_ok=True),
                        ),
                    },
                )(),
                "settings": type(
                    "Settings",
                    (),
                    {
                        "notify_default": False,
                        "notify_on": "never",
                        "notify_open_target": "file",
                        "notify_sound": None,
                        "terminal_notifier_path": None,
                        "report_dir": runtime_home / "reports",
                        "report_retention_days": 30,
                        "log_max_bytes": 10485760,
                        "log_keep_files": 3,
                        "runtime_home": runtime_home,
                    },
                )(),
                "providers": (provider,),
            },
        )(),
    )
    monkeypatch.setattr(
        cli,
        "fetch_raw_models",
        lambda provider, api_key, profile: [
            {"id": "alpha", "name": "Alpha"},
            {"id": "beta", "name": "Beta"},
        ],
    )

    exit_code = cli.main(["scan", "--save"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "added: 2" in captured.out
    assert "+ alpha (Alpha)" in captured.out
    assert "+ beta (Beta)" in captured.out


def test_scan_writes_full_html_companion_report(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    settings_path = runtime_home / "settings.env"
    settings_path.write_text(
        settings_path.read_text(encoding="utf-8")
        .replace("MODEL_SENTINEL_NOTIFY_DEFAULT=0", "MODEL_SENTINEL_NOTIFY_DEFAULT=1")
        .replace("MODEL_SENTINEL_NOTIFY_ON=never", "MODEL_SENTINEL_NOTIFY_ON=changes"),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    monkeypatch.setattr(cli, "send_notification", lambda **kwargs: None)

    payloads = iter(
        [
            [{"id": "alpha", "name": "Alpha", "benchmarks": {"design_arena": [{"elo": 1}]}}],
            [{"id": "alpha", "name": "Alpha", "benchmarks": {"design_arena": [{"elo": 2}]}}],
        ]
    )
    monkeypatch.setattr(
        cli,
        "fetch_raw_models",
        lambda provider, api_key, profile: next(payloads),
    )

    assert cli.main(["scan", "--save"]) == 0
    assert cli.main(["scan", "--save"]) == 0
    capsys.readouterr()

    report_dir = runtime_home / "reports"
    concise_reports = sorted(path for path in report_dir.glob("scan_*.html") if not path.name.endswith("_full.html"))
    full_reports = sorted(report_dir.glob("scan_*_full.html"))

    assert concise_reports
    assert full_reports
    assert any("1 field change across 1 model" in path.read_text(encoding="utf-8") for path in concise_reports)
    assert any("Design arena" in path.read_text(encoding="utf-8") for path in full_reports)


def test_changes_writes_its_html_companion_when_a_model_was_added(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`changes` always renders HTML alongside its text report, so the summary
    table crashed the whole command for any added model, removed model or
    squelched change -- after the text report had already been written."""
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    # One scan that produces all three previously-fatal record kinds at once,
    # on three distinct models: `changes` groups rows by date/provider/model.
    payloads = iter(
        [
            [
                {"id": "alpha", "name": "Alpha", "benchmarks": {"design_arena": [{"elo": 1}]}},
                {"id": "gamma", "name": "Gamma"},
            ],
            [
                {"id": "alpha", "name": "Alpha", "benchmarks": {"design_arena": [{"elo": 2}]}},
                {"id": "beta", "name": "Beta"},
            ],
        ]
    )
    monkeypatch.setattr(
        cli,
        "fetch_raw_models",
        lambda provider, api_key, profile: next(payloads),
    )

    assert cli.main(["scan", "--save"]) == 0
    # beta added, gamma removed, alpha's benchmarks change squelched
    assert cli.main(["scan", "--save"]) == 0
    capsys.readouterr()

    assert cli.main(["changes"]) == 0
    capsys.readouterr()

    html_reports = sorted((runtime_home / "reports").glob("changes_*.html"))
    assert html_reports, "changes wrote no HTML companion report"
    html = html_reports[-1].read_text(encoding="utf-8")
    summary = html.split('<section class="summary-section">', 1)
    assert len(summary) == 2, "changes HTML rendered without a Change Summary"
    assert "<td>Added</td>" in summary[1]
    assert "<td>Removed</td>" in summary[1]
    assert "<td>Squelched</td>" in summary[1]
    assert "<code>beta</code>" in summary[1]
    assert "<code>gamma</code>" in summary[1]
    # Squelched rows account for the hidden change instead of printing it.
    assert "Design arena" not in summary[1]


def test_history_model_list_lists_known_models(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2026-03-13T12:00:00-04:00",
        completed_at="2026-03-13T12:00:01-04:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=2,
        error_message=None,
    )
    from model_sentinel.models import NormalizedModel, canonical_json

    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id="openrouter",
        models=[
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="alpha",
                display_name="Alpha",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=2,
                output_price=8,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "alpha", "name": "Alpha"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="beta",
                display_name="Beta",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=4,
                output_price=12,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "beta", "name": "Beta"}),
            ),
        ],
    )

    exit_code = cli.main(["history", "--provider", "openrouter", "--model", "list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Known models for openrouter" in captured.out
    assert "- alpha" in captured.out
    assert "- beta" in captured.out
    assert "price: 2 / 8" in captured.out
    assert f"first: {to_local_human('2026-03-13T16:00:01+00:00')}" in captured.out


def test_history_model_list_groups_prefixed_models(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2026-03-13T12:53:40-04:00",
        completed_at="2026-03-13T12:53:41-04:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=3,
        error_message=None,
    )
    from model_sentinel.models import NormalizedModel, canonical_json

    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id="openrouter",
        models=[
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="zai-org/glm-4.5",
                display_name="zai-org/glm-4.5",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=0.1,
                output_price=0.2,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "zai-org/glm-4.5"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="zai-org/glm-4.6",
                display_name="zai-org/glm-4.6",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=0.11,
                output_price=0.22,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "zai-org/glm-4.6"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="route-llm",
                display_name="route-llm",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=0.4,
                output_price=0.4,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "route-llm"}),
            ),
        ],
    )

    exit_code = cli.main(["history", "--provider", "openrouter", "--model", "list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "zai-org/" in captured.out
    assert "  - glm-4.5" in captured.out
    assert "    price: 0.1 / 0.2" in captured.out
    assert "  - glm-4.6" in captured.out
    assert "- route-llm" in captured.out
    assert "    price: 0.4 / 0.4" in captured.out


def test_history_model_list_supports_partial_filter(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2026-03-13T12:53:40-04:00",
        completed_at="2026-03-13T12:53:41-04:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=3,
        error_message=None,
    )
    from model_sentinel.models import NormalizedModel, canonical_json

    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id="openrouter",
        models=[
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="openai/chatgpt-5.2",
                display_name="ChatGPT 5.2",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=2,
                output_price=8,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "openai/chatgpt-5.2", "name": "ChatGPT 5.2"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="openai/gpt-4.1",
                display_name="GPT-4.1",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "openai/gpt-4.1", "name": "GPT-4.1"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="anthropic/claude-sonnet-4.5",
                display_name="Claude Sonnet 4.5",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5"}),
            ),
        ],
    )

    exit_code = cli.main(["history", "--provider", "openrouter", "--model", "list", "chatgpt"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "chatgpt-5.2" in captured.out.casefold()
    assert "price:" in captured.out.casefold()
    assert "gpt-4.1" not in captured.out.casefold()
    assert "claude-sonnet-4.5" not in captured.out.casefold()


def test_history_pattern_without_model_list_exits_cleanly(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    try:
        cli.main(["history", "--provider", "openrouter", "--model", "chatgpt-5.2", "chatgpt"])
    except SystemExit as exc:
        assert exc.code == 2
    captured = capsys.readouterr()
    assert "only supported with `--model list`" in captured.err


def test_history_specific_model_includes_latest_prices(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2026-03-13T12:53:40-04:00",
        completed_at="2026-03-13T12:53:41-04:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    from model_sentinel.models import NormalizedModel, canonical_json

    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id="openrouter",
        models=[
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="openai/chatgpt-5.2",
                display_name="ChatGPT 5.2",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=2,
                output_price=8,
                cache_read_price=1,
                cache_write_price=3,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "openai/chatgpt-5.2", "name": "ChatGPT 5.2"}),
            ),
        ],
    )

    exit_code = cli.main(["history", "--provider", "openrouter", "--model", "openai/chatgpt-5.2"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Latest price in/out: 2 / 8" in captured.out
    assert "Latest cache pricing: 1 / 3" in captured.out


def test_history_with_unknown_provider_exits_cleanly(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    try:
        cli.main(["history", "--provider", "abacusai", "--model", "list"])
    except SystemExit as exc:
        assert exc.code == 2
    captured = capsys.readouterr()
    assert "Unknown provider 'abacusai'" in captured.err


# ---------------------------------------------------------------------------
# A colliding provider label has to be visible where the user goes looking for
# config problems -- and NOWHERE ELSE. It used to be a `ConfigError` raised
# from `load_config`, which made it visible everywhere by halting every
# command; design Amendment 9 downgraded it to a `provider_labels` check with
# status `warn` in `healthcheck` alone. Both halves are pinned below: the
# warning is emitted and named, and it does not move the exit code.
# ---------------------------------------------------------------------------


def test_healthcheck_warns_about_a_duplicate_provider_label(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    providers_path = runtime_home / "providers.env"
    providers_path.write_text(
        providers_path.read_text(encoding="utf-8")
        + "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_ENABLED=1\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_LABEL=OpenRouter\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_KIND=openrouter\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_BASE_URL=https://synth.invalid/api/v1\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_MODELS_PATH=/models\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_API_KEY_ENV=SYNTHTWIN_CREDS\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_PRICE_MULTIPLIER=1\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHTWIN_PRICE_DIVISOR=1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("SYNTHTWIN_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    exit_code = cli.main(["healthcheck"])
    captured = capsys.readouterr()

    # DELIBERATELY INVERTED: this asserted `exit_code == 1` and a failed
    # `config_load` check. A duplicate label no longer fails anything -- the
    # config loads, every command runs, and the exit code stays 0. An exit code
    # of 1 here would mean a scheduled `healthcheck` had started paging someone
    # about a cosmetic problem.
    assert exit_code == 0
    assert "config_load" not in captured.out
    assert "WARN    provider_labels" in captured.out
    # The message the user acts on, not just a generic warning.
    assert "Duplicate provider label" in captured.out
    assert "'OpenRouter'" in captured.out
    assert "openrouter, synthtwin" in captured.out
    # And it says the reports are still correct, so the user can schedule the
    # edit rather than treat it as an outage.
    assert "Label (provider_id)" in captured.out


def test_healthcheck_reports_distinct_provider_labels_as_ok(tmp_path: Path, monkeypatch, capsys) -> None:
    """Control: the check passes, visibly, on the shipped single-provider fixture."""
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    exit_code = cli.main(["healthcheck"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "OK      provider_labels" in captured.out
    assert "WARN" not in captured.out
    assert "Duplicate provider label" not in captured.out
    assert "config_load" not in captured.out


def test_healthcheck_warns_when_provider_kind_has_no_registered_profile(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    runtime_home = _write_config_files(tmp_path)
    providers_path = runtime_home / "providers.env"
    providers_path.write_text(
        providers_path.read_text(encoding="utf-8")
        + "MODEL_SENTINEL_PROVIDER_SYNTHETIC_ENABLED=0\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHETIC_LABEL=Synthetic Provider\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHETIC_KIND=synthetic\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHETIC_BASE_URL=https://synthetic.invalid/v1\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHETIC_MODELS_PATH=/models\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHETIC_API_KEY_ENV=SYNTHETIC_API_KEY\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHETIC_PRICE_MULTIPLIER=1\n"
        "MODEL_SENTINEL_PROVIDER_SYNTHETIC_PRICE_DIVISOR=1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    exit_code = cli.main(["healthcheck"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "WARN    provider_profile" in captured.out
    assert (
        "Provider 'synthetic' kind 'synthetic' has no registered profile; "
        "using the generic profile (labels and price-field detection will be "
        "best-effort)."
    ) in captured.out
    assert "Provider 'openrouter'" not in captured.out
