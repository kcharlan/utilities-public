from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_runtime_layout(runtime_home: Path) -> None:
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "runs").mkdir(parents=True, exist_ok=True)
    (runtime_home / "worktrees").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(runtime_home / "index.sqlite3") as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                benchmark_id TEXT NOT NULL,
                benchmark_mode TEXT NOT NULL,
                model TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                elapsed_ms REAL,
                cost_usd REAL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                score_percent REAL NOT NULL,
                run_dir TEXT NOT NULL,
                report_path TEXT NOT NULL,
                manifest_path TEXT NOT NULL
            )
            """
        )
        _ensure_column(connection, "runs", "elapsed_ms", "REAL")
        _ensure_column(connection, "runs", "cost_usd", "REAL")
        _ensure_column(connection, "runs", "input_tokens", "INTEGER")
        _ensure_column(connection, "runs", "output_tokens", "INTEGER")
        _ensure_column(connection, "runs", "total_tokens", "INTEGER")
        connection.commit()


def record_run(runtime_home: Path, row: dict[str, Any]) -> None:
    with sqlite3.connect(runtime_home / "index.sqlite3") as connection:
        connection.execute(
            """
            INSERT INTO runs (
                run_id,
                benchmark_id,
                benchmark_mode,
                model,
                started_at,
                ended_at,
                elapsed_ms,
                cost_usd,
                input_tokens,
                output_tokens,
                total_tokens,
                score_percent,
                run_dir,
                report_path,
                manifest_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["run_id"],
                row["benchmark_id"],
                row["benchmark_mode"],
                row["model"],
                row["started_at"],
                row["ended_at"],
                row.get("elapsed_ms"),
                row.get("cost_usd"),
                row.get("input_tokens"),
                row.get("output_tokens"),
                row.get("total_tokens"),
                row["score_percent"],
                row["run_dir"],
                row["report_path"],
                row["manifest_path"],
            ),
        )
        connection.commit()


def list_runs(runtime_home: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(runtime_home / "index.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT run_id, benchmark_id, benchmark_mode, model, started_at, ended_at,
                   elapsed_ms, cost_usd, input_tokens, output_tokens, total_tokens,
                   score_percent, run_dir, report_path, manifest_path
            FROM runs
            ORDER BY started_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_run(runtime_home: Path, run_id: str) -> dict[str, Any]:
    rows = list_runs(runtime_home)
    if run_id == "latest":
        if not rows:
            raise FileNotFoundError("No runs found.")
        return rows[0]
    for row in rows:
        if row["run_id"] == run_id:
            return row
    raise FileNotFoundError(f"Run {run_id} not found.")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=False) + "\n" for row in rows),
        encoding="utf-8",
    )
