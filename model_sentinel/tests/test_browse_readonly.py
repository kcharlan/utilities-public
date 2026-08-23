from __future__ import annotations

import gc
import hashlib
import json
import queue
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import model_sentinel.browse.readonly as readonly
from model_sentinel.browse.readonly import (
    MissingDatabaseError,
    SchemaError,
    ensure_schema,
    open_readonly,
)
from tests.browse_fixtures import build_fixture_db, decoded_change_rows


def test_fixture_records_the_scripted_browser_history(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        scrape_counts = connection.execute(
            """SELECT status, saved_snapshot, COUNT(*) AS total
               FROM scrapes WHERE provider_id = 'example-provider'
               GROUP BY status, saved_snapshot
               ORDER BY status, saved_snapshot"""
        ).fetchall()
        other_times = connection.execute(
            """SELECT completed_at FROM scrapes
               WHERE provider_id = 'other-provider' ORDER BY scrape_id"""
        ).fetchall()
        before_price = connection.execute(
            """SELECT input_price, metadata_json FROM snapshot_models
               WHERE scrape_id = ? AND provider_model_id = ?""",
            (facts.price_step[1], facts.price_step[0]),
        ).fetchone()
        after_price = connection.execute(
            """SELECT input_price, metadata_json FROM snapshot_models
               WHERE scrape_id = ? AND provider_model_id = ?""",
            (facts.price_step[2], facts.price_step[0]),
        ).fetchone()

    assert facts.provider_ids == ("example-provider", "other-provider")
    assert len(facts.scrape_ids) == 6
    assert len(set(facts.scrape_dates)) == 6
    assert len(facts.bulk_list_models) == 3
    assert [tuple(row) for row in scrape_counts] == [("error", 0, 1), ("success", 1, 6)]
    assert other_times[0]["completed_at"] == "2026-08-18T12:00:00+00:00"
    assert other_times[1]["completed_at"] == "2026-08-18T12:20:00+00:00"
    assert before_price["input_price"] == facts.price_step[5] == 2.0
    assert after_price["input_price"] == facts.price_step[6] == 3.5
    assert json.loads(before_price["metadata_json"])["pricing"]["prompt"] == facts.price_step[3] == 0.000002
    assert json.loads(after_price["metadata_json"])["pricing"]["prompt"] == facts.price_step[4] == 0.0000035

    changes = decoded_change_rows(database_path)
    assert any(
        row["provider_model_id"] == facts.added_model
        and row["to_scrape_id"] == facts.added_at_scrape
        and row["change_kind"] == "added"
        for row in changes
    )
    assert any(
        row["provider_model_id"] == facts.removed_model
        and row["to_scrape_id"] == facts.removed_at_scrape
        and row["change_kind"] == "removed"
        for row in changes
    )
    bulk_rows = [
        row for row in changes
        if row["to_scrape_id"] == facts.scrape_ids[5]
        and row["field_name"] == "supported_parameters"
    ]
    assert tuple(row["provider_model_id"] for row in bulk_rows) == facts.bulk_list_models
    churn_rows = [
        row for row in changes
        if row["provider_model_id"] == facts.benchmark_churn_model
        and row["field_name"] == "benchmarks.design_arena.score"
    ]
    assert len(churn_rows) == 5


def test_missing_database_raises_without_creating_file(tmp_path: Path) -> None:
    database_path = tmp_path / "missing.db"
    with pytest.raises(MissingDatabaseError) as exc_info:
        open_readonly(database_path)
    assert exc_info.value.path == database_path
    assert not database_path.exists()


def test_connection_is_query_only_and_rejects_insert(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    database = open_readonly(database_path)
    connection = database.connection()
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute(
            "INSERT INTO providers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("never-written", "Never", "generic", "", "", "", 0, ""),
        )
    database.close_all()


def test_schema_validation_names_first_missing_table(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE field_changes")
    with sqlite3.connect(database_path) as connection:
        with pytest.raises(SchemaError) as exc_info:
            ensure_schema(connection)
    assert exc_info.value.missing == "field_changes"


def test_schema_failure_closes_the_connection_opened_for_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    captured: list[sqlite3.Connection] = []

    def reject_schema(connection: sqlite3.Connection) -> None:
        captured.append(connection)
        raise SchemaError("synthetic_missing_table")

    monkeypatch.setattr(readonly, "ensure_schema", reject_schema)
    with pytest.raises(SchemaError, match="synthetic_missing_table"):
        open_readonly(database_path)

    assert len(captured) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        captured[0].execute("SELECT 1")


def test_threads_receive_distinct_connections_and_close_all_closes_each_one(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    database = open_readonly(database_path)
    ready = threading.Barrier(3)
    release = threading.Event()
    connection_ids: queue.Queue[int] = queue.Queue()

    def query_after_close() -> bool:
        connection = database.connection()
        assert connection.execute("SELECT COUNT(*) FROM scrapes").fetchone()[0] == 9
        connection_ids.put(id(connection))
        ready.wait(timeout=5)
        assert release.wait(timeout=5)
        try:
            connection.execute("SELECT COUNT(*) FROM scrapes").fetchone()
        except sqlite3.ProgrammingError as exc:
            return "closed database" in str(exc)
        return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(query_after_close) for _ in range(2))
        ready.wait(timeout=5)
        ids = (connection_ids.get_nowait(), connection_ids.get_nowait())
        assert ids[0] != ids[1]
        database.close_all()
        release.set()
        assert tuple(future.result(timeout=5) for future in futures) == (True, True)


def test_short_lived_threads_close_connections_and_do_not_grow_registry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    database = open_readonly(database_path)
    worker_connections: list[sqlite3.Connection] = []

    def open_and_query() -> sqlite3.Connection:
        connection = database.connection()
        assert connection.execute("SELECT COUNT(*) FROM scrapes").fetchone()[0] == 9
        return connection

    for _ in range(40):
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker_connections.append(executor.submit(open_and_query).result(timeout=5))
    gc.collect()

    assert len(database._owners) <= 1
    for connection in worker_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    database.close_all()


def test_query_sweep_does_not_change_fixture_bytes(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    before = hashlib.sha256(database_path.read_bytes()).digest()
    database = open_readonly(database_path)
    connection = database.connection()
    for table in ("providers", "scrapes", "snapshot_models", "field_changes"):
        connection.execute(f"SELECT * FROM {table}").fetchall()
    database.close_all()
    assert hashlib.sha256(database_path.read_bytes()).digest() == before
