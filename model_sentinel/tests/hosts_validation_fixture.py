"""Build an isolated, wholly synthetic runtime for Hosts acceptance."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from model_sentinel.config import build_runtime_paths, load_settings
from tests.browse_fixtures import build_hosts_fixture_db
from tests.validation_runtime import _prepare_empty_runtime_home


def build_hosts_validation_home(runtime_home: Path) -> Path:
    runtime_home = _prepare_empty_runtime_home(runtime_home)
    providers_path = runtime_home / "providers.env"
    settings_path = runtime_home / "settings.env"
    settings_path.write_text(
        "MODEL_SENTINEL_LOG_MAX_BYTES=1048576\n"
        "MODEL_SENTINEL_LOG_KEEP_FILES=1\n"
        "MODEL_SENTINEL_NOTIFY_DEFAULT=0\n"
        "MODEL_SENTINEL_NOTIFY_ON=never\n"
        "MODEL_SENTINEL_NOTIFY_OPEN_TARGET=folder\n"
        "MODEL_SENTINEL_REPORT_DIR=synthetic-reports\n",
        encoding="utf-8",
    )
    settings = load_settings(settings_path, runtime_home=runtime_home)
    paths = build_runtime_paths(
        project_root=Path(__file__).resolve().parents[1],
        providers_env=providers_path,
        settings_env=settings_path,
        settings=settings,
    )
    facts = build_hosts_fixture_db(paths.database_path, provider_id="hosts_synthetic", single_provider_id="hosts_single_synthetic")
    providers_path.write_text(
        "".join(
            f"MODEL_SENTINEL_PROVIDER_{provider_id.upper()}_{suffix}={value}\n"
            for provider_id, label in (
                (facts.provider_id, "Synthetic Hosts"),
                (facts.single_provider_id, "Synthetic Single Host"),
            )
            for suffix, value in (
                ("ENABLED", "1"), ("LABEL", label), ("KIND", "openrouter"),
                ("BASE_URL", "https://synthetic-hosts.example.invalid/api/v1"),
                ("MODELS_PATH", "/models"),
                ("API_KEY_ENV", "SYNTHETIC_HOSTS_FAKE_TOKEN"),
                ("PRICE_MULTIPLIER", "1000000"), ("PRICE_DIVISOR", "1"),
            )
        ),
        encoding="utf-8",
    )
    return runtime_home


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build isolated synthetic Hosts browser data.")
    parser.add_argument("runtime_home", type=Path)
    args = parser.parse_args(argv)
    print(build_hosts_validation_home(args.runtime_home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
