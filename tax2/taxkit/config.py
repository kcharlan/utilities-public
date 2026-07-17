from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.yaml"
DEFAULT_CONFIG = {
    "default_states": ["GA"],
    "legacy_combined_alias": "GA",
    "qif_overrides": {},
}


def runtime_home() -> Path:
    override = os.environ.get("TAX2_HOME")
    return Path(override).expanduser() if override else Path.home() / ".tax2"


def config_path() -> Path:
    return runtime_home() / CONFIG_FILENAME


def default_config() -> dict[str, Any]:
    return {
        "default_states": list(DEFAULT_CONFIG["default_states"]),
        "legacy_combined_alias": DEFAULT_CONFIG["legacy_combined_alias"],
        "qif_overrides": dict(DEFAULT_CONFIG["qif_overrides"]),
    }


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = default_config()
    if not isinstance(raw, dict):
        return cfg

    default_states = raw.get("default_states")
    if isinstance(default_states, list) and default_states:
        cfg["default_states"] = [str(state).upper() for state in default_states]

    legacy_alias = raw.get("legacy_combined_alias")
    if isinstance(legacy_alias, str) and legacy_alias.strip():
        cfg["legacy_combined_alias"] = legacy_alias.strip().upper()

    qif_overrides = raw.get("qif_overrides")
    if isinstance(qif_overrides, dict):
        cfg["qif_overrides"] = qif_overrides

    return cfg


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        cfg = default_config()
        save_config(cfg)
        return cfg

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Unable to read %s: %s; using defaults", path, exc)
        return default_config()

    return normalize_config(raw)


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_config(cfg)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(normalized, sort_keys=False), encoding="utf-8")
    return normalized
