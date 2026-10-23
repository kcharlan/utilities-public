"""Synthetic endpoint-capture and alias fixtures for the scan report tests.

Shared by `test_reporting.py` (text, Markdown, JSON and HTML assertions) and
`test_report_html_browser.py` (rendered HTML in Chromium), so both build the
same invented captures. Every provider, model, endpoint, path and price here
is invented.
"""

from __future__ import annotations

from model_sentinel.alias_check import divergence_events as _divergence_events
from model_sentinel.config import ProviderConfig as _ProviderConfig
from model_sentinel.endpoints import (
    CONCISE_ENDPOINT_LIST_CAP,
    compare_endpoint_captures,
    endpoint_state_hash,
)
from model_sentinel.models import (
    BaselineInfo,
    EndpointCaptureSummary,
    EndpointListRecord,
    EndpointObservationRecord,
    FieldChange,
    ModelDelta,
    ProviderScanResult,
)
from model_sentinel.normalize import normalize_models as _normalize_models
from model_sentinel.provider_profiles import OPENROUTER_PROFILE
from model_sentinel.reporting import make_report_detail_policy, render_scan_report


# The baseline a real saved scan carries (see `test_reporting._BASELINE`).
_BASELINE = BaselineInfo(scrape_id=7, completed_at="2026-07-24T05:00:00+00:00")
_EP_PREFIX = "/api/v1/models/"
_EP_PROFILE = OPENROUTER_PROFILE
_EP_PROVIDER = _ProviderConfig(
    provider_id="openrouter",
    label="OpenRouter",
    kind="openrouter",
    base_url="https://fake-router.invalid/api/v1",
    models_path="/models",
    credential_env_var="FAKE_ROUTER_NOT_A_REAL_KEY",
    price_multiplier=1,
    price_divisor=1,
    enabled=True,
)
_EP_TARGET = "fake-org/test-model-a"
_EP_ALIAS = "fake-org/test-model-latest"


def _capability_result(count: int = 1) -> ProviderScanResult:
    """Invented membership and attribute changes, plus metadata and a set no-op."""
    before, after = [], []
    for index in range(count):
        model = f"synthetic/capability-{index:02d}"
        for destination, members, defaults in (
            (before, ["synthetic-kept", "synthetic-removed"], None),
            (after, ["synthetic-kept", "synthetic-added"], {"temperature": 0.25}),
        ):
            state = {**_ep_state("synthetic-host"), "supported_parameters": members}
            if defaults is not None:
                state["default_parameters"] = defaults
            destination.append(_ep_list(model, _ep_obs("synthetic-host", state), model_ids=(model, model + "-mapped")))
    for model, old, new in (
        ("synthetic/metadata-only", {"description": "before"}, {"description": "after"}),
        ("synthetic/noop-only", {"parameters": ["synthetic-a", "synthetic-b"]}, {"parameters": ["synthetic-b", "synthetic-a", "synthetic-a"]}),
    ):
        before.append(_ep_list(model, _ep_obs("synthetic-host", {**_ep_state("synthetic-host"), **old})))
        after.append(_ep_list(model, _ep_obs("synthetic-host", {**_ep_state("synthetic-host"), **new})))
    return _ep_result(_ep_capture(before, after))


def _ep_path(model_id: str) -> str:
    return f"{_EP_PREFIX}{model_id}/endpoints"


def _ep_state(tag: str, *, context_length: int = 1000, **pricing) -> dict:
    return {"tag": tag, "provider_name": f"Fake Host {tag}", "context_length": context_length, "pricing": pricing}


def _ep_obs(tag: str, state: dict, status: int = 0, occurrence: int = 0) -> EndpointObservationRecord:
    return EndpointObservationRecord(f"{tag}#{occurrence}", endpoint_state_hash(state), state, status)


def _ep_list(model_id: str, *observations, outcome: str | None = None, model_ids=None, path=None) -> EndpointListRecord:
    if outcome is None:
        outcome = "ok" if observations else "empty"
    return EndpointListRecord(
        list_path=path or _ep_path(model_id),
        list_model_id=model_id,
        outcome=outcome,
        endpoint_count=len(observations),
        error_code="http_status" if outcome == "error" else None,
        error_message="HTTP 503" if outcome == "error" else None,
        model_ids=(model_id,) if model_ids is None else model_ids,
        observations=observations,
    )


def _ep_capture(baseline_lists, current_lists, **overrides) -> EndpointCaptureSummary:
    if baseline_lists is None:
        changes, gaps = (), ()
    else:
        changes, gaps = compare_endpoint_captures(baseline_lists, current_lists, from_capture_id=1)
    failed = sum(1 for listing in current_lists if not listing.succeeded)
    values = dict(
        capture_id=2,
        scrape_id=8,
        provider_id="openrouter",
        started_at="2030-01-02T03:04:05+00:00",
        completed_at="2030-01-02T03:04:06+00:00",
        status="complete" if not failed else "partial",
        paths_requested=len(current_lists),
        paths_attempted=len(current_lists),
        paths_failed=failed,
        mapping_failures=0,
        first_capture=False,
        comparison_state="available" if baseline_lists is not None else "no_selected_baseline",
        baseline_capture_id=1 if baseline_lists is not None else None,
        error_summary=None,
        changes=changes,
        comparison_gaps=gaps,
        lists=tuple(current_lists),
    )
    values.update(overrides)
    return EndpointCaptureSummary(**values)


def _ep_result(capture=None, alias_events=(), changed=()) -> ProviderScanResult:
    return ProviderScanResult(
        provider_id="openrouter",
        provider_label="OpenRouter",
        status="success",
        current_count=2,
        saved=True,
        baseline=_BASELINE,
        baseline_message=None,
        scrape_id=8,
        added=(),
        removed=(),
        changed=changed,
        profile=_EP_PROFILE,
        endpoint_capture=capture,
        alias_events=alias_events,
    )


def _ep_report(result, format_name: str = "text", mode: str = "default") -> str:
    return render_scan_report(
        generated_at="2030-01-02T03:04:06+00:00",
        command="scan",
        format_name=format_name,
        provider_results=[result],
        detail_policy=make_report_detail_policy(mode=mode),
    )


def _ep_html(result, mode: str = "default", companion_link: tuple[str, str] | None = None) -> str:
    """The HTML scan report, with the companion link `cli.run_scan` would pass."""
    return render_scan_report(
        generated_at="2030-01-02T03:04:06+00:00",
        command="scan",
        format_name="html",
        provider_results=[result],
        detail_policy=make_report_detail_policy(mode=mode),
        companion_link=companion_link,
    )


def _price_move_delta(model_id: str = "fake-org/test-model-a") -> ModelDelta:
    """A catalog price move, so the HTML report carries a Price Movement card."""
    return ModelDelta(
        "changed",
        model_id,
        "Fake Test Model A",
        (FieldChange("pricing.prompt", "0.000001", "0.000002"),),
    )


def _ep_section(report: str, heading: str) -> str:
    """One appended section of a text or Markdown scan report, heading included."""
    markers = {
        "Alias check": ("\nAlias check\n", "\n## Alias check\n"),
        "Provider endpoints": ("\nProvider endpoints\n", "\n## Provider endpoints\n"),
    }[heading]
    starts = [report.find(marker) for marker in markers if marker in report]
    assert starts, f"{heading!r} section missing"
    start = starts[0] + 1
    following = [
        report.find(marker, start)
        for other in ("Alias check", "Provider endpoints")
        if other != heading
        for marker in ("\nAlias check\n", "\n## Alias check\n", "\nProvider endpoints\n", "\n## Provider endpoints\n")
        if other in marker and report.find(marker, start) > start
    ]
    return report[start : min(following) if following else len(report)]


def _ep_catalog(*raw_models: dict) -> dict:
    models = _normalize_models(_EP_PROVIDER, list(raw_models), _EP_PROFILE)
    return {model.provider_model_id: model for model in models}


def _ep_listed(model_id: str, **pricing) -> dict:
    return {"id": model_id, "links": {"details": _ep_path(model_id)}, "pricing": pricing}


def _ep_alias(model_id: str, target: str, **pricing) -> dict:
    return {"id": model_id, "alias_target": {"slug": target}, "pricing": pricing}


_TARGET_PRICES = {"prompt": "0.000003", "completion": "0.000015", "request": "0.02"}


def _alias_catalog(target: str = _EP_TARGET, *, extra=(), **alias_pricing) -> dict:
    pricing = dict(_TARGET_PRICES)
    pricing.update(alias_pricing)
    return _ep_catalog(
        _ep_listed(_EP_TARGET, **_TARGET_PRICES),
        *extra,
        _ep_alias(_EP_ALIAS, target, **pricing),
    )


def _three_list_capture() -> EndpointCaptureSummary:
    """A price move, presence changes, a conditional change and full-detail-only changes."""
    model_b = "fake-org/test-model-b"
    baseline = (
        _ep_list(
            _EP_TARGET,
            _ep_obs("host-a", _ep_state("host-a", prompt="0.000001", completion="0.000002")),
            _ep_obs("host-b", _ep_state("host-b", prompt="0.000001", completion="0.000002")),
        ),
        _ep_list(model_b, _ep_obs("host-c", {**_ep_state("host-c", prompt="0.000001"), "pricing": {
            "prompt": "0.000001", "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000002"}]}})),
    )
    current = (
        _ep_list(
            _EP_TARGET,
            _ep_obs(
                "host-a",
                _ep_state("host-a", context_length=2000, prompt="0.000002", completion="0.000002"),
                status=1,
            ),
            _ep_obs("host-d", _ep_state("host-d", prompt="0.000004", completion="0.000005")),
        ),
        _ep_list(model_b, _ep_obs("host-c", {**_ep_state("host-c", prompt="0.000001"), "pricing": {
            "prompt": "0.000001", "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000003"}]}})),
    )
    return _ep_capture(baseline, current)


_PERSISTING_ALIAS = "fake-org/test-model-stable-alias"


def _rich_html_result() -> ProviderScanResult:
    """Everything the HTML additions draw, for the browser tests and screenshots.

    A catalog price move (so the page has a Price Movement card and an Other
    changes disclosure), a new and a persisting alias divergence, a crowded
    target list for the ladders, the three-list capture, and enough changed
    lists to pass the concise cap.
    """
    crowd = tuple(
        _ep_obs(f"crowd-host-{index}", _ep_state(f"crowd-host-{index}", prompt="0.000002", completion="0.000015"))
        for index in range(4)
    ) + (
        _ep_obs("budget-host", _ep_state("budget-host", prompt="0.0000005", completion="0.000004")),
        _ep_obs("premium-host", _ep_state("premium-host", prompt="0.00001", completion="0.00003")),
        _ep_obs("free-host", _ep_state("free-host", prompt="0", completion="0")),
    )
    three = _three_list_capture()
    capped_ids = [f"fake-org/capped-{index:02d}" for index in range(CONCISE_ENDPOINT_LIST_CAP)]
    baseline_capped = tuple(_ep_list(m, _ep_obs("host", _ep_state("host", prompt="0.000001"))) for m in capped_ids)
    current_capped = tuple(_ep_list(m, _ep_obs("host", _ep_state("host", prompt="0.0000015"))) for m in capped_ids)
    model_b = "fake-org/test-model-b"
    baseline_lists = (
        _ep_list(
            _EP_TARGET,
            _ep_obs("host-a", _ep_state("host-a", prompt="0.000001", completion="0.000002")),
            _ep_obs("host-b", _ep_state("host-b", prompt="0.000001", completion="0.000002")),
            *crowd,
        ),
        *(listing for listing in _baseline_of_three() if listing.list_model_id == model_b),
        *baseline_capped,
    )
    current_target = next(listing for listing in three.lists if listing.list_model_id == _EP_TARGET)
    current_lists = (
        _ep_list(_EP_TARGET, *current_target.observations, *crowd),
        *(listing for listing in three.lists if listing.list_model_id == model_b),
        *current_capped,
    )
    capture = _ep_capture(baseline_lists, current_lists)
    stable = _ep_alias(_PERSISTING_ALIAS, _EP_TARGET, **{**_TARGET_PRICES, "completion": "0.000012"})
    baseline_catalog = _ep_catalog(_ep_listed(_EP_TARGET, **_TARGET_PRICES), stable)
    current_catalog = _alias_catalog(prompt="0.000002", request="0.03", extra=(stable,))
    events = _divergence_events(baseline_catalog, current_catalog, _EP_PROFILE, capture.lists)
    return _ep_result(capture, alias_events=events, changed=(_price_move_delta(),))


def _baseline_of_three() -> tuple[EndpointListRecord, ...]:
    """The baseline lists `_three_list_capture` compares against."""
    model_b = "fake-org/test-model-b"
    return (
        _ep_list(model_b, _ep_obs("host-c", {**_ep_state("host-c", prompt="0.000001"), "pricing": {
            "prompt": "0.000001", "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000002"}]}})),
    )
