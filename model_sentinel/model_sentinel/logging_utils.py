from __future__ import annotations

import gzip
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os

from .config import RuntimePaths, Settings


def configure_logging(paths: RuntimePaths, settings: Settings) -> logging.Logger:
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("model_sentinel")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        paths.log_file,
        maxBytes=settings.log_max_bytes,
        backupCount=max(0, settings.log_keep_files - 1),
        encoding="utf-8",
    )
    file_handler.namer = _gzip_namer
    file_handler.rotator = _gzip_rotator
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def _gzip_namer(default_name: str) -> str:
    return f"{default_name}.gz"


def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as src, gzip.open(dest, "wb") as dst:
        dst.writelines(src)
    os.remove(source)

