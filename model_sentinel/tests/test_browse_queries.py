from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date
from pathlib import Path

import pytest

from model_sentinel.browse import queries
from model_sentinel.browse.readonly import DatabaseBusyError
from model_sentinel.storage import Store
from model_sentinel.time_utils import local_date_for
from tests.browse_fixtures import build_fixture_db


def _connection(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def test_list_scrapes_orders_newest_first_and_reports_saved_status(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.list_scrapes(connection)

    assert [row["completed_at"] for row in rows] == sorted(
        (row["completed_at"] for row in rows), reverse=True
    )
    failed = next(row for row in rows if row["status"] == "error")
    assert failed["saved"] is False
    assert failed["model_count"] == 0
    saved = next(row for row in rows if row["scrape_id"] == facts.scrape_ids[-1])
    assert saved["status"] == "success"
    assert saved["saved"] is True


def test_list_scrapes_uses_local_date_instead_of_utc_date(tmp_path: Path) -> None:
    previous_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        database_path = tmp_path / "fixture.db"
        build_fixture_db(database_path)
        completed_at = "2026-08-19T00:30:00+00:00"
        assert local_date_for(completed_at) != date.fromisoformat(completed_at[:10])
        scrape_id = Store(database_path).create_scrape(
            provider_id="example-provider",
            started_at=completed_at,
            completed_at=completed_at,
            status="error",
            baseline_mode="previous",
            baseline_scrape_id=None,
            saved_snapshot=False,
            model_count=0,
            error_message="Synthetic date-boundary failure",
        )

        with _connection(database_path) as connection:
            row = next(
                row
                for row in queries.list_scrapes(connection)
                if row["scrape_id"] == scrape_id
            )

        assert row["date"] == local_date_for(completed_at)
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        time.tzset()


def test_date_span_covers_successful_saved_scrapes_only(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        span = queries.date_span(connection)

    assert span == (facts.scrape_dates[0], date(2026, 8, 18))


def test_date_span_is_none_without_successful_saved_scrapes() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE scrapes (completed_at TEXT, status TEXT, saved_snapshot INTEGER)"
    )
    try:
        assert queries.date_span(connection) is None
    finally:
        connection.close()


def test_change_counts_include_added_and_removed_local_dates(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.change_counts_by_date(
            connection,
            provider_ids=["example-provider"],
            since=facts.scrape_dates[3],
            until=facts.scrape_dates[4],
        )

    assert any(
        row["change_kind"] == "added"
        and local_date_for(row["detected_at"]) == facts.scrape_dates[3]
        for row in rows
    )
    assert any(
        row["change_kind"] == "removed"
        and local_date_for(row["detected_at"]) == facts.scrape_dates[4]
        for row in rows
    )
    assert all(row["count"] >= 1 for row in rows)


def test_change_counts_excludes_initial_baseline_seed_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.change_counts_by_date(
            connection,
            provider_ids=["example-provider"],
            since=facts.scrape_dates[0],
            until=facts.scrape_dates[0],
        )

    assert rows == []


def test_saved_scrape_ids_returns_only_successful_saved_scrapes_in_range(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.saved_scrape_ids(
            connection,
            provider_id="example-provider",
            since=facts.scrape_dates[1],
            until=facts.scrape_dates[3],
        )

    assert [row["scrape_id"] for row in rows] == list(facts.scrape_ids[1:4])
    assert all(row["provider_id"] == "example-provider" for row in rows)
    assert [row["date"] for row in rows] == list(facts.scrape_dates[1:4])


def test_series_rows_returns_only_scrapes_where_model_exists(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.series_rows(
            connection,
            provider_id="example-provider",
            scrape_ids=list(facts.scrape_ids),
            model_ids=[facts.added_model],
            columns=["input_price"],
            paths=["pricing.prompt"],
        )

    assert [row["scrape_id"] for row in rows] == list(facts.scrape_ids[3:])
    assert all(row["provider_model_id"] == facts.added_model for row in rows)
    assert all(row["input_price"] == 2.0 for row in rows)
    value_key = queries.path_value_key("pricing.prompt")
    type_key = queries.path_type_key("pricing.prompt")
    assert all(row[value_key] == 0.000002 for row in rows)
    assert all(row[type_key] == "real" for row in rows)


def test_series_rows_keeps_fixed_canonical_path_and_type_keys_distinct(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)
    scrape_id = facts.scrape_ids[-1]
    model_id = facts.model_ids[0]
    with _connection(database_path) as connection:
        metadata = json.loads(
            connection.execute(
                """SELECT metadata_json FROM snapshot_models
                   WHERE scrape_id = ? AND provider_model_id = ?""",
                (scrape_id, model_id),
            ).fetchone()["metadata_json"]
        )
        metadata.update(
            {
                "status": "synthetic-path-status",
                "display_name": "synthetic-path-display-name",
                "Foo": "synthetic-path-uppercase-foo",
                "foo": "synthetic-path-lowercase-foo",
                "foo__type": "synthetic-path-foo-type",
            }
        )
        connection.execute(
            """UPDATE snapshot_models
               SET status = ?, metadata_json = ?
               WHERE scrape_id = ? AND provider_model_id = ?""",
            ("synthetic-canonical-status", json.dumps(metadata), scrape_id, model_id),
        )
        rows = queries.series_rows(
            connection,
            provider_id="example-provider",
            scrape_ids=[scrape_id],
            model_ids=[model_id],
            columns=["status"],
            paths=["status", "display_name", "Foo", "foo", "foo__type"],
        )

    assert len(rows) == 1
    row = rows[0]
    value_keys = {
        path: queries.path_value_key(path)
        for path in ("status", "display_name", "Foo", "foo", "foo__type")
    }
    type_keys = {
        path: queries.path_type_key(path)
        for path in ("status", "display_name", "Foo", "foo", "foo__type")
    }
    assert set(row.keys()) == {
        "scrape_id",
        "provider_model_id",
        "status",
        *value_keys.values(),
        *type_keys.values(),
    }
    assert len(row.keys()) == len(set(row.keys()))
    assert len(row.keys()) == len({key.casefold() for key in row.keys()})
    assert row["scrape_id"] == scrape_id
    assert row["provider_model_id"] == model_id
    assert row["status"] == "synthetic-canonical-status"
    assert row[value_keys["status"]] == "synthetic-path-status"
    assert row[type_keys["status"]] == "text"
    assert row[value_keys["display_name"]] == "synthetic-path-display-name"
    assert row[type_keys["display_name"]] == "text"
    assert row[value_keys["Foo"]] == "synthetic-path-uppercase-foo"
    assert row[type_keys["Foo"]] == "text"
    assert row[value_keys["foo"]] == "synthetic-path-lowercase-foo"
    assert row[type_keys["foo"]] == "text"
    assert row[value_keys["foo__type"]] == "synthetic-path-foo-type"
    assert row[type_keys["foo__type"]] == "text"


@pytest.mark.parametrize(
    ("columns", "paths"),
    [(["metadata_json"], []), ([], ["pricing.$unsafe"])],
)
def test_series_rows_rejects_non_whitelisted_identifiers(
    tmp_path: Path, columns: list[str], paths: list[str]
) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection, pytest.raises(ValueError):
        queries.series_rows(
            connection,
            provider_id="example-provider",
            scrape_ids=[facts.scrape_ids[0]],
            model_ids=[facts.model_ids[0]],
            columns=columns,
            paths=paths,
        )


def test_events_for_models_parses_price_values_as_floats(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.events_for_models(
            connection,
            provider_id="example-provider",
            model_ids=[facts.price_step[0]],
            since=facts.scrape_dates[2],
            until=facts.scrape_dates[2],
        )

    price = next(row for row in rows if row["field_name"] == "pricing.prompt")
    assert price["old_value"] == facts.price_step[3]
    assert price["new_value"] == facts.price_step[4]
    assert isinstance(price["old_value"], float)
    assert isinstance(price["new_value"], float)


def test_events_for_models_excludes_initial_baseline_seed_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.events_for_models(
            connection,
            provider_id="example-provider",
            model_ids=[facts.model_ids[0]],
            since=facts.scrape_dates[0],
            until=facts.scrape_dates[0],
        )

    assert rows == []


def test_catalog_rows_reflects_exact_scrape_and_keeps_raw_metadata_json(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.catalog_rows(
            connection,
            scrape_id=facts.scrape_ids[-1],
            columns=["input_price", "context_window"],
            paths=["pricing.prompt"],
        )

    assert facts.removed_model not in rows
    assert facts.added_model in rows
    model = rows[facts.model_ids[0]]
    assert model["display_name"] == "Synthetic Test Model A"
    assert model["input_price"] == 3.5
    assert model[queries.path_value_key("pricing.prompt")] == 0.0000035
    assert json.loads(model["metadata_json"])["id"] == facts.model_ids[0]


def test_catalog_rows_keeps_fixed_canonical_and_path_keys_distinct(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)
    scrape_id = facts.scrape_ids[-1]
    model_id = facts.model_ids[0]
    with _connection(database_path) as connection:
        metadata = json.loads(
            connection.execute(
                """SELECT metadata_json FROM snapshot_models
                   WHERE scrape_id = ? AND provider_model_id = ?""",
                (scrape_id, model_id),
            ).fetchone()["metadata_json"]
        )
        metadata.update(
            {
                "status": "synthetic-path-status",
                "display_name": "synthetic-path-display-name",
                "Foo": "synthetic-path-uppercase-foo",
                "foo": "synthetic-path-lowercase-foo",
                "foo__type": "synthetic-path-foo-type",
            }
        )
        raw_metadata = json.dumps(metadata, sort_keys=True)
        connection.execute(
            """UPDATE snapshot_models
               SET display_name = ?, status = ?, metadata_json = ?
               WHERE scrape_id = ? AND provider_model_id = ?""",
            (
                "Synthetic Fixed Display Name",
                "synthetic-canonical-status",
                raw_metadata,
                scrape_id,
                model_id,
            ),
        )
        rows = queries.catalog_rows(
            connection,
            scrape_id=scrape_id,
            columns=["status"],
            paths=["status", "display_name", "Foo", "foo", "foo__type"],
        )

    model = rows[model_id]
    value_keys = {
        path: queries.path_value_key(path)
        for path in ("status", "display_name", "Foo", "foo", "foo__type")
    }
    assert set(model) == {
        "display_name",
        "metadata_json",
        "status",
        *value_keys.values(),
    }
    assert len(model) == len({key.casefold() for key in model})
    assert model["display_name"] == "Synthetic Fixed Display Name"
    assert model["metadata_json"] == raw_metadata
    assert model["status"] == "synthetic-canonical-status"
    assert model[value_keys["status"]] == "synthetic-path-status"
    assert model[value_keys["display_name"]] == "synthetic-path-display-name"
    assert model[value_keys["Foo"]] == "synthetic-path-uppercase-foo"
    assert model[value_keys["foo"]] == "synthetic-path-lowercase-foo"
    assert model[value_keys["foo__type"]] == "synthetic-path-foo-type"


def test_search_models_matches_id_or_latest_name_as_literal_substring(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.search_models(
            connection,
            provider_ids=["example-provider"],
            query="MODEL-A",
            limit=50,
        )
        wildcard = queries.search_models(
            connection,
            provider_ids=["example-provider"],
            query="%",
            limit=50,
        )

    assert [row["model_id"] for row in rows] == [facts.model_ids[0]]
    assert rows[0]["display_name"] == "Synthetic Test Model A"
    assert wildcard == []


def test_change_by_id_returns_parsed_values_and_both_scrapes(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)
    with _connection(database_path) as connection:
        change_id = connection.execute(
            """SELECT change_id FROM field_changes
               WHERE provider_model_id = ? AND field_name = 'pricing.prompt'""",
            (facts.price_step[0],),
        ).fetchone()["change_id"]
        row = queries.change_by_id(connection, change_id)
        missing = queries.change_by_id(connection, 999_999)

    assert row is not None
    assert row["old_value"] == facts.price_step[3]
    assert row["new_value"] == facts.price_step[4]
    assert row["from_scrape"]["scrape_id"] == facts.price_step[1]
    assert row["to_scrape"]["scrape_id"] == facts.price_step[2]
    assert row["from_scrape"]["date"] == facts.scrape_dates[1]
    assert row["to_scrape"]["date"] == facts.scrape_dates[2]
    assert missing is None


def test_db_providers_lists_all_database_providers(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)

    with _connection(database_path) as connection:
        rows = queries.db_providers(connection)

    assert rows == [
        {
            "provider_id": "example-provider",
            "label": "Example Provider",
            "kind": "openrouter",
            "enabled": True,
        },
        {
            "provider_id": "other-provider",
            "label": "Other Provider",
            "kind": "generic",
            "enabled": True,
        },
    ]


class _FailingConnection:
    def __init__(self, message: str) -> None:
        self.message = message

    def execute(self, *_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError(self.message)


@pytest.mark.parametrize(
    "call",
    [
        lambda connection: queries.list_scrapes(connection),
        lambda connection: queries.date_span(connection),
        lambda connection: queries.change_counts_by_date(
            connection, provider_ids=["example-provider"], since=None, until=None
        ),
        lambda connection: queries.saved_scrape_ids(
            connection, provider_id="example-provider", since=None, until=None
        ),
        lambda connection: queries.series_rows(
            connection,
            provider_id="example-provider",
            scrape_ids=[1],
            model_ids=["fake-org/test-model-a"],
            columns=[],
            paths=[],
        ),
        lambda connection: queries.events_for_models(
            connection,
            provider_id="example-provider",
            model_ids=["fake-org/test-model-a"],
            since=None,
            until=None,
        ),
        lambda connection: queries.catalog_rows(
            connection, scrape_id=1, columns=[], paths=[]
        ),
        lambda connection: queries.search_models(
            connection, provider_ids=["example-provider"], query="a", limit=10
        ),
        lambda connection: queries.change_by_id(connection, 1),
        lambda connection: queries.db_providers(connection),
    ],
)
def test_every_public_query_translates_busy_operational_errors(call) -> None:
    with pytest.raises(DatabaseBusyError):
        call(_FailingConnection("database is locked"))


def test_non_busy_operational_errors_are_not_translated() -> None:
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        queries.list_scrapes(_FailingConnection("no such table: scrapes"))


def test_busy_operational_error_is_translated() -> None:
    with pytest.raises(DatabaseBusyError):
        queries.list_scrapes(_FailingConnection("database table is busy"))
