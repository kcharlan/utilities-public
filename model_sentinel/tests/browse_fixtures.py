from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from model_sentinel.browse import api, queries
from model_sentinel.browse.aspects import build_aspect_catalog
from model_sentinel.config import ProviderConfig
from model_sentinel.diffing import compare_models
from model_sentinel.endpoints import (
    build_endpoint_capture,
    build_endpoint_error_summary,
    build_endpoint_mappings,
    endpoint_origin,
    planned_endpoint_paths,
)
from model_sentinel.models import EndpointFetchResult, EndpointPathResult, NormalizedModel
from model_sentinel.normalize import normalize_models
from model_sentinel.provider_profiles import profiles_for, resolve_profile
from model_sentinel.reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    DEFAULT_REPORT_SQUELCH_FIELDS,
    detail_policy_from_settings,
)
from model_sentinel.storage import Store
from model_sentinel.time_utils import local_date_for
from tests.conditional_pricing_fixtures import (
    SYNTHETIC_SCHEDULED_RATE_MODEL_ID,
    synthetic_scheduled_rate_models,
)


@dataclass(frozen=True)
class FixtureFacts:
    provider_ids: tuple[str, ...]
    scrape_ids: tuple[int, ...]
    scrape_dates: tuple[date, ...]
    model_ids: tuple[str, ...]
    added_model: str
    added_at_scrape: int
    removed_model: str
    removed_at_scrape: int
    price_step: tuple[str, int, int, float, float, float, float]
    context_step: tuple[str, int, int, int, int]
    bool_flip: tuple[str, int, int, bool, bool]
    bulk_list_models: tuple[str, ...]
    benchmark_churn_model: str
    equal_length_list_step: tuple[str, date]
    conditional_pricing_model: str
    conditional_provider_id: str
    # Set only by `build_fixture_db(..., with_endpoints=True)`.
    endpoint: EndpointFixtureFacts | None = None


EXAMPLE_PROVIDER = ProviderConfig(
    provider_id="example-provider",
    label="Example Provider",
    kind="openrouter",
    base_url="https://example.invalid/api/v1",
    models_path="/models",
    credential_env_var="EXAMPLE_PROVIDER_FAKE_TOKEN",
    price_multiplier=1_000_000,
    price_divisor=1,
    enabled=True,
)
OTHER_PROVIDER = ProviderConfig(
    provider_id="other-provider",
    label="Other Provider",
    kind="generic",
    base_url="https://other.invalid/api",
    models_path="/models",
    credential_env_var="OTHER_PROVIDER_FAKE_TOKEN",
    price_multiplier=1,
    price_divisor=1,
    enabled=True,
)
CONDITIONAL_PROVIDER = ProviderConfig(
    provider_id="conditional-example",
    label="Conditional Example",
    kind="openrouter",
    base_url="https://conditional.invalid/api/v1",
    models_path="/models",
    credential_env_var="CONDITIONAL_EXAMPLE_FAKE_TOKEN",
    price_multiplier=1_000_000,
    price_divisor=1,
    enabled=False,
)


ENDPOINT_PROVIDER = ProviderConfig(
    provider_id="endpoint-example",
    label="Endpoint Example",
    kind="openrouter",
    base_url="https://endpoint-router.invalid/api/v1",
    models_path="/models",
    credential_env_var="ENDPOINT_EXAMPLE_FAKE_TOKEN",
    price_multiplier=1,
    price_divisor=1,
    enabled=True,
)


@dataclass(frozen=True)
class EndpointFixtureFacts:
    """Identities and expected evidence of the synthetic endpoint history.

    Scrapes of `provider_id`, oldest first: `first_scrape` (capture
    `first_capture`, the provider's first), `second_scrape` and
    `third_scrape` (captures compared with the first one; the third scrape's
    capture was saved and completed *before* the second's, so capture order is
    the reverse of catalog order), `error_scrape` (the minimal error capture
    written by `Store.save_endpoint_error_capture`, comparison `available`),
    `uncaptured_scrape` (no capture) and `rebased_scrape` (a capture whose
    selected baseline is the uncaptured scrape: `missing_baseline_capture`).

    The listed, twin, alias, empty, failed, no-link, invalid-link,
    missing-alias, cycle and bulk models are observed in the first three
    scrapes only, so their dossier is the third scrape. `error_only_model` is
    last observed in `error_scrape`, `uncaptured_model` in
    `uncaptured_scrape` and `rebased_model` in `rebased_scrape`.
    """

    provider_id: str
    first_scrape: int
    second_scrape: int
    third_scrape: int
    error_scrape: int
    uncaptured_scrape: int
    rebased_scrape: int
    first_capture: int
    second_capture: int
    third_capture: int
    error_capture: int
    rebased_capture: int
    listed_model: str
    twin_model: str
    alias_model: str
    empty_model: str
    failed_model: str
    no_link_model: str
    invalid_link_model: str
    missing_alias_model: str
    cycle_models: tuple[str, str]
    bulk_model: str
    error_only_model: str
    uncaptured_model: str
    rebased_model: str
    listed_path: str
    empty_path: str
    failed_path: str
    bulk_path: str
    rebased_path: str
    # Response order of the listed path's endpoints in each capture.
    listed_keys_by_capture: tuple[tuple[int, tuple[str, ...]], ...]
    failed_error: tuple[str, str]
    error_summary: str
    first_capture_completed_at: str
    alias_divergent_leaf: str
    alias_matching_keys: tuple[str, ...]
    bulk_change_count: int
    # Listed in the second and third scrapes only: an `ok` list whose path has
    # no baseline list, recorded as a `new_path_unpaired` comparison gap.
    new_path_model: str
    new_path_path: str


def browse_settings() -> SimpleNamespace:
    return SimpleNamespace(
        report_detail="default",
        report_show_fields=DEFAULT_REPORT_SHOW_FIELDS,
        report_squelch_fields=DEFAULT_REPORT_SQUELCH_FIELDS,
        report_unclassified_limit=20,
    )


def browse_context(db) -> api.ApiContext:
    providers = (EXAMPLE_PROVIDER, OTHER_PROVIDER)
    db_providers = tuple(queries.db_providers(db.connection()))
    profiles = profiles_for(providers)
    for row in db_providers:
        profiles.setdefault(str(row["provider_id"]), resolve_profile(str(row["kind"])))
    settings = browse_settings()
    aspects = build_aspect_catalog(
        db,
        profiles=profiles,
        policy=detail_policy_from_settings(settings),
    )
    return api.ApiContext(db, providers, db_providers, profiles, settings, aspects)


def _raw_model(model_id: str, scrape_number: int) -> dict[str, object]:
    suffix = model_id.rsplit("-", 1)[-1]
    supported = ["tools"]
    if scrape_number >= 2 and suffix == "e":
        supported = ["response_format"]
    if scrape_number >= 6 and suffix in {"a", "b", "c"}:
        supported.append("reasoning_effort")
    prompt = 0.0000035 if suffix == "a" and scrape_number >= 3 else 0.000002
    context_length = 256_000 if suffix == "b" and scrape_number >= 4 else 128_000
    return {
        "id": model_id,
        "name": f"Synthetic Test Model {suffix.upper()}",
        "pricing": {"prompt": prompt, "completion": 0.000008},
        "context_length": context_length,
        "top_provider": {"max_completion_tokens": 16_384},
        "supported_parameters": supported,
        "reasoning": suffix == "c" and scrape_number >= 5,
        "benchmarks": {
            "design_arena": {
                "score": 1000 + scrape_number if suffix == "a" else 900,
            }
        },
    }


def _example_raw_models(scrape_number: int) -> list[dict[str, object]]:
    suffixes = ["a", "b", "c", "e"]
    if scrape_number >= 4:
        suffixes.append("d")
    if scrape_number >= 5:
        suffixes.remove("e")
    return [_raw_model(f"fake-org/test-model-{suffix}", scrape_number) for suffix in suffixes]


def _save_scrape(
    store: Store,
    provider: ProviderConfig,
    *,
    completed_at: str,
    raw_models: list[dict[str, object]],
    previous_id: int | None,
    previous_models: list[NormalizedModel],
) -> tuple[int, list[NormalizedModel]]:
    profile = resolve_profile(
        provider.kind,
        price_multiplier=provider.price_multiplier,
        price_divisor=provider.price_divisor,
    )
    models = normalize_models(provider, raw_models, profile)
    scrape_id = store.create_scrape(
        provider_id=provider.provider_id,
        started_at=completed_at,
        completed_at=completed_at,
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=previous_id,
        saved_snapshot=True,
        model_count=len(models),
        error_message=None,
    )
    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id=provider.provider_id,
        models=models,
    )
    added, removed, changed = compare_models(
        baseline_models={model.provider_model_id: model for model in previous_models},
        current_models={model.provider_model_id: model for model in models},
    )
    store.record_field_changes(
        provider_id=provider.provider_id,
        from_scrape_id=previous_id,
        to_scrape_id=scrape_id,
        deltas=added + removed + changed,
        detected_at=completed_at,
    )
    return scrape_id, models


_EP_MODEL = "fake-org/endpoint-model-a"
_EP_TWIN = "fake-org/endpoint-twin"
_EP_ALIAS = "fake-org/endpoint-alias"
_EP_EMPTY = "fake-org/endpoint-empty"
_EP_FAILED = "fake-org/endpoint-failed"
_EP_NO_LINK = "fake-org/endpoint-no-link"
_EP_INVALID_LINK = "fake-org/endpoint-invalid-link"
_EP_MISSING_ALIAS = "fake-org/endpoint-missing-alias"
_EP_CYCLE = ("fake-org/endpoint-cycle-1", "fake-org/endpoint-cycle-2")
_EP_BULK = "fake-org/endpoint-bulk"
_EP_ERROR_ONLY = "fake-org/endpoint-error-only"
_EP_UNCAPTURED = "fake-org/endpoint-uncaptured"
_EP_REBASED = "fake-org/endpoint-rebased"
# Listed from the second scrape on, so its path has no baseline list (a gap).
_EP_NEW_PATH = "fake-org/endpoint-new-path"
_EP_BULK_COUNT = 105
_EP_FAILED_ERROR = ("http_status", "HTTP 503 from the synthetic endpoint host")
_EP_ERROR_SUMMARY = "RuntimeError: synthetic endpoint capture failure"


def _ep_path(model_id: str) -> str:
    return f"/api/v1/models/{model_id}/endpoints"


def _ep_listed(model_id: str, *, path: str | None = None, prompt: str = "0.000002") -> dict[str, object]:
    return {
        "id": model_id,
        "name": f"Synthetic {model_id.rsplit('/', 1)[-1]}",
        "pricing": {"prompt": prompt, "completion": "0.000008"},
        "context_length": 32_000,
        "links": {"details": path or _ep_path(model_id)},
    }


def _ep_alias(model_id: str, target: str, *, prompt: str = "0.000002") -> dict[str, object]:
    return {
        "id": model_id,
        "name": f"Synthetic {model_id.rsplit('/', 1)[-1]}",
        "pricing": {"prompt": prompt, "completion": "0.000008"},
        "context_length": 32_000,
        "alias_target": {"slug": target},
    }


def _ep_endpoint(tag: str, *, prompt: str, completion: str, status: int = 0) -> dict[str, object]:
    return {
        "name": f"Synthetic Host {tag}",
        "tag": tag,
        "provider_name": f"Synthetic Host {tag}",
        "context_length": 32_000,
        "pricing": {"prompt": prompt, "completion": completion},
        "status": status,
        "uptime_last_30m": 99.5,
    }


def _ep_catalog(number: int) -> list[dict[str, object]]:
    """The endpoint provider's raw catalog at scrape `number` (1-6)."""
    models: list[dict[str, object]] = []
    if number <= 3:
        models.extend(
            (
                _ep_listed(_EP_MODEL),
                # A distinct model sharing the listed model's endpoint list.
                _ep_listed(_EP_TWIN, path=_ep_path(_EP_MODEL), prompt="0.000004"),
                _ep_alias(_EP_ALIAS, _EP_MODEL, prompt="0.0000025"),
                _ep_listed(_EP_EMPTY),
                _ep_listed(_EP_FAILED),
                {"id": _EP_NO_LINK, "name": "Synthetic no link", "pricing": {"prompt": "0.000001"}},
                {
                    "id": _EP_INVALID_LINK,
                    "name": "Synthetic invalid link",
                    "pricing": {"prompt": "0.000001"},
                    "links": {"details": "https://elsewhere.invalid/endpoints"},
                },
                _ep_alias(_EP_MISSING_ALIAS, "fake-org/endpoint-nowhere"),
                _ep_alias(_EP_CYCLE[0], _EP_CYCLE[1]),
                _ep_alias(_EP_CYCLE[1], _EP_CYCLE[0]),
                _ep_listed(_EP_BULK),
            )
        )
    if 2 <= number <= 3:
        models.append(_ep_listed(_EP_NEW_PATH))
    if number <= 4:
        models.append(_ep_listed(_EP_ERROR_ONLY))
    if number <= 5:
        models.append(_ep_listed(_EP_UNCAPTURED))
    models.append(_ep_listed(_EP_REBASED))
    return models


def _ep_lists(number: int) -> dict[str, tuple[dict[str, object], ...]]:
    """Each successful planned path's endpoints at scrape `number`; `_EP_FAILED`'s path always fails."""
    bulk_prompt, bulk_completion = ("0.0000011", "0.0000022") if number == 2 else ("0.000001", "0.000002")
    # Against the first capture, the second moves fake-host-1's prompt price
    # and adds fake-host-3; the third moves fake-host-1's completion price.
    # fake-host-2 carries the alias's catalog prices throughout.
    listed = [
        _ep_endpoint(
            "fake-host-1",
            prompt="0.000003" if number == 2 else "0.000002",
            completion="0.00001" if number == 3 else "0.000008",
        ),
        _ep_endpoint("fake-host-2", prompt="0.0000025", completion="0.000008"),
    ]
    if number == 2:
        listed.append(_ep_endpoint("fake-host-3", prompt="0.0000015", completion="0.000007"))
    host = (_ep_endpoint("fake-host-1", prompt="0.000002", completion="0.000008"),)
    return {
        _ep_path(_EP_MODEL): tuple(listed),
        _ep_path(_EP_EMPTY): (),
        _ep_path(_EP_BULK): tuple(
            _ep_endpoint(f"fake-bulk-host-{index:03d}", prompt=bulk_prompt, completion=bulk_completion)
            for index in range(_EP_BULK_COUNT)
        ),
        _ep_path(_EP_ERROR_ONLY): host,
        _ep_path(_EP_UNCAPTURED): host,
        _ep_path(_EP_REBASED): host,
        _ep_path(_EP_NEW_PATH): host,
    }


def _ep_fetch(models: list[NormalizedModel], number: int, *, completed_at: str) -> EndpointFetchResult:
    """An invented fetch of every planned path, built like `fetch_endpoint_lists`'s result."""
    current = {model.provider_model_id: model for model in models}
    mappings = build_endpoint_mappings(current, endpoint_origin(ENDPOINT_PROVIDER.models_url).path_prefix)
    available = _ep_lists(number)
    paths: list[EndpointPathResult] = []
    bodies: dict[str, object] = {}
    for path in planned_endpoint_paths(mappings):
        if path == _ep_path(_EP_FAILED):
            code, message = _EP_FAILED_ERROR
            paths.append(EndpointPathResult(path, None, "error", (), code, message, 503))
            continue
        value = available[path]
        list_id = path.removeprefix("/api/v1/models/").removesuffix("/endpoints")
        paths.append(EndpointPathResult(path, list_id, "ok" if value else "empty", value, None, None, None))
        bodies[path] = {"data": {"id": list_id, "endpoints": list(value)}}
    return EndpointFetchResult(
        provider_id=ENDPOINT_PROVIDER.provider_id,
        started_at=completed_at,
        completed_at=completed_at,
        mappings=mappings,
        paths=tuple(paths),
        paths_requested=len(paths),
        paths_attempted=len(paths),
        paths_failed=sum(1 for result in paths if result.outcome == "error"),
        mapping_failures=sum(1 for mapping in mappings if mapping.is_failure),
        bodies=bodies,
    )


def _ep_save_capture(
    store: Store,
    models: list[NormalizedModel],
    number: int,
    *,
    scrape_id: int,
    baseline_scrape_id: int | None,
    completed_at: str,
) -> int:
    profile = resolve_profile(ENDPOINT_PROVIDER.kind)
    baseline = None if baseline_scrape_id is None else store.get_endpoint_capture_for_scrape(baseline_scrape_id)
    candidate = build_endpoint_capture(
        _ep_fetch(models, number, completed_at=completed_at),
        profile=profile,
        scrape_id=scrape_id,
        baseline_scrape_id=baseline_scrape_id,
        baseline_capture=baseline,
    )
    summary = store.save_endpoint_capture(candidate)
    assert summary.capture_id is not None
    return summary.capture_id


def _build_endpoint_history(store: Store) -> EndpointFixtureFacts:
    times = {number: f"2026-09-{number:02d}T12:00:00+00:00" for number in range(1, 7)}
    baselines = {1: None, 2: 1, 3: 1, 4: 3, 5: 4, 6: 5}
    scrape_ids: dict[int, int] = {}
    models: dict[int, list[NormalizedModel]] = {}
    for number in range(1, 7):
        baseline = baselines[number]
        scrape_ids[number], models[number] = _save_scrape(
            store,
            ENDPOINT_PROVIDER,
            completed_at=times[number],
            raw_models=_ep_catalog(number),
            previous_id=None if baseline is None else scrape_ids[baseline],
            previous_models=[] if baseline is None else models[baseline],
        )

    first_completed = "2026-09-01T12:05:00+00:00"
    first = _ep_save_capture(
        store, models[1], 1, scrape_id=scrape_ids[1], baseline_scrape_id=None, completed_at=first_completed
    )
    # The third scrape's capture is saved and completes before the second's.
    third = _ep_save_capture(
        store, models[3], 3, scrape_id=scrape_ids[3], baseline_scrape_id=scrape_ids[1],
        completed_at="2026-09-03T12:30:00+00:00",
    )
    second = _ep_save_capture(
        store, models[2], 2, scrape_id=scrape_ids[2], baseline_scrape_id=scrape_ids[1],
        completed_at="2026-09-04T06:00:00+00:00",
    )
    error = store.save_endpoint_error_capture(
        build_endpoint_error_summary(
            provider_id=ENDPOINT_PROVIDER.provider_id,
            scrape_id=scrape_ids[4],
            completed_at="2026-09-04T12:01:00+00:00",
            started_at=times[4],
            error_summary=_EP_ERROR_SUMMARY,
            baseline_scrape_id=scrape_ids[3],
            baseline_capture=store.get_endpoint_capture_for_scrape(scrape_ids[3]),
        )
    )
    assert error.capture_id is not None and error.persistence_error is None
    rebased = _ep_save_capture(
        store, models[6], 6, scrape_id=scrape_ids[6], baseline_scrape_id=scrape_ids[5],
        completed_at="2026-09-06T12:01:00+00:00",
    )
    return EndpointFixtureFacts(
        provider_id=ENDPOINT_PROVIDER.provider_id,
        first_scrape=scrape_ids[1],
        second_scrape=scrape_ids[2],
        third_scrape=scrape_ids[3],
        error_scrape=scrape_ids[4],
        uncaptured_scrape=scrape_ids[5],
        rebased_scrape=scrape_ids[6],
        first_capture=first,
        second_capture=second,
        third_capture=third,
        error_capture=error.capture_id,
        rebased_capture=rebased,
        listed_model=_EP_MODEL,
        twin_model=_EP_TWIN,
        alias_model=_EP_ALIAS,
        empty_model=_EP_EMPTY,
        failed_model=_EP_FAILED,
        no_link_model=_EP_NO_LINK,
        invalid_link_model=_EP_INVALID_LINK,
        missing_alias_model=_EP_MISSING_ALIAS,
        cycle_models=_EP_CYCLE,
        bulk_model=_EP_BULK,
        error_only_model=_EP_ERROR_ONLY,
        uncaptured_model=_EP_UNCAPTURED,
        rebased_model=_EP_REBASED,
        listed_path=_ep_path(_EP_MODEL),
        empty_path=_ep_path(_EP_EMPTY),
        failed_path=_ep_path(_EP_FAILED),
        bulk_path=_ep_path(_EP_BULK),
        rebased_path=_ep_path(_EP_REBASED),
        listed_keys_by_capture=(
            (first, ("fake-host-1#0", "fake-host-2#0")),
            (second, ("fake-host-1#0", "fake-host-2#0", "fake-host-3#0")),
            (third, ("fake-host-1#0", "fake-host-2#0")),
        ),
        failed_error=_EP_FAILED_ERROR,
        error_summary=_EP_ERROR_SUMMARY,
        first_capture_completed_at=first_completed,
        alias_divergent_leaf="pricing.prompt",
        alias_matching_keys=("fake-host-2#0",),
        bulk_change_count=2 * _EP_BULK_COUNT,
        new_path_model=_EP_NEW_PATH,
        new_path_path=_ep_path(_EP_NEW_PATH),
    )


UNSENT_ERROR_MESSAGE = "not requested within the synthetic admission budget"


def mark_failed_list_unsent(path: Path, endpoint: EndpointFixtureFacts) -> None:
    """Rewrite a `with_endpoints` fixture so the failed model's list was never
    sent (`budget_exceeded`) in any capture, as `fetch_endpoint_lists` records
    a path not started before its admission deadline."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            """UPDATE endpoint_captures SET paths_attempted = paths_attempted - 1
               WHERE capture_id IN (SELECT capture_id FROM endpoint_lists WHERE list_path = ?)""",
            (endpoint.failed_path,),
        )
        connection.execute(
            "UPDATE endpoint_lists SET error_code = 'budget_exceeded', error_message = ? WHERE list_path = ?",
            (UNSENT_ERROR_MESSAGE, endpoint.failed_path),
        )
    connection.close()


def build_fixture_db(path: Path, with_endpoints: bool = False) -> FixtureFacts:
    store = Store(path)
    store.initialize()
    store.upsert_provider_configs(
        (EXAMPLE_PROVIDER, OTHER_PROVIDER, CONDITIONAL_PROVIDER)
        + ((ENDPOINT_PROVIDER,) if with_endpoints else ()),
        updated_at="2026-08-01T12:00:00+00:00",
    )

    example_times = tuple(f"2026-08-{day:02d}T12:00:00+00:00" for day in range(10, 16))
    example_ids: list[int] = []
    previous_id: int | None = None
    previous_models: list[NormalizedModel] = []
    for number, completed_at in enumerate(example_times, start=1):
        scrape_id, previous_models = _save_scrape(
            store,
            EXAMPLE_PROVIDER,
            completed_at=completed_at,
            raw_models=_example_raw_models(number),
            previous_id=previous_id,
            previous_models=previous_models,
        )
        example_ids.append(scrape_id)
        previous_id = scrape_id

    store.create_scrape(
        provider_id=EXAMPLE_PROVIDER.provider_id,
        started_at="2026-08-17T12:00:00+00:00",
        completed_at="2026-08-17T12:00:01+00:00",
        status="error",
        baseline_mode="previous",
        baseline_scrape_id=previous_id,
        saved_snapshot=False,
        model_count=0,
        error_message="Synthetic provider failure",
    )

    other_raw = [
        {
            "id": "fake-org/other-test-model",
            "name": "Synthetic Other Test Model",
            "pricing": {"prompt": 1, "completion": 2},
            "context_length": 4096,
            "top_provider": {"max_completion_tokens": 1024},
            "supported_parameters": [],
            "benchmarks": {"design_arena": {"score": 500}},
        }
    ]
    other_first, other_models = _save_scrape(
        store,
        OTHER_PROVIDER,
        completed_at="2026-08-18T12:00:00+00:00",
        raw_models=other_raw,
        previous_id=None,
        previous_models=[],
    )
    _save_scrape(
        store,
        OTHER_PROVIDER,
        completed_at="2026-08-18T12:20:00+00:00",
        raw_models=other_raw,
        previous_id=other_first,
        previous_models=other_models,
    )

    conditional_old, conditional_new = synthetic_scheduled_rate_models()
    conditional_first, conditional_models = _save_scrape(
        store,
        CONDITIONAL_PROVIDER,
        completed_at="2026-07-01T12:00:00+00:00",
        raw_models=[conditional_old],
        previous_id=None,
        previous_models=[],
    )
    _save_scrape(
        store,
        CONDITIONAL_PROVIDER,
        completed_at="2026-07-02T12:00:00+00:00",
        raw_models=[conditional_new],
        previous_id=conditional_first,
        previous_models=conditional_models,
    )

    endpoint = _build_endpoint_history(store) if with_endpoints else None

    ids = tuple(example_ids)
    return FixtureFacts(
        provider_ids=(EXAMPLE_PROVIDER.provider_id, OTHER_PROVIDER.provider_id),
        scrape_ids=ids,
        scrape_dates=tuple(local_date_for(value) for value in example_times),
        model_ids=tuple(f"fake-org/test-model-{suffix}" for suffix in "abcde"),
        added_model="fake-org/test-model-d",
        added_at_scrape=ids[3],
        removed_model="fake-org/test-model-e",
        removed_at_scrape=ids[4],
        price_step=("fake-org/test-model-a", ids[1], ids[2], 0.000002, 0.0000035, 2.0, 3.5),
        context_step=("fake-org/test-model-b", ids[2], ids[3], 128_000, 256_000),
        bool_flip=("fake-org/test-model-c", ids[3], ids[4], False, True),
        bulk_list_models=tuple(f"fake-org/test-model-{suffix}" for suffix in "abc"),
        benchmark_churn_model="fake-org/test-model-a",
        equal_length_list_step=("fake-org/test-model-e", local_date_for(example_times[1])),
        conditional_pricing_model=SYNTHETIC_SCHEDULED_RATE_MODEL_ID,
        conditional_provider_id=CONDITIONAL_PROVIDER.provider_id,
        endpoint=endpoint,
    )


def decoded_change_rows(path: Path) -> tuple[dict[str, object], ...]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM field_changes ORDER BY change_id").fetchall()
    return tuple(
        {
            **dict(row),
            "old_value": json.loads(row["old_value_json"]) if row["old_value_json"] is not None else None,
            "new_value": json.loads(row["new_value_json"]) if row["new_value_json"] is not None else None,
        }
        for row in rows
    )


@dataclass(frozen=True)
class HostsFixtureFacts:
    """Invented Hosts scenarios; identities and hand-derived expectations for UI/API tests."""

    provider_id: str
    single_provider_id: str
    scrapes: dict[str, int]
    captures: dict[str, int]
    host_history_attribution: dict
    host_history_truncation: dict
    host_single_capture: dict
    host_grouping_and_ties: dict
    host_precision_conditions: dict
    host_missing_ranking: dict
    host_exact_prices: dict
    host_partial_coverage: dict
    host_empty_results: dict
    host_tier_identity: dict
    host_condition_counts: dict
    host_row_admission: dict
    host_list_identity: dict
    host_legacy_and_reasons: dict


def build_hosts_fixture_db(path: Path) -> HostsFixtureFacts:
    """Build only synthetic Hosts evidence, independent of the existing browse fixture."""
    from dataclasses import replace

    provider = replace(ENDPOINT_PROVIDER, provider_id="hosts-synthetic", label="Synthetic Hosts")
    single = replace(provider, provider_id="hosts-single-synthetic", label="Synthetic Single Host")
    store = Store(path)
    store.initialize()
    store.upsert_provider_configs((provider, single), updated_at="2026-09-01T12:00:00+00:00")
    profile = resolve_profile(provider.kind)
    paths = {name: _ep_path("fake-org/hosts-" + name) for name in ("shared", "moved", "solo", "bare", "empty", "bulk", "unranked", "unmapped", "exact")}
    alpha, beta, gamma = "Synthetic Alpha", "Synthetic Beta", "Synthetic Gamma"

    def endpoint(tag, host=alpha, price="0.000001", **extra):
        return {"tag": tag, "provider_name": host, "pricing": {"prompt": price},
                "status": 0, "context_length": 128000, "max_completion_tokens": 32000,
                "max_prompt_tokens": 96000, "quantization": "fp16", "uptime_last_1d": 99,
                "supported_parameters": ["tools"], "native_tools": {"search": {}},
                "supports_implicit_caching": True, **extra}

    quants = ("fp32", "bf16", "fp16", "fp8", "int8", "fp6", "fp4", "mxfp4", "nvfp4", "int4", "unknown", "synthetic-q", None, 7)
    shared = [
        endpoint("alpha-fast", price="0.000002", context_length=256000, uptime_last_1d=98),
        endpoint("alpha-cheap", price="0.000001", uptime_last_1d=100),
        endpoint("beta", beta, "0.000001", context_length=64000, uptime_last_1d=97, service_tier="standard"),
        endpoint("gamma", gamma, "0.000003", service_tier="null", supported_parameters=["response_format"], native_tools={"code": {}, "search": {}}, supports_implicit_caching="true", status=2),
    ]
    bare = [endpoint(f"precision-{i}", beta, quantization=q, service_tier=[None, "standard", "null", "priority", 9][i % 5]) for i, q in enumerate(quants)]
    bare += [endpoint("exact-low", price="0.00000100000000000000001"), endpoint("exact-high", beta, "0.00000100000000000000002"),
             endpoint("tiny", gamma, "1e-10000"), endpoint("negative", gamma, "-0.000001"), endpoint("zero", gamma, "0")]
    unranked = [{"tag": "missing", "name": "Synthetic Missing", "status": None, "quantization": None,
                 "service_tier": {}, "native_tools": [], "supports_implicit_caching": 1},
                {"tag": "fallback", "provider_name": 7, "name": "Synthetic Name Fallback", "supported_parameters": ["tools", 7]}]
    initial = {"shared": shared, "solo": [endpoint("solo", "Synthetic Solo", "0.000004", context_length=512000), endpoint("moved-removed", "Synthetic Moved Removed")],
               "bare": bare, "empty": [], "bulk": [endpoint(f"bulk-{i:03}", "Synthetic Bulk") for i in range(105)], "unranked": unranked}
    initial["exact"] = [bare[14], dict(bare[15], context_length=None, max_completion_tokens=None, uptime_last_1d=None),
                        endpoint("price-missing", gamma, None, context_length=512000)]
    initial["bare"] = bare[:14] + bare[16:]
    initial["unmapped"] = [{"tag": "tag-only"}, {}]
    catalog = [_ep_listed("fake-org/hosts-" + name, path=paths[name]) for name in initial if name != "unmapped"]
    catalog += [_ep_listed("fake-org/hosts-twin", path=paths["shared"]), _ep_alias("fake-org/hosts-alias", "fake-org/hosts-shared")]
    scrapes, captures = {}, {}
    previous_id, previous_models = None, []

    def save(name, number, contents, raw_catalog, *, failed=(), baseline=None, pending=False, capture=True, error=False, source=provider):
        nonlocal previous_id, previous_models
        when = f"2026-09-{number:02d}T12:00:00+00:00"
        primary = source.provider_id == provider.provider_id
        sid, models = _save_scrape(store, source, completed_at=when, raw_models=raw_catalog,
                                  previous_id=previous_id if primary else None,
                                  previous_models=previous_models if primary else [])
        scrapes[name] = sid
        if primary:
            previous_id, previous_models = sid, models
        if not capture:
            return
        if error:
            summary = store.save_endpoint_error_capture(build_endpoint_error_summary(provider_id=provider.provider_id,
                      scrape_id=sid, started_at=when, completed_at=when, error_summary="Synthetic capture failure",
                      baseline_scrape_id=baseline, baseline_capture=store.get_endpoint_capture_for_scrape(baseline) if baseline else None))
        else:
            mappings = build_endpoint_mappings({m.provider_model_id: m for m in models}, endpoint_origin(provider.models_url).path_prefix)
            results, bodies = [], {}
            for key, values in contents.items():
                list_path = paths.get(key, key)
                list_id = None if key == "bare" else "synthetic-response-" + key
                if key in failed:
                    results.append(EndpointPathResult(list_path, None, "error", (), "http_status", "Synthetic list unavailable", 503))
                else:
                    results.append(EndpointPathResult(list_path, list_id, "ok" if values else "empty", tuple(values), None, None, None))
                    bodies[list_path] = {"data": {"id": list_id, "endpoints": values}}
            fetched = EndpointFetchResult(source.provider_id, when, when, mappings, tuple(results), len(results), len(results), len(failed), 0, bodies)
            candidate = build_endpoint_capture(fetched, profile=profile, scrape_id=sid, baseline_scrape_id=baseline,
                        baseline_capture=store.get_endpoint_capture_for_scrape(baseline) if baseline else None)
            summary = store.save_endpoint_capture(candidate)
        assert summary.capture_id is not None
        captures[name] = summary.capture_id
        if pending:
            with sqlite3.connect(path) as connection:
                connection.execute("DELETE FROM endpoint_telemetry WHERE capture_id = ?", (summary.capture_id,))
                connection.execute("DELETE FROM endpoint_telemetry_captures WHERE capture_id = ?", (summary.capture_id,))

    save("first", 1, initial, catalog)
    changed = dict(initial)
    changed["shared"] = [dict(shared[0], context_length=512000), dict(shared[1], status=3),
                         dict(shared[2], provider_name="Synthetic Renamed"), endpoint("added", alpha)]
    changed["bulk"] = [dict(e, context_length=256000, max_completion_tokens=64000) for e in initial["bulk"]]
    changed["moved"] = [dict(changed.pop("solo")[0], context_length=1024000)]
    moved_catalog = [dict(m, links={"details": paths["moved"]}) if m["id"] == "fake-org/hosts-solo" else m for m in catalog]
    save("second", 2, changed, moved_catalog, baseline=scrapes["first"])
    save("partial", 3, changed, moved_catalog, failed=("moved",), baseline=scrapes["second"])
    absent = {key: [e for e in values if e.get("provider_name") not in (gamma, "Synthetic Solo")] for key, values in changed.items()}
    save("absent", 4, absent, moved_catalog, baseline=scrapes["partial"])
    # Another capture-capable provider, a single archived capture without a marker.
    save("no_prices", 5, {"unranked": unranked}, [_ep_listed("fake-org/hosts-unranked")], pending=True, source=single)
    save("empty", 6, {"empty": []}, [_ep_listed("fake-org/hosts-empty")])
    save("uncaptured", 7, {}, catalog, capture=False)
    save("error", 8, {}, catalog, error=True)
    return HostsFixtureFacts(
        provider.provider_id, single.provider_id, scrapes, captures,
        {"host": alpha, "kinds": ("endpoint_added", "field_changed", "status_changed"), "removed_host": gamma, "moved_path": paths["moved"], "from_path": paths["solo"], "moved_host": "Synthetic Solo", "moved_removed_host": "Synthetic Moved Removed", "target_display": "synthetic-response-moved", "renamed_host": "Synthetic Renamed", "renamed_from": beta},
        {"host": "Synthetic Bulk", "count": 210},
        {"scrape": scrapes["no_prices"], "telemetry": "pending"},
        {"path": paths["shared"], "hosts": (alpha, beta, gamma), "alpha_endpoints": 2, "price_winners": (alpha, beta), "context_winner": alpha},
        {"values": quants, "bits": (32, 16, 16, 8, 8, 6, 4, 4, 4, 4, None, None, None, None)},
        {"path": paths["unranked"], "keys": ("missing#0", "fallback#0"), "zero_key": "zero#0", "no_prices_scrape": scrapes["no_prices"], "missing_window": "5m"},
        {"path": paths["exact"], "low_key": "exact-low#0", "high_key": "exact-high#0", "low": "1.00000000000000001", "high": "1.00000000000000002", "threshold": "1.000000000000000015", "tiny_key": "tiny#0", "tiny_denominator_power": 9994, "negative_key": "negative#0"},
        {"host": "Synthetic Solo", "scrapes": (scrapes["first"], scrapes["partial"], scrapes["absent"])},
        {"empty_scrape": scrapes["empty"], "disjoint_hosts": (alpha, "Synthetic Missing")},
        {"tiers": (None, "null", "priority", "standard")},
        {"shared_statuses": (0, 0, 0, 2), "shared_uptimes": (98, 100, 97, 99), "shared_contexts": (256000, 128000, 64000, 128000)},
        {"shared_path": paths["shared"], "solo_path": paths["solo"], "unranked_path": paths["unranked"]},
        {"missing_id_path": paths["bare"], "shared_models": ("fake-org/hosts-shared", "fake-org/hosts-twin"), "alias": "fake-org/hosts-alias"},
        {"uncaptured": scrapes["uncaptured"], "error": scrapes["error"]},
    )
