"""Synthetic dated ledgers; all expectations are hand-derived.

Resolution numbers follow CostUsagePricing.swift resolvedCodexPricing 562–620,
codexCostUSD 694–731, historical table 394–407 and fast multiplier 682–692
at 3bbf6bc48. History selection/recording follows spec §5.6 and plan Task 16.
Compiler diagnostics are exercised through their inputs here; Task 18 renders
history_begins, unrecorded_catalog_rates and invalid-ledger cost availability.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from catalogs import catalog, model
from tools.testkit import load_launcher

DATE = "2030-01-07T00:00:00Z"
LATER = "2030-01-08T00:00:00Z"
RATES = {"input": 2, "cached_input": 0.5, "cache_write": 3, "output": 7}


def entry(identifier="gpt-synthetic-history", at=DATE, source="catalog", **changes):
    result = {"model": identifier, "effective_from": at, "source": source,
              "per_million": dict(RATES),
              "recorded_at": DATE}
    result.update(changes)
    return result


def ledger(*entries):
    return {"schema": 1, "entries": list(entries)}


def index(c, identifier="gpt-synthetic-history", **cost):
    return c.ModelsDevIndex.from_catalog(catalog({identifier: model(identifier, **(cost or {
        "input": 2, "output": 7, "cache_read": 0.5, "cache_write": 3}))}))


def stamp(c, date=DATE):
    return c.parse_rfc3339_ms(date)


@pytest.mark.parametrize("doc", [None, [], {}, {"schema": 2, "entries": []},
                                  {"schema": True, "entries": []}, {"schema": 1},
                                  {"schema": 1, "entries": {}}, "{broken"],
                         ids=["null-document", "array-document", "missing-schema", "unknown-schema",
                              "boolean-schema", "missing-entries", "wrong-entries", "invalid-json"])
def test_invalid_document(colophon, doc):
    result = colophon.validate_ledger(doc, curated=False)
    assert result.errors
    assert result.entries == []


INVALID_FIELDS = [
    ("model", None), ("model", 1), ("effective_from", None),
    ("effective_from", "broken"), ("effective_from", "2030-02-30T00:00:00Z"),
    ("effective_from", "2030-01-07T00:00:00+01:00"),
    ("effective_from", "2030-01-07T00:00:00.001Z"),
    ("per_million", None), ("per_million", []),
    ("source", "unknown"), ("source", "curated"), ("source", None),
    ("recorded_at", None), ("recorded_at", "bad"),
    ("long_context", []), ("priority", []), ("long_context", None), ("priority", None),
    ("note", 5), ("approximate_date", "yes"),
]


@pytest.mark.parametrize("field,value", INVALID_FIELDS)
def test_invalid_entry_field(colophon, field, value):
    result = colophon.validate_ledger(ledger(entry(**{field: value})), curated=False)
    assert result.errors and "entry 0" in result.errors[0] and field in " ".join(result.errors)
    assert result.entries == []


@pytest.mark.parametrize("field", ["model", "effective_from", "per_million", "source", "recorded_at"])
def test_missing_required_field(colophon, field):
    value = entry()
    del value[field]
    result = colophon.validate_ledger(ledger(value), curated=False)
    assert result.errors and field in " ".join(result.errors)


@pytest.mark.parametrize("value", [None, "bad", [], True, -1, float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["input", "cached_input", "cache_write", "output"])
@pytest.mark.parametrize("container", ["per_million", "long_context"])
def test_invalid_rate(colophon, container, field, value):
    rates = dict(RATES)
    rates[field] = value
    if container == "long_context":
        rates["threshold"] = 200000
    result = colophon.validate_ledger(ledger(entry(**{container: rates})), curated=False)
    assert result.errors and field in " ".join(result.errors)


@pytest.mark.parametrize("container", ["per_million", "long_context"])
@pytest.mark.parametrize("field", ["input", "cached_input", "cache_write", "output"])
def test_missing_rate(colophon, container, field):
    rates = dict(RATES, threshold=200000) if container == "long_context" else dict(RATES)
    del rates[field]
    assert colophon.validate_ledger(ledger(entry(**{container: rates})), curated=False).errors


@pytest.mark.parametrize("value", [None, 0, -1, 1.5, True, "1"])
def test_invalid_long_threshold(colophon, value):
    assert colophon.validate_ledger(ledger(entry(long_context=dict(RATES, threshold=value))), curated=False).errors


def test_missing_long_threshold(colophon):
    assert colophon.validate_ledger(ledger(entry(long_context=RATES)), curated=False).errors


@pytest.mark.parametrize("field,value", [("multiplier", None), ("multiplier", 0),
    ("multiplier", -1), ("multiplier", True), ("multiplier", "2"),
    ("multiplier", float("inf")), ("multiplier", float("nan")),
    ("max_input_tokens", 0), ("max_input_tokens", -1),
    ("max_input_tokens", True), ("max_input_tokens", 2.5), ("max_input_tokens", "2")])
def test_invalid_priority(colophon, field, value):
    priority = {"multiplier": 2, "max_input_tokens": None, field: value}
    assert colophon.validate_ledger(ledger(entry(priority=priority)), curated=False).errors


@pytest.mark.parametrize("field", ["multiplier", "max_input_tokens"])
def test_missing_priority_field(colophon, field):
    priority = {"multiplier": 2, "max_input_tokens": None}
    del priority[field]
    assert colophon.validate_ledger(ledger(entry(priority=priority)), curated=False).errors


def test_invalid_entry_object(colophon):
    assert "entry 0" in colophon.validate_ledger(ledger([]), curated=False).errors[0]


def test_recorded_at_allows_rfc3339_fraction_metadata(colophon):
    value = entry(recorded_at="2030-01-07T00:00:00.123Z")
    assert not colophon.validate_ledger(ledger(value), curated=False).errors


@pytest.mark.parametrize("identifier", ["", " ", "\t", " gpt-synthetic-history", "gpt-5.6",
    "catalog:|gpt-synthetic-history", "catalog:gpt-synthetic-alias|",
    "catalog:gpt-synthetic-alias|gpt-5.6"])
def test_invalid_pricing_identity_never_establishes_history(colophon, identifier):
    result = colophon.validate_ledger(ledger(entry(identifier=identifier)), curated=False)
    assert result.entries == [] and "model" in " ".join(result.errors)


def test_oversized_rate_is_not_representable_price_evidence(colophon):
    result = colophon.validate_ledger(ledger(entry(per_million=dict(RATES, input=10 ** 1000))), curated=False)
    assert result.entries == [] and "input" in " ".join(result.errors)


def test_curated_requires_curated_source(colophon):
    assert colophon.validate_ledger(ledger(entry()), curated=True).errors


def test_optional_objects_and_zero_rates(colophon):
    value = entry(source="manual", per_million={key: 0 for key in RATES})
    del value["recorded_at"]
    assert not colophon.validate_ledger(ledger(value), curated=False).errors


def test_exact_duplicates_collapse_and_warn(colophon):
    value = entry()
    second = entry(note="synthetic note", recorded_at=LATER)
    result = colophon.validate_ledger(ledger(value, value, second), curated=False)
    assert result.entries == [value]
    assert not result.errors and len(result.warnings) == 2


@pytest.mark.parametrize("left,right", [(True, 1), ([False], [0]),
    ({"value": True}, {"value": 1})], ids=["boolean-number", "array-boolean-number", "object-boolean-number"])
def test_duplicate_metadata_json_types_conflict(colophon, left, right):
    result = colophon.validate_ledger(ledger(entry(synthetic_extra=left),
        entry(synthetic_extra=right)), curated=False)
    assert result.entries == []
    assert result.errors == ["entry 1: conflicts with entry 0"]
    assert result.warnings == []


def test_duplicate_metadata_numbers_compare_as_json_numbers(colophon):
    first = entry(synthetic_extra={"value": [1, 0.5, None, True]})
    second = entry(synthetic_extra={"value": [1.0, 0.5, None, True]}, note="synthetic note")
    result = colophon.validate_ledger(ledger(first, second), curated=False)
    assert result.entries == [first] and result.entries[0] is first
    assert result.errors == [] and result.warnings == ["entry 1: duplicate of entry 0; collapsed"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")], ids=["nan", "infinity", "negative-infinity"])
@pytest.mark.parametrize("location", ["root", "entry", "rates", "note", "recorded_at"])
def test_nonfinite_metadata_is_not_json(colophon, value, location):
    doc = ledger(entry())
    if location == "root":
        doc["synthetic_extra"] = {"nested": [value]}
    elif location == "rates":
        doc["entries"][0]["per_million"]["synthetic_extra"] = [value]
    elif location in ("note", "recorded_at"):
        doc["entries"][0][location] = value
    else:
        doc["entries"][0]["synthetic_extra"] = {"nested": [value]}
    result = colophon.validate_ledger(doc, curated=False)
    assert result.entries == [] and result.errors
    assert any("nonfinite JSON number" in error for error in result.errors)
    assert any(error.startswith("ledger: " if location == "root" else "entry 0: ")
               for error in result.errors)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("location", ["root", "entry"])
def test_append_rejects_nonstandard_json_constants(colophon, tmp_path, constant, location):
    doc = ledger(entry())
    target = doc if location == "root" else doc["entries"][0]
    target["synthetic_extra"] = {"nested": ["CONSTANT"]}
    original = json.dumps(doc).replace('"CONSTANT"', constant).encode()
    path = tmp_path / "price-history.json"
    path.write_bytes(original)
    result, warning = colophon.append_user_ledger(path, [entry(at=LATER)], path.stat().st_mtime_ns)
    assert result is False and constant in warning
    assert path.read_bytes() == original


@pytest.mark.parametrize("changes", [{"per_million": dict(RATES, input=99)},
    {"priority": {"multiplier": 2, "max_input_tokens": None}}, {"approximate_date": True},
    {"long_context": dict(RATES, threshold=3)}, {"synthetic_extra": "conflict"}])
def test_conflicting_duplicates_reject_entire_ledger(colophon, changes):
    result = colophon.validate_ledger(ledger(entry(), entry(**changes)), curated=False)
    assert result.entries == [] and "entry 1" in result.errors[0]


def test_merge_ties_null_and_exact_keys(colophon):
    base = entry(at=None, source="curated")
    dated = entry(at=DATE, source="curated")
    recorded = entry(at=DATE)
    manual = entry(at=DATE, source="manual")
    history = colophon.PriceHistory([base, dated], [recorded, manual])
    assert history.pick(base["model"], -100000).entry == base
    picked = history.pick(base["model"], stamp(colophon))
    assert picked.entry == manual and picked.period_index == 3 and not picked.before_first
    assert history.entries_for(base["model"]) == [base, dated, recorded, manual]
    assert history.pick(" " + base["model"], stamp(colophon)) is None
    assert not history.has_any("gpt-synthetic-absent")
    catalog_only = colophon.PriceHistory([dated], [recorded])
    assert catalog_only.pick(base["model"], stamp(colophon)).entry == recorded


def test_earliest_entry_supplies_begins_diagnostic_inputs(colophon):
    early = entry()
    history = colophon.PriceHistory([], [entry(at=LATER), early])
    picked = history.pick(early["model"], stamp(colophon) - 1)
    assert picked.entry == early and picked.before_first and picked.period_index == 0
    assert colophon.parse_rfc3339_ms(picked.entry["effective_from"]) == 1893974400000


def test_first_sight_truncated_fetch_time_not_last_updated(colophon):
    idx = index(colophon)
    idx._models["gpt-synthetic-history"]["last_updated"] = "1999-01-01"
    new = colophon.record_catalog_rates(colophon.PriceHistory([], []), idx,
        stamp(colophon) + 999, {}, stamp(colophon, LATER) + 123)
    assert new == [entry(approximate_date=True, recorded_at=LATER)]


def test_record_change_idempotence_and_past_rates(colophon):
    old = entry(at=None, source="curated")
    history = colophon.PriceHistory([old], [])
    changed = index(colophon, input=4, output=11, cache_read=1, cache_write=5)
    new = colophon.record_catalog_rates(history, changed, stamp(colophon), {}, stamp(colophon))
    assert len(new) == 1 and new[0]["per_million"] == {"input": 4, "cached_input": 1, "cache_write": 5, "output": 11}
    merged = colophon.PriceHistory([old], new)
    assert colophon.record_catalog_rates(merged, changed, stamp(colophon), {}, stamp(colophon, LATER)) == []
    assert merged.pick(old["model"], stamp(colophon) - 1).entry == old


def test_older_cached_fetch_compares_at_fetch_time(colophon):
    old = entry(at=None, source="curated")
    future = entry(at=LATER, per_million=dict(RATES, input=99))
    assert colophon.record_catalog_rates(colophon.PriceHistory([old], [future]), index(colophon),
        stamp(colophon), {}, stamp(colophon, LATER)) == []


def test_manual_only_catalog_appears_and_copies_priority(colophon):
    priority = {"multiplier": 3, "max_input_tokens": None}
    manual = entry(at="2029-01-01T00:00:00Z", source="manual", priority=priority)
    new = colophon.record_catalog_rates(colophon.PriceHistory([], [manual]), index(colophon),
        stamp(colophon), {}, stamp(colophon))
    assert new == [entry(priority=priority, approximate_date=True)]


def test_manual_correction_not_compared_until_catalog_changes(colophon):
    old = entry(at=None, source="curated")
    manual = entry(at="2029-01-01T00:00:00Z", source="manual", per_million=dict(RATES, input=99))
    history = colophon.PriceHistory([old], [manual])
    assert colophon.record_catalog_rates(history, index(colophon), stamp(colophon), {}, stamp(colophon)) == []
    changed = colophon.record_catalog_rates(history, index(colophon, input=4, output=7), stamp(colophon), {}, stamp(colophon))
    assert len(changed) == 1
    assert colophon.PriceHistory([old], [manual] + changed).pick(old["model"], stamp(colophon)).entry == changed[0]


def test_record_long_context_change_and_priority_not_compared(colophon):
    old = entry(at=None, source="curated", priority={"multiplier": 2, "max_input_tokens": 10})
    changed = index(colophon, input=2, output=7, cache_read=0.5, cache_write=3,
                    context_over_200k={"input": 4, "output": 11})
    new = colophon.record_catalog_rates(colophon.PriceHistory([old], []), changed, stamp(colophon), {}, stamp(colophon))
    assert new[0]["long_context"] == {"threshold": 200000, "input": 4, "cached_input": 0.5, "cache_write": 3, "output": 11}
    assert new[0]["priority"] == old["priority"]


@pytest.mark.parametrize("field", ["threshold", "input", "cached_input", "cache_write", "output"])
def test_every_long_context_field_compared(colophon, field):
    long = {"threshold": 200000, "input": 4, "cached_input": 0.5, "cache_write": 3, "output": 11}
    old = entry(at=None, source="curated", long_context=dict(long, **{field: 99}))
    idx = index(colophon, input=2, output=7, cache_read=0.5, cache_write=3,
                context_over_200k={"input": 4, "output": 11})
    result = colophon.record_catalog_rates(colophon.PriceHistory([old], []), idx,
        stamp(colophon), {}, stamp(colophon))
    assert len(result) == 1 and result[0]["long_context"] == long


def test_priority_difference_alone_never_records(colophon):
    old = entry(at=None, source="curated", priority={"multiplier": 2, "max_input_tokens": 10})
    manual = entry(at="2029-01-01T00:00:00Z", source="manual",
                   priority={"multiplier": 9, "max_input_tokens": None})
    assert colophon.record_catalog_rates(colophon.PriceHistory([old], [manual]), index(colophon),
        stamp(colophon), {}, stamp(colophon)) == []


def test_any_source_at_fetch_instant_prevents_recording(colophon):
    manual = entry(source="manual", per_million=dict(RATES, input=99))
    assert colophon.record_catalog_rates(colophon.PriceHistory([], [manual]), index(colophon),
        stamp(colophon), {}, stamp(colophon)) == []


def test_bundled_only_never_recorded(colophon):
    assert colophon.record_catalog_rates(colophon.PriceHistory([], []), index(colophon),
        stamp(colophon), {"gpt-5.4": "gpt-5.4"}, stamp(colophon)) == [entry(approximate_date=True)]


def test_unused_new_and_seeded_repriced_models_record(colophon):
    old = entry(at=None, source="curated")
    idx = colophon.ModelsDevIndex.from_catalog(catalog({
        old["model"]: model(old["model"], input=4, output=7),
        "gpt-synthetic-new": model("gpt-synthetic-new", input=2, output=7)}))
    result = colophon.record_catalog_rates(colophon.PriceHistory([old], []), idx, stamp(colophon), {}, stamp(colophon))
    assert [value["model"] for value in result] == [old["model"], "gpt-synthetic-new"]


def test_unfolded_dated_spelling_gets_exact_history_and_later_change(colophon):
    dated = "gpt-synthetic-history-2030-01-01"
    initial = colophon.record_catalog_rates(colophon.PriceHistory([], []), index(colophon),
        stamp(colophon), {dated: dated}, stamp(colophon))
    history = colophon.PriceHistory([], initial)
    assert history.pick(dated, stamp(colophon) - 1).before_first
    assert history.pick(dated, stamp(colophon)).entry["per_million"] == RATES
    idx = colophon.ModelsDevIndex.from_catalog(catalog({
        "gpt-synthetic-history": model("gpt-synthetic-history", input=2, output=7, cache_read=0.5, cache_write=3),
        dated: model(dated, input=8, output=9)}))
    new = colophon.record_catalog_rates(history, idx, stamp(colophon, LATER), {dated: dated}, stamp(colophon, LATER))
    assert len(new) == 1 and new[0]["model"] == dated and new[0]["per_million"]["input"] == 8
    assert colophon.PriceHistory([], initial + new).pick(dated, stamp(colophon)).entry["per_million"] == RATES


def test_canonical_alias_and_override_source_mapping(colophon):
    # normalizeCodexModel 481–508: ordinary alias is Sol. resolvedCodexPricing
    # 584–616: raw override alone uses alias catalog input/output and Sol caches.
    idx = colophon.ModelsDevIndex.from_catalog(catalog({
        "gpt-5.6": model("gpt-5.6", input=8, output=9),
        "gpt-5.6-sol": model("gpt-5.6-sol", input=4, output=20)}))
    key = "catalog:gpt-5.6|gpt-5.6-sol"
    new = colophon.record_catalog_rates(colophon.PriceHistory([], []), idx, stamp(colophon),
        {key: "gpt-5.6"}, stamp(colophon))
    history = colophon.PriceHistory([], new)
    ordinary = history.pick(colophon.normalize_codex_model("gpt-5.6"), stamp(colophon))
    override = history.pick(key, stamp(colophon))
    assert ordinary.entry["per_million"]["input"] == 4
    assert override.entry["per_million"] == {"input": 8, "cached_input": 0.4, "cache_write": 5, "output": 9}
    assert history.pick(" " + key, stamp(colophon)) is None
    without = colophon.record_catalog_rates(colophon.PriceHistory([], []), idx, stamp(colophon), {}, stamp(colophon))
    assert [value["model"] for value in without] == ["gpt-5.6-sol"]


def test_existing_override_key_without_source_evidence_not_recorded(colophon):
    key = "catalog:gpt-synthetic-alias|gpt-synthetic-history"
    old = entry(identifier=key, at=None, source="curated")
    new = colophon.record_catalog_rates(colophon.PriceHistory([old], []), index(colophon),
        stamp(colophon), {"gpt-synthetic-unpriced": "gpt-synthetic-unpriced"}, stamp(colophon))
    assert [value["model"] for value in new] == ["gpt-synthetic-history"]


def test_append_preserves_entries_and_private_mode(colophon, tmp_path):
    path = tmp_path / "price-history.json"
    existing = entry(source="manual", note="synthetic retained", synthetic_extra=[1, 2])
    colophon.atomic_write_json(path, ledger(existing))
    before = path.stat().st_mtime_ns
    new = entry(at=LATER)
    assert colophon.append_user_ledger(path, [new], before) == (True, None)
    assert json.loads(path.read_text()) == ledger(existing, new)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text().endswith("\n") and '\n  "entries"' in path.read_text()


def test_edited_ledger_skips_and_leaves_transient_diagnostic_inputs(colophon, tmp_path):
    path = tmp_path / "price-history.json"
    colophon.atomic_write_json(path, ledger())
    before = path.stat().st_mtime_ns
    os.utime(path, ns=(before + 1000000, before + 1000000))
    data = path.read_bytes()
    assert colophon.append_user_ledger(path, [entry()], before) == (
        False, "price-history.json changed during the run; recording skipped")
    assert path.read_bytes() == data
    history = colophon.PriceHistory([], [])
    assert not history.has_any("gpt-synthetic-history")
    assert colophon.resolve_rates("gpt-synthetic-history", index(colophon)) == {
        "per_million": RATES, "long_context": None}
    assert colophon.resolve_rates("gpt-synthetic-unpriced", index(colophon)) is None


def test_invalid_ledger_never_appended(colophon, tmp_path):
    path = tmp_path / "price-history.json"
    path.write_text("{broken")
    before = path.stat().st_mtime_ns
    appended, warning = colophon.append_user_ledger(path, [entry()], before)
    assert not appended and "price-history.json" in warning
    assert path.read_text() == "{broken"


def test_edit_during_ledger_reread_is_detected(colophon, tmp_path, monkeypatch):
    path = tmp_path / "price-history.json"
    colophon.atomic_write_json(path, ledger())
    before = path.stat().st_mtime_ns
    original = Path.read_bytes

    def read_and_edit(candidate, *args, **kwargs):
        text = original(candidate, *args, **kwargs)
        if candidate == path:
            os.utime(path, ns=(before + 1000000, before + 1000000))
        return text

    monkeypatch.setattr(Path, "read_bytes", read_and_edit)
    assert colophon.append_user_ledger(path, [entry()], before) == (
        False, "price-history.json changed during the run; recording skipped")
    assert json.loads(original(path)) == ledger()


def test_edit_during_reread_takes_precedence_over_invalid_json(colophon, tmp_path, monkeypatch):
    path = tmp_path / "price-history.json"
    colophon.atomic_write_json(path, ledger())
    before = path.stat().st_mtime_ns

    def read_edited(candidate, *args, **kwargs):
        os.utime(candidate, ns=(before + 1000000, before + 1000000))
        return b"{synthetic partially edited JSON"

    monkeypatch.setattr(Path, "read_bytes", read_edited)
    assert colophon.append_user_ledger(path, [entry()], before) == (
        False, "price-history.json changed during the run; recording skipped")


def test_edit_during_reread_takes_precedence_over_invalid_utf8(colophon, tmp_path, monkeypatch):
    path = tmp_path / "price-history.json"
    colophon.atomic_write_json(path, ledger())
    before = path.stat().st_mtime_ns
    original = Path.open

    def open_edited(candidate, mode="r", *args, **kwargs):
        if candidate == path and "r" in mode:
            with original(candidate, "wb") as stream:
                stream.write(b"\xffsynthetic partial edit")
            os.utime(candidate, ns=(before + 1000000, before + 1000000))
        return original(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_edited)
    assert colophon.append_user_ledger(path, [entry()], before) == (
        False, "price-history.json changed during the run; recording skipped")


def test_append_preserves_duplicates_and_top_level_metadata(colophon, tmp_path):
    path = tmp_path / "price-history.json"
    old = entry(source="manual")
    doc = dict(ledger(old, old), synthetic_metadata="retained")
    colophon.atomic_write_json(path, doc)
    assert colophon.append_user_ledger(path, [entry(at=LATER)], path.stat().st_mtime_ns) == (True, None)
    assert json.loads(path.read_text()) == dict(doc, entries=[old, old, entry(at=LATER)])


def test_empty_append_has_no_write(colophon, tmp_path):
    path = tmp_path / "price-history.json"
    assert colophon.append_user_ledger(path, [], None) == (False, None)
    assert not path.exists()


@pytest.mark.parametrize("exists", [False, True])
def test_ledger_creation_or_deletion_detected(colophon, tmp_path, exists):
    path = tmp_path / "price-history.json"
    if exists:
        colophon.atomic_write_json(path, ledger())
        before = path.stat().st_mtime_ns
        path.unlink()
    else:
        before = None
        colophon.atomic_write_json(path, ledger())
    assert colophon.append_user_ledger(path, [entry()], before)[0] is False


def test_curated_block_valid_and_historical_cutoffs(colophon):
    result = colophon.validate_ledger(colophon.CURATED_PRICE_HISTORY, curated=True)
    assert not result.errors and not result.warnings
    history = colophon.PriceHistory(result.entries, [])
    # Historical table 394–407: Sol 5/0.5/6.25/30; Terra 2.5/.25/3.125/15;
    # Luna 1/.1/1.25/6 per million, long tuples doubled except output x1.5.
    expected = {"gpt-5.6-sol": [5, 0.5, 6.25, 30, 10, 1, 12.5, 45],
                "gpt-5.6-terra": [2.5, 0.25, 3.125, 15, 5, 0.5, 6.25, 22.5],
                "gpt-5.6-luna": [1, 0.1, 1.25, 6, 2, 0.2, 2.5, 9]}
    for name, values in expected.items():
        cutoff = colophon.HISTORICAL_CUTOFFS[name]
        old = history.pick(name, cutoff - 1).entry
        current = history.pick(name, cutoff).entry
        assert [old["per_million"][key] for key in RATES] == values[:4]
        assert [old["long_context"][key] for key in RATES] == values[4:]
        assert old["long_context"]["threshold"] == 272000
        assert current["effective_from"] == colophon.format_rfc3339(cutoff)
        assert colophon.cost_usd(old, input=1000000, cached=0, output=0) == values[4]


def test_manual_multiplier_starts_on_its_date(colophon):
    old = entry(at=None, source="curated")
    manual = entry(source="manual", priority={"multiplier": 3, "max_input_tokens": None})
    history = colophon.PriceHistory([old], [manual])
    assert history.pick(old["model"], stamp(colophon) - 1).entry.get("priority") is None
    assert history.pick(old["model"], stamp(colophon)).entry["priority"] == manual["priority"]


def test_picked_entry_without_long_context_prices_standard_rates(colophon):
    # codexCostUSD 704–726: absent threshold selects standard 2/0.5/7 rates.
    value = entry(source="manual")
    picked = colophon.PriceHistory([], [value]).pick(value["model"], stamp(colophon))
    assert picked.entry == value and "long_context" not in picked.entry
    assert colophon.cost_usd(picked.entry, input=1000000, cached=200000, output=100000) == 2.4


def seed_tool():
    path = Path(__file__).parent / "tools" / "seed_price_history.py"
    assert path.is_file(), "Task16 seed generator is missing"
    return load_launcher(path)


def test_seed_synthetic_exact_expected(colophon, monkeypatch, tmp_path):
    tool = seed_tool()
    # Restrict bundled input to hand-written synthetic fields, so the full JSON
    # oracle stays independent of production resolver/table output.
    monkeypatch.setattr(colophon, "CURATED_BUNDLED", {"gpt-synthetic-bundled": {
        "inputCostPerToken": 0.000002, "outputCostPerToken": 0.000007}})
    monkeypatch.setattr(colophon, "HISTORICAL_CUTOFFS", {})
    snapshot = catalog({"gpt-synthetic-catalog": model("gpt-synthetic-catalog", input=4, output=11)})
    expected = ledger(
        entry(identifier="gpt-synthetic-bundled", at=None, source="curated",
              per_million={"input": 2.0, "cached_input": 2.0, "cache_write": 2.0, "output": 7.0},
              note="seed from models.dev snapshot 2030-01-07"),
        entry(identifier="gpt-synthetic-catalog", at=None, source="curated",
              per_million={"input": 4, "cached_input": 4, "cache_write": 4, "output": 11},
              note="seed from models.dev snapshot 2030-01-07"))
    for value in expected["entries"]:
        del value["recorded_at"]
    actual = tool.build_seed(colophon, snapshot, "2030-01-07")
    assert actual == expected
    history = colophon.PriceHistory(actual["entries"], [])
    assert history.pick("gpt-synthetic-catalog", -999999).entry["per_million"]["input"] == 4
    assert colophon.record_catalog_rates(history, colophon.ModelsDevIndex.from_catalog(snapshot),
        stamp(colophon), {}, stamp(colophon)) == []


def test_seed_full_synthetic_snapshot_no_record_and_priority(colophon):
    tool = seed_tool()
    snapshot = catalog({"gpt-5.6-sol": model("gpt-5.6-sol", input=4, output=20),
                        "gpt-synthetic-catalog": model("gpt-synthetic-catalog", input=4, output=11)})
    actual = tool.build_seed(colophon, snapshot, "2030-01-07")
    assert not colophon.validate_ledger(actual, curated=True).errors
    history = colophon.PriceHistory(actual["entries"], [])
    assert colophon.record_catalog_rates(history, colophon.ModelsDevIndex.from_catalog(snapshot),
        stamp(colophon), {}, stamp(colophon)) == []
    for name, multiplier, cap in [("gpt-5.4", 2, 272000), ("gpt-5.4-mini", 2, 272000),
        ("gpt-5.6-sol", 2, 272000), ("gpt-5.6-terra", 2, 272000), ("gpt-5.6-luna", 2, 272000),
        ("gpt-6-astra", 2, None), ("gpt-5.5", 2.5, 272000)]:
        assert history.pick(name, stamp(colophon)).entry["priority"] == {
            "multiplier": multiplier, "max_input_tokens": cap}
    assert [value["model"] for value in actual["entries"]] == sorted(value["model"] for value in actual["entries"])


def test_seed_historical_exact_expected_and_cutoff_cost(colophon, monkeypatch):
    tool = seed_tool()
    monkeypatch.setattr(colophon, "CURATED_BUNDLED", {"gpt-5.6-sol": {
        "inputCostPerToken": 0.000004, "outputCostPerToken": 0.000020}})
    monkeypatch.setattr(colophon, "HISTORICAL_CUTOFFS", {"gpt-5.6-sol": 1787270400000})
    snapshot = catalog({"gpt-5.6-sol": model("gpt-5.6-sol", input=8, output=9)})
    # Historical table 394–407 supplies the old tuple; 562–620 + 704–726
    # supplies catalog 8/8/8/9 with no bundled caches/threshold in this input.
    expected = ledger(
        entry(identifier="gpt-5.6-sol", at=None, source="curated",
              per_million={"input": 5, "cached_input": 0.5, "cache_write": 6.25, "output": 30},
              long_context={"threshold": 272000, "input": 10, "cached_input": 1, "cache_write": 12.5, "output": 45},
              priority={"multiplier": 2, "max_input_tokens": 272000}, note="seed from models.dev snapshot 2030-01-07"),
        entry(identifier="gpt-5.6-sol", at="2026-08-21T00:00:00Z", source="curated",
              per_million={"input": 8, "cached_input": 8, "cache_write": 8, "output": 9},
              priority={"multiplier": 2, "max_input_tokens": 272000}, note="seed from models.dev snapshot 2030-01-07"))
    for value in expected["entries"]:
        del value["recorded_at"]
    actual = tool.build_seed(colophon, snapshot, "2030-01-07")
    assert actual == expected
    history = colophon.PriceHistory(actual["entries"], [])
    old = history.pick("gpt-5.6-sol", 1787270399999).entry
    new = history.pick("gpt-5.6-sol", 1787270400000).entry
    assert colophon.cost_usd(old, input=100000, cached=0, output=0) == 0.5
    assert colophon.cost_usd(new, input=100000, cached=0, output=0) == pytest.approx(0.8)


@pytest.mark.parametrize("snapshot", [None, [], "synthetic invalid"])
def test_seed_rejects_nonobject_snapshot(colophon, snapshot):
    with pytest.raises(ValueError, match="snapshot must be a JSON object"):
        seed_tool().build_seed(colophon, snapshot, "2030-01-07")


@pytest.mark.parametrize("raw,expected", [
    ("128000.0", 128000), ("1e5", 100000), ("5E+3", 5000), ("-0.0", 0),
    ("1.5", None), ("true", None), ('"1"', None), ("1e19", None),
    ("9223372036854775808", None), ("9223372036854775807.0", None),
    ("9223372036854774784.0", 9223372036854774784),
    ("-9223372036854775808.0", None), ("-9223372036854775809.0", None),
    ("-9223372036854775808", -9223372036854775808),
    ("-9223372036854774784.0", -9223372036854774784),
    ("-9223372036854775807.0", -9223372036854775807),
    ("1.000000000000000000000000000001", 1), ("0.999999999999999999999999999999", 1),
    ("1e-9999", 0), ("1e-100", None), ("1.000000000000001", None),
    ("1.0000000000000001", 1), ("9007199254740993.0", 9007199254740993),
    ("9223372036854774785.0", 9223372036854774785),
    ("9007199254740993.0000000000000000000000000000001", 9007199254740993),
    ("9223372036854774785.00000000000000000000000000001", 9223372036854774785),
    ("9007199254740993.00000000000000000001", None),
    ("9007199254740993.0000000000000000000001", None),
    ("9007199254740993.00000000000000000000001", 9007199254740993),
    ("9223372036854774785.0000000000000000001", None),
    ("9223372036854774785.00000000000000000001", 9223372036854774785),
    ("-9007199254740993.00000000000000000000001", -9007199254740993),
    ("-9223372036854774785.00000000000000000001", -9223372036854774785),
    ("9007199254740993.9999999999999999999999999999999", None),
    ("9007199254740992.1", 9007199254740992),
    ("9007199254740992.01", 9007199254740992),
    ("9007199254740993.1", 9007199254740993),
    ("9007199254740993.01", 9007199254740993),
    ("-9007199254740992.1", -9007199254740992),
    ("-9007199254740992.01", -9007199254740992),
    ("-9007199254740993.1", -9007199254740993),
    ("-9007199254740993.01", -9007199254740993),
    ("9223372036854774785.1", None),
    ("-9223372036854774785.1", None),
])
def test_seed_raw_context_preserves_jsondecoder_acceptance(colophon, raw, expected):
    # ModelsDevPricing.swift ModelsDevLimit.context 291–293; independently
    # hand-expected Int results corroborated by Task13/Task16 pinned-struct
    # probes. Foundation swift-6.2-RELEASE JSONDecoder.swift 1044–1104 checks
    # compacted UInt64 mantissa before division (which discards remainders).
    text = '{"openai":{"models":{"gpt-synthetic-context":{"id":"gpt-synthetic-context",' \
           '"cost":{"input":2,"output":7},"limit":{"context":' + raw + '}}}}}'
    snapshot = seed_tool().load_snapshot(text)
    lookup = colophon.ModelsDevIndex.from_catalog(snapshot).pricing("openai", "gpt-synthetic-context")
    assert (lookup is not None) == (expected is not None)
    if expected is not None:
        context = snapshot["openai"]["models"]["gpt-synthetic-context"]["limit"]["context"]
        assert type(context) is int and context == expected
        # Raw cost values stay in the existing numeric resolver contract.
        assert snapshot["openai"]["models"]["gpt-synthetic-context"]["cost"] == {"input": 2, "output": 7}


def test_seed_cli_deterministic(colophon, tmp_path):
    tool = Path(__file__).parent / "tools" / "seed_price_history.py"
    assert tool.is_file(), "Task16 seed generator is missing"
    snapshot = tmp_path / "synthetic-catalog.json"
    snapshot.write_text(json.dumps(catalog({"gpt-synthetic-history": model(input=2, output=7)})))
    command = [sys.executable, str(tool), "--snapshot", str(snapshot), "--snapshot-date", "2030-01-07"]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert first.stdout == second.stdout
    parsed = json.loads(first.stdout)
    assert first.stdout == json.dumps(parsed, indent=2) + "\n"
    assert not colophon.validate_ledger(parsed, curated=True).errors
