# CodexBar 0.74.1 Usage Alignment Implementation Plan

Completed historical implementation plan, retained as provenance at cutover
baseline `38d6998eb223f690fc9dc0bde0ba528fcf784449`. The four scoped source
changes are already implemented. Original unchecked steps, failing-first
expectations, branch/commit commands and private acceptance instructions below
describe that historical workflow; they are not a current task list or new
authorization. Source paths are updated to the canonical `colophon/` location
for inspection. Current rules and retained decision identifiers live in
[token rules](token_rules.md) and [architecture](architecture.md); current
build/test instructions are in [development](development.md).

**Goal:** Make native Colophon count and price Codex usage the way CodexBar v0.74.1 does: long-context thresholds, request-ledger validation, per-request pairing of ledger records with `token_count` snapshots, and thread-settings priority.

**Architecture:** All changes stay inside the existing pipeline (parse → scan/cache → corpus → compose → price). Pricing changes live in `src/price/catalog.c` and the embedded seed assets. A new `src/price/request_ledger.c` owns ledger-record validation and mirror pairing. `compose_usage` in `src/price/compose.c` uses it in place of today's per-turn primary/fallback rule. The accounting parser attaches each fallback row's raw snapshot totals. The token stream keeps `turn_context` turn ids and gains an observation for thread priority settings.

**Tech Stack:** C17 (clang, `-Werror`), yyjson 0.13.0, assets embedded by `tools/embed.pl`, the C unit runner in `tests/unit/`, pytest 9.1.1 and Playwright for CLI and browser checks.

## Execution amendments

The original execution used an isolated worktree and local commits, superseding
the historical existing-checkout branch commands below. Tasks ran in order
1 → 2 → 3 → 4, supplying the shared CLI helpers before use and preserving
distinct cache schemas. This records the earlier authorization only.

Source preflight found these corrections; they supersede conflicting steps below:

- Task 1 validates raw keys and Unicode in `context_over_200k.tier` as well as `tiers[].tier`.
- Task 2 also updates both ledger fixtures in `tests/unit/test_compose.c` with required synthetic response, timestamp, output and thread-total fields, retaining every assertion. Ledger and context turn aliases follow upstream's first nonempty `turn_id`, `turnId`, `id`, then the same keys in `info`; cover this with regressions and reuse an existing helper where possible.
- Task 3 resolves pairing in physical event order rather than reserving all whole-file exact matches first. Keep exact matching across boundaries against already observed candidates. A later exact snapshot must not displace an earlier accepted adjacent near match. Add pure-function and compose/CLI regressions with one ledger at `:02`, an equal-sized no-total snapshot at `:03`, and a later equal-sized no-total snapshot at `:02`: the first snapshot pairs and the later exact alias is suppressed, leaving one record unit. See the [source audit](codexbar_0741_alignment_audit.md) for pinned upstream references.
- Task 3 also preserves pending evidence when a repeated snapshot is already owned by a different response (`beginLegacyObservation`, `CostUsageScanner.swift` L428–445). Share mirror-key generation with cross-copy reconciliation and track canonical response ownership. Regressions use two 100/0/10 records at `:02` and `:04`, snapshots at `:03`, repeated `:03`, then `:05`, all snapshots without totals: the repeated first snapshot cannot consume the second pending response, and final usage is 200/0/20 in two record units.

**Spec:** There is no separate spec document. The normative reference is CodexBar tag `v0.74.1`, commit `7c08c0ae783b72040b728757eb85a6cfe4fc2443`; the annotated tag object itself is `2a9026427`. Read upstream files from a local CodexBar clone with `git show v0.74.1:Sources/CodexBarCore/Vendored/CostUsage/<file>`. The investigation that produced this plan is summarized under Background, and each task names the exact upstream lines it ports.

## Background

Native Colophon adapts CodexBar `3bbf6bc48` plus Colophon's earlier approved deviation: a per-response `token_usage_record` takes precedence over snapshot accounting for its turn. A 2026-10-13 investigation compared it with CodexBar v0.74.1 and found:

1. **Not a bug:** a suspected 2× token count came from comparing the page's default 90-day period with CodexBar's month-to-date view. Nothing changes for that.
2. **A, long-context threshold (cost).** v0.74.1 (upstream commit `04b23bed6`) takes the threshold from the models.dev `tiers` entry whose rates match `context_over_200k`. When there is none, it uses the documented OpenAI threshold, then 200,000. Native Colophon uses the bundled `thresholdTokens` when the model has one, otherwise 200,000. That puts these models at 200,000:
   - models with no bundled row: gpt-6.1-sol, gpt-6-sol, gpt-6-luna;
   - models whose bundled row has no threshold: gpt-5.4-pro, gpt-5.5-pro.

   Their curated seed entries also have 200,000 baked in. Requests between 200,000 and 272,000 input tokens on these models are priced at long-context rates by mistake. The public catalog already publishes `{"type":"context","size":272000}` tiers for every OpenAI long-context model.
3. **B, request pairing (tokens).** v0.74.1 counts each request once by pairing each `token_count` snapshot with the `token_usage_record` it mirrors. Colophon drops every snapshot row in any turn that has a ledger record and keeps all others. That undercounts snapshot-only requests inside a turn that has records, and double-counts ledger mirrors whose snapshot row carries no turn.
4. **C, record validation.** v0.74.1 rejects records without `response_id`, without `thread_token_usage` or with non-integral counts. It also requires `session_id` to match the session's own `session_meta.payload.session_id`; for subagents that is the root session, not the thread.
5. **D, thread priority.** v0.74.1 also treats a turn as priority when `thread_settings_applied` set `service_tier` to `priority` before the turn's `task_started`. Colophon uses only the trace database and its remembered priority turns.

A private real-data comparison, kept outside this repository, found:
- **Task 1 alone closes the measured gap.** A was the whole remaining cost difference.
- **B and C changed no totals.** In recent logs every ledger record is followed by its matching snapshot.
- **D changed labelling only.** The affected model has no Fast multiplier.

Tasks 2–4 therefore matter for logs unlike the recent ones (resumed, copied and older logs) and for models with a Fast multiplier. Each can be deferred. Ship Task 1 first. Task 3 requires Task 2. Task 4 is independent of Tasks 2 and 3, apart from the cache-format numbering.

## Remaining differences from v0.74.1

This is the single list of known differences between native Colophon and v0.74.1 that remain after this plan. Upstream code this plan did not examine may add others. Acceptance against CodexBar therefore explains each gap by an entry here, or investigates it.

Each entry names the historical task whose documentation step records it in `docs/architecture.md`. Current inherited decisions are retained locally in [token rules](token_rules.md), with their historical identifiers.

- **Bundled-row keying.** See the "Bundled-row keying" note in Task 1. *Recorded by Task 1.*
- **Ledger-record model** (out of scope). Colophon prices a ledger record with the model that `model_at` in `src/price/compose.c` selects. Upstream's selection is `handleRequestLedger` in `CostUsageScanner.swift` L4332–4336. *Recorded by Task 1.*
- **Overflow guard** (out of scope). Colophon has no guard against a ledger record's running counted total overflowing. Upstream's guard is `CostUsageScanner.swift` L4290–4297. *Recorded by Task 1.*
- **Incremental and turn-performance machinery** (out of scope). Colophon does not port these v0.74.1 parts:
  - `rememberMirroredLegacyPricingKey` (`CostUsageScanner.swift` L4355);
  - `ledgerLegacyPricingKeys` (L361, L4141);
  - turn-performance state (`CostUsageScanner+TurnPerformance.swift`).

  Colophon reparses changed logs from the start. *Recorded by Task 1.*
- **Existing adaptations and approved differences.** Native Colophon inherits the historical Python decisions now retained in the [local adaptation table](token_rules.md#explicit-adaptations-and-approved-differences), except where later alignment rules replace a row. *Recorded by Task 1.*
- **Per-turn primary record rule replaced.** Per-request pairing replaces that table's "Spec §15 difference 1" row. *Recorded by Task 3.*
- **Task 3's deliberate deviations.** See "Deliberate deviations" in Task 3. *Recorded by Task 3.*

## Global Constraints

- **Public repository.**
  - Fixtures, docs and commit messages use only conspicuously synthetic values: `synthetic-…` identifiers and `/synthetic/…` paths.
  - Never copy real session data, counts, costs or home-directory paths into the repository, this plan included.
  - Stage files by explicit path, never a whole directory. This plan file is not staged unless Kevin asks.
  - Before every commit, run `git diff --cached --name-only` and `git diff --cached`. Review both for sensitive data, as `AGENTS.md` requires.
- **Build.** Flags stay `-std=c17 … -Wall -Wextra -Wpedantic -Werror`. Add no dependencies. `qsort` is forbidden (`make check-sort`); use `stable_sort` from `src/util/sort.h`.
- **Validation.**
  - Every task ends with all of these passing: `make test`, `make sanitize`, `make tsan`, `make check-assets`, `make check-sort`.
  - Prepare `.venv` only as `docs/development.md` describes.
  - Name every failure with its output. Never weaken a test to make it pass.
- **Cache format.** Any change to cached `LogRecord`/`TokenStream` content bumps `format[]` in `src/cache/cache.c` (currently `"native:1:1"`).
  - Task 2 sets `"native:1:2"`: new `SessionMeta`/`UsageRecord` fields, and turn ids on `turn_context` observations.
  - Task 4 sets `"native:1:3"`: thread-priority observations.
  - `AccountingRow` and compose state are rebuilt every run and are not cached.
- **Assets.** Every edit to `assets/*.json` updates that file's SHA-256 in `assets/MANIFEST` (`shasum -a 256 assets/<file>`). `make check-assets` must pass, printing its "local asset digests verified" line.
- **Compatibility with prior releases.** Historical Python releases used the same default ledger and a 200,000 catalog fallback. Keep separate runtime homes when running them; retirement does not migrate private state. Shared-home commands must be sequential and concurrent ledger edits remain unsafe.
- **Working directories.**
  - Run every `make` target from `colophon/`.
  - Run every `git` command against this repository from its root; the paths in those commands carry the `colophon/` prefix.
  - The `git show v0.74.1:…` reads of upstream source run in the CodexBar clone.
- **Historical Git workflow (not current instructions).**
  - Use one feature branch, `colophon-native-codexbar-0741`, created from up-to-date `main` in the existing checkout.
  - Commit only when Kevin has asked for commits.
  - Every commit has an imperative subject and a body.
- **Out of scope.**
  - The page's default period.
  - Python Colophon.
  - Every entry marked out of scope in "Remaining differences from v0.74.1".
- **Docs.** Keep these in step with behaviour, in the task that changes it:
  - `docs/architecture.md`: the "Usage accounting rules" section created in Task 1. Each task's documentation step records there every entry of "Remaining differences from v0.74.1" that names that task.
  - `THIRD_PARTY.md`: the CodexBar row.
  - The test counts stated in `docs/development.md` and `tests/README.md`. Replace them with the counts the runs print.

## Review Focus

1. **Resumed sessions.** A snapshot's `total_token_usage` restarts while `thread_token_usage` keeps counting. The adjacent same-turn, same-size pair within 5 s must still pair. Test: `pairing_matches_near_pair_despite_counter_offset` (Task 3).
2. **One session in both `sessions/` and `archived_sessions/`.** Whichever copy is processed first, each response counts once. A snapshot mirrored in one copy is not counted from the other. Test: `compose_mirror_in_one_copy_suppresses_other_copy_both_orders` (Task 3).
3. **Subagent records.** Their `session_id` is the root session, different from `thread_id`. They must be accepted. Test: `ledger_accepts_root_session_id_for_subagent` (Task 2).
4. **Catalog `tiers`.**
   - A malformed `tiers` rejects that catalog model.
   - Well-formed tiers with no rate-matching context tier fall back to the bundled threshold, then 200,000.

   Tests: `catalog_malformed_tiers_reject_model` and `catalog_tier_rate_mismatch_uses_bundled_then_200000` (Task 1).
5. **Two requests in one turn, only one with a ledger record.** Exactly one snapshot pairs; the other still counts.
   - The same-sized case is `pairing_claims_one_snapshot_per_record` (Task 3).
   - The CLI test `test_ledger_mirror_counts_once_and_snapshot_only_request_counts` (Task 3) covers a differently sized snapshot-only request.

---

### Task 1: Long-context threshold from catalog tiers; corrected seeds

**Files:**
- Modify: `src/price/catalog.h` (`CatalogModel`)
- Modify: `src/price/catalog.c`: `decode_model` (≈L43–67), `resolve_rates` (≈L205–262), `raw_model_valid` (≈L331–348)
- Modify: `assets/curated_bundled.json`, `assets/curated_price_history.json`, `assets/MANIFEST`
- Modify: `tests/helpers.py`
- Test: `tests/unit/test_price.c`, `tests/test_cli.py`
- Docs: `docs/architecture.md`, `THIRD_PARTY.md`, `docs/development.md`, `tests/README.md`

`catalog_lookup_json` is called only by a unit test, which discards its output. Leave it unchanged.

**Upstream:**
- `ModelsDevPricing.swift`:
  - L233–262: threshold choice.
  - L265–302: `tiers` and `tier` decoding.
- `CostUsagePricing.swift`:
  - L47–66: `longContextPricing`, `codexLongContextThreshold`.
  - L154–166: bundled table rows.
  - L589: the catalog threshold now takes precedence over the bundled one.

**Interfaces:**
- Produces: `CatalogModel` gains `bool has_context_tier; int64_t context_tier_size;`.
- `resolve_rates(Str raw, ModelsDevIndex *index, PriceEntry *out, bool *found)` keeps its signature. Only `out->threshold` follows the new rule.

**Threshold rule (v0.74.1):**
- **The catalog model has `context_over_200k`:** use the matching tier's size. If there is no matching tier, use the bundled `thresholdTokens`, then 200,000.
- **The catalog model has no `context_over_200k`, or no catalog model is found:** use the bundled threshold when present. This is unchanged.
- **A matching tier** is the first `cost.tiers[]` element that meets all of these:
  - `tier.type == "context"` and `tier.size > 0`;
  - its rates have the same presence and values as `context_over_200k`;
  - `context_over_200k` itself carries no `tier`. Swift's `Equatable` compares that field too, so a `tier` present there prevents every match.
- **Decoding is strict, as in Swift.**
  - A non-null `tiers` must be an array, and each element an object whose rates pass `decode_rates`.
  - Each element's `tier` is absent, null, or an object with a string `type` and an integer `size` that passes `pynum_context_int`.
  - Any violation rejects the whole catalog model, as a malformed `context_over_200k` does today.
  - A `tier` inside `context_over_200k` is decoded by the same rule.

This supersedes the historical rule ignoring catalog `tiers`; its disposition is retained in [token rules](token_rules.md). Current matching-tier behavior is documented in architecture.

- [ ] **Historical Step 0: Create the branch** (record only; do not rerun)

```bash
git switch main
git pull --ff-only
git switch -c colophon-native-codexbar-0741
```

- [ ] **Step 1: Write the failing unit tests** (append to `tests/unit/test_price.c`; it already includes `catalog.h`, `cost.h` and `util/json_number.h`)

```c
static PriceEntry resolve_with_catalog(const char *catalog, const char *model, bool *found) {
    JsonRead read=json_read((Str){catalog,(uint32_t)strlen(catalog)},BYTES,JSON_CONSTANTS_REJECT,"test.price.tier");
    ASSERT_TRUE(read.status==JSON_OK);
    ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(read.doc),&index).code);
    PriceEntry rates;ASSERT_EQ(ERR_OK,resolve_rates((Str){model,(uint32_t)strlen(model)},&index,&rates,found).code);
    models_dev_destroy(&index);json_read_free(&read);return rates;
}
#define SYNTHETIC_LONG "\"context_over_200k\":{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5}"
#define SYNTHETIC_COST "\"input\":2,\"output\":10,\"cache_read\":0.1,\"cache_write\":2.5"
TEST(catalog_context_tier_sets_threshold_when_not_bundled) {
    bool found=false;
    PriceEntry rates=resolve_with_catalog("{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST "," SYNTHETIC_LONG
        ",\"tiers\":[{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":272000}}]}}}}}","gpt-synthetic-tier",&found);
    ASSERT_TRUE(found);ASSERT_TRUE(rates.has_extended);ASSERT_EQ(272000,rates.threshold);
}
TEST(catalog_tier_rate_mismatch_uses_bundled_then_200000) {
    bool found=false;
    const char *mismatch="{\"openai\":{\"models\":{\"%s\":{\"id\":\"%s\",\"cost\":{" SYNTHETIC_COST "," SYNTHETIC_LONG
        ",\"tiers\":[{\"input\":5,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":300000}}]}}}}}";
    char catalog[1024];
    snprintf(catalog,sizeof catalog,mismatch,"gpt-synthetic-tier","gpt-synthetic-tier");
    ASSERT_EQ(200000,resolve_with_catalog(catalog,"gpt-synthetic-tier",&found).threshold);ASSERT_TRUE(found);
    snprintf(catalog,sizeof catalog,mismatch,"gpt-6.1-sol","gpt-6.1-sol");
    ASSERT_EQ(272000,resolve_with_catalog(catalog,"gpt-6.1-sol",&found).threshold);ASSERT_TRUE(found);
}
TEST(catalog_matching_tier_precedes_bundled_threshold) {
    bool found=false;
    PriceEntry rates=resolve_with_catalog("{\"openai\":{\"models\":{\"gpt-5.4\":{\"id\":\"gpt-5.4\",\"cost\":{\"input\":2.5,\"output\":15,\"cache_read\":0.25,"
        "\"context_over_200k\":{\"input\":5,\"output\":22.5,\"cache_read\":0.5},"
        "\"tiers\":[{\"input\":5,\"output\":22.5,\"cache_read\":0.5,\"tier\":{\"type\":\"context\",\"size\":300000}}]}}}}}","gpt-5.4",&found);
    ASSERT_TRUE(found);ASSERT_EQ(300000,rates.threshold);
}
TEST(catalog_malformed_tiers_reject_model) {
    const char *bad[]={
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":\"synthetic\"}}}}}",
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":[{\"tier\":{\"type\":\"context\",\"size\":\"272000\"}}]}}}}}",
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":[{\"tier\":{\"size\":272000}}]}}}}}",
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":[{\"input\":\"4\"}]}}}}}"};
    for(size_t i=0;i<sizeof bad/sizeof *bad;i++) {
        JsonRead read=json_read((Str){bad[i],(uint32_t)strlen(bad[i])},BYTES,JSON_CONSTANTS_REJECT,"test.price.bad_tier");
        ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(read.doc),&index).code);
        CatalogLookup lookup={0};ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("gpt-synthetic-tier"),&lookup).code);
        ASSERT_TRUE(lookup.model==NULL);models_dev_destroy(&index);json_read_free(&read);
    }
}
TEST(curated_seed_has_no_200000_long_context_threshold) {
    JsonRead read=json_read((Str){(const char *)cp_asset_curated_price_history,(uint32_t)cp_asset_curated_price_history_len},STR,JSON_CONSTANTS_REJECT,"test.price.seed");
    ASSERT_TRUE(read.status==JSON_OK);
    yyjson_val *entries=yyjson_obj_get(yyjson_doc_get_root(read.doc),"entries");size_t idx,max;yyjson_val *entry;
    yyjson_arr_foreach(entries,idx,max,entry) {
        yyjson_val *lc=yyjson_obj_get(entry,"long_context");PyNum threshold;
        /* json_read keeps numbers raw (YYJSON_READ_NUMBER_AS_RAW); decode through json_number. */
        if(yyjson_is_obj(lc)){ASSERT_TRUE(json_number(yyjson_obj_get(lc,"threshold"),"test.price.seed",&threshold));
            ASSERT_FALSE(threshold.is_float);ASSERT_EQ(272000,threshold.i);}
    }
    json_read_free(&read);
}
TEST(bundled_new_models_resolve_offline_with_272000_threshold) {
    const char *models[]={"gpt-6.1-sol","gpt-6-sol","gpt-6-luna","gpt-5.4-pro","gpt-5.5-pro"};
    for(size_t i=0;i<sizeof models/sizeof *models;i++){PriceEntry rates;bool found=false;
        ASSERT_EQ(ERR_OK,resolve_rates((Str){models[i],(uint32_t)strlen(models[i])},NULL,&rates,&found).code);
        ASSERT_TRUE(found);ASSERT_TRUE(rates.has_extended);ASSERT_EQ(272000,rates.threshold);}
}
```

If `cp_asset_curated_price_history` is not yet visible in `test_price.c`, add `#include "gen/assets.h"`.

Then write the failing CLI test, which goes through the curated ledger (`tests/helpers.py`, `tests/test_cli.py`).

In `tests/helpers.py`, add these at module level and in `NativeRun`. Make `session()` build its rows with them, so its bytes stay the same:

```python
def row(kind, payload, second, fraction=""):
    return {"type": kind, "timestamp": f"2026-01-02T12:00:{second:02d}{fraction}Z", "payload": payload}

def usage(input_tokens, cached, output, reasoning=0):
    return {"input_tokens": input_tokens, "cached_input_tokens": cached, "output_tokens": output,
            "reasoning_output_tokens": reasoning, "total_tokens": input_tokens + output}

# NativeRun method
    def write_session(self, rows, name="rollout-synthetic.jsonl"):
        directory = self.codex / "sessions" / "2026" / "01" / "02"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text("".join(json.dumps(value) + "\n" for value in rows))
        return path
```

In `tests/test_cli.py`, import `row` and `usage` from `helpers` and add:

```python
def test_long_context_threshold_prices_250k_request_at_standard_rates(native):
    turn = "synthetic-long-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("turn_context", {"model": "gpt-6.1-sol", "turn_id": turn}, 1),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 1),
        row("event_msg", {"type": "token_count", "turn_id": turn, "info": {
            "last_token_usage": usage(250_000, 0, 1_000), "total_token_usage": usage(250_000, 0, 1_000)}}, 3),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    cost = native.payload()["sessions"][0]["own_usage"]["cost_usd"]
    # 250,000 × $2/M + 1,000 × $10/M; the 200K threshold would give 1.015.
    assert cost == pytest.approx(0.51)
```

- [ ] **Step 2: Run the unit and CLI tests and confirm they fail**

Run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'`

Expected: every unit test added in the previous step reports `FAIL`, and the existing tests still pass.

Run: `make test-cli`
Expected:
- `test_long_context_threshold_prices_250k_request_at_standard_rates` fails on its cost assertion: a cost of about 1.015 against pytest's `0.51 ± 5.1e-07`. The curated gpt-6.1-sol entry still says 200,000.
- Every existing CLI test passes, which shows the `session()` refactor kept its bytes.

- [ ] **Step 3: Decode `tiers` and record the matching context tier** (`src/price/catalog.h`, `src/price/catalog.c`)

Add `bool has_context_tier; int64_t context_tier_size;` to `CatalogModel`. In `catalog.c`, add these helpers above `decode_model`:

```c
/* v0.74.1 ModelsDevContextOver200KCost.tier: absent/null, else {type:String,size:Int}. */
static bool decode_tier(yyjson_val *v,const char *prefix,bool *present,Str *type,int64_t *size) {
    *present=false;
    if(!v||yyjson_is_null(v))return true;
    char site[256];snprintf(site,sizeof site,"%s.tier.size",prefix);
    yyjson_val *kind=get(v,"type");PyNum number;
    if(!yyjson_is_obj(v)||!yyjson_is_str(kind)||!json_number(get(v,"size"),site,&number)||!pynum_context_int(number))return false;
    *present=true;*type=string(kind);*size=number.is_float?(int64_t)number.f:number.i;return true;
}
static bool same_rates(const double *a,uint8_t ap,const double *b,uint8_t bp) {
    if(ap!=bp)return false;
    for(size_t i=0;i<4;i++)if((ap&(1u<<i))&&a[i]!=b[i])return false;
    return true;
}
```

Then call them at the end of `decode_model`, after the `context_over_200k` block:

```c
    /* inside decode_model, after the context_over_200k block */
    bool extended_tier=false;
    if(out->has_extended) {
        Str ignored;int64_t unused;
        if(!decode_tier(get(extended,"tier"),site,&extended_tier,&ignored,&unused))return false;
    }
    yyjson_val *tiers=get(cost,"tiers");
    if(tiers&&!yyjson_is_null(tiers)) {
        if(!yyjson_is_arr(tiers))return false;
        size_t i,max;yyjson_val *tier;
        yyjson_arr_foreach(tiers,i,max,tier) {
            char tier_site[256];snprintf(tier_site,sizeof tier_site,"%s.cost.tiers[%zu]",prefix,i);
            double rates[4]={0};uint8_t present=0;bool has_tier;Str type;int64_t size;
            if(!yyjson_is_obj(tier)||!decode_rates(tier,rates,&present,tier_site)||
               !decode_tier(get(tier,"tier"),tier_site,&has_tier,&type,&size))return false;
            if(!out->has_context_tier&&out->has_extended&&!extended_tier&&has_tier&&size>0&&
               str_equal(type,STR_LIT("context"))&&same_rates(rates,present,out->extended,out->extended_present)) {
                out->has_context_tier=true;out->context_tier_size=size;
            }
        }
    }
```

Validation continues after the first match: Swift decodes the whole array, so a later malformed element must still reject the model.

- [ ] **Step 4: Apply the precedence in `resolve_rates`**

Inside `if(m->has_extended)`, replace `if(!threshold){threshold=true;out->threshold=200000;}` with:

```c
            /* v0.74.1: catalog threshold = matching tier ?? documented bundled ?? 200000, and it precedes bundled. */
            if(m->has_context_tier)out->threshold=m->context_tier_size;
            else if(!threshold)out->threshold=200000;
            threshold=true;
```

When the catalog has no `context_over_200k`, the bundled threshold already read from `row` still applies, unchanged.

**Bundled-row keying.** Upstream and Colophon key the documented threshold differently. Upstream reads it by the normalized *catalog* id (`ModelsDevPricing.swift` L246–247, calling `codexLongContextThreshold` at `CostUsagePricing.swift` L65–67). Colophon's bundled `row` is keyed by the normalized *requested* model. The targets resolve to the same key in practice, so keep the single `row` lookup. "Remaining differences from v0.74.1" lists this note.

- [ ] **Step 5: Extend catalog sanitization to `tiers`** (`raw_model_valid`)

After the existing `keys_valid(cost)||keys_valid(extended)` check, iterate `get(cost,"tiers")` when it is an array, and for each element:
- require `keys_valid` for the element and for its `tier` object;
- require `str_utf8_scalar_valid` for a string `tier.type`;
- apply to its rate leaves the same zero-lexeme underflow loop already used for `cost` and `context_over_200k`.

This keeps the cached catalog accepting exactly the models `decode_model` can decode.

- [ ] **Step 6: Update the embedded seeds and manifest**

`assets/curated_bundled.json` (use the existing pretty-printed style and the key order of the `gpt-6-astra` row):
- Replace the `gpt-5.4-pro` and `gpt-5.5-pro` rows with:

  ```json
  "inputCostPerToken": 3e-5, "outputCostPerToken": 1.8e-4, "thresholdTokens": 272000,
  "inputCostPerTokenAboveThreshold": 6e-5, "outputCostPerTokenAboveThreshold": 2.7e-4
  ```

- Insert these rows after `gpt-6-astra`. Values are per token, from v0.74.1 L163–165:

  | Model | input | output | cacheRead | cacheWrite | threshold | inputAbove | outputAbove | cacheReadAbove | cacheWriteAbove |
  |---|---|---|---|---|---|---|---|---|---|
  | `gpt-6.1-sol` | 2e-6 | 1e-5 | 1e-7 | 2.5e-6 | 272000 | 4e-6 | 1.5e-5 | 2e-7 | 5e-6 |
  | `gpt-6-sol` | 2e-6 | 1e-5 | 2e-7 | 2.5e-6 | 272000 | 4e-6 | 1.5e-5 | 4e-7 | 5e-6 |
  | `gpt-6-luna` | 1e-7 | 5e-7 | 1e-8 | 1.25e-7 | 272000 | 2e-7 | 7.5e-7 | 2e-8 | 2.5e-7 |

- Bundled keys are also normalization bases (`curated()` in `src/price/model.c`), so the new rows' dated spellings fold to their base names, as they do upstream. The existing test `price_unicode_date_and_alias_rate_paths_survive_sanitized_owners` covers that folding rule; this plan adds no test of its own for it.

`assets/curated_price_history.json`:
- Change `"threshold": 200000` to `272000` in every entry that has it. `curated_seed_has_no_200000_long_context_threshold` fails until none remain.
- Edit them in place; do not add dated entries. The old value was a mistake, not a price change, so all history must be repriced.
- If only the resolver changed, `record_catalog_rates` (`src/price/ledger.c`) would see a threshold difference through `price_entry_equal`. It would append a catalog entry dated at fetch time and leave earlier usage at 200,000.

`assets/MANIFEST`: update the digests from `shasum -a 256 assets/curated_bundled.json assets/curated_price_history.json`.

- [ ] **Step 7: Run the unit tests and confirm they pass**

Run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'`
Expected: no `FAIL` lines; summary `<N> test(s), 0 failure(s)`.

- [ ] **Step 8: Confirm the CLI regression passes**

Run: `make test-cli PYTEST_ARGS='-k long_context_threshold'`
Expected: PASS. It failed at this task's failing-first run.

- [ ] **Step 9: Documentation**
  - **`docs/architecture.md`:** add a section "Usage accounting rules". It names CodexBar `v0.74.1` (commit `7c08c0ae7`) as the reference for long-context thresholds, then states:
    - the threshold rule;
    - every entry of "Remaining differences from v0.74.1" that names Task 1.

    Later tasks append to this section.
  - **`THIRD_PARTY.md`:** change the CodexBar row to "Adapted from CodexBar at `3bbf6bc48`; long-context thresholds, request-ledger validation and pairing, and thread-settings priority follow `v0.74.1` (commit `7c08c0ae7`). MIT, © 2026 Peter Steinberger". Keep the notice link. Name only the rules that have shipped, extending the row as Tasks 2–4 land.
  - **`docs/development.md`, `tests/README.md`:** update the unit and CLI counts.

- [ ] **Step 10: Full validation**

Run, in order: `make check-sort`, `make check-assets`, `make test`, `make sanitize`, `make tsan`.
Expected: `make check-assets` prints its "local asset digests verified" line; every category passes; no sanitizer reports.

- [ ] **Step 11: Commit** (only if Kevin asked for commits)

```bash
git add colophon/src/price/catalog.h colophon/src/price/catalog.c \
  colophon/assets/curated_bundled.json colophon/assets/curated_price_history.json colophon/assets/MANIFEST \
  colophon/tests/unit/test_price.c colophon/tests/helpers.py colophon/tests/test_cli.py \
  colophon/docs/architecture.md colophon/docs/development.md colophon/tests/README.md colophon/THIRD_PARTY.md
git diff --cached --name-only   # must list exactly the files above
git diff --cached               # review for sensitive data before committing
git commit -m "Take Codex long-context thresholds from catalog context tiers" -m "Port CodexBar v0.74.1 threshold resolution (matching models.dev context tier, then documented threshold, then 200K), add the v0.74.1 bundled rows, and correct the curated seeds that carried a 200K threshold to 272K so earlier usage is repriced."
```

---

### Task 2: Ledger-record validation, ownership and turn fallback

Deferrable: the private comparison found no effect on recent totals.

**Files:**
- Modify: `src/model/logrecord.h` (`UsageRecord`, `SessionMeta`)
- Modify: `src/parse/record.c`: `session_meta` (≈L177), and the `token_usage_record` block (≈L368–398)
- Modify: `src/parse/tokenstream.c`: the `turn_context` branch (≈L530–535)
- Modify: `src/cache/codec.c`: the `SessionMeta` fields (≈L301) and the `usage_records` loop (≈L445–463)
- Modify: `src/cache/cache.c:20`: `"native:1:2"`
- Create: `src/price/request_ledger.h`, `src/price/request_ledger.c`
- Modify: `src/price/compose.c`: the record loop in `compose_usage` (≈L515–585)
- Test: `tests/unit/test_request_ledger.c` (new), `tests/unit/test_codec.c`
- Docs: `docs/architecture.md`, `THIRD_PARTY.md`, `docs/development.md`, `tests/README.md`

**Upstream:** all in `CostUsageScanner.swift`:
- L3855–3877: `codexRequestUsageRecord`.
- L3888–3906: `codexRequestUsage`.
- L4230–4243: the `handleRequestLedger` ownership guard and turn fallback `record.turnID ?? currentTurnID ?? requestLedger.activeTurnID`.
- L4882–4889: `turn_context` sets `activeTurnID`.
- L5032–5040: truncated `turn_context` lines carry no turn id.
- L4549–4592: `requestLedger.sessionID = metadata.requestSessionID ?? metadata.sessionId`.
- L3968: `requestSessionID` is the `session_meta` payload's `session_id`.

**Interfaces:**
- Produces (`src/model/logrecord.h`):
  - `typedef struct { JScalar input, cached_input, output, reasoning; } UsageScalars;`
  - `UsageRecord` gains `JScalar session_id; UsageScalars thread_usage, turn_usage;`.
  - `SessionMeta` gains `Str request_session_id;`.
  - `TOKEN_C` observations now carry `turn_id`.
- Produces (`src/price/request_ledger.h`):

```c
#include "model/logrecord.h"
typedef struct { int64_t input, cached, output, reasoning; } RequestTotals;
typedef enum { LEDGER_ACCEPTED, LEDGER_FOREIGN, LEDGER_INVALID } LedgerVerdict;
typedef struct {
  Str response_id, turn_id, timestamp; /* response trimmed; turn as written (nonempty) or empty */
  MaybeMs timestamp_ms;
  RequestTotals usage, thread_total, turn_total;
  bool has_turn_total, has_reasoning;
} LedgerRecord;
bool request_totals_decode(const UsageScalars *scalars, RequestTotals *out);
bool request_totals_at_least(RequestTotals total, RequestTotals usage);
/* session and request_session are canonical (NFC) identities. */
Err ledger_record_accept(Arena *scratch, const UsageRecord *record, Str session,
                         Str request_session, LedgerRecord *out, LedgerVerdict *verdict);
```

- Produces (`src/price/compose.c`, static): `turns_before(const LogRecord *r, uint64_t line, Str *started, Str *context)` and `request_turn_at(const LogRecord *r, uint64_t line)`. Task 3 reuses them.

**Acceptance rule (v0.74.1).** Apply the checks in order:
1. **`thread_id`:** must be a string whose trimmed value (`token_model_trim`) is non-empty; otherwise INVALID. If its NFC form differs from the session, the verdict is FOREIGN: not counted and not diagnosed.
2. **`session_id`:** an absent value is fine. Otherwise it must be a string with a non-empty trimmed value (else INVALID), and its NFC form must equal `request_session` (else FOREIGN). `request_session` is the trimmed `session_meta` payload `session_id` of the file, falling back to the session id.
3. **`response_id`:** must be a string with a non-empty trimmed value; otherwise INVALID. Records without a response id are no longer counted.
4. **`timestamp`:** must be a string accepted by `time_day_key` or `time_day_key_iso`; otherwise INVALID.
5. **`usage`:** must decode by `request_totals_decode` (below); otherwise INVALID.
6. **`thread_token_usage`:** must decode, and be ≥ `usage` in input, cached and output; otherwise INVALID.
7. **`turn_token_usage`:** kept only if it decodes and is ≥ `usage`; otherwise ignored.

**`request_totals_decode`:**
- `input_tokens` and `output_tokens` are required. `cached_input_tokens` and `reasoning_output_tokens` default to 0 when absent.
- A JSON integer value must satisfy `0 ≤ v` and `(double)v < 2^63`.
- A JSON float value must be finite and integral, with `0 ≤ f < 2^63`.
- Everything else is invalid: null, bool, string, array, object.
- Then require `cached ≤ input`, `reasoning ≤ output`, and no int64 overflow in `input + output`.
- Ledger records now take cached input from `cached_input_tokens` only, as upstream does. Snapshot rows keep `max(cached_input_tokens, cache_read_input_tokens)`.

**Turn rule.** A record without a `turn_id` takes, in this order:
1. the turn of the latest `task_started` (`TOKEN_S`) before it in the same file (upstream `currentTurnID`);
2. if that is absent or has no turn id, the turn id of the latest `turn_context` (`TOKEN_C`) before it (upstream `activeTurnID`).

Truncated `turn_context` lines (`TOKEN_XC`) carry no turn id upstream and leave the active turn unchanged.

- [ ] **Step 1: Write the fixture and failing tests** (create `tests/unit/test_request_ledger.c`; the Makefile compiles every `tests/unit/*.c`)

If Task 4 shipped first, this file already exists. Add to it everything Task 4's "Fallback note" left out, and the tests below. Keep Task 4's tests.

```c
#define _DARWIN_C_SOURCE
#include "corpus/assemble.h"
#include "meta/metadata.h"
#include "parse/record.h"
#include "price/compose.h"
#include "price/request_ledger.h"
#include "runner.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h> /* mkdtemp; macOS declares it here */

typedef struct {
    char dir[1024], paths[2][1100];
    Intern ids;
    LogRecord records[2];
    size_t count;
    Corpus corpus;
    CodexMetadata metadata;
    PriorityTurns priority;
} LedgerFixture;

/* files[i] is a NULL-terminated list of JSONL lines; mtimes[i] orders copies (newest first). */
static void ledger_fixture(LedgerFixture *f, const char *const *const *files, size_t count, const long *mtimes) {
    memset(f, 0, sizeof *f);
    snprintf(f->dir, sizeof f->dir, "%s/synthetic-ledger-XXXXXX", getenv("COLOPHON_HOME"));
    ASSERT_TRUE(mkdtemp(f->dir));
    ASSERT_EQ(ERR_OK, intern_init(&f->ids).code);
    AssemblyRecord input[2];
    ASSERT_TRUE(count >= 1 && count <= 2);
    for (size_t i = 0; i < count; i++) {
        snprintf(f->paths[i], sizeof f->paths[i], "%s/rollout-synthetic-%zu.jsonl", f->dir, i);
        FILE *file = fopen(f->paths[i], "wb");
        ASSERT_TRUE(file);
        for (const char *const *line = files[i]; *line; line++) ASSERT_TRUE(fprintf(file, "%s\n", *line) > 0);
        ASSERT_EQ(0, fclose(file));
        long when = mtimes ? mtimes[i] : 1700000000L;
        struct timeval times[2] = {{when, 0}, {when, 0}};
        ASSERT_EQ(0, utimes(f->paths[i], times));
        struct stat st;
        ASSERT_EQ(0, stat(f->paths[i], &st));
        DiscoveredLog key = {.path = {f->paths[i], (uint32_t)strlen(f->paths[i])}, .size = st.st_size,
                             .mtime_ns = (int64_t)st.st_mtimespec.tv_sec * 1000000000 + st.st_mtimespec.tv_nsec,
                             .stat_ok = true};
        ASSERT_EQ(ERR_OK, record_parse(&key, &f->ids, NULL, &f->records[i]).code);
        input[i] = assembly_record(&f->records[i]);
    }
    f->count = count;
    ASSERT_EQ(ERR_OK, corpus_build(input, count, &f->metadata, 0, &f->ids, &f->corpus).code);
    ASSERT_EQ(ERR_OK, compose_usage(&f->corpus, &f->priority).code);
}
static void ledger_fixture_destroy(LedgerFixture *f) {
    corpus_destroy(&f->corpus);
    priority_destroy(&f->priority);
    metadata_destroy(&f->metadata);
    for (size_t i = 0; i < f->count; i++) record_destroy(&f->records[i]);
    intern_destroy(&f->ids);
}
static SessionModel *only_session(LedgerFixture *f) {
    ASSERT_EQ(1, f->corpus.sessions.size);
    return f->corpus.sessions.first->value;
}
#define META(id, sid) "{\"type\":\"session_meta\",\"timestamp\":\"2030-01-02T12:00:00Z\",\"payload\":{\"id\":\"" id "\",\"session_id\":\"" sid "\",\"cwd\":\"/synthetic/kite\"}}"
#define STARTED(sec, turn) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"type\":\"task_started\",\"turn_id\":\"" turn "\"}}"
#define CONTEXT(sec, turn) "{\"type\":\"turn_context\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"model\":\"gpt-5\",\"turn_id\":\"" turn "\"}}"
#define USAGE(i, c, o) "{\"input_tokens\":" #i ",\"cached_input_tokens\":" #c ",\"output_tokens\":" #o ",\"reasoning_output_tokens\":0}"
/* LEDGER(time, thread, session_id field (with trailing comma or empty), response field, turn field, usage, thread total) */
#define LEDGER(ts, thread, sid, resp, turn, use, total) "{\"type\":\"token_usage_record\",\"timestamp\":\"2030-01-02T12:00:" ts "Z\",\"payload\":{\"thread_id\":\"" thread "\"," sid resp turn "\"usage\":" use ",\"thread_token_usage\":" total "}}"
#define COUNT(ts, last, total) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" ts "Z\",\"payload\":{\"type\":\"token_count\",\"info\":{\"last_token_usage\":" last ",\"total_token_usage\":" total "}}}"

static size_t record_units(SessionModel *s) {
    size_t n = 0;
    for (size_t i = 0; i < s->unit_count; i++) n += str_equal(s->units[i].source, STR_LIT("record"));
    return n;
}
TEST(ledger_rejects_record_without_response_id) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
        LEDGER("02", "synthetic-ledger", "", "", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    ASSERT_EQ(0, record_units(only_session(&f)));
    ledger_fixture_destroy(&f);
}
TEST(ledger_rejects_missing_or_short_thread_total) {
    const char *missing = "{\"type\":\"token_usage_record\",\"timestamp\":\"2030-01-02T12:00:02Z\",\"payload\":{\"thread_id\":\"synthetic-ledger\",\"response_id\":\"synthetic-r1\",\"usage\":" USAGE(100, 0, 10) "}}";
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), missing,
        LEDGER("03", "synthetic-ledger", "", "\"response_id\":\"synthetic-r2\",", "", USAGE(100, 0, 10), USAGE(99, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    ASSERT_EQ(0, record_units(only_session(&f)));
    ledger_fixture_destroy(&f);
}
TEST(ledger_rejects_fractional_or_boolean_counts_and_accepts_integral_float) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"),
        LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", "{\"input_tokens\":7.5,\"output_tokens\":1}", USAGE(100, 0, 10)),
        LEDGER("03", "synthetic-ledger", "", "\"response_id\":\"synthetic-r2\",", "", "{\"input_tokens\":7,\"output_tokens\":true}", USAGE(100, 0, 10)),
        LEDGER("04", "synthetic-ledger", "", "\"response_id\":\"synthetic-r3\",", "", "{\"input_tokens\":7.0,\"output_tokens\":1}", USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_EQ(7, s->units[0].input);
    ledger_fixture_destroy(&f);
}
TEST(ledger_accepts_root_session_id_for_subagent) {
    const char *lines[] = {META("synthetic-child", "synthetic-root"),
        LEDGER("02", "synthetic-child", "\"session_id\":\"synthetic-root\",", "\"response_id\":\"synthetic-r1\",", "", USAGE(100, 0, 10), USAGE(100, 0, 10)),
        LEDGER("03", "synthetic-child", "\"session_id\":\"synthetic-other\",", "\"response_id\":\"synthetic-r2\",", "", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_EQ(100, s->units[0].input);
    ledger_fixture_destroy(&f);
}
TEST(ledger_record_without_turn_inherits_task_started_turn) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), CONTEXT("01", "synthetic-context"), STARTED("01", "synthetic-turn"),
        LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_TRUE(str_equal(s->units[0].turn_id, STR_LIT("synthetic-turn")));
    ledger_fixture_destroy(&f);
}
TEST(ledger_record_without_turn_falls_back_to_turn_context) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), CONTEXT("01", "synthetic-context"),
        LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_TRUE(str_equal(s->units[0].turn_id, STR_LIT("synthetic-context")));
    ledger_fixture_destroy(&f);
}
```

In `tests/unit/test_codec.c`, add `codec_round_trips_ledger_session_totals_and_context_turn`. Follow `compose_borrows_immutable_cached_stream_and_priority_until_destroy` in `test_compose.c`. Build a `LogRecord` with:
- one `UsageRecord` with `session_id`, `thread_usage` and `turn_usage` set;
- `meta.request_session_id = STR_LIT("synthetic-root")`;
- one `TOKEN_C` observation with `turn_id = STR_LIT("synthetic-context")`.

Encode, decode and re-encode it. Assert byte equality, and that the decoded fields match.

- [ ] **Step 2: Confirm the failing state**

Run: `make test-unit`
Expected: compilation fails, because `price/request_ledger.h` and the new `UsageRecord`/`SessionMeta` fields do not exist yet. That is the failing state for this step. The following steps make the tests compile. The run at the end of the "Implement `src/price/request_ledger.c` (validation half)" step then shows the behavioural failures, before `compose_usage` changes.

- [ ] **Step 3: Parse and cache the new fields; keep `turn_context` turn ids**
  - **`src/model/logrecord.h`:** add `UsageScalars`, and the `UsageRecord` and `SessionMeta` fields listed under Interfaces.
  - **`src/parse/record.c`, `session_meta()`:** when `record_get(payload,"session_id")` is a string, `record_intern` its raw text into `meta->request_session_id`.
  - **`src/parse/record.c`, the `token_usage_record` block:**
    - `record_scalar` `payload.session_id` into `row.session_id`.
    - Read `input_tokens`, `cached_input_tokens`, `output_tokens` and `reasoning_output_tokens` from `payload.thread_token_usage` and `payload.turn_token_usage` into `thread_usage` and `turn_usage`.
    - `record_get` returns NULL for a missing object, so a missing object yields `JS_ABSENT` fields.
  - **`src/parse/tokenstream.c`, the `turn_context` branch (`obs.tag = TOKEN_C`):** set `obs.turn_id` with the same id search the `event_msg` branch uses (`turn_id`, `turnId`, `id` in `payload`, then in `info`), via `retain`. The truncated `TOKEN_XC` path stays without a turn id.
  - **`src/cache/codec.c`:**
    - After `ID(r->meta.id);`, add `ID(r->meta.request_session_id);`.
    - In the `usage_records` loop, add `RAW` for `session_id` and for every field of `thread_usage` and `turn_usage`, in a fixed order.
    - The `ARRAY(... UsageRecord, 40)` minimum stays a valid lower bound.
    - Observation `turn_id` is already encoded for every tag.
  - **`src/cache/cache.c:20`:** `static const char format[] = "native:1:2";`.
  - **`src/price/request_ledger.h`:** create it with the Interfaces declarations.

- [ ] **Step 4: Implement `src/price/request_ledger.c` (validation half)**

```c
#include "request_ledger.h"
#include "parse/tokenstream.h"
#include "util/time.h"
#include <math.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
/* CodexBar v0.74.1 codexRequestUsage: NSNumber (not CFBoolean), finite, >= 0,
 * < Double(Int.max), integral. Absent optional keys default to zero; null is invalid. */
static bool request_integer(JScalar v, bool required, int64_t *out) {
  *out = 0;
  if (v.kind == JS_ABSENT) return !required;
  if (v.kind == JS_INT) { *out = v.value.i; return v.value.i >= 0 && (double)v.value.i < 0x1p63; }
  if (v.kind != JS_FLOAT) return false;
  double f = v.value.f;
  if (!isfinite(f) || f < 0 || f >= 0x1p63 || trunc(f) != f) return false;
  *out = (int64_t)f;
  return true;
}
bool request_totals_decode(const UsageScalars *s, RequestTotals *out) {
  int64_t sum;
  return request_integer(s->input, true, &out->input) && request_integer(s->output, true, &out->output) &&
         request_integer(s->cached_input, false, &out->cached) &&
         request_integer(s->reasoning, false, &out->reasoning) &&
         out->cached <= out->input && out->reasoning <= out->output &&
         !__builtin_add_overflow(out->input, out->output, &sum);
}
bool request_totals_at_least(RequestTotals t, RequestTotals u) {
  return t.input >= u.input && t.cached >= u.cached && t.output >= u.output;
}
static Str trimmed(JScalar v) { return v.kind == JS_STRING ? token_model_trim(v.value.s) : (Str){0}; }
Err ledger_record_accept(Arena *a, const UsageRecord *u, Str session, Str request_session,
                         LedgerRecord *out, LedgerVerdict *verdict) {
  *out = (LedgerRecord){0};
  *verdict = LEDGER_INVALID;
  Str thread = trimmed(u->thread_id), identity;
  if (!thread.n) return ERR_SUCCESS;
  TRY(str_nfc(a, thread, "ledger.thread", &identity));
  if (!str_equal(identity, session)) { *verdict = LEDGER_FOREIGN; return ERR_SUCCESS; }
  if (u->session_id.kind != JS_ABSENT) {
    Str sid = trimmed(u->session_id);
    if (!sid.n) return ERR_SUCCESS;
    TRY(str_nfc(a, sid, "ledger.session", &identity));
    if (!str_equal(identity, request_session)) { *verdict = LEDGER_FOREIGN; return ERR_SUCCESS; }
  }
  Str response = trimmed(u->response_id), ts = u->ts.kind == JS_STRING ? u->ts.value.s : (Str){0};
  char day[11];
  int64_t ms;
  if (!response.n || !ts.n ||
      (!time_day_key(ts, "ledger.timestamp", day, &ms) && !time_day_key_iso(ts, "ledger.timestamp", day, &ms)))
    return ERR_SUCCESS;
  UsageScalars usage = {u->input, u->cached_input, u->output, u->reasoning};
  if (!request_totals_decode(&usage, &out->usage) || !request_totals_decode(&u->thread_usage, &out->thread_total) ||
      !request_totals_at_least(out->thread_total, out->usage))
    return ERR_SUCCESS;
  out->has_turn_total = request_totals_decode(&u->turn_usage, &out->turn_total) &&
                        request_totals_at_least(out->turn_total, out->usage);
  out->response_id = response;
  out->timestamp = ts;
  out->timestamp_ms = u->timestamp_unix_ms;
  out->turn_id = u->turn_id.kind == JS_STRING && u->turn_id.value.s.n ? u->turn_id.value.s : (Str){0};
  out->has_reasoning = u->reasoning.kind != JS_ABSENT;
  *verdict = LEDGER_ACCEPTED;
  return ERR_SUCCESS;
}
```

Then run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'`.

Expected:
- the codec test passes;
- every `ledger_*` test reports `FAIL`, because `compose_usage` still uses the old acceptance.

- [ ] **Step 5: Use it in `compose_usage`** (`src/price/compose.c`)

Add these helpers:

```c
/* Latest task_started turn (upstream currentTurnID) and latest turn_context turn
 * (upstream activeTurnID) strictly before `line`. Truncated contexts carry no turn. */
static void turns_before(const LogRecord *r, uint64_t line, Str *started, Str *context) {
  *started = *context = (Str){0};
  for (size_t i = 0; i < r->token_stream.count; i++) {
    const TokenObservation *o = &r->token_stream.observations[i];
    if (o->line >= line) break;
    if (o->tag == TOKEN_S) *started = o->turn_id;
    else if (o->tag == TOKEN_C && o->turn_id.n) *context = o->turn_id;
  }
}
/* handleRequestLedger: record.turnID ?? currentTurnID ?? activeTurnID (record part applied by caller). */
static Str request_turn_at(const LogRecord *r, uint64_t line) {
  Str started, context;
  turns_before(r, line, &started, &context);
  return started.n ? started : context;
}
```

In the per-file record loop (the body after `const UsageRecord *u = ordered[i];`):
1. **Request session, once per file:** take `token_model_trim(r->meta.request_session_id)`, or `s->id` when that is empty, then `canon` it.
2. **Validate:** call `ledger_record_accept(&c->usage_arena, u, session, request_session, &ledger, &verdict)`.
   - FOREIGN: `continue`.
   - INVALID: increment a function-level `size_t rejected`, then `continue`.
3. **De-duplicate** responses on `canon(ledger.response_id)`, which is now always present. Remove the "missing response id is never deduplicated" branch.
4. **Turn:** `ledger.turn_id`, else `request_turn_at(r, u->line)`.
5. **Build the unit from `ledger`:**
   - `.input = ledger.usage.input`, `.cached = ledger.usage.cached`, `.output = ledger.usage.output`;
   - `.reasoning = {ledger.has_reasoning, ledger.usage.reasoning}`;
   - `.cache_write = positive(u->cache_write)`;
   - `.timestamp_ms = ledger.timestamp_ms`; keep `.at_ms = u->at_ms`.
6. **Primary turns:** add the turn to `primary` as today. Task 3 removes that map.
7. **After the session loop:** if `rejected > 0`, call `event_note("usage_record_rejected", "compose.token_usage_record", rejected)`.

- [ ] **Step 6: Confirm the tests pass**

Run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'`
Expected: `<N> test(s), 0 failure(s)`.

- [ ] **Step 7: Documentation**
  - **`docs/architecture.md`:** append the acceptance rule, the turn rule, and the note that ledger cached input is `cached_input_tokens` only.
  - **`THIRD_PARTY.md`:** extend the CodexBar row with request-ledger validation.
  - **`docs/development.md`, `tests/README.md`:** update the unit count. This task adds no CLI test.

- [ ] **Step 8: Full validation.**

Run: `make check-sort`, `make check-assets`, `make test`, `make sanitize`, `make tsan`.
Expected: all pass. The first warm CLI run after the format bump reports every log as parsed; that is expected.

- [ ] **Step 9: Commit** (only if asked; from the repository root)

```bash
git add colophon/src/model/logrecord.h colophon/src/parse/record.c colophon/src/parse/tokenstream.c \
  colophon/src/cache/codec.c colophon/src/cache/cache.c \
  colophon/src/price/request_ledger.h colophon/src/price/request_ledger.c colophon/src/price/compose.c \
  colophon/tests/unit/test_request_ledger.c colophon/tests/unit/test_codec.c \
  colophon/docs/architecture.md colophon/THIRD_PARTY.md colophon/docs/development.md colophon/tests/README.md
git diff --cached --name-only   # must list exactly the files above
git diff --cached               # review for sensitive data before committing
git commit -m "Validate Codex request-ledger records like CodexBar 0.74.1" -m "Accept token_usage_record lines only as CodexBar v0.74.1 does: require a response id, integral usage and a thread total that covers it, and match session_id against the session's own session_meta session_id (the root session for subagents). Records without a turn take the task_started turn, then the turn_context turn. Ledger cached input now comes from cached_input_tokens only. Bump the native cache format to native:1:2."
```

---

### Task 3: Per-request pairing of ledger records with `token_count` snapshots

Deferrable: the private comparison found no effect on recent totals. Requires Task 2.

**Files:**
- Modify: `src/acct/parser.h` (`AccountingRow`), `src/acct/parser.c` (`row()` ≈L90–114)
- Modify: `src/price/request_ledger.h`, `src/price/request_ledger.c` (pairing half)
- Modify: `src/price/compose.c` (`compose_usage` ≈L438–665)
- Test: `tests/unit/test_request_ledger.c`, `tests/test_cli.py`
- Docs: `docs/architecture.md`, `THIRD_PARTY.md`, `docs/development.md`, `tests/README.md`

**Upstream:**
- `CostUsageScanner.swift`:
  - L366–387: `CodexNearMirror`.
  - L389–455: `CodexRequestLedgerState`, `beginLegacyObservation`.
  - L4146–4228: `mirrorKey`, `adjacentMirrorKeys`, `nearMirror`, `observeLegacyMirror`.
  - L4230–4351: `handleRequestLedger`; replay is per file at L4253.
  - L4603–4846: the `handleTokenCount` mirror path, including the counter-history conditions at L4633 and L4704.
  - L4882–4912: `turnContext`, `taskStarted` and `mirrorBoundary` clear pending pairs.
  - L4553–4560: a same-leaf `session_meta` restart clears pending pairs and both counter histories.
- `CostUsageScanner+RequestIdentity.swift` L58–112: `reconcileCodexRequestMirrors`, for both scan orders.

**Interfaces:**
- Consumes (Task 2): `LedgerRecord`, `ledger_record_accept`, `RequestTotals`, `turns_before`, `request_turn_at`.
- Produces: `AccountingRow` gains `TokenTotals raw_last, raw_total;`, the observation's clamped `last_token_usage` and `total_token_usage`.
- Produces, added to `src/price/request_ledger.h`:

```c
typedef enum { PAIR_BOUNDARY, PAIR_RESTART, PAIR_SNAPSHOT, PAIR_LEDGER } PairKind;
typedef struct { PairKind kind; uint64_t line; size_t index; } PairEvent;
typedef struct {
  Str turn;              /* canonical mirror turn; empty when unknown */
  RequestTotals usage;   /* reasoning 0 when absent */
  bool has_total;        /* snapshot: total_token_usage present; ledger: always (thread total) */
  RequestTotals total;
  bool has_turn_total;   /* ledger only */
  RequestTotals turn_total;
  Str timestamp;         /* as written */
  MaybeMs ms;
  bool replay;           /* ledger only: response already seen earlier in this file */
} PairSide;
/* events sorted by line. Sets matched[i] for each snapshot that mirrors a ledger record;
 * each record claims at most one snapshot. */
Err request_pair_file(const PairSide *snapshots, size_t snapshot_count, const PairSide *ledgers,
                      size_t ledger_count, const PairEvent *events, size_t event_count, bool *matched);
```

**Pairing rule (v0.74.1, adapted to compose).** Ledger records always count, subject to Task 2 and session-wide response de-duplication. A snapshot row is dropped only when paired.

- **Mirror turns.**
  - A record uses its unit turn (Task 2).
  - A snapshot uses the row's turn. If that is empty, it uses the latest `turn_context` turn before the row (upstream mirror turn `record.turnID ?? currentTurnID ?? activeTurnID`).
- **Exact match, anywhere in the file.** All of:
  - same mirror turn;
  - same usage, including reasoning;
  - identical timestamp text;
  - the snapshot has no total, or its total equals the record's thread or turn total.
- **Adjacent match.** The pair must be consecutive among request events.
  - Boundaries: every `task_started`, every `turn_context` (truncated ones included), every bare-usage row, and every restart of the same session's `session_meta` (`handleSessionMetadata`, `CostUsageScanner.swift` L4553–4560).
  - An adjacent pair matches when any one of these holds:
    - **Counter alias:** same mirror turn and same usage including reasoning, and the snapshot total equals the record's thread total;
    - **Timestamp alias:** same mirror turn and same usage including reasoning, and identical timestamp text;
    - **Near:** non-empty mirror turn; same input, cached and output (reasoning ignored, as in upstream's near key); an original record; |Δt| ≤ 5,000 ms; and the later side's counter advance is not "intervening";
    - **Delayed:** as Near, but outside the window, with the snapshot after the record, not earlier in time, and the counter advances of the snapshot and the record both "exact".
- **Replay scope.**
  - A record is a replay when its response id appeared earlier in the *same file* (upstream's per-file `responseIDs`). A second copy's record is therefore an original in its own file and can pair with its own snapshot.
  - Counting still de-duplicates responses across all files of the session.
- **Counter advance.** Compare a side's total with the previous total of the same kind in the file:
  - exact when the step equals its own usage;
  - intervening when any component of the step exceeds its own usage;
  - bounded otherwise;
  - unknown when there is no previous total.

  The record history advances on original records only. A restart resets both histories (L4558–4560).
- **Across copies.** Build one session-wide set of mirror keys. A mirror key is session, mirror turn, usage including reasoning, total and timestamp, as in upstream's `mirrorKey`. The set holds:
  - the key of every paired snapshot. A snapshot without `last_token_usage` also has an observation key with empty usage fields (L4617–4618); both its keys join the set when it pairs (L4288, L4818);
  - each accepted record's own exact keys, with the record's timestamp and, in turn, its thread total, no total, and its turn total when present. Upstream remembers these for every record, replays included, except in a file whose fork baseline is unresolved (`rememberMirrors` gated on `!hasUnresolvedForkBaseline`, L4299). Upstream also skips the records its overflow guard rejects (see "Overflow guard" in "Remaining differences from v0.74.1").

  This set is upstream's `mirroredResponses` alias set. An unpaired snapshot row in any file is not counted when its snapshot key, or its observation key when it has one, is in the set (upstream's `reconcileCodexRequestMirrors`, both orders, `+RequestIdentity.swift` L58–112, matching any of a row's `requestMirrorKeys`, L81). The existing `compose_row_key`/`seen` de-duplication of identical rows stays.

**Deliberate deviations.** Each entry states Colophon's rule and cites the upstream code it departs from. The upstream behaviour is not restated here; read the cited lines.
- **Snapshots that produce no row.** Colophon's pairing sees only snapshots that produce a row. Every other snapshot leaves a pending pair intact. Upstream decides when a snapshot clears a pending pair in `handleTokenCount` (`CostUsageScanner.swift` L4603–4632, L4812–4813) and `beginLegacyObservation` (L428–437).
- **Snapshot counter history.** Colophon advances the snapshot counter history when a snapshot ends up unpaired, or paired with the immediately pending original record. Upstream advances it through the `rememberLegacyCounter` calls in `handleTokenCount` (L4633, L4704).
- **Records repeated within a file.** A record whose response id already appeared earlier in the same file pairs only by an exact match, the counter alias or the timestamp alias. Upstream's handling of such records is in `handleRequestLedger` (L4253–4263).

- [ ] **Step 1: Write the failing pure-function tests** (append to `tests/unit/test_request_ledger.c`)

```c
/* Output is one tenth of input on both usage and totals, so counter advances can be exact. */
static PairSide snap(const char *turn, int64_t in, int64_t total_in, const char *ts, int64_t ms) {
  return (PairSide){.turn = turn ? (Str){turn, (uint32_t)strlen(turn)} : (Str){0}, .usage = {in, 0, in / 10, 0},
                    .has_total = true, .total = {total_in, 0, total_in / 10, 0}, .timestamp = {ts, (uint32_t)strlen(ts)},
                    .ms = {true, ms}};
}
static PairSide ledger(const char *turn, int64_t in, int64_t total_in, const char *ts, int64_t ms, bool replay) {
  PairSide side = snap(turn, in, total_in, ts, ms);
  side.replay = replay;
  return side;
}
static bool pair_one(PairSide s, PairSide l, bool snapshot_first, bool boundary_between) {
  PairEvent events[3];
  size_t n = 0;
  PairEvent se = {PAIR_SNAPSHOT, snapshot_first ? 1 : 3, 0}, le = {PAIR_LEDGER, snapshot_first ? 3 : 1, 0};
  events[n++] = snapshot_first ? se : le;
  if (boundary_between) events[n++] = (PairEvent){PAIR_BOUNDARY, 2, 0};
  events[n++] = snapshot_first ? le : se;
  bool matched = false;
  ASSERT_EQ(ERR_OK, request_pair_file(&s, 1, &l, 1, events, n, &matched).code);
  return matched;
}
TEST(pairing_matches_adjacent_snapshot_either_order) {
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, false), false, false));
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "a", 1300), ledger("t", 100, 100, "b", 1000, false), true, false));
}
TEST(pairing_rejects_other_turn_other_usage_or_boundary) {
  ASSERT_FALSE(pair_one(snap("t", 100, 900, "a", 1000), ledger("u", 100, 100, "b", 1300, false), false, false));
  ASSERT_FALSE(pair_one(snap("t", 101, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, false), false, false));
  ASSERT_FALSE(pair_one(snap("t", 100, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, false), false, true));
}
TEST(pairing_counter_alias_matches_without_time_or_turn) {
  ASSERT_TRUE(pair_one(snap(NULL, 100, 400, "a", 1000), ledger(NULL, 100, 400, "b", 90000, false), false, false));
  ASSERT_FALSE(pair_one(snap(NULL, 100, 900, "a", 1000), ledger(NULL, 100, 400, "b", 1100, false), false, false));
}
TEST(pairing_near_match_ignores_reasoning_but_alias_does_not) {
  PairSide l = ledger("t", 100, 100, "b", 1300, false);
  l.usage.reasoning = 5;
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "a", 1000), l, false, false));
  PairSide aliased = ledger(NULL, 100, 400, "b", 90000, false);
  aliased.usage.reasoning = 5;
  ASSERT_FALSE(pair_one(snap(NULL, 100, 400, "a", 1000), aliased, false, false));
}
TEST(pairing_matches_near_pair_despite_counter_offset) {
  ASSERT_TRUE(pair_one(snap("t", 100, 100, "a", 5000), ledger("t", 100, 7100, "b", 1000, false), false, false));
  ASSERT_FALSE(pair_one(snap("t", 100, 100, "a", 6001), ledger("t", 100, 7100, "b", 1000, false), false, false));
}
TEST(pairing_replay_needs_alias_or_same_time) {
  ASSERT_FALSE(pair_one(snap("t", 100, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, true), false, false));
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "same", 1000), ledger("t", 100, 100, "same", 1000, true), false, false));
}
TEST(pairing_intervening_later_side_blocks_near_match) {
  /* S0 sets the snapshot counter at 100; a boundary separates it from the record. S1 then
   * advances the counter by 300 for a 100-token request (intervening) or by exactly 100 (control). */
  const int64_t later_totals[2] = {400, 200};
  const bool expected[2] = {false, true};
  for (size_t i = 0; i < 2; i++) {
    PairSide snaps[2] = {snap("t", 100, 100, "a", 0), snap("t", 100, later_totals[i], "c", 1300)};
    PairSide led = ledger("t", 100, 7000, "b", 1000, false);
    PairEvent events[4] = {{PAIR_SNAPSHOT, 1, 0}, {PAIR_BOUNDARY, 2, 0}, {PAIR_LEDGER, 3, 0}, {PAIR_SNAPSHOT, 4, 1}};
    bool matched[2];
    ASSERT_EQ(ERR_OK, request_pair_file(snaps, 2, &led, 1, events, 4, matched).code);
    ASSERT_FALSE(matched[0]);
    ASSERT_EQ(expected[i], matched[1]);
  }
}
TEST(pairing_delayed_exact_advances_pair_outside_window) {
  /* Ledger counters sit 1000 above snapshot counters, so only the delayed exact rule can pair S1. */
  PairSide snaps[2] = {snap("t", 50, 50, "a", 0), snap("t", 100, 150, "d", 40000)};
  PairSide leds[2] = {ledger("t", 50, 1050, "b", 0, false), ledger("t", 100, 1150, "c", 1000, false)};
  PairEvent events[4] = {{PAIR_LEDGER, 1, 0}, {PAIR_SNAPSHOT, 2, 0}, {PAIR_LEDGER, 3, 1}, {PAIR_SNAPSHOT, 4, 1}};
  bool matched[2];
  ASSERT_EQ(ERR_OK, request_pair_file(snaps, 2, leds, 2, events, 4, matched).code);
  ASSERT_TRUE(matched[0]);
  ASSERT_TRUE(matched[1]);
}
TEST(pairing_claims_one_snapshot_per_record) {
  PairSide snaps[2] = {snap("t", 100, 900, "a", 1100), snap("t", 100, 1000, "c", 1200)};
  PairSide led = ledger("t", 100, 100, "b", 1000, false);
  PairEvent events[3] = {{PAIR_LEDGER, 1, 0}, {PAIR_SNAPSHOT, 2, 0}, {PAIR_SNAPSHOT, 3, 1}};
  bool matched[2];
  ASSERT_EQ(ERR_OK, request_pair_file(snaps, 2, &led, 1, events, 3, matched).code);
  ASSERT_TRUE(matched[0]);
  ASSERT_FALSE(matched[1]);
}
```

Then add compose-level tests that use `ledger_fixture` and the line macros from Task 2:

```c
TEST(compose_counts_snapshot_only_request_in_ledgered_turn) {
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 40, 10), USAGE(100, 40, 10)),
      COUNT("03", USAGE(100, 40, 10), USAGE(100, 40, 10)),
      COUNT("09", USAGE(50, 0, 5), USAGE(150, 40, 15)), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
  SessionModel *s = only_session(&f);
  ASSERT_EQ(2, s->unit_count);           /* the record, plus the snapshot-only request */
  ASSERT_EQ(150, s->own_usage->input);
  ASSERT_EQ(15, s->own_usage->output);
  ledger_fixture_destroy(&f);
}
TEST(compose_turn_context_breaks_adjacent_pair) {
  /* Thread total differs from the snapshot total, so only the near rule could pair them. */
  const char *paired[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(7100, 0, 710)),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *separated[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(7100, 0, 710)),
      CONTEXT("02", "synthetic-turn"), COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *const *first[] = {paired}, *const *second[] = {separated};
  LedgerFixture f; ledger_fixture(&f, first, 1, NULL);
  ASSERT_EQ(1, only_session(&f)->unit_count);
  ledger_fixture_destroy(&f);
  ledger_fixture(&f, second, 1, NULL);
  ASSERT_EQ(2, only_session(&f)->unit_count);
  ledger_fixture_destroy(&f);
}
TEST(compose_mirror_in_one_copy_suppresses_other_copy_both_orders) {
  const char *with_record[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *snapshot_only[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *const *files[] = {with_record, snapshot_only};
  const long orders[2][2] = {{1700000000L, 1700000100L}, {1700000100L, 1700000000L}};
  for (size_t i = 0; i < 2; i++) {
    LedgerFixture f; ledger_fixture(&f, files, 2, orders[i]);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, s->unit_count);
    ASSERT_TRUE(str_equal(s->units[0].source, STR_LIT("record")));
    ledger_fixture_destroy(&f);
  }
}
#define COUNT_TOTAL(ts, total) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" ts "Z\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":" total "}}}"
TEST(compose_observation_key_suppresses_diverged_copy_snapshot) {
  /* Snapshots without last_token_usage. Copy A pairs its snapshot (total 100 at :03) with the record.
   * Copy B saw an extra snapshot first, so its :03 snapshot has delta 40, not 100: its snapshot key
   * differs, but its observation key (turn, no usage, total, timestamp) matches A's. Upstream drops it
   * (reconcileCodexRequestMirrors over requestMirrorKeys) and keeps B's unmatched first snapshot. */
  const char *paired[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)),
      COUNT_TOTAL("03", USAGE(100, 0, 10)), NULL};
  const char *diverged[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      COUNT_TOTAL("02", USAGE(60, 0, 6)), COUNT_TOTAL("03", USAGE(100, 0, 10)), NULL};
  const char *const *files[] = {paired, diverged};
  const long orders[2][2] = {{1700000000L, 1700000100L}, {1700000100L, 1700000000L}};
  for (size_t i = 0; i < 2; i++) {
    LedgerFixture f; ledger_fixture(&f, files, 2, orders[i]);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(2, s->unit_count);   /* the record, plus copy B's first snapshot */
    for (size_t u = 0; u < s->unit_count; u++) ASSERT_TRUE(s->units[u].input != 40);
    ledger_fixture_destroy(&f);
  }
}
TEST(compose_record_keys_suppress_same_time_snapshot_in_other_copy) {
  /* One copy has only the record; the other has only a snapshot carrying the record's exact key
   * (same turn, usage, thread total and timestamp text). Upstream's alias set drops that snapshot. */
  const char *record_only[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *snapshot_only[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      COUNT("02", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *const *files[] = {record_only, snapshot_only};
  const long orders[2][2] = {{1700000000L, 1700000100L}, {1700000100L, 1700000000L}};
  for (size_t i = 0; i < 2; i++) {
    LedgerFixture f; ledger_fixture(&f, files, 2, orders[i]);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, s->unit_count);
    ASSERT_TRUE(str_equal(s->units[0].source, STR_LIT("record")));
    ledger_fixture_destroy(&f);
  }
}
```

Then add the failing CLI test to `tests/test_cli.py`. It uses the `row`/`usage` helpers from Task 1:

```python
def test_ledger_mirror_counts_once_and_snapshot_only_request_counts(native):
    turn = "synthetic-ledger-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "session_id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("turn_context", {"model": "gpt-5", "turn_id": turn}, 1),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 1),
        row("token_usage_record", {"thread_id": SESSION, "session_id": SESSION, "response_id": "synthetic-response-1",
            "turn_id": turn, "usage": usage(100, 40, 10), "thread_token_usage": usage(100, 40, 10)}, 3),
        row("event_msg", {"type": "token_count", "info": {"last_token_usage": usage(100, 40, 10),
            "total_token_usage": usage(100, 40, 10)}}, 3, ".200"),
        row("event_msg", {"type": "token_count", "info": {"last_token_usage": usage(50, 0, 5),
            "total_token_usage": usage(150, 40, 15)}}, 9),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    own = native.payload()["sessions"][0]["own_usage"]
    assert (own["input"], own["cached_input"], own["output"]) == (150, 40, 15)
```

- [ ] **Step 2: Add the declarations and a stub, then confirm failure**

Add the `PairKind`, `PairEvent` and `PairSide` declarations and the `request_pair_file` prototype from Interfaces to `src/price/request_ledger.h`. Add this stub to `request_ledger.c` (with `#include <string.h>`). The `(void)` casts keep `-Wextra -Werror` from rejecting the unused parameters:

```c
Err request_pair_file(const PairSide *snapshots, size_t snapshot_count, const PairSide *ledgers,
                      size_t ledger_count, const PairEvent *events, size_t event_count, bool *matched) {
  (void)snapshots; (void)ledgers; (void)ledger_count; (void)events; (void)event_count;
  if (snapshot_count) memset(matched, 0, snapshot_count * sizeof *matched);
  return ERR_SUCCESS;
}
```

Run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'`

Expected:
- Every `pairing_*` test that asserts a match reports `FAIL`. A test that asserts only non-pairing passes against the stub; the run after the real implementation checks it.
- Every new `compose_*` test reports `FAIL`, except any test whose "Guard checks" entry below says it passes before the change.

Run: `make test-cli PYTEST_ARGS='-k ledger_mirror'`
Expected: fails with `(100, 40, 10) == (150, 40, 15)`. Today's per-turn rule drops every snapshot in the ledgered turn.

**Guard checks.** Run each once the pairing code is in place. Each temporarily removes one piece of code, expects the named test to fail on its unit-count assertion, and then restores the code. Each entry also states the test's result before the change.
- Remove the `omap_get(&mirrored, …)` check in Pass B. Expect `compose_mirror_in_one_copy_suppresses_other_copy_both_orders` to fail. *Before the change it passes:* today's per-turn rule also excludes the other copy's row.
- Skip adding a record's exact keys to `mirrored`. Expect `compose_record_keys_suppress_same_time_snapshot_in_other_copy` to fail. *Before the change it passes,* for the same reason.
- Skip the observation keys (`row_observation_key`). Expect `compose_observation_key_suppresses_diverged_copy_snapshot` to fail. *Before the change it fails:* today's per-turn rule excludes every snapshot in copy B, so the test's unit-count assertion fails.

- [ ] **Step 3: Attach raw snapshot totals to rows** (`src/acct/parser.h`, `src/acct/parser.c`)

Add `TokenTotals raw_last, raw_total;` to `AccountingRow`. In `row()`, add `.raw_last = o->last, .raw_total = o->total` to the initializer. These are the observation's clamped totals. Bare rows keep whatever `o` carries; they are never paired.

- [ ] **Step 4: Implement `request_pair_file`** (`src/price/request_ledger.c`, replacing the stub)

```c
#include "util/omap.h"
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
enum { NEAR_WINDOW_MS = 5000 };
typedef enum { ADVANCE_UNKNOWN, ADVANCE_BOUNDED, ADVANCE_EXACT, ADVANCE_INTERVENING } Advance;
static bool same_counts(RequestTotals a, RequestTotals b) {
  return a.input == b.input && a.cached == b.cached && a.output == b.output;
}
/* nearMirror key: turn, input, cached, output (no reasoning). */
static bool same_near_key(const PairSide *a, const PairSide *b) {
  return str_equal(a->turn, b->turn) && same_counts(a->usage, b->usage);
}
/* mirrorKey usage: also reasoning (reasoning ?? 0). */
static bool same_mirror_usage(const PairSide *a, const PairSide *b) {
  return same_near_key(a, b) && a->usage.reasoning == b->usage.reasoning;
}
/* CodexNearMirror.CounterAdvance relative to the same kind's previous total. */
static Advance advance(bool has_previous, RequestTotals previous, const PairSide *side) {
  if (!has_previous || !side->has_total) return ADVANCE_UNKNOWN;
  int64_t step[3], own[3] = {side->usage.input, side->usage.cached, side->usage.output};
  if (__builtin_sub_overflow(side->total.input, previous.input, &step[0]) ||
      __builtin_sub_overflow(side->total.cached, previous.cached, &step[1]) ||
      __builtin_sub_overflow(side->total.output, previous.output, &step[2]))
    return ADVANCE_UNKNOWN;
  if (step[0] == own[0] && step[1] == own[1] && step[2] == own[2]) return ADVANCE_EXACT;
  for (size_t i = 0; i < 3; i++)
    if (step[i] > own[i]) return ADVANCE_INTERVENING;
  return ADVANCE_BOUNDED;
}
/* handleRequestLedger keys / legacyRowIndices: these carry the timestamp. */
static bool exact_mirror(const PairSide *t, const PairSide *l) {
  if (!same_mirror_usage(t, l) || !str_equal(t->timestamp, l->timestamp)) return false;
  return !t->has_total || same_counts(t->total, l->total) ||
         (l->has_turn_total && same_counts(t->total, l->turn_total));
}
/* adjacentMirrorKeys + CodexNearMirror.matches; only the later side's advance can veto. */
static bool adjacent_mirror(const PairSide *t, Advance ta, const PairSide *l, Advance la, bool snapshot_later) {
  if (same_mirror_usage(t, l) &&
      ((t->has_total && same_counts(t->total, l->total)) || str_equal(t->timestamp, l->timestamp)))
    return true;
  if (!same_near_key(t, l) || !t->turn.n || l->replay || !t->ms.present || !l->ms.present) return false;
  int64_t gap;
  if (__builtin_sub_overflow(t->ms.value, l->ms.value, &gap) || gap == INT64_MIN) return false;
  if (gap < 0) gap = -gap;
  if (gap <= NEAR_WINDOW_MS && (snapshot_later ? ta : la) != ADVANCE_INTERVENING) return true;
  return snapshot_later && t->ms.value >= l->ms.value && ta == ADVANCE_EXACT && la == ADVANCE_EXACT;
}
Err request_pair_file(const PairSide *snapshots, size_t snapshot_count, const PairSide *ledgers,
                      size_t ledger_count, const PairEvent *events, size_t event_count, bool *matched) {
  bool *claimed = calloc(ledger_count ? ledger_count : 1, sizeof *claimed);
  Advance *ta = calloc(snapshot_count ? snapshot_count : 1, sizeof *ta);
  Advance *la = calloc(ledger_count ? ledger_count : 1, sizeof *la);
  size_t *chain = calloc(snapshot_count ? snapshot_count : 1, sizeof *chain);   /* next snapshot+1 with same timestamp */
  size_t *partner = calloc(snapshot_count ? snapshot_count : 1, sizeof *partner); /* paired ledger+1 */
  Omap by_time = {0};
  Err error = ERR_SUCCESS;
  if (!claimed || !ta || !la || !chain || !partner) { error = err_make(ERR_NOMEM, "request pairing allocation"); goto done; }
  if (snapshot_count) memset(matched, 0, snapshot_count * sizeof *matched);
  /* 1. Exact keys anywhere in the file: index snapshots by timestamp text in line order. */
  for (size_t e = 0; e < event_count && !error.code; e++) {
    if (events[e].kind != PAIR_SNAPSHOT) continue;
    size_t t = events[e].index;
    uintptr_t head = (uintptr_t)omap_get(&by_time, snapshots[t].timestamp);
    if (!head) { error = omap_put(&by_time, snapshots[t].timestamp, (void *)(t + 1)); continue; }
    size_t at = head - 1;
    while (chain[at]) at = chain[at] - 1;
    chain[at] = t + 1;
  }
  for (size_t e = 0; e < event_count && !error.code; e++) {
    if (events[e].kind != PAIR_LEDGER) continue;
    size_t l = events[e].index;
    for (uintptr_t next = (uintptr_t)omap_get(&by_time, ledgers[l].timestamp); next && !claimed[l]; next = chain[next - 1])
      if (!matched[next - 1] && exact_mirror(&snapshots[next - 1], &ledgers[l])) {
        matched[next - 1] = claimed[l] = true;
        partner[next - 1] = l + 1;
      }
  }
  /* 2. Adjacent pairs: one pending observation, cleared by every boundary. */
  enum { NONE, SNAPSHOT, LEDGER } pending = NONE;
  size_t pending_index = 0;
  bool has_t = false, has_l = false;
  RequestTotals prev_t = {0}, prev_l = {0};
  for (size_t e = 0; e < event_count && !error.code; e++) {
    const PairEvent *ev = &events[e];
    if (ev->kind == PAIR_BOUNDARY || ev->kind == PAIR_RESTART) {
      pending = NONE;
      if (ev->kind == PAIR_RESTART) has_t = has_l = false;
    } else if (ev->kind == PAIR_SNAPSHOT) {
      size_t t = ev->index;
      bool after_original = pending == LEDGER && !ledgers[pending_index].replay;
      ta[t] = advance(has_t, prev_t, &snapshots[t]);
      if (!matched[t] && pending == LEDGER && !claimed[pending_index] &&
          adjacent_mirror(&snapshots[t], ta[t], &ledgers[pending_index], la[pending_index], true)) {
        matched[t] = claimed[pending_index] = true;
        partner[t] = pending_index + 1;
      }
      /* Approximates rememberLegacyCounter: unpaired, or paired with the pending original. */
      if (snapshots[t].has_total && (!matched[t] || (after_original && partner[t] == pending_index + 1))) {
        prev_t = snapshots[t].total;
        has_t = true;
      }
      pending = matched[t] ? NONE : SNAPSHOT;
      pending_index = t;
    } else {
      size_t l = ev->index;
      la[l] = ledgers[l].replay ? ADVANCE_UNKNOWN : advance(has_l, prev_l, &ledgers[l]);
      if (!ledgers[l].replay) { prev_l = ledgers[l].total; has_l = true; }
      if (!claimed[l] && pending == SNAPSHOT && !matched[pending_index] &&
          adjacent_mirror(&snapshots[pending_index], ta[pending_index], &ledgers[l], la[l], false)) {
        matched[pending_index] = claimed[l] = true;
        partner[pending_index] = l + 1;
      }
      pending = claimed[l] ? NONE : LEDGER;
      pending_index = l;
    }
  }
done:
  omap_destroy(&by_time);
  free(claimed); free(ta); free(la); free(chain); free(partner);
  return error;
}
```

Each timestamp key is put into `by_time` once only, because of the `!head` guard.

- [ ] **Step 5: Replace per-turn selection in `compose_usage`**

Add a mirror-key helper beside `compose_row_key`, in the same style:

```c
/* Upstream mirrorKey(turn, usage, total, timestamp), scoped by session for cross-copy reconciliation.
 * with_usage=false writes the empty usage fields of upstream's observation key for a snapshot
 * without last_token_usage (mirrorKey(usage: nil), L4617–4618). */
static Err mirror_key(Arena *a, Str session, const PairSide *side, bool with_usage, Str *out) {
  JsonWriter w = {0};
  jsonw_bytes(&w, session.p, session.n);
  jsonw_raw(&w, "\x1f");
  jsonw_bytes(&w, side->turn.p, side->turn.n);
  const int64_t usage[] = {side->usage.input, side->usage.cached, side->usage.output, side->usage.reasoning};
  for (size_t i = 0; i < 4; i++) { jsonw_raw(&w, "\x1f"); if (with_usage) jsonw_i64(&w, usage[i]); }
  const int64_t total[] = {side->total.input, side->total.cached, side->total.output};
  for (size_t i = 0; i < 3; i++) { jsonw_raw(&w, "\x1f"); if (side->has_total) jsonw_i64(&w, total[i]); }
  jsonw_raw(&w, "\x1f");
  jsonw_bytes(&w, side->timestamp.p, side->timestamp.n);
  Err e = w.error;
  if (!e.code) e = canon(a, (Str){w.data, (uint32_t)w.length}, out);
  jsonw_free(&w);
  return e;
}
```

Inside the per-session block, remove the `primary` map, add `Omap mirrored = {0}` (destroyed with the other per-session maps), and run Pass A, then Pass B. Per-file arrays (`bool *row_mirrored`, `Str *row_mirror_key`, `Str *row_observation_key`) live in `c->usage_arena`; allocate them with the existing `alloc` helper.

*Pass A, for each file in `s->records` order:*
1. **Ledger records.** Run the Task 2 record loop, keeping a per-file `Omap file_responses`. For every ACCEPTED record, whether counted or not:
   - `replay` is true when `canon(ledger.response_id)` is already in `file_responses`; otherwise add it.
   - Build a `PairSide side`, stored as `ledgers[k]`:
     - `turn = canon(unit turn)`;
     - `usage = ledger.usage`;
     - `has_total = true`, `total = ledger.thread_total`;
     - `has_turn_total`, `turn_total`;
     - `timestamp = ledger.timestamp`, `ms = ledger.timestamp_ms`.
   - Append `PairEvent{PAIR_LEDGER, u->line, k}`.
   - Add the record's exact keys to `mirrored`, unless the file's fork baseline is unresolved (`result->unresolved`). Upstream gates `rememberMirrors` on `!hasUnresolvedForkBaseline`. Here `side` is the `PairSide` just built for this record:

     ```c
     /* rememberMirrors(keys, responseID): the record's own keys alias its response (L4244–4250, L4299). */
     PairSide alias = side;                                   /* variant 0: thread total */
     for (int variant = 0; variant < 3 && !error.code && !result->unresolved; variant++) {
       if (variant == 1) alias.has_total = false;             /* variant 1: no total */
       if (variant == 2) {                                    /* variant 2: turn total */
         if (!side.has_turn_total) break;
         alias.has_total = true;
         alias.total = side.turn_total;
       }
       Str key;
       error = mirror_key(&c->usage_arena, session, &alias, true, &key);
       if (!error.code) error = omap_put(&mirrored, key, (void *)1);
     }
     if (error.code) goto session_done;
     ```
   - Only records whose response is new to the session-wide `responses` map append a `"record"` unit, as today.
2. **Snapshot rows.** For each non-bare row `i` in `result->rows`:
   - Mirror turn: `row->turn_id`. If that is empty, call `turns_before(r, row->line, &started, &context)` and use `context`. Then `canon`.
   - `usage`: from `row->raw_last` when present, with `reasoning = raw_last.has_reasoning ? raw_last.reasoning : 0`; otherwise from `row->tokens`.
   - `has_total = row->raw_total.present`, and `total` from it.
   - `timestamp = row->timestamp`, `ms = row->timestamp_ms`.
   - Record `snapshot_row[k] = i`, and compute the row's keys:
     - `row_mirror_key[i] = mirror_key(…, &side, true, …)`;
     - when `row->raw_last` is absent, also `row_observation_key[i] = mirror_key(…, &side, false, …)`. Otherwise leave it empty. These are upstream's legacy-row `requestMirrorKeys`: the snapshot key, plus the observation key when `last` is absent (L4837).
   - Append `PairEvent{PAIR_SNAPSHOT, row->line, k}`.
3. **Bare rows.** Append `PairEvent{PAIR_BOUNDARY, row->line, 0}` for each.
4. **Observations.** Walk `r->token_stream.observations`:
   - Each `TOKEN_S`, `TOKEN_C` and `TOKEN_XC` → `PAIR_BOUNDARY`.
   - The first `TOKEN_M` whose `canon(meta.session_id)` equals `session` marks the leaf. Every later `TOKEN_M` with the same identity → `PAIR_RESTART`. Other `TOKEN_M` (ancestors) are ignored.
5. **Pair.** `stable_sort` the events by `line`; ties keep insertion order. Call `request_pair_file`.
6. **Record pairings.** For each paired snapshot, with `i = snapshot_row[k]`:
   - set `row_mirrored[i] = true`;
   - put `row_mirror_key[i]` into `mirrored`, and also `row_observation_key[i]` when it is non-empty. Upstream aliases both when a pair forms (L4288, L4818).

   Skip the `mirrored` puts when `result->unresolved`, as for the record keys.

*Pass B, for each file:* use the existing fallback loop. `row_mirrored`, `row_mirror_key` and `row_observation_key` below are that file's arrays from Pass A. Replace the `primary` check with:

```c
        if (!row->bare && (row_mirrored[i] || omap_get(&mirrored, row_mirror_key[i]) ||
                           (row_observation_key[i].n && omap_get(&mirrored, row_observation_key[i]))))
          continue;
        error = compose_row_key(&c->usage_arena, result->session_id, s->records[file]->key.path, row, &key);
        if (error.code) break;
        if (omap_get(&seen, key)) continue;
```

Keep the `accepted` → `seen` merge as it is. Units stay in today's order: all record units for every file, then fallback units file by file.

- [ ] **Step 6: Confirm the unit tests pass**

Run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'`
Expected: `<N> test(s), 0 failure(s)`. Then run every check in this task's "Guard checks" list.

- [ ] **Step 7: Confirm the CLI regression passes**

Run: `make test-cli PYTEST_ARGS='-k ledger_mirror'`
Expected: PASS. It failed at this task's failing-first run.

- [ ] **Step 8: Documentation**
  - **`docs/architecture.md`:** append the pairing rule, and every entry of "Remaining differences from v0.74.1" that names Task 3.
  - **`THIRD_PARTY.md`:** extend the CodexBar row with request-ledger pairing.
  - **`docs/development.md`, `tests/README.md`:** update the test counts.

- [ ] **Step 9: Full validation.**

Run: `make check-sort`, `make check-assets`, `make test`, `make sanitize`, `make tsan`.
Expected: all pass.

- [ ] **Step 10: Commit** (only if asked; from the repository root)

```bash
git add colophon/src/acct/parser.h colophon/src/acct/parser.c \
  colophon/src/price/request_ledger.h colophon/src/price/request_ledger.c colophon/src/price/compose.c \
  colophon/tests/unit/test_request_ledger.c colophon/tests/test_cli.py \
  colophon/docs/architecture.md colophon/THIRD_PARTY.md colophon/docs/development.md colophon/tests/README.md
git diff --cached --name-only   # must list exactly the files above
git diff --cached               # review for sensitive data before committing
git commit -m "Pair Codex token_count snapshots with their ledger records" -m "Replace the per-turn primary/fallback rule with CodexBar v0.74.1 per-request pairing. A token_count snapshot is dropped only when it mirrors a ledger record by exact key, by counter or timestamp alias, or as an adjacent near or delayed match. Paired-snapshot and ledger keys also suppress the same snapshot in other copies of the session. The deliberate deviations are recorded in docs/architecture.md."
```

---

### Task 4: Thread-settings priority

Deferrable: it changes cost only for models with a Fast multiplier (`codex_api_fast_multiplier` in `src/price/model.c`, which matches v0.74.1 L661–667 exactly).

**Files:**
- Modify: `src/parse/tokenstream.h` (`TokenTag`, `TokenObservation`), `src/parse/tokenstream.c` (decoded routing ≈L523–550)
- Modify: `src/cache/codec.c` (observation loop ≈L470–491); `src/cache/cache.c:20` (`"native:1:3"`)
- Modify: `src/price/compose.c` (`append`, `compose_usage`)
- Test: `tests/unit/test_request_ledger.c`, `tests/unit/test_codec.c`, `tests/test_cli.py`
- Docs: `docs/architecture.md`, `THIRD_PARTY.md`, `docs/development.md`, `tests/README.md`

**Fallback note.** If Task 2 has not shipped, create `tests/unit/test_request_ledger.c` from Task 2's test file, keeping only what builds without Task 2:
- Leave out everything that needs Task 2: the `price/request_ledger.h` include, and everything that uses it or Task 2's new fields.
- Leave out any static helper that only the left-out tests use. Under `-Werror`, an unused static function fails the build.

Task 4's unit tests use no `turn_context` lines, which carry turn ids only after Task 2.

**Upstream:** all in `CostUsageScanner.swift`:
- L3778–3784: `thread_settings_applied` decoding.
- L4900–4912: `threadSettingsApplied`, `taskStarted`.
- L4404–4421: `pricingMode = "priority"` when the turn is in `priorityTurnIDs` at the moment a row is appended.

**Interfaces:**
- Produces: a new `TOKEN_P` appended after `TOKEN_XC` in `TokenTag`, so existing values keep their numbers; and `bool priority;` in `TokenObservation`.
- Produces: `UsageUnit.priority_tier` becomes true for units without a trace `PriorityEntry` whose thread priority was in force for their turn, by the rule below; `priority` stays NULL. `src/price/pricing.c` already handles `priority_tier` without a trace entry (L97–135).

**Rule (v0.74.1).**
- A `thread_settings_applied` event sets thread priority to whether `payload.thread_settings.service_tier`, trimmed, equals `"priority"`. A missing value, or one that is not a string, means not priority.
- The setting persists until replaced, including across resumes.
- Each `task_started` records, for its turn id, whether priority was on. A `task_started` with no turn id records under the empty id, as upstream inserts `turnID ?? ""`.
- A unit is priority when the latest such record for its turn before the unit's line was "on". A unit with no turn uses the empty id. Upstream checks membership when each row is appended.
- The trace database and sticky memory still apply, combined with thread settings.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_request_ledger.c`:

```c
#define SETTINGS(sec, tier) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"type\":\"thread_settings_applied\",\"thread_settings\":{\"service_tier\":\"" tier "\"}}}"
#define STARTED_NO_TURN(sec) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"type\":\"task_started\"}}"
TEST(tokenstream_records_thread_settings_priority) {
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", " priority "), SETTINGS("02", "default"), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
  const TokenStream *t = &f.records[0].token_stream;
  size_t seen = 0;
  for (size_t i = 0; i < t->count; i++)
    if (t->observations[i].tag == TOKEN_P) ASSERT_EQ(seen++ == 0, t->observations[i].priority);
  ASSERT_EQ(2, seen);
  ledger_fixture_destroy(&f);
}
TEST(compose_marks_turns_started_under_priority_setting) {
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED("02", "synthetic-fast"),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), SETTINGS("04", "default"), STARTED("05", "synthetic-standard"),
      COUNT("06", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
  SessionModel *s = only_session(&f);
  ASSERT_EQ(2, s->unit_count);
  ASSERT_TRUE(s->units[0].priority_tier && s->units[0].priority == NULL);
  ASSERT_FALSE(s->units[1].priority_tier);
  ledger_fixture_destroy(&f);
}
TEST(compose_priority_follows_latest_start_of_same_turn) {
  /* The same turn resumes under default settings: earlier rows stay priority, later rows do not. */
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED("02", "synthetic-turn"),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), SETTINGS("04", "default"), STARTED("05", "synthetic-turn"),
      COUNT("06", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
  SessionModel *s = only_session(&f);
  ASSERT_EQ(2, s->unit_count);
  ASSERT_TRUE(s->units[0].priority_tier);
  ASSERT_FALSE(s->units[1].priority_tier);
  ledger_fixture_destroy(&f);
}
TEST(compose_turnless_rows_follow_turnless_start) {
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED_NO_TURN("02"),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), SETTINGS("04", "default"), STARTED_NO_TURN("05"),
      COUNT("06", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
  SessionModel *s = only_session(&f);
  ASSERT_EQ(2, s->unit_count);
  ASSERT_TRUE(s->units[0].priority_tier);
  ASSERT_FALSE(s->units[1].priority_tier);
  ledger_fixture_destroy(&f);
}
```

In `tests/unit/test_codec.c`, add `codec_round_trips_thread_priority_observation`: a stream with a `TOKEN_P` observation whose `priority = true`, encoded, decoded, and checked for its tag and flag.

In `tests/test_cli.py`:

```python
def test_thread_settings_priority_applies_fast_multiplier(native):
    turn = "synthetic-fast-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("turn_context", {"model": "gpt-6-astra", "turn_id": turn}, 1),
        row("event_msg", {"type": "thread_settings_applied", "thread_settings": {"service_tier": "priority"}}, 1),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 2),
        row("event_msg", {"type": "token_count", "turn_id": turn, "info": {
            "last_token_usage": usage(1_000, 0, 100), "total_token_usage": usage(1_000, 0, 100)}}, 3),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    session = native.payload()["sessions"][0]
    # Standard 1,000 × $10/M + 100 × $50/M = 0.015; curated Astra priority multiplier ×2.
    assert session["own_usage"]["cost_usd"] == pytest.approx(0.03)
    assert any(bucket[2] == "priority" for bucket in session["buckets"])
```

- [ ] **Step 2: Confirm the failing state**

Run: `make test-unit`
Expected: compilation fails, because `TOKEN_P` and `TokenObservation.priority` do not exist yet. The run at the end of the "Cache it, then confirm the behavioural failure" step shows the behavioural failures.

- [ ] **Step 3: Produce `TOKEN_P` observations** (`src/parse/tokenstream.h`, `src/parse/tokenstream.c`)
  - **`tokenstream.h`:** append `TOKEN_P` after `TOKEN_XC`, and add `bool priority;` to `TokenObservation`.
  - **`tokenstream.c`, compact filter:** the `event_msg` filter currently passes only `token_count` and `task_started`. Extend it to also pass lines containing `"\"thread_settings_applied\""`.
  - **`tokenstream.c`, the `event_msg` branch:** add this before the `task_started`/`token_count` checks:

```c
        if (str_equal(type,STR_LIT("thread_settings_applied"))) {
            obs.tag = TOKEN_P;
            Str tier = token_model_trim(string(object(payload,"thread_settings"),"service_tier",false));
            obs.priority = str_equal(tier,STR_LIT("priority"));
            return append(s,obs);
        }
```

The existing valid-timestamp gate already applies; upstream also requires a valid timestamp (`requiresValidTimestamp`). The `TOKEN_*` consumers in `src/acct/parser.c`, `src/acct/rollout.c`, `src/price/pricing.c` and `src/price/compose.c` test tags explicitly, so they ignore `TOKEN_P`. Confirm with `rg -n 'tag *==|->tag' src`.

- [ ] **Step 4: Cache it, then confirm the behavioural failure**
  - **`src/cache/codec.c`:** change `enumeration(w, &tag, TOKEN_XC)` to `enumeration(w, &tag, TOKEN_P)`, and add `B(v->priority);` after `B(v->trigger);`.
  - **`src/cache/cache.c:20`:** `"native:1:3"`.

Run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'` and `make test-cli PYTEST_ARGS='-k thread_settings'`.

Expected:
- The new tokenstream and codec tests pass.
- Every new `compose_*` test reports `FAIL`.
- The CLI test fails on its cost assertion: a cost of about 0.015 against pytest's `0.03 ± 3.0e-08`.

- [ ] **Step 5: Apply it in compose** (`src/price/compose.c`)

```c
typedef struct { uint64_t line; bool on; } PriorityStart;
typedef struct { PriorityStart *items; size_t count, capacity; } PriorityStarts;
/* CodexBar v0.74.1 processFastLine: settings persist until replaced; each task_started
 * records, for its turn id ("" when absent), whether priority was in force. */
static Err thread_priority_starts(Arena *a, const LogRecord *r, Omap *out) {
  bool on = false;
  for (size_t i = 0; i < r->token_stream.count; i++) {
    const TokenObservation *o = &r->token_stream.observations[i];
    if (o->tag == TOKEN_P) { on = o->priority; continue; }
    if (o->tag != TOKEN_S) continue;
    Str key = STR_LIT("");
    if (o->turn_id.n) TRY(canon(a, o->turn_id, &key));
    PriorityStarts *starts = omap_get(out, key);
    if (!starts) {
      TRY(alloc(a, 1, sizeof *starts, _Alignof(PriorityStarts), (void **)&starts));
      TRY(omap_put(out, key, starts));
    }
    PriorityStart start = {o->line, on};
    TRY(record_append(a, (void **)&starts->items, &starts->count, &starts->capacity, sizeof start, &start));
  }
  return ERR_SUCCESS;
}
/* priorityTurnIDs.contains(turnID ?? "") at the moment a row is appended. */
static bool thread_priority_at(const Omap *starts_by_turn, Str key, uint64_t line) {
  const PriorityStarts *starts = omap_get(starts_by_turn, key);
  bool on = false;
  for (size_t i = 0; starts && i < starts->count && starts->items[i].line < line; i++) on = starts->items[i].on;
  return on;
}
```

Wire it in:
- Build one `Omap` per file with `thread_priority_starts`, and keep the maps in an arena array, so both the record-unit loop and the fallback-unit loop can use them. After Task 3 these loops are Pass A and Pass B. Destroy the maps when the session ends.
- Give `append()` a `const Omap *thread_priority` parameter. After `u.priority_tier = u.priority != NULL;`, add:

```c
  if (!u.priority && thread_priority_at(thread_priority, identity.n ? identity : STR_LIT(""), u.line))
    u.priority_tier = true;
```

Pass the current file's map for both record units and fallback units.

- [ ] **Step 6: Confirm the tests pass**

Run: `make test-unit 2>&1 | grep -E '^(FAIL|[0-9]+ test)'` and `make test-cli PYTEST_ARGS='-k thread_settings'`.
Expected: no failures.

- [ ] **Step 7: Documentation**
  - **`docs/architecture.md`:** append the priority rule.
  - **`THIRD_PARTY.md`:** extend the CodexBar row with thread-settings priority.
  - **`docs/development.md`, `tests/README.md`:** update the test counts.

- [ ] **Step 8: Full validation.**

Run: `make check-sort`, `make check-assets`, `make test`, `make sanitize`, `make tsan`.
Expected: all pass.

- [ ] **Step 9: Commit** (only if asked; from the repository root)

```bash
git add colophon/src/parse/tokenstream.h colophon/src/parse/tokenstream.c \
  colophon/src/cache/codec.c colophon/src/cache/cache.c colophon/src/price/compose.c \
  colophon/tests/unit/test_request_ledger.c colophon/tests/unit/test_codec.c colophon/tests/test_cli.py \
  colophon/docs/architecture.md colophon/THIRD_PARTY.md colophon/docs/development.md colophon/tests/README.md
git diff --cached --name-only   # must list exactly the files above
git diff --cached               # review for sensitive data before committing
git commit -m "Mark Codex turns priority from thread settings" -m "Record thread_settings_applied service tiers as token-stream observations, and mark a unit priority when the latest task_started for its turn ran under priority, which is when CodexBar v0.74.1 checks as each row is appended. Trace-database priority evidence still applies. Bump the native cache format to native:1:3."
```

---

## Historical real-data acceptance procedure (not current authorization)

The suite proves only synthetic behaviour. The procedure below records the
original proposal and does not establish captured-corpus parity or current
acceptance. Any new real-data comparison or private-ledger change requires
Kevin's explicit approval; do not execute these steps as part of the source
cutover. Keep every output outside the repository.

1. **Check the shared ledger first.**
   - Run `jq '[.entries[] | select(.long_context.threshold == 200000) | .model]' ~/.colophon/price-history.json`.
   - The result must be `[]`. Any listed model would keep 200,000 from that entry's date. Correct such entries by hand before relying on repriced history.
2. **Build and run with a fresh private runtime home.** Copy in `price-history.json`, `pricing-cache.json` and `priority-turns.json` from `~/.colophon`, so the comparison uses the same ledger, catalog and remembered priority turns:

   ```bash
   make
   COLOPHON_HOME=<new private directory> ./colophon --no-open --codex-home ~/.codex
   ```

3. **Compare.** Open the page and select **month to date**. Compare its totals with CodexBar 0.74.1's month-to-date for the same moment.
4. **Expected:**
   - Tokens agree, apart from activity after CodexBar's last refresh and any entry in "Remaining differences from v0.74.1" that applies.
   - Cost agrees to rounding, apart from the same entries.
   - Report every difference with its model and window, and with the entry that explains it. Investigate any difference that no entry explains; never call it "close enough".
5. **Rejected records.** Confirm that the private run's `native-events.jsonl` has no `usage_record_rejected` note, or report its count.
6. **Redeploy.** The installed native binary changes only after a separate, approved deployment of the merged build.

## Self-review record

- **Background coverage.** A → Task 1. B → Task 3. C → Task 2. D → Task 4. The default-period finding needs no change. The private comparison's result is stated: Task 1 closes the measured gap; Tasks 2–4 can be deferred.
- **Upstream fidelity.** Each task's "Upstream" block lists the upstream code it ports. Known differences from v0.74.1 are listed once, in "Remaining differences from v0.74.1". Each entry names the task that records it.
- **Test discipline.** Every new CLI test runs failing before its fix. Each task's failing-first run states which new unit tests are expected to pass, or only to fail to compile, before the change.
- **No examples or counted cross-references.** Behaviour is shown by unit tests and by named existing tests, not by examples in prose. Cross-references point at named sections, lists, notes and step titles.
- **Placeholders.** None. Every code step names its file, function and approximate lines. The codec tests described in prose name the existing test they follow.
- **Type consistency.** These are defined in Tasks 2 and 3 and used with the same names afterwards: `RequestTotals`, `LedgerRecord`, `LedgerVerdict`, `UsageScalars`, `PairSide`, `PairEvent`, `request_pair_file`, `turns_before`, `request_turn_at`. `TOKEN_P` and `TokenObservation.priority` are introduced in Task 4 only.
- **Review Focus.** Each entry names its test and its owning task.
