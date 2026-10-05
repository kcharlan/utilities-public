"""Pinned upstream rules with hand-derived expectations and synthetic catalogs."""

import copy
import math

import pytest

from catalogs import catalog, model


@pytest.mark.parametrize("raw, expected", [
    ("gpt-5.6", "gpt-5.6-sol"), ("gpt-reserve", "gpt-5.6-luna"),
    ("gpt-daybreak-blue-latest", "gpt-5.6-sol"), ("gpt-daybreak-red-latest", "gpt-5.6-cyber"),
    ("openai/gpt-5.6", "gpt-5.6-sol"), ("gpt-5.4-2026-01-02", "gpt-5.4"),
    ("gpt-synthetic-2026-01-02", "gpt-synthetic-2026-01-02"),
    ("gpt-5.4-20260102", "gpt-5.4-20260102"), ("gpt-5.4-v1:2", "gpt-5.4-v1:2"),
    ("gpt-5.4@20260102", "gpt-5.4@20260102"), ("OPENAI/gpt-5.4", "OPENAI/gpt-5.4"),
    ("\u200bgpt-5.4\u200b", "gpt-5.4"), ("\x1cgpt-5.4\x1c", "\x1cgpt-5.4\x1c"),
    ("openai/ gpt-5.4", " gpt-5.4"),
    ("gpt-5.4-٢٠٢٦-٠١-٠٢", "gpt-5.4"), ("gpt-5.4-2026-01-02\u0301", "gpt-5.4"),
])
def test_normalization(colophon, raw, expected):
    # normalizeCodexModel, CostUsagePricing.swift L487–526.
    assert colophon.normalize_codex_model(raw) == expected


def test_every_bundled_id_is_retained_and_schema_has_no_nil(colophon):
    allowed = {"inputCostPerToken", "outputCostPerToken", "cacheReadInputCostPerToken",
               "cacheWriteInputCostPerToken", "displayLabel", "thresholdTokens",
               "inputCostPerTokenAboveThreshold", "outputCostPerTokenAboveThreshold",
               "cacheReadInputCostPerTokenAboveThreshold", "cacheWriteInputCostPerTokenAboveThreshold"}
    assert len(colophon.CURATED_BUNDLED) == 26
    for key, value in colophon.CURATED_BUNDLED.items():
        assert colophon.normalize_codex_model(key) == key
        assert set(value) <= allowed
        assert {"inputCostPerToken", "outputCostPerToken"} <= set(value)
        assert all(item is not None for item in value.values())


@pytest.mark.parametrize("key, expected", [
    ("gpt-5", {"inputCostPerToken": 1.25e-6, "outputCostPerToken": 1e-5,
                "cacheReadInputCostPerToken": 1.25e-7}),
    ("gpt-5-pro", {"inputCostPerToken": 1.5e-5, "outputCostPerToken": 1.2e-4}),
    ("gpt-5.4", {"inputCostPerToken": 2.5e-6, "outputCostPerToken": 1.5e-5,
                  "cacheReadInputCostPerToken": 2.5e-7, "thresholdTokens": 272000,
                  "inputCostPerTokenAboveThreshold": 5e-6,
                  "outputCostPerTokenAboveThreshold": 2.25e-5,
                  "cacheReadInputCostPerTokenAboveThreshold": 5e-7}),
])
def test_hand_transcribed_spot_table(colophon, key, expected):
    # Direct literals from CostUsagePricing.swift L85–103, L144–152.
    assert colophon.CURATED_BUNDLED[key] == expected


@pytest.mark.parametrize("raw, expected", [
    ("gpt-5.6", [("openai", "gpt-5.6"), ("openai", "gpt-5.6-sol")]),
    ("openai/gpt-5.6", [("openai", "gpt-5.6"), ("openai", "gpt-5.6-sol")]),
    ("OPENAI/gpt-5.4", [("openai", "gpt-5.4")]),
    ("\u200bgpt-synthetic-1\u200b", [("openai", "gpt-synthetic-1")]),
    ("gpt-5.4-2026-01-02", [("openai", "gpt-5.4-2026-01-02"), ("openai", "gpt-5.4")]),
    ("synthetic-other/gpt-5.4", []), ("/gpt-5.4", []), ("openai/", []),
    ("openai//gpt-5.4", []), ("gpt-synthetic/", []), ("", []), ("\u200b", []),
])
def test_targets(colophon, raw, expected):
    # CostUsagePricing L453–485; TargetResolver whole file; A4 OpenAI-only.
    assert colophon.codex_models_dev_pricing_targets(raw) == expected


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("spelling", ["gpt-synthetic-1", "gpt-synthetic-1-2030-01-02",
                                     "gpt-synthetic-1-20300102", "gpt-synthetic-1-v2:3",
                                     "gpt-synthetic-1@20300102", "openai/gpt-synthetic-1",
                                     "\u200bgpt-synthetic-1\u200b",
                                     "gpt-synthetic-1-2030-01-02\u0301"])
def test_catalog_lookup_candidates(colophon, wrapped, spelling):
    index = colophon.ModelsDevIndex.from_catalog(catalog(wrapped=wrapped))
    lookup = index.pricing("\u200bOPENAI\u200b", spelling)
    assert lookup["normalized_model_id"] == "gpt-synthetic-1"
    assert lookup["model_id"] == "gpt-synthetic-1"
    # ModelsDevModel.pricing L237–250: per-million 2 and 7, retained per A4.
    assert lookup["per_million"] == {"input": 2, "output": 7, "cached_input": 0.5, "cache_write": 3}
    assert index.pricing("synthetic-other", "gpt-synthetic-other") is None
    assert index.pricing("openai", "synthetic-other/gpt-synthetic-1") is None


@pytest.mark.parametrize("extension, folds", [
    ("\u0301", True), ("\u200c", True), ("\u200d", True), ("\u093e", True),
    ("\u102b", False), ("\U0001f3fb", True), ("\U000e0061", True),
    ("\u0600", False), ("\ufe0f", True), ("\u20e3", True),
])
def test_suffix_regex_uses_digit_graphemes_not_category_m(colophon, extension, folds):
    # ModelsDevModelIDNormalizer.range L309–317 selects String.range for non-ASCII;
    # synthetic Swift/Foundation probe validates GB9/9a extensions and spacing exception U+102B.
    spelling = "gpt-synthetic-1-2030-01-02" + extension
    index = colophon.ModelsDevIndex.from_catalog(catalog())
    result = index.pricing("openai", spelling)
    assert (result is not None) == folds
    assert index.pricing("openai", "gpt-synthetic-1-" + extension + "2030-01-02") is None
    assert index.pricing("openai", "gpt-synthetic-1-v" + extension + "1:2") is None


@pytest.mark.parametrize("digit", ["²", "½", "Ⅳ", "三", "⑵", "௰", "𝟚"])
def test_non_ascii_suffix_digit_class(colophon, digit):
    # String.range regex uses Character numeric classification on non-ASCII, not ICU Nd.
    spelling = "gpt-synthetic-1-" + digit * 4 + "-" + digit * 2 + "-" + digit * 2
    assert colophon.ModelsDevIndex.from_catalog(catalog()).pricing("openai", spelling) is not None


def test_prepend_character_prevents_suffix_literal_match(colophon):
    spelling = "gpt-synthetic-1\u0600-2030-01-02"
    # GB9b attaches Prepend to the dash; String.range's literal dash cannot match the whole grapheme.
    assert colophon.ModelsDevIndex.from_catalog(catalog()).pricing("openai", spelling) is None


@pytest.mark.parametrize("spelling", ["gpt-synthetic-1@\u030120300102", "gpt-synthetic-1\u0600@20300102"])
def test_non_character_at_sign_does_not_invent_base_candidate(colophon, spelling):
    # candidates L367 firstIndex(of: "@") matches a whole Character, never part of a grapheme.
    assert colophon.ModelsDevIndex.from_catalog(catalog()).pricing("openai", spelling) is None


def test_non_character_slash_does_not_strip_provider_prefix(colophon):
    spelling = "openai/\u0301gpt-5.4"
    # normalizeCodexModel.hasPrefix and targets.firstIndex match complete graphemes.
    assert colophon.normalize_codex_model(spelling) == spelling
    assert colophon.codex_models_dev_pricing_targets(spelling) == [("openai", spelling)]


def test_snapshot_candidate_precedes_undated_base(colophon):
    index = colophon.ModelsDevIndex.from_catalog(catalog({
        "gpt-synthetic-1-20300102": model("gpt-synthetic-1-20300102", input=3, output=8),
        "gpt-synthetic-1": model(input=2, output=7),
    }))
    # candidates L370–374 append converted snapshot before base; provider returns first priceable match.
    assert index.pricing("openai", "gpt-synthetic-1@20300102")["normalized_model_id"] == "gpt-synthetic-1-20300102"


def test_normalizer_preserves_all_source_candidate_branches(colophon):
    # Hand replay of candidates L343–395, including anthropic prefix, last dot,
    # claude @default, and breadth-first version removal. OpenAI index can contain these synthetic IDs.
    assert colophon._models_dev_candidates("anthropic.claude-synthetic-v1:2") == [
        "anthropic.claude-synthetic-v1:2", "claude-synthetic-v1:2", "anthropic.claude-synthetic",
        "claude-synthetic-v1:2@default", "claude-synthetic", "claude-synthetic@default"]


def test_lookup_direct_key_precedes_normalized_model_id(colophon):
    index = colophon.ModelsDevIndex.from_catalog(catalog({
        "gpt-synthetic-1": model("gpt-synthetic-different", input=3, output=8),
        "synthetic-map-key": model(input=2, output=7),
    }))
    # ModelsDevProvider.pricing L185–220: first test dictionary key, then model.id index.
    assert index.pricing("openai", "gpt-synthetic-1")["per_million"]["input"] == 3
    assert index.pricing("openai", " gpt-synthetic-different ")["model_id"] == "gpt-synthetic-different"


def test_unicode_equivalent_lookup_preserves_catalog_identity(colophon):
    index = colophon.ModelsDevIndex.from_catalog(catalog({
        "synthetic-map-key": model(" gpt-synthetic-cafe\u0301 ", input=2, output=7),
        "gpt-synthetic-direct-cafe\u0301": model("gpt-synthetic-unrelated", input=3, output=8),
    }))
    # ModelsDevProvider L212–219: normalized index returns stored spelling;
    # direct-key branch L190–194 returns candidate spelling, including canonically equivalent keys.
    assert index.pricing("openai", "gpt-synthetic-café")["normalized_model_id"] == "gpt-synthetic-cafe\u0301"
    assert index.pricing("openai", "gpt-synthetic-direct-café")["normalized_model_id"] == "gpt-synthetic-direct-café"


@pytest.mark.parametrize("bad", [
    {"id": "gpt-synthetic-1"}, model(input=2), model(output=7), model(),
    model(input=None, output=7), model(input=True, output=7), model(input="2", output=7),
    model(input=2, output=7, cache_read="synthetic-invalid"),
    model(input=2, output=7, context_over_200k=[]),
    model(input=10**1000, output=7),
    {"cost": {"input": 2, "output": 7}},
])
def test_unpriceable_or_malformed_models_are_not_evidence(colophon, bad):
    # ModelsDevProvider decoder L162–169 skips invalid model; isPriceable L230–232.
    index = colophon.ModelsDevIndex.from_catalog(catalog({"gpt-synthetic-1": bad,
        "gpt-synthetic-neighbor": model("gpt-synthetic-neighbor", input=3, output=8)}))
    assert index.pricing("openai", "gpt-synthetic-1") is None
    assert colophon.resolve_rates("gpt-synthetic-1", index) is None
    assert colophon.resolve_rates("gpt-synthetic-neighbor", index)["per_million"]["input"] == 3


def test_zero_rates_are_priceable(colophon):
    index = colophon.ModelsDevIndex.from_catalog(catalog({"gpt-synthetic-1": model(input=0, output=0)}))
    # isPriceable requires presence, not positivity.
    assert colophon.resolve_rates("gpt-synthetic-1", index)["per_million"] == {
        "input": 0, "output": 0, "cached_input": 0, "cache_write": 0}


@pytest.mark.parametrize("cost, standard, long", [
    ({"input": 2, "output": 7}, {"input": 2, "output": 7, "cached_input": 2, "cache_write": 2}, None),
    ({"input": 2, "output": 7, "cache_read": 0.5, "cache_write": 3},
     {"input": 2, "output": 7, "cached_input": 0.5, "cache_write": 3}, None),
    ({"input": 2, "output": 7, "cache_write": 3},
     {"input": 2, "output": 7, "cached_input": 2, "cache_write": 3}, None),
    ({"input": 2, "output": 7, "context_over_200k": {"input": 4, "output": 11}},
     {"input": 2, "output": 7, "cached_input": 2, "cache_write": 2},
     {"threshold": 200000, "input": 4, "output": 11, "cached_input": 4, "cache_write": 4}),
    ({"input": 2, "output": 7, "cache_read": 0.5, "context_over_200k": {}},
     {"input": 2, "output": 7, "cached_input": 0.5, "cache_write": 2},
     {"threshold": 200000, "input": 2, "output": 7, "cached_input": 0.5, "cache_write": 2}),
    ({"input": 2, "output": 7, "cache_read": 0.5, "cache_write": 3,
      "context_over_200k": {"input": 4, "output": 11, "cache_read": 0.25, "cache_write": 6}},
     {"input": 2, "output": 7, "cached_input": 0.5, "cache_write": 3},
     {"threshold": 200000, "input": 4, "output": 11, "cached_input": 0.25, "cache_write": 6}),
])
def test_catalog_resolver_fill_order(colophon, cost, standard, long):
    # resolvedCodexPricing L584–616 then codexCostUSD L704–726; preserve raw nils until long fill.
    index = colophon.ModelsDevIndex.from_catalog(catalog({"gpt-synthetic-1": model(**cost)}))
    assert colophon.resolve_rates("gpt-synthetic-1", index) == {"per_million": standard, "long_context": long}


def test_missing_catalog_preserves_bundled_rates(colophon):
    # Literal 15/120 per million from table L101–103; absent cached/write -> input L704–725.
    assert colophon.resolve_rates("gpt-5-pro", None) == {"per_million": {
        "input": 15, "output": 120, "cached_input": 15, "cache_write": 15}, "long_context": None}
    empty = colophon.ModelsDevIndex.from_catalog(catalog({}))
    assert colophon.resolve_rates("gpt-5.4", empty) == colophon.resolve_rates("gpt-5.4", None)
    assert colophon.resolve_rates("gpt-synthetic-unlisted", empty) is None
    assert colophon.resolve_rates("synthetic-other/gpt-5.4", empty) is None
    assert colophon.resolve_rates("unknown", colophon.ModelsDevIndex.from_catalog(catalog({
        "unknown": model("unknown", input=2, output=7)}))) is None


@pytest.mark.parametrize("context, expected_long", [
    (None, {"threshold": 272000, "input": 5, "output": 22.5, "cached_input": 0.5, "cache_write": 5}),
    ({"input": 4, "output": 11},
     {"threshold": 272000, "input": 4, "output": 11, "cached_input": 4, "cache_write": 4}),
    ({}, {"threshold": 272000, "input": 1.5, "output": 9, "cached_input": 1.5, "cache_write": 1.5}),
])
def test_bundled_threshold_and_catalog_block_precedence(colophon, context, expected_long):
    # L587–605: a catalog block's nil caches use catalog input, never bundled 0.25/0.5.
    cost = {"input": 1.5, "output": 9}
    if context is not None:
        cost["context_over_200k"] = context
    index = colophon.ModelsDevIndex.from_catalog(catalog({"gpt-5.4": model("gpt-5.4", **cost)}))
    assert colophon.resolve_rates("gpt-5.4", index) == {"per_million": {
        "input": 1.5, "output": 9, "cached_input": 0.25, "cache_write": 1.5}, "long_context": expected_long}


def test_tiers_do_not_set_or_override_threshold(colophon):
    index = colophon.ModelsDevIndex.from_catalog(catalog())
    assert colophon.resolve_rates("gpt-synthetic-tiers", index)["long_context"] is None
    models = {"gpt-synthetic-1": model(input=2, output=7, context_over_200k={},
              tiers=[{"threshold": 272000, "input": 99, "output": 99}])}
    index = colophon.ModelsDevIndex.from_catalog(catalog(models))
    # ModelsDevModel L246: context block -> 200000 regardless of tiers.
    assert colophon.resolve_rates("gpt-synthetic-1", index)["long_context"]["threshold"] == 200000


def test_raw_alias_and_dated_catalog_match_precede_normalized_fallback(colophon):
    index = colophon.ModelsDevIndex.from_catalog(catalog({
        "gpt-5.6": model("gpt-5.6", input=2, output=7),
        "gpt-5.6-sol": model("gpt-5.6-sol", input=3, output=8),
        "gpt-5.4-2030-01-02": model("gpt-5.4-2030-01-02", input=11, output=12),
        "gpt-5.4": model("gpt-5.4", input=13, output=14),
    }))
    # targets L480–484 and resolver L578–583 use raw lookup; bundled still keyed by normalized id.
    assert colophon.resolve_rates("gpt-5.6", index)["per_million"]["input"] == 2
    assert colophon.resolve_rates("gpt-5.6-sol", index)["per_million"]["input"] == 3
    assert colophon.resolve_rates("gpt-5.4-2030-01-02", index)["per_million"]["input"] == 11
    fallback = colophon.ModelsDevIndex.from_catalog(catalog({"gpt-5.6-sol": model("gpt-5.6-sol", input=3, output=8)}))
    assert colophon.resolve_rates("gpt-5.6", fallback)["per_million"]["input"] == 3


def test_every_bundled_literal_roundtrips_within_one_ulp(colophon):
    fields = {"inputCostPerToken": "input", "outputCostPerToken": "output",
              "cacheReadInputCostPerToken": "cached_input", "cacheWriteInputCostPerToken": "cache_write"}
    for key, raw in colophon.CURATED_BUNDLED.items():
        resolved = colophon.resolve_rates(key, None)
        for field, rate in fields.items():
            for suffix, section in [("", "per_million"), ("AboveThreshold", "long_context")]:
                if field + suffix in raw:
                    literal = raw[field + suffix]
                    actual = resolved[section][rate] / 1_000_000
                    assert abs(actual - literal) <= math.ulp(literal), (key, field + suffix)


def test_catalog_conversion_reproduces_upstream_division_exactly(colophon):
    values = {"input": 0.12345678901234567, "output": 9.876543210987654,
              "cache_read": 0.1111111111111111, "cache_write": 3.3333333333333335}
    index = colophon.ModelsDevIndex.from_catalog(catalog({"gpt-synthetic-1": model(**values)}))
    rates = colophon.resolve_rates("gpt-synthetic-1", index)["per_million"]
    for source, target in [("input", "input"), ("output", "output"),
                           ("cache_read", "cached_input"), ("cache_write", "cache_write")]:
        assert rates[target] == values[source]
        assert rates[target] / 1_000_000 == values[source] / 1_000_000


@pytest.mark.parametrize("input_tokens, cached, output, expected", [
    (1000, 250, 100, 0.002325),  # 750*2e-6 + 250*0.5e-6 + 100*7e-6.
    (1000, 2000, 100, 0.0012),  # clamp cache: 1000*0.5e-6 + 100*7e-6.
    (1000, -5, 100, 0.0027),  # clamp negative cache: 1000*2e-6 + 100*7e-6.
    (-1000, 250, -100, 0),  # totalInput and output both clamp at zero.
])
def test_cost_clamps_and_uses_reported_output(colophon, input_tokens, cached, output, expected):
    entry = colophon.resolve_rates("gpt-synthetic-1", colophon.ModelsDevIndex.from_catalog(catalog()))
    # codexCostUSD L698–731; output already includes reasoning, no extra component.
    assert colophon.cost_usd(entry, input=input_tokens, cached=cached, output=output) == pytest.approx(expected, rel=0, abs=1e-15)


@pytest.mark.parametrize("input_tokens, expected", [(200000, 0.4007), (200001, 0.801104), (250000, 1.0011)])
def test_catalog_long_context_boundary_and_200k_272k_band(colophon, input_tokens, expected):
    entry = colophon.resolve_rates("gpt-synthetic-long", colophon.ModelsDevIndex.from_catalog(catalog()))
    # <=200000: input*2e-6 + 100*7e-6. Above: input*4e-6 + 100*11e-6 (L706–731).
    assert colophon.cost_usd(entry, input=input_tokens, cached=0, output=100) == pytest.approx(expected, rel=0, abs=1e-12)


@pytest.mark.parametrize("input_tokens, expected", [(250000, 0.625), (272000, 0.68), (272001, 1.360005)])
def test_bundled_threshold_uses_total_input(colophon, input_tokens, expected):
    entry = colophon.resolve_rates("gpt-5.4", None)
    # Bundled 2.5/5 per million at threshold 272000 (table L144–152).
    assert colophon.cost_usd(entry, input=input_tokens, cached=0, output=0) == pytest.approx(expected, rel=0, abs=1e-12)


def test_logged_cache_write_is_display_only(colophon):
    entry = colophon.resolve_rates("gpt-synthetic-1", colophon.ModelsDevIndex.from_catalog(catalog()))
    entry["cache_write"] = 999999  # Display payload count must never enter the billed formula.
    # L730's cacheWrite term is zero in Codex; 1000*2e-6 + 100*7e-6.
    assert colophon.cost_usd(entry, input=1000, cached=0, output=100) == pytest.approx(0.0027, rel=0, abs=1e-15)


def test_formula_keeps_source_operation_order(colophon):
    entry = {"per_million": {"input": 0.123456789, "cached_input": 0.987654321,
                            "cache_write": 3, "output": 9.87654321}, "long_context": None}
    # Exact source order L728–731, including zero write term, no regrouping or total-token multiplication.
    expected = ((123456789 - 9876543) * (0.123456789 / 1000000)
                + 9876543 * (0.987654321 / 1000000) + 0.0 * (3 / 1000000)
                + 987654321 * (9.87654321 / 1000000))
    assert colophon.cost_usd(entry, input=123456789, cached=9876543, output=987654321) == expected


def test_codexbar_reference_a10_hand_calculation(colophon):
    entry = colophon.resolve_rates("gpt-5.4", colophon.ModelsDevIndex.from_catalog(catalog()))
    # 1000*1.5/1e6 + 100*9/1e6 = .0024 per L728–731; CodexBar also computed
    # .0024 for reference a10 (Task 14). This test reads no reference fixture.
    assert colophon.cost_usd(entry, input=1000, cached=0, output=100) == pytest.approx(0.0024, rel=0, abs=1e-12)


@pytest.mark.parametrize("tokens, cap, expected", [
    (272000, 272000, 1.088), (272001, 272000, None), (300000, None, 1.2), (1, 272000, 0.000004),
])
def test_priority_separate_multiplier_and_cap(colophon, tokens, cap, expected):
    entry = colophon.resolve_rates("gpt-synthetic-missing-caches", colophon.ModelsDevIndex.from_catalog(catalog()))
    # codexPriorityCostUSD L659–676: cost (tokens*2e-6) then *2; inclusive cap.
    priority = {"multiplier": 2, "max_input_tokens": cap}
    result = colophon.priority_cost_usd(entry, priority, input=tokens, cached=0, output=0)
    assert result is None if expected is None else result == pytest.approx(expected, rel=0, abs=1e-12)
    assert colophon.priority_cost_usd(entry, None, input=tokens, cached=0, output=0) is None


def test_astra_priority_has_no_cap_and_long_rates(colophon):
    rates = colophon.resolve_rates("gpt-6-astra", None)
    # Table L171–181 and multiplier L684: 300000*20e-6 * 2 = 12.
    assert colophon.priority_cost_usd(rates, {"multiplier": 2, "max_input_tokens": None},
                                      input=300000, cached=0, output=0) == pytest.approx(12, rel=0, abs=1e-12)


@pytest.mark.parametrize("identifier, expected", [
    ("gpt-5.4", 2), ("gpt-5.4-mini", 2), ("gpt-5.6-sol", 2), ("gpt-5.6-terra", 2),
    ("gpt-5.6-luna", 2), ("gpt-6-astra", 2), ("gpt-5.5", 2.5),
    ("gpt-5.4-2030-01-02", 2), ("gpt-5.6", 2), ("gpt-synthetic-unlisted", None),
])
def test_api_fast_multiplier(colophon, identifier, expected):
    # Direct switch literals CostUsagePricing L682–688.
    assert colophon.codex_api_fast_multiplier(identifier) == expected


def test_historical_cutoffs_are_epoch_milliseconds(colophon):
    # Date epoch seconds at CostUsagePricing L396–407 times exactly 1000.
    assert colophon.HISTORICAL_CUTOFFS == {"gpt-5.6-sol": 1787270400000,
                                         "gpt-5.6-terra": 1785369600000,
                                         "gpt-5.6-luna": 1785369600000}


def test_resolver_does_not_mutate_catalog_or_bundled_data(colophon):
    source = catalog()
    before = copy.deepcopy((source, colophon.CURATED_BUNDLED))
    index = colophon.ModelsDevIndex.from_catalog(source)
    result = colophon.resolve_rates("gpt-5.4", index)
    result["per_million"]["input"] = 999
    assert (source, colophon.CURATED_BUNDLED) == before
    assert colophon.resolve_rates("gpt-5.4", index)["per_million"]["input"] == 1.5


@pytest.mark.parametrize("bad_provider", [
    {"id": "synthetic-other"}, {"models": None}, {"models": []}, 42,
    {"id": 42, "models": {}}, {"name": 42, "models": {}},
])
@pytest.mark.parametrize("top_level", [False, True])
def test_invalid_wrapper_provider_abandons_entire_wrapped_map(colophon, bad_provider, top_level):
    # ModelsDevCatalog.init L36–58: one invalid provider fails the whole wrapped
    # dictionary; then decode top-level keys separately, including any usable OpenAI provider.
    source = {"providers": {"openai": catalog()["openai"], "synthetic-other": bad_provider}}
    if top_level:
        source["openai"] = catalog({"gpt-synthetic-1": model(input=3, output=8)})["openai"]
    lookup = colophon.ModelsDevIndex.from_catalog(source).pricing("openai", "gpt-synthetic-1")
    if top_level:
        assert lookup["per_million"]["input"] == 3
    else:
        assert lookup is None


@pytest.mark.parametrize("wrapper", [None, [1], "synthetic-invalid", 42])
def test_non_dictionary_wrapper_falls_back_to_top_level_provider(colophon, wrapper):
    source = {"providers": wrapper, "openai": catalog()["openai"]}
    assert colophon.ModelsDevIndex.from_catalog(source).pricing("openai", "gpt-synthetic-1") is not None


def test_valid_empty_wrapper_suppresses_top_level_provider(colophon):
    # Empty [String: ModelsDevProvider] successfully decodes; no top-level fallback follows.
    source = {"providers": {}, "openai": catalog()["openai"]}
    assert colophon.ModelsDevIndex.from_catalog(source).pricing("openai", "gpt-synthetic-1") is None


def test_invalid_models_do_not_abandon_valid_provider_wrapper(colophon):
    # Provider.init L166–169 skips individual malformed models rather than failing its container.
    source = catalog({"gpt-synthetic-1": model(input=2, output=7),
                      "gpt-synthetic-invalid": {"id": 42}}, wrapped=True)
    source["openai"] = catalog({"gpt-synthetic-1": model(input=3, output=8)})["openai"]
    assert colophon.ModelsDevIndex.from_catalog(source).pricing("openai", "gpt-synthetic-1")["per_million"]["input"] == 2


@pytest.mark.parametrize("context, priceable", [
    (128000.0, True), (1e5, True), (5e3, True), (-0.0, True), (0.0, True),
    (9223372036854774784.0, True), (-9223372036854774784.0, True),
    (2**63 - 1, True), (-(2**63), True), (None, True),
    (True, False), ("1", False), (1.5, False), (1e19, False), (2**63, False),
    (float(2**63), False), (float(-(2**63)), False), (math.inf, False), (math.nan, False),
])
def test_context_uses_jsondecoder_int_number_semantics(colophon, context, priceable):
    # ModelsDevLimit.context (ModelsDevPricing L291–293) uses JSONDecoder Int.
    # Standalone pinned-struct probes accept finite integral floats and exponent
    # spellings, reject fractional/bool/nonfinite/overflow values, and reject
    # floating -2**63 while accepting the integer spelling of -2**63.
    entry = model(input=2, output=7)
    entry["limit"] = {"context": context}
    lookup = colophon.ModelsDevIndex.from_catalog(catalog({"gpt-synthetic-1": entry})).pricing(
        "openai", "gpt-synthetic-1")
    assert (lookup is not None) == priceable


@pytest.mark.parametrize("raw, expected", [
    ("openai/openai/gpt-synthetic-1/", [("openai", "gpt-synthetic-1/")]),
    ("openai/openai/gpt-5/", [("openai", "gpt-5/")]),
    ("openai/ gpt-synthetic-1/", [("openai", "gpt-synthetic-1/")]),
])
def test_normalized_target_fallback_survives_resolver_rejection(colophon, raw, expected):
    # CostUsagePricing L466–474 appends normalized modelID even when the
    # TargetResolver rejected the trailing slash. This is downstream lookup
    # evidence, not permission to price a non-OpenAI provider.
    assert colophon.codex_models_dev_pricing_targets(raw) == expected
    index = colophon.ModelsDevIndex.from_catalog(catalog({
        "gpt-synthetic-1/": model("gpt-synthetic-1/", input=2, output=7),
        "gpt-5/": model("gpt-5/", input=3, output=8),
    }))
    assert colophon.resolve_rates(raw, index) is not None
    assert colophon.resolve_rates("synthetic-other/" + raw.split("/", 1)[1], index) is None
