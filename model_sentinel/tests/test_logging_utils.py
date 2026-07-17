import logging
from pathlib import Path

from model_sentinel.config import RuntimePaths, Settings
from model_sentinel.logging_utils import configure_logging


def test_logging_rotation_creates_gzip_archives(tmp_path: Path) -> None:
    runtime_home = tmp_path / "runtime"
    paths = RuntimePaths(
        project_root=tmp_path,
        providers_env=tmp_path / "providers.env",
        settings_env=tmp_path / "settings.env",
        runtime_home=runtime_home,
        database_path=runtime_home / "model_sentinel.db",
        logs_dir=runtime_home / "logs",
        log_file=runtime_home / "logs" / "model_sentinel.log",
        debug_dir=runtime_home / "debug",
        report_dir=runtime_home / "reports",
    )
    settings = Settings(
        log_max_bytes=100,
        log_keep_files=3,
        report_dir=runtime_home / "reports",
        report_retention_days=30,
        report_detail="default",
        report_show_fields=("pricing.*",),
        report_squelch_fields=("benchmarks", "benchmarks.*"),
        report_unclassified_limit=20,
        notify_default=False,
        notify_on="never",
        notify_open_target="file",
        notify_sound=None,
        terminal_notifier_path=None,
        runtime_home=runtime_home,
    )
    paths.ensure_directories()
    logger = configure_logging(paths, settings)
    for _ in range(20):
        logger.info("x" * 40)
    for handler in logger.handlers:
        handler.flush()
    assert paths.log_file.exists()
    archives = sorted(paths.logs_dir.glob("model_sentinel.log.*.gz"))
    assert archives
