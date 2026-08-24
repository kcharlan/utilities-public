from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from model_sentinel.browse import api, queries
from model_sentinel.browse.aspects import build_aspect_catalog
from model_sentinel.browse.readonly import open_readonly
from model_sentinel.config import load_provider_configs, load_settings
from model_sentinel.provider_profiles import profiles_for
from model_sentinel.reporting import detail_policy_from_settings


EXPECTED_MODEL_IDS = tuple(
    f"synthetic-lab/comparator-{number:02d}" for number in range(1, 9)
)
EXPECTED_TIMESTAMPS = tuple(
    f"2040-02-{day:02d}T15:00:00+00:00" for day in range(1, 6)
)


def _validation_context(runtime_home: Path):
    providers = load_provider_configs(runtime_home / "providers.env")
    settings = load_settings(runtime_home / "settings.env", runtime_home=runtime_home)
    database = open_readonly(runtime_home / "model_sentinel.db")
    profiles = profiles_for(providers)
    context = api.ApiContext(
        database,
        providers,
        tuple(queries.db_providers(database.connection())),
        profiles,
        settings,
        build_aspect_catalog(
            database,
            profiles=profiles,
            policy=detail_policy_from_settings(settings),
        ),
    )
    return context, database


def test_model_view_validation_home_is_isolated_and_loadable(tmp_path: Path) -> None:
    from tests.model_view_validation_fixture import build_model_view_validation_home

    occupied_home = tmp_path / "occupied"
    occupied_home.mkdir()
    (occupied_home / "synthetic-sentinel.txt").write_text(
        "conspicuously synthetic occupied target\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="new or empty directory"):
        build_model_view_validation_home(occupied_home)
    with pytest.raises(ValueError, match="outside the git repository"):
        build_model_view_validation_home(
            Path(__file__).parent / "synthetic-validation-runtime-must-not-exist"
        )

    requested_home = tmp_path / "runtime"
    runtime_home = build_model_view_validation_home(requested_home)

    assert runtime_home == requested_home.resolve()
    assert {
        path.relative_to(runtime_home)
        for path in runtime_home.rglob("*")
        if path.is_file()
    } == {
        Path("providers.env"),
        Path("settings.env"),
        Path("model_sentinel.db"),
    }

    [provider] = load_provider_configs(runtime_home / "providers.env")
    assert provider.provider_id == "validation"
    assert provider.label == "Synthetic Validation Provider"
    assert provider.kind == "openrouter"
    assert provider.base_url.startswith("https://")
    assert provider.base_url.endswith(".example.invalid/api/v1")
    assert provider.credential_env_var == "SYNTHETIC_MODEL_SENTINEL_TOKEN"
    assert provider.enabled is True
    assert not any(
        line.startswith("SYNTHETIC_MODEL_SENTINEL_TOKEN=")
        for line in (runtime_home / "providers.env").read_text(
            encoding="utf-8"
        ).splitlines()
    )

    settings = load_settings(
        runtime_home / "settings.env",
        runtime_home=runtime_home,
    )
    assert settings.notify_default is False
    assert settings.notify_on == "never"

    with sqlite3.connect(runtime_home / "model_sentinel.db") as connection:
        scrapes = connection.execute(
            """SELECT completed_at, status, saved_snapshot
               FROM scrapes
               ORDER BY completed_at, scrape_id"""
        ).fetchall()
    assert scrapes == [(timestamp, "success", 1) for timestamp in EXPECTED_TIMESTAMPS]


def test_model_view_validation_home_has_eight_searchable_models(tmp_path: Path) -> None:
    from tests.model_view_validation_fixture import build_model_view_validation_home

    runtime_home = build_model_view_validation_home(tmp_path / "runtime")
    context, database = _validation_context(runtime_home)
    try:
        rows = api.models(
            context,
            {"providers": "validation", "q": "comparator", "limit": "8"},
        )
    finally:
        database.close_all()

    assert len(rows) == 8
    assert tuple(row["model_id"] for row in rows) == EXPECTED_MODEL_IDS
    assert all(row["provider_id"] == "validation" for row in rows)
    assert all("comparator" in row["model_id"] for row in rows)


def test_model_view_validation_home_has_close_and_missing_numeric_observations(
    tmp_path: Path,
) -> None:
    from tests.model_view_validation_fixture import build_model_view_validation_home

    runtime_home = build_model_view_validation_home(tmp_path / "runtime")
    context, database = _validation_context(runtime_home)
    pins = ",".join(f"validation/{model_id}" for model_id in EXPECTED_MODEL_IDS)
    try:
        input_aspect = next(
            aspect
            for aspect in context.aspects
            if aspect.id == "validation:input_price"
        )
        result = api.series(
            context,
            {"models": pins, "aspects": input_aspect.id},
        )
    finally:
        database.close_all()

    assert input_aspect.label == "Input"
    assert [point["completed_at"] for point in result["axis"]] == list(
        EXPECTED_TIMESTAMPS
    )
    assert len(result["series"]) == 8
    assert all(item["aspect"] == input_aspect.id for item in result["series"])
    assert all(len(item["values"]) == len(result["axis"]) == 5 for item in result["series"])

    by_model = {item["model"].split("/", 1)[1]: item["values"] for item in result["series"]}
    assert by_model["synthetic-lab/comparator-08"] == [
        1.000008,
        1.000008,
        None,
        1.000008,
        1.000008,
    ]
    assert all(
        values[2] is not None
        for model_id, values in by_model.items()
        if model_id != "synthetic-lab/comparator-08"
    )
    assert by_model["synthetic-lab/comparator-01"][0] != by_model[
        "synthetic-lab/comparator-01"
    ][2]
    assert by_model["synthetic-lab/comparator-01"][2] != by_model[
        "synthetic-lab/comparator-01"
    ][-1]
    exact_strings = {
        str(value)
        for item in result["series"]
        for value in item["values"]
        if value is not None
    }
    assert {"1.000001", "1.000002"} <= exact_strings
