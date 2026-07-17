"""Shared configuration, tax-table, and QIF helpers for MD AutoTax."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class ConfigError(ValueError):
    """Raised when the private runtime configuration is missing or invalid."""


def runtime_home() -> Path:
    override = os.environ.get("MD_AUTOTAX_HOME")
    return Path(override).expanduser() if override else Path.home() / ".md-autotax"


def default_config_path() -> Path:
    return runtime_home() / "config.json"


def _secure_regular_file(path: Path, mode: int) -> None:
    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Private config not found: {path}. Copy config.example.json there, "
            "replace every SYNTHETIC value, and retry."
        ) from exc
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise ConfigError(f"Private config must be a regular file, not a symlink: {path}")
    os.chmod(path, mode)


def _require_qif_text(value: Any, field: str, *, account: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    if any(char in value for char in "\r\n^"):
        raise ConfigError(f"{field} contains a QIF control character")
    if account and any(char in value for char in "[]"):
        raise ConfigError(f"{field} must not contain square brackets")
    return value


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path).expanduser() if path else default_config_path()
    if not config_path.is_absolute():
        raise ConfigError(f"Private config path must be absolute: {config_path}")

    parent = config_path.parent
    try:
        parent_stat = parent.lstat()
    except FileNotFoundError as exc:
        raise ConfigError(f"Private config directory not found: {parent}") from exc
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise ConfigError(f"Private config directory must be a real directory: {parent}")
    os.chmod(parent, 0o700)
    _secure_regular_file(config_path, 0o600)

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read valid JSON from {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ConfigError("Private config root must be a JSON object")

    table_value = config.get("tax_table")
    if not isinstance(table_value, str) or not table_value.strip():
        raise ConfigError("tax_table must be a non-empty path string")
    table_path = Path(table_value).expanduser()
    if not table_path.is_absolute():
        raise ConfigError("tax_table must be an absolute path")

    qif = config.get("qif")
    if not isinstance(qif, dict):
        raise ConfigError("qif must be a JSON object")
    for jurisdiction in ("federal", "state"):
        entry = qif.get(jurisdiction)
        if not isinstance(entry, dict):
            raise ConfigError(f"qif.{jurisdiction} must be a JSON object")
        _require_qif_text(entry.get("payee"), f"qif.{jurisdiction}.payee")
        _require_qif_text(entry.get("memo"), f"qif.{jurisdiction}.memo")
        _require_qif_text(
            entry.get("expense_category"), f"qif.{jurisdiction}.expense_category"
        )
        _require_qif_text(
            entry.get("transfer_account"),
            f"qif.{jurisdiction}.transfer_account",
            account=True,
        )

    config["tax_table"] = str(table_path)
    return config


def parse_currency(value: Any) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = (
            value.replace("$", "")
            .replace(",", "")
            .replace("(", "-")
            .replace(")", "")
            .strip()
        )
        if not cleaned:
            return 0.0
        if cleaned.endswith("%"):
            return float(cleaned[:-1]) / 100
        return float(cleaned)
    return float(value)


def load_tax_table(csv_path: str | Path) -> tuple[pd.DataFrame | None, str | None]:
    try:
        frame = pd.read_csv(csv_path)
        column_mapping: dict[str, str] = {}
        for column in frame.columns:
            normalized = column.replace("\n", " ").strip().lower()
            if "monthly gross" in normalized and "income" in normalized:
                column_mapping[column] = "MonthlyIncome"
            elif "federal monthly" in normalized and "tax" in normalized:
                column_mapping[column] = "FederalTax"
            elif "state monthly" in normalized and "tax" in normalized:
                column_mapping[column] = "StateTax"
        if set(column_mapping.values()) != {"MonthlyIncome", "FederalTax", "StateTax"}:
            return None, (
                "Could not find columns for monthly gross income, federal monthly tax, "
                "and state monthly tax."
            )
        frame = frame.rename(columns=column_mapping)
        frame = frame[["MonthlyIncome", "FederalTax", "StateTax"]]
        for column in frame.columns:
            frame[column] = frame[column].apply(parse_currency)
        return frame[frame["MonthlyIncome"] > 0], None
    except Exception as exc:  # Streamlit presents the source error to the local user.
        return None, str(exc)


def generate_qif_content(
    date_obj: datetime, fed_tax: float, state_tax: float, config: dict[str, Any]
) -> str:
    qif_date = date_obj.strftime("%m/%d/%y")
    memo_date = date_obj.strftime("%m/%d/%Y")
    lines = ["!Type:Bank"]
    for jurisdiction, amount in (("federal", fed_tax), ("state", state_tax)):
        entry = config["qif"][jurisdiction]
        for signed_amount, category in (
            (-amount, entry["expense_category"]),
            (amount, f'[{entry["transfer_account"]}]'),
        ):
            lines.extend(
                [
                    f"D{qif_date}",
                    f"T{signed_amount:.2f}",
                    f'P{entry["payee"]}',
                    f'M{entry["memo"]} - {memo_date}',
                    f"L{category}",
                    "^",
                ]
            )
    return "\n".join(lines)


def write_qif(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise
