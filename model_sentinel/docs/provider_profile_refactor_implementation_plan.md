# Provider Profile Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all provider-specific knowledge (schema vocabulary, field labels, classification rules, price handling, envelope extraction, structured-change expansion) out of hardcoded module constants and into per-provider `ProviderProfile` objects keyed by the existing-but-unused `ProviderConfig.kind`, with a generic fallback profile — at **full behavior parity for OpenRouter**.

**Architecture:** A new `model_sentinel/provider_profiles.py` module owns a frozen `ProviderProfile` dataclass, a registry keyed by `kind`, and a `GENERIC_PROFILE` fallback. The classification/rendering pipeline (`change_render.py`, `reporting.py`), the fetch layer (`providers.py`), and the normalizer (`normalize.py`) take a required profile parameter instead of consulting module-level OpenRouter constants or two-int price plumbing. The OpenRouter profile is a verbatim relocation of today's constants, so all characterization goldens stay byte-identical.

**Tech Stack:** Python stdlib only (project constraint — no third-party runtime deps). Tests via `pytest`.

## Global Constraints

- **Runtime stays stdlib-only.** No new dependencies, no PEP 723 header changes (this project deliberately is not a uv launcher).
- **Behavior parity is the acceptance bar.** Every existing characterization golden (expected output string) in `tests/` must pass **unmodified**. Test *plumbing* (construction arguments, call signatures) may change mechanically; test *expectations* may not. The one accepted behavioral delta is documented in "Accepted behavioral deltas" below.
- **Public repo.** No secrets, no personal data. Captured provider payloads are public API data but must NOT be committed; schema knowledge goes into `docs/provider_schema_notes.md` as prose/tables only. Test fixtures remain conspicuously synthetic.
- **Historical data is immutable.** `field_changes` rows in SQLite store raw dotted field paths. Nothing in this refactor may rename, rewrite, or migrate stored paths.
- **JSON output contract is untouched.** `_provider_result_json` / `_delta_to_json` (reporting.py:1497–1520) serialize raw `FieldChange` data and never route through labels; profiles must not reach that output.
- **Commit per task**, concise imperative subject lines, per repo commit style.
- **Full test suite (`pytest` from `model_sentinel/`) at entry and exit.** Report any pre-existing failures at entry before proceeding.

## Context: where the coupling lives today (verified against code)

| Location | OpenRouter-specific content |
|---|---|
| `change_render.py:68` | `KNOWN_BOOLEAN_FIELDS` — OpenRouter paths (`top_provider.is_moderated`, `reasoning.*`, `deprecated`) |
| `change_render.py:123` / `:195` | `FIELD_PATH_LABELS` / `FIELD_LEAF_LABELS` — 42-entry registry seeded from OpenRouter history |
| `change_render.py:425` | `_classify_field` — substring category heuristics |
| `change_render.py:460` | `_is_price_amount_field` — "leaf without `token`" heuristic |
| `change_render.py:469` | `_is_count_field` — "leaf with `token`" heuristic |
| `change_render.py:1272` | `classify_change(fc, *, price_multiplier=1, price_divisor=1)` — two-int price plumbing |
| `reporting.py:66` | `_PRICING_OVERRIDE_CONDITION_FIELDS` — OpenRouter conditional-pricing identity (`min_prompt_tokens`, `utc_start`, `utc_end`) |
| `reporting.py:72` | `DEFAULT_REPORT_SHOW_FIELDS` — all OpenRouter paths; duplicated as a string literal in `config.py:260–268` |
| `reporting.py:492` | `_expand_pricing_override_changes` — explicitly OpenRouter (per its docstring) |
| `providers.py:46` | envelope guessing: `("data", "models", "result", "results")` |
| `normalize.py:21–71` | or-chain fallbacks across provider schemas (`pricing.input` or `pricing.prompt` or `cost.input` or `input_token_rate`, …) |
| `models.py:76` | `ProviderScanResult.price_multiplier` / `price_divisor` — the two-int plumbing carried through results |
| `reporting.py:1367` | `render_changes_report(..., provider_pricing: dict[str, tuple[int, int]])` — per-provider threading precedent, with `(1, 1)` fallback at `:1457` |

Captured evidence (2026-07-26, public unauthenticated endpoints — see Task 6 for where this gets documented):

- **Abacus.AI** (`routellm.abacus.ai/v1/models`): flat schema, envelope `{"data": [...]}`, 146 models across `model_type` values `text_generation`/`image_generation`/`audio_generation`/`video_generation`. Prices are dozens of flat `*_rate` fields, **string-typed, per-token for token rates** (`input_token_rate: "0.000003"` ≈ $3/1M) but per-image/per-second/per-clip for media rates, plus one model with `unit: "megapixel"`. Two consequences: (a) today's heuristics misclassify `input_token_rate` as a **count** (leaf contains "token"), so Abacus prices would render as token counts with a `tok` unit; (b) a single per-provider multiplier/divisor cannot be correct for Abacus — the shipped `providers.env.template` `MULTIPLIER=1` for Abacus is wrong for token rates and no single value fixes media rates. Fixing Abacus rendering is **deferred** (no active subscription to validate the authenticated view); this plan only makes the profile interface able to express the fix later.
- **OpenCode Zen** (`opencode.ai/zen/v1/models`): bare OpenAI-style list — `id`/`object`/`created`/`owned_by` only, no pricing. The generic profile handles it with zero additional work.
- **OpenRouter**: envelope `{"data": [...], "total_count", "links"}` — the profile can pin `envelope_keys=("data",)`.

## File structure

- **Create:** `model_sentinel/provider_profiles.py` — `ProviderProfile` dataclass, default heuristic functions, `GENERIC_PROFILE`, `OPENROUTER_PROFILE`, registry, `resolve_profile`. Imports nothing from other `model_sentinel` modules (leaf module; prevents cycles).
- **Create:** `tests/test_provider_profiles.py`
- **Create:** `docs/provider_schema_notes.md`
- **Modify:** `model_sentinel/change_render.py` — constants/heuristics move out; `classify_change` and `resolve_field_label` take a required `profile`.
- **Modify:** `model_sentinel/reporting.py` — profile threading; conditional-pricing identity from profile; show-fields default deduplicated.
- **Modify:** `model_sentinel/models.py` — `ProviderScanResult` carries a `profile` instead of two ints.
- **Modify:** `model_sentinel/providers.py`, `model_sentinel/normalize.py` — envelope keys and normalized-field candidate paths from profile.
- **Modify:** `model_sentinel/cli.py` — resolve and thread profiles; healthcheck advisory.
- **Modify:** `model_sentinel/config.py` — show-fields default imported from one shared location.
- **Modify:** `README.md`, `docs/DESIGN.md`, `providers.env.template` — documentation and template caveat.
- **Modify (mechanically):** `tests/test_change_render.py`, `tests/test_reporting.py`, `tests/test_render_characterization.py`, `tests/test_render_bulk_characterization.py`, `tests/test_render_changes_characterization.py`, `tests/test_cli.py`, `tests/test_normalize.py` — plumbing only, goldens untouched.

## Accepted behavioral deltas (the complete list)

1. **Rows attributed to a provider whose `kind` has no registered profile** (today: only `kind=abacus`, plus any provider deleted from `providers.env` with history still in SQLite) resolve to `GENERIC_PROFILE`: empty label tables (labels fall back to `_prettify_leaf`), no known-boolean set. Today those rows borrow the OpenRouter label tables, which is a false claim (`.prompt` → "Input" for a non-price field, etc.). Prettified labels are more honest, and pricing math for deconfigured providers is `(1, 1)` both before and after. If any existing characterization golden turns out to assert OpenRouter labels for a non-OpenRouter `provider_id`, **stop and present it** — do not silently update the golden.

Everything else — every OpenRouter rendering, every sentinel/precision rule, category order, bulk consolidation, HTML structure — must be byte-identical.

---

### Task 1: `provider_profiles.py` — the profile model, registry, and OpenRouter/generic profiles

**Files:**
- Create: `model_sentinel/provider_profiles.py`
- Create: `tests/test_provider_profiles.py`
- Modify: `model_sentinel/change_render.py` (constants become re-export aliases only — no signature changes yet)

**Interfaces (Produces — later tasks depend on these exact names):**

```python
# provider_profiles.py
from __future__ import annotations
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

# Each inner tuple is a nested key path tried in order; first non-falsy value wins
# (preserving normalize.py's current `or`-chain semantics exactly, including its
# treatment of falsy-but-present values — see Task 5).
PathCandidates = tuple[tuple[str, ...], ...]

@dataclass(frozen=True)
class ProviderProfile:
    kind: str
    # Pricing (bound per provider instance from ProviderConfig via with_pricing()):
    price_multiplier: int = 1
    price_divisor: int = 1
    # Fetch:
    envelope_keys: tuple[str, ...] = ("data", "models", "result", "results")
    # Normalize (candidate paths; keys fixed by Task 5):
    normalized_fields: Mapping[str, PathCandidates] = field(default_factory=dict)
    # Classification & labels:
    field_path_labels: Mapping[str, str] = field(default_factory=dict)
    field_leaf_labels: Mapping[str, str] = field(default_factory=dict)
    known_boolean_fields: frozenset[str] = frozenset()
    categorize: Callable[[str], str] = ...            # default: default_categorize
    is_price_amount_field: Callable[[str], bool] = ...  # default composes default_categorize
    is_count_field: Callable[[str], bool] = ...
    # Structured expansion (conditional pricing):
    pricing_override_condition_fields: tuple[str, ...] = (
        "min_prompt_tokens", "utc_start", "utc_end",
    )
    # Report defaults (global policy for now — see Task 6 deferred notes):
    default_show_fields: tuple[str, ...] = ()
    default_squelch_fields: tuple[str, ...] = ()

    def with_pricing(self, multiplier: int, divisor: int) -> "ProviderProfile":
        return replace(self, price_multiplier=multiplier, price_divisor=divisor)

GENERIC_PROFILE: ProviderProfile   # kind="generic"
OPENROUTER_PROFILE: ProviderProfile  # kind="openrouter"
PROFILE_REGISTRY: dict[str, ProviderProfile]  # {"openrouter": OPENROUTER_PROFILE}

def resolve_profile(kind: str, *, price_multiplier: int = 1, price_divisor: int = 1) -> ProviderProfile: ...
def default_categorize(field_name: str) -> str: ...          # verbatim body of _classify_field
def default_is_price_amount_field(field_name: str) -> bool: ...  # verbatim body of _is_price_amount_field
def default_is_count_field(field_name: str) -> bool: ...     # verbatim body of _is_count_field
```

**Requirements and decisions:**

1. The three `default_*` heuristics are **moved verbatim** from `change_render.py:425–472`. `default_is_price_amount_field` and `default_is_count_field` call `default_categorize` directly (as today). Custom profiles that override `categorize` and want the price/count predicates to follow must supply those too — document this in the module docstring; do not build automatic composition (YAGNI).
2. `OPENROUTER_PROFILE` receives the **verbatim** contents of `FIELD_PATH_LABELS`, `FIELD_LEAF_LABELS`, and `KNOWN_BOOLEAN_FIELDS` from `change_render.py`, `_PRICING_OVERRIDE_CONDITION_FIELDS` and `DEFAULT_REPORT_SHOW_FIELDS`/`DEFAULT_REPORT_SQUELCH_FIELDS` from `reporting.py:66–93`, and `envelope_keys=("data",)`. **Move the extensive design-reasoning comments with the data** — the leaf-key-claims-every-path warning and the path-vs-leaf table rules at `change_render.py:78–121` are load-bearing documentation and must not be orphaned.
3. `GENERIC_PROFILE` keeps today's cross-provider behavior for everything that is *not* the OpenRouter vocabulary: default heuristics, default envelope guessing, default condition fields (today's `_expand_pricing_override_changes` runs for every provider, so the generic profile keeps its condition fields), **empty** label tables, **empty** known-boolean set, empty show/squelch defaults (Task 6 wires the shared defaults).
4. `resolve_profile` looks up `PROFILE_REGISTRY.get(kind)`, falls back to `GENERIC_PROFILE`, then applies `with_pricing`. Lookup is exact on the lowercased `kind` string.
5. Profiles hold dict fields and callables: they are **not hashable** — never use them as dict keys or set members. Note this in the class docstring.
6. In `change_render.py`, replace the moved constant/function definitions with imports from `provider_profiles` aliased to the old names (`FIELD_PATH_LABELS = OPENROUTER_PROFILE.field_path_labels`, `_classify_field = default_categorize`, etc.) so every existing consumer — including `reporting.py`'s imports of `_classify_field` / `_is_price_amount_field` — is untouched in this task. These aliases are transitional; Tasks 2–3 remove them.

**Steps:**

- [ ] **Entry gate:** run `pytest` from `model_sentinel/`; record the result. Expected: all pass (report any pre-existing failure and stop for a decision).
- [ ] Write failing tests in `tests/test_provider_profiles.py` covering: registry resolution (`resolve_profile("openrouter")` is `OPENROUTER_PROFILE` data with bound pricing), generic fallback (`resolve_profile("abacus")` and `resolve_profile("never-heard-of-it")` return generic-kind profiles), `with_pricing` binding (returns a new frozen instance; original unchanged), OpenRouter profile content spot-checks (e.g. `"top_provider.is_moderated" in known_boolean_fields`, `field_leaf_labels["prompt"] == "Input"`, `envelope_keys == ("data",)`), and default-heuristic parity (`default_categorize("pricing.prompt") == "Pricing"`, `default_is_price_amount_field("input_token_rate") is False` — pin today's behavior, including this known limitation).
- [ ] Run: `pytest tests/test_provider_profiles.py -v` — expected: FAIL (module missing).
- [ ] Implement `provider_profiles.py`; rewire `change_render.py` aliases.
- [ ] Run: `pytest tests/test_provider_profiles.py -v` then the full `pytest` — expected: all PASS, zero golden edits.
- [ ] Commit: `Add provider profile model with OpenRouter and generic profiles`

### Task 2: Thread profiles through `change_render.py`

**Files:**
- Modify: `model_sentinel/change_render.py`
- Modify: `tests/test_change_render.py` (plumbing only)

**Interfaces:**
- Consumes: `ProviderProfile`, `GENERIC_PROFILE`, `OPENROUTER_PROFILE` from Task 1.
- Produces (Task 3 relies on these):

```python
def resolve_field_label(field_path: str, profile: ProviderProfile) -> tuple[str, str | None]: ...
def classify_change(field_change: FieldChange, *, profile: ProviderProfile) -> RenderedChange: ...
```

**Requirements and decisions:**

1. `profile` is a **required keyword** with no default. This is deliberate: a default of `GENERIC_PROFILE` would silently strip labels at call sites that forget to pass one, and a default of `OPENROUTER_PROFILE` would re-anchor the module. Forcing the choice at every call site is the point of the refactor.
2. Internal dispatch: label lookup reads `profile.field_path_labels` / `profile.field_leaf_labels`; `_is_boolean_side` reads `profile.known_boolean_fields`; the price/count branch guards call `profile.is_price_amount_field` / `profile.is_count_field`; price normalization reads `profile.price_multiplier` / `profile.price_divisor` (delete the `price_multiplier`/`price_divisor` parameters of `classify_change`, `_classify_price` takes the profile). The classification **cascade order, sentinel rule, precision rules, and every formatter are untouched** — read the module docstring's branch-order warning before editing and preserve it.
3. `_is_boolean_side` currently takes `field_name` and consults the module-level set; it must now receive the profile (or the set) from its callers. Keep the narrowness argument documented at `change_render.py:930–943` intact.
4. Remove the Task 1 transitional aliases for whatever this task rewires (`FIELD_PATH_LABELS`, `FIELD_LEAF_LABELS`, `KNOWN_BOOLEAN_FIELDS`). Keep `_classify_field`/`_is_price_amount_field` aliases alive until Task 3 rewires `reporting.py`.
5. Test updates are **mechanical**: every `classify_change(fc)` becomes `classify_change(fc, profile=OPENROUTER_PROFILE)`; every `classify_change(fc, price_multiplier=m, price_divisor=d)` becomes `classify_change(fc, profile=OPENROUTER_PROFILE.with_pricing(m, d))`; `resolve_field_label(path)` gains `OPENROUTER_PROFILE`. A module-level helper or fixture in the test file is fine. **No expected-output string may change.** ~70 call sites in `tests/test_change_render.py`.

**Steps:**

- [ ] Add one new test first: `classify_change` with `GENERIC_PROFILE` on a `FieldChange("pricing.prompt", "0.000002", "0.000003")` yields `label == "Prompt"` (prettified, not "Input") and `kind == "price"` (heuristics still fire) — pinning the profile boundary itself.
- [ ] Run it — expected: FAIL (signature does not accept `profile`).
- [ ] Implement the threading; update `tests/test_change_render.py` mechanically.
- [ ] Run: `pytest tests/test_change_render.py -v` — expected: all PASS. Then full `pytest` — expected: only failures are in modules not yet rewired **if the transitional aliases were broken**; with aliases intact, expected: all PASS.
- [ ] Verify goldens untouched: `git diff tests/test_change_render.py | grep '^[+-]' | grep -v profile` and inspect — the diff must contain only profile-plumbing lines.
- [ ] Commit: `Thread provider profiles through change classification`

### Task 3: Thread profiles through `models.py`, `reporting.py`, and `cli.py`

**Files:**
- Modify: `model_sentinel/models.py:63–82` (`ProviderScanResult`)
- Modify: `model_sentinel/reporting.py` (all `classify_change` / `_render_smart_change_text` / `_classify_field` / `_is_price_amount_field` call sites; `render_changes_report`; `render_history_report`; conditional-pricing expansion)
- Modify: `model_sentinel/cli.py` (result construction at :239/:295/:324; `provider_pricing` dict at :474; history path)
- Modify: `tests/test_reporting.py`, `tests/test_render_characterization.py`, `tests/test_render_bulk_characterization.py`, `tests/test_render_changes_characterization.py`, `tests/test_cli.py` (plumbing only)

**Interfaces:**
- Consumes: Task 2 signatures.
- Produces:

```python
# models.py — ProviderScanResult: REPLACE
#   price_multiplier: int = 1
#   price_divisor: int = 1
# WITH (required, no default — same rationale as Task 2):
profile: ProviderProfile

# reporting.py
def render_changes_report(..., provider_profiles: dict[str, ProviderProfile] | None = None) -> str: ...
def _render_smart_change_text(fc: FieldChange, profile: ProviderProfile) -> str: ...
```

**Requirements and decisions:**

1. `models.py` importing `provider_profiles` is safe (leaf module, no cycle). `ProviderScanResult.change_count` and the JSON contract are untouched — `_provider_result_json` (reporting.py:1497) never serialized the two ints, so nothing in JSON output changes. Verify no `dataclasses.asdict` call is applied to `ProviderScanResult` itself (today: only `result.baseline` and `FieldChange`, at reporting.py:1504/1519).
2. `cli.py` scan path: `profile = resolve_profile(provider.kind, price_multiplier=provider.price_multiplier, price_divisor=provider.price_divisor)` once per provider, passed into `ProviderScanResult` and into `normalize_models`/`fetch_raw_models` when Task 4/5 land (this task: only the result object).
3. `render_changes_report` / history: replace `provider_pricing: dict[str, tuple[int, int]]` with `provider_profiles: dict[str, ProviderProfile]`; the per-row fallback at reporting.py:1457 becomes `(provider_profiles or {}).get(group_provider_id, GENERIC_PROFILE)` — this is accepted delta #1. `cli.py:474` builds the dict from `loaded.providers` (all configured providers, enabled or not, exactly as today's pricing dict does).
4. Conditional pricing: `_expand_structured_field_change` and `_expand_pricing_override_changes` take the profile and read `profile.pricing_override_condition_fields`; delete `_PRICING_OVERRIDE_CONDITION_FIELDS`. Callers of `_expand_structured_field_changes` thread the profile from the result/row context.
5. Category grouping and price-movement detection: replace direct imports of `_classify_field` / `_is_price_amount_field` with `profile.categorize` / `profile.is_price_amount_field` at each use, threading the profile from the enclosing result/row. Then delete the transitional aliases from `change_render.py` and update its `reporting.py` import list (reporting.py:48–59).
6. `DEFAULT_REPORT_SHOW_FIELDS` / `DEFAULT_REPORT_SQUELCH_FIELDS` stay where they are for this task (Task 6 deduplicates); do not conflate the two changes.
7. Test updates mechanical, same pattern as Task 2 (~15 `ProviderScanResult(...)` constructions, ~58 `price_multiplier=` lines). The shared fixture at `tests/test_reporting.py:50` centralizes most of it. **Goldens untouched**; if any golden asserts OpenRouter labels for a non-OpenRouter `provider_id`, stop and present (accepted-delta rule).

**Steps:**

- [ ] Update `models.py` and chase compile errors outward (`python3 -m compileall model_sentinel/` is a quick loop gate).
- [ ] Rewire `reporting.py` and `cli.py` per requirements 2–5.
- [ ] Update test plumbing.
- [ ] Run: `pytest` (full) — expected: all PASS.
- [ ] Grep gate (no-duplicate-logic exit check): `rg -n "price_multiplier|price_divisor" model_sentinel/ --glob '!provider_profiles.py'` — expected: zero hits outside `config.py` (`ProviderConfig` still carries the raw config values) and `cli.py`'s single `resolve_profile` call.
- [ ] Run a live smoke: `./model-sentinel providers` and, if credentials are present in the shell, `./model-sentinel` (compare-only). Expected: output identical to a pre-refactor run.
- [ ] Commit: `Carry provider profiles through scan results and reporting`

### Task 4: Profile-driven envelope extraction in `providers.py`

**Files:**
- Modify: `model_sentinel/providers.py:16–50`
- Test: extend `tests/test_provider_profiles.py` or the existing fetch tests if present (check `rg -l extract_model_list tests/`)

**Interfaces:**
- Produces: `fetch_raw_models(provider, api_key, profile, *, timeout=30.0)` and `extract_model_list(provider, payload, profile)` — `profile.envelope_keys` replaces the hardcoded `("data", "models", "result", "results")`. A top-level JSON list still bypasses envelope search (current behavior).

**Steps:**

- [ ] Write failing tests: generic profile accepts `{"models": [...]}`; OpenRouter profile (`envelope_keys=("data",)`) accepts `{"data": [...]}` and **rejects** `{"models": [...]}` with `ProviderFetchError` naming the provider label; top-level list accepted under both.
- [ ] Run — expected: FAIL on signature.
- [ ] Implement; update `cli.py` call site to pass the resolved profile.
- [ ] Run: full `pytest` — expected: all PASS.
- [ ] Commit: `Drive model-list envelope extraction from provider profiles`

### Task 5: Profile-driven field mapping in `normalize.py`

**Files:**
- Modify: `model_sentinel/normalize.py`
- Modify: `tests/test_normalize.py` (plumbing; goldens untouched)

**Interfaces:**
- Produces: `normalize_models(provider, raw_models, profile) -> list[NormalizedModel]`.
- The or-chains at `normalize.py:13–71` become `profile.normalized_fields` candidate paths. Fixed key set (these exact strings, one per `NormalizedModel` column they feed):
  `"provider_model_id"`, `"display_name"`, `"description"`, `"model_family"`, `"created_at_provider"`, `"context_window"`, `"max_output_tokens"`, `"input_price"`, `"output_price"`, `"cache_read_price"`, `"cache_write_price"`.
- `GENERIC_PROFILE.normalized_fields` encodes today's chains **verbatim in today's order**, e.g. `"input_price": (("pricing", "input"), ("pricing", "prompt"), ("cost", "input"), ("input_token_rate",))`. `OPENROUTER_PROFILE` uses the same mapping for parity (narrowing it is not worth a golden risk).

**Requirements and decisions (load-bearing):**

1. **Preserve `or`-chain semantics exactly**: the current code takes the first *truthy* candidate (`raw.get(a) or raw.get(b)`), which skips explicit `0`, `""`, `False`, and `null`. A "first present key" implementation would be a behavior change (e.g. an explicit `"context_length": 0` currently falls through to the next candidate). The candidate-path resolver must therefore return the first candidate whose resolved value is **truthy**, mirroring today, and say so in its docstring.
2. Capability detection (`_supports_parameter`, `_detect_modality`, the `reasoning`/`tool_call` fallbacks) stays as-is — shared heuristic code, not profile data. Generalizing it has no consumer yet (YAGNI).
3. Price normalization keeps using `profile.price_multiplier`/`price_divisor` via the existing `_normalize_price` (drop its `provider` parameter in favor of the profile).

**Steps:**

- [ ] Write failing test: a synthetic raw model shaped like today's fixtures normalizes identically through `GENERIC_PROFILE` as it did through the old signature (assert the full `NormalizedModel` equality), plus one test pinning the truthy-skip semantics (`{"context_length": 0, "context_window": 128}` → `context_window == 128`).
- [ ] Run — expected: FAIL on signature.
- [ ] Implement; update `cli.py` call site.
- [ ] Run: full `pytest` — expected: all PASS.
- [ ] Commit: `Drive normalized-field mapping from provider profiles`

### Task 6: Deduplicate report-policy defaults; healthcheck advisory for unregistered kinds

**Files:**
- Modify: `model_sentinel/config.py:258–272`, `model_sentinel/reporting.py:72–93`, `model_sentinel/provider_profiles.py`
- Modify: `model_sentinel/cli.py` (healthcheck command)
- Test: `tests/test_config.py`, `tests/test_cli.py`

**Requirements and decisions:**

1. The default show/squelch field lists exist twice (config.py literal string, reporting.py tuples). Single source: move the canonical tuples to `provider_profiles.py` as the OpenRouter profile's `default_show_fields`/`default_squelch_fields`; `reporting.DEFAULT_REPORT_SHOW_FIELDS` and the `config.py` default string derive from them (`",".join(...)` for the env-default path). Report policy remains **global** (one `ReportDetailPolicy` for the whole run) — per-provider policy is deferred (see Deferred work) because it requires distinguishing "user set the env var" from "defaulted", and has rendering implications in cross-provider reports. Do not implement it now.
2. Healthcheck gains an **advisory** (warn, non-fatal — same severity philosophy as `describe_duplicate_labels`, config.py:182): for each configured provider whose `kind` is not in `PROFILE_REGISTRY`, emit `"Provider '<id>' kind '<kind>' has no registered profile; using the generic profile (labels and price-field detection will be best-effort)."`
3. Test: healthcheck output includes the advisory for a provider with `kind=abacus` and not for `kind=openrouter`; config default round-trips (`load_settings` with no explicit show-fields yields exactly `DEFAULT_REPORT_SHOW_FIELDS`).

**Steps:**

- [ ] Write failing tests per requirement 3.
- [ ] Implement.
- [ ] Run: full `pytest` — expected: all PASS.
- [ ] Commit: `Deduplicate report-policy defaults and warn on unregistered provider kinds`

### Task 7: Documentation

**Files:**
- Create: `docs/provider_schema_notes.md`
- Modify: `docs/DESIGN.md` (new section after §8: "8.4 Provider Profiles"), `README.md` (short subsection under Configuration), `providers.env.template` (Abacus caveat comment)

**Requirements:**

1. `docs/provider_schema_notes.md` records the 2026-07-26 public-endpoint capture: per-provider envelope shape, field inventory summary, value-typing quirks (Abacus string-typed rates, mixed `int`/`str` on the same field across models), the per-token vs per-media-unit pricing finding, and the explicit caveat that the **authenticated** Abacus/OpenCode views are unvalidated. Reproduce the field lists from this plan's Context section; do not commit raw payloads.
2. `DESIGN.md` §8.4 documents: profile purpose, registry-by-`kind` resolution with generic fallback, what is profile data vs shared heuristic, the required-parameter (no-default) decision, the unhashability note, and the rule that raw stored field paths are never rewritten.
3. `providers.env.template`: above the Abacus block, add a comment stating that `MULTIPLIER=1` is known to be wrong for Abacus token rates (observed per-token pricing on the public endpoint, 2026-07-26) and that correct Abacus pricing requires the deferred per-field price rules — pointing at `docs/provider_schema_notes.md`. Do **not** change the value: a single multiplier is wrong in both directions for a provider with mixed units, and silently changing seeded config behavior is worse than documenting the limitation.
4. README: 3–6 lines under Configuration explaining `KIND` now selects a provider profile, unknown kinds fall back to generic with a healthcheck warning.

**Steps:**

- [ ] Write all four documents/edits.
- [ ] **Exit gate:** full `pytest` from `model_sentinel/` — expected: all PASS, every test named. Then `git diff main --stat` review: confirm no test file shows changes beyond plumbing; confirm `git ls-files` includes the two new files.
- [ ] Grep exit check (duplicate-logic rule): `rg -n "min_prompt_tokens|top_provider.is_moderated" model_sentinel/ --glob '!provider_profiles.py'` — expected: no constant definitions outside the profiles module (doc/comment mentions are fine).
- [ ] Commit: `Document provider profiles and captured provider schemas`

---

## Deferred work (explicitly out of scope now; revisit when a paid provider account exists)

- **Abacus profile.** Registered `kind="abacus"` profile with: label tables for `*_rate` fields; `is_price_amount_field` override that *includes* `*_token_rate` and the media-rate families; **per-field price rules** (per-token fields ×1M with `/1M` unit; media rates passed through with their own unit strings — this requires extending the profile's price handling from two ints to a per-field rule lookup, and relaxing `classify_change`'s fixed `unit="/1M"`); `envelope_keys=("data",)`; `normalized_fields` mapping `input_token_rate`/`output_token_rate`/`cached_input_token_rate` directly. Blocked on validating the authenticated payload against the public one and on renewed account access. The captured public schema in `docs/provider_schema_notes.md` is the starting spec.
- **Per-provider report policy defaults** (profile `default_show_fields` actually consulted per provider, with user `settings.env` overrides distinguished from defaults). Needs a second real provider to justify; design constraint recorded in Task 6.
- **OpenCode Zen profile.** Likely nothing needed beyond registering the kind (generic handles the bare list); confirm pricing fields never appear before bothering.
- **`pricing.request` per-request unit.** OpenRouter's per-request price is currently ×1M-normalized and labeled `/1M` like token prices — an existing latent misstatement, fixable by the same per-field price rules the Abacus profile needs. Keep with that effort so the unit mechanism is designed once.

## Self-review notes

- Every coupling row in the Context table maps to a task: labels/booleans/heuristics → 1–2; two-int plumbing and `ProviderScanResult` → 3; condition fields and show-field duplication → 3/6; envelope → 4; or-chains → 5; template/docs → 7.
- Type consistency: `resolve_profile` signature identical in Tasks 1/3; `classify_change(fc, *, profile)` identical in Tasks 2/3; `normalized_fields` key strings fixed in Task 5 and referenced nowhere else.
- Parity risk concentrated in Tasks 2–3; both carry the goldens-untouched gate and a grep-based diff audit.
