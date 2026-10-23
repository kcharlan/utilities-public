# Token and pricing rules

## Antigravity accounting and oracle provenance (0.5.0)

Collect ChatModelMetadata.usage and retry_infos[].usage plus
CortexStepMetadata.model_usage and retry_infos[].usage, regardless of cleared
or checkpoint step status. Merge repeated singular embedded messages before
reading scalar fields. Skip token-empty events; reject components above int64
(including negative varint encodings) or int64 token-sum overflow while retaining
valid sibling events. Generator rows lacking eligible usage increment
antigravity_requests_without_usage; this cannot detect individual missing fields
or changed meanings.

The native ccusage 20.0.42 binary, SHA-256
`b0529e16d914b42d5f7cfb1b30cd318f520b776f93798a3219741b8589a648b3`,
was independently executed on invented external SQLite fixtures. These probes
establish namespaced response_id/provider_assigned_message_id/message_id aliases:
any shared alias merges, bridges join transitively, and absent/empty IDs do not
merge equal-token requests. Copies merge by component maximum; first discovery
owns the record/model. Global later-session copies count as
antigravity_cross_session_duplicates. This is behavioral evidence, not a claim
that upstream Rust source algorithms were independently located or verified.

Each observation first derives visible output as max(response_output_tokens,
max(0, output_tokens-thinking_output_tokens)). Copies then merge the visible and
thinking components by maximum; reconciled output is their sum. Reconciling only
after raw maxima can erase visible evidence from a copy with fewer reasoning
tokens. Explicit zero reasoning remains present; absent reasoning remains absent. Unit input includes
fresh input plus cache read plus cache write. Oracle comparisons project fresh
input as input-cached-cache_write, visible output as output-reasoning (absent
reasoning uses zero), compare cache components directly and total as input+output;
the providers' raw output columns have different meanings.

Colophon additionally preserves first session/display-turn ownership, including
outside-turn units, while preferring a later step-derived clock. Generator events
match execution_id first, otherwise first step_indices entry. Dating prefers
step completed_at, finished_generating_at, created_at, chat-start created_at,
then session start with antigravity_unknown_clocks. These fallback/turn policies
are explicit Colophon adaptations. TTFT uses the turn's first generator row.

Attribution prefers generator response_model, meaningful mapped usage enum,
step ModelInfo.chat_model_name then model_name, latest attributed conversation
model, then antigravity/unattributed. Display/Vertex/URL strings are excluded.
Public fully qualified Model descriptors from Antigravity 2.26.0 binary SHA-256
`6f7e5004629070ac0c4651a1dc29030eaadcd5dc68fa9edf170047d7f8424f4d`
match all 1,691 earlier candidates from the pinned public binary SHA-256
`060ebf79719024f1b3acb52a21c7a182cb6466b2ac4ac25e93391169b1c1bb46`.
`models.inc` retains those values and native-oracle slugs; the self-contained
model-oracle fixture retains public names and observed expectations. Generic
oracle labels deliberately yield empty attribution so meaningful fallbacks win.
Schema provenance remains tied to its producing binary, not reassigned to the
earlier hash after the app updated.

Normalization adapts CodexBar commit
`e5d6977ba547aa7046eed3865f8ee1cdd5d58731`, AntigravityLocalReader.swift
pricingBaseModelID/routingVariantSuffixes/pricingModelAliases, adding -medium,
-high and -trial. The moving gemini-pro-default/gemini-pro-agent aliases assume
gemini-3.1-pro-preview. The explicit Vertex entry is excluded and unsupported;
there is no google-vertex routing lane. Shared catalog pricing preserves Claude
behavior, context tiers and provenance while memoizing provider-prefixed
identities. Antigravity looks up normalized model; Claude looks up model_raw.
Unknown models remain unpriced. Each composition rebuilds summaries after the
shared usage arena reset, including zero-unit sessions.

This ledger preserves the still-applicable decisions inherited from Python
Colophon at repository baseline `38d6998eb223f690fc9dc0bde0ba528fcf784449`.
The complete historical Python ledger and design specification remain in Git
history; their section numbers below are decision identifiers, not dependencies
on a maintained Python document. Native implementation lives in `src/acct/`
and `src/price/`. [Architecture](architecture.md#usage-accounting-rules) records
the current rules and deliberate differences from CodexBar v0.74.1.

The inherited upstream pin is [CodexBar `3bbf6bc48`](https://github.com/steipete/CodexBar/tree/3bbf6bc48/Sources/CodexBarCore/Vendored/CostUsage).
The later alignment pin is [`v0.74.1`, `7c08c0ae783b72040b728757eb85a6cfe4fc2443`](https://github.com/steipete/CodexBar/tree/7c08c0ae783b72040b728757eb85a6cfe4fc2443/Sources/CodexBarCore/Vendored/CostUsage).
Upstream paths in the table are relative to `Sources/CodexBarCore/Vendored/CostUsage/`.
These adaptations do not establish captured-corpus parity or performance acceptance.

## Explicit adaptations and approved differences

| Decision identifier | Upstream file/function at `3bbf6bc48` | Retained native decision |
| --- | --- | --- |
| Non-ported append/resume and checkpoints | `CostUsageScanner.swift`: `parseCodexFileCancellable`, `cachedSnapshotResolution` | Reparse changed logs from the beginning; replay parent snapshots from the first. No incremental start offset, resume state or token-index checkpoints. |
| Non-ported day range | `CostUsageScanner.swift`: `parseCodexFileCancellable` | Account all history rather than upstream day-range filtering. |
| Non-ported incremental refresh budget/queue | `CostUsageScanner.swift`: `CodexInheritedTotalsResolver`, `sortedCodexSessionFilesNewestFirst` | On-demand recursive parent resolution replaces scan budgets and pending queues; difference 7 defines the chain result. |
| Non-ported custom overlay | `CostUsagePricing+Overlay.swift`: `codexCostUSD` | Dated curated/user ledgers replace custom pricing overlays. |
| Spec §15 difference 1 (superseded) | `CostUsageScanner.swift`: `parseCodexFileCancellable`, `handleTokenCount` | Historical per-turn primary-record precedence is retired. Existing v0.74.1 per-request mirror pairing retains unmatched snapshot requests even within ledgered turns; see architecture. |
| Spec §15 difference 2 | `CostUsagePricing.swift`: `resolvedCodexPricing`, `codexAPIFastMultiplier`, `codexCostUSD` | Dated rates and priority multiplier/cap prevent later changes repricing earlier usage. Untimed units use current resolved rates transiently, without an invented date. |
| Spec §15 difference 3 / A1 sticky evidence | `CostUsageScanner+CodexPriority.swift`: `resolveCodexPriorityTurns` | Sticky detected-turn memory survives trace pruning; replacement metadata retains first-seen time. Undetected usage older than trace retention and first run stays standard-priced. |
| Spec §15 difference 4 / A1 trace location | `CostUsageScanner+CodexPriority.swift`: `resolveCodexPriorityTurns` | `logs_2.sqlite` follows `--codex-home`; isolated sources remain isolated. |
| Spec §15 difference 5 (Codex lookup only) | `ModelsDevPricingTargetResolver.swift`: `targets` | Codex keeps only OpenAI catalog lookup; strip `openai/`, diagnose other provider-qualified Codex models as unpriced. The shared catalog also retains Claude's providers, indexed independently. Never read CodexBar settings/cache. |
| Spec §15 difference 6 | `CostUsageScanner.swift`: `CodexSessionFileIndex`, `remember` | Select duplicate-id parent by newest mtime/ascending path rather than incremental arrival; distinct fallback rows still union. |
| Spec §15 difference 7 | `CostUsageScanner.swift`: `CodexInheritedTotalsResolver`, `snapshotResolution` | Resolve fork-of-fork chains regardless of order; approved b10 behavior replaces one-level retry. |
| A1 trace cache machinery | `CostUsageScanner+CodexPriority.swift`: `resolveCodexPriorityTurns`, `boundedCodexPriorityTurns` | All-history cold scans omit memo/cursor anchors and bounded historical windows. Missing DB is silent; unreadable/locked DB retains sticky evidence with diagnostics. |
| A1 priority override model / C1 | `CostUsageScanner+PricingRows.swift`: `codexPriorityPricingModel`, `codexResolvedCostUSD` | Latest completed/raw priority override retains its pricing key/cap; ordinary aliases remain normalized. |

The historical catalog rule ignored `tiers`; v0.74.1 alignment supersedes it
with strict matching tier decoding and corrected curated thresholds, as recorded
in architecture. Seed provenance is public `https://models.dev/api.json`,
snapshot date 2026-10-04, SHA-256
`9095031166fec35632248c736bd29d383771ea8eb2c73dcc5ccdb3082923bc6e`.
The historical snapshot and Python seed generator are not shipped. Committed
native assets and their manifest remain the build inputs; refreshes require
deliberate provenance review rather than invoking retired tooling.

## Claude accounting

Claude usage follows CodexBar **v0.74.1**, commit
[`7c08c0ae783b72040b728757eb85a6cfe4fc2443`](https://github.com/steipete/CodexBar/tree/7c08c0ae783b72040b728757eb85a6cfe4fc2443).
The authoritative anchors in `Sources/CodexBarCore/Vendored/CostUsage/` are
`CostUsageScanner+Claude.swift::parseClaudeFileCancellable` (L153–241),
`claudeOneHourCacheCreationTokens` (L281), `claudeCanonicalRowKey` (L291),
`shouldReplaceClaudeRow` (L304), `claudeRowWins` (L345), `addClaudeRow`
(L426), and `claudeTemporalPricing` (L1050–1109).
`CostUsageFetcher.swift::configureScannerRefresh` (L1820–1823) selects
`excludeVertexAI`; the native composer preserves that filter, including
metadata dictionary recursion and its dictionary-only array traversal.
`CostUsageClaudeJSON.swift::decode` and
`CostUsageScanner+Timestamp.swift::claudeTimestampAndDayKey` supply the JSON
and timestamp contracts. Claude uses CoreFoundation's ISO8601 formatter
for the historical Foundation fallback; Codex's separate timestamp policy
remains unchanged.
`src/claude/foundation.c` delegates original-object validity and oversized
integer and fractional coercion to system `NSJSONSerialization`/`NSNumber`. This preserves
`NSDecimalNumber` rounding and rejection instead of approximating arbitrary
precision through the Codex numeric parser. Ordinary integer token values retain
the native C fast path; fractional spellings also use Foundation because it may
decode them as decimal numbers. The build links the system Foundation/Objective-C runtime.

`src/claude/compose.c` observes original physical lines, with the pinned
512 KiB ceiling and literal assistant/usage prefilter. Display suffix
recovery does not manufacture accounting rows. Local cumulative replacement
precedes cross-file selection; complete, non-sidechain, parent-path rows
win in that order before ascending original path breaks ties. A winning
incomplete request is counted but contributes no token unit or bucket.
Accounting keys use Swift's canonical-equivalent string equality through NFC;
original row IDs and D7 session/history identities retain their exact strings.
The original-path tiebreak likewise uses Swift's canonical-equivalent ordering
without rewriting stored path provenance.

The shared unit mapping is Colophon output design: `input` is fresh input
plus cache reads plus cache creation, `cached` is cache reads, `cache_write`
is cache creation, and `cache_write_1h` is the bounded one-hour component.
Output and optional thinking tokens remain separate. Claude tiers are
`fast|standard`; buckets retain the nine original entries and append the
provider. The Codex accounting composer and pricing engine skip Claude.
Claude's independent pricing stage does not consume the Codex ledger;
unpriced Claude units do not affect Codex totals or availability.

Advisor usage is the secondary-reference extension from **ccusage v20.0.33**,
commit [`1308c416a7da73b63463f953a51b5ae29fb784a4`](https://github.com/ccusage/ccusage/tree/1308c416a7da73b63463f953a51b5ae29fb784a4):
`rust/adapters/claude/src/lib.rs::advisor_usages_from_line` (L635–658) and
advisor-entry construction (L559–568), plus
`rust/crates/ccusage-core/src/types.rs::TokenUsageRaw`.
Only structurally valid `advisor_message` iterations with nonempty models
become entries. Their IDs are `<parent message id>:advisor:<filtered index>`
when the parent has an ID; unkeyed parents leave advisors unkeyed. Construction
precedes Claude dedupe. A zero-token parent remains a dropped parent row but
does not suppress its valid advisor entries. Nested advisor cache creation
uses ccusage's saturating five-minute/one-hour sum. ccusage's different copy
preference and sidechain loader rules do not replace CodexBar's winner rules.

Colophon omits CodexBar's day-range restriction. Its added diagnostics count
rejected physical rows by reason in `claude_rows_dropped`; count all losing
keyed candidates, including local cumulative replacements, in
`claude_duplicate_responses.row_count`; and count distinct canonical keys
with losers in `.key_count`. Unique unkeyed entries are not duplicates.
`claude_incomplete_requests` counts only winning incomplete rows. All fixture
identities, prompts and paths are invented and runtime evidence stays in
test scratch directories outside this public checkout.

## Claude pricing and public seed provenance

`src/price/claude_cost.c` and `claude_model.c` port the same CodexBar
v0.74.1 pin above: `CostUsagePricing.swift::claude` (L221),
`claudeFullContextStandardPricingCutoff`/`claudeHistoricalLongContext`
(L389–416), `normalizeClaudeModel` (L509), `claudeCostUSD` (L712–813),
and first-party targets/lookup (L937–1049).
`ModelsDevPricing.swift::ModelsDevModel.pricing` (L233–263) defines catalog
rate conversion and matching context tiers. `ModelsDevPricingTargetResolver`
defines explicit Codex-compatible route aliases within Claude lookup.

`assets/curated_bundled_claude.json` transcribes every bundled and historical
Claude row at that pin (`CostUsagePricing.swift` SHA-256
`fb196b2de0308f54a72f84aef1099f9b35ae68ddf6356d2805e696eb5055445e`).
Each array stores USD per token in the order fresh
input, cached read, five-minute cache creation, output; optional entries
are threshold, then the four above-threshold rates in the same order.
The cutoff is exactly `1773360000000` ms. Opus/Sonnet 4.6 with a pricing
timestamp always use the pinned historical/current branch; other models
try the catalog before the bundled fallback. A request switches its whole
context only when fresh input plus cache reads plus cache creation exceeds
the threshold. Missing long-context components retain the standard rate.
Missing catalog cache components use standard input. One-hour cache
creation uses twice the selected fresh-input rate, with its count bounded
by total cache creation. Public upstream data is a build input, never a
private runtime ledger.

Fast pricing is the secondary-reference extension from ccusage v20.0.33,
commit `1308c416a7da73b63463f953a51b5ae29fb784a4`:
`rust/crates/ccusage-core/src/cost.rs` (L110–115),
`pricing.rs::SpeedMultiplierOverrides.multiplier_for` (L944–980), and its
models.dev loader (L1309–1311). The committed
`assets/ccusage_fast_multiplier_overrides.json` is copied verbatim from
that pin. Exact keys, family aliases, date suffixes and provider/dotted
parts resolve before normalized-prefix matching; an unmatched fast model
uses multiplier 1. Fast applies to the complete Claude request estimate.
The verbatim override asset SHA-256 is
`f055ffafcf93bc164a0fe071bb462d17c5d888ddf2314ce876cba12fd1f67c42`.
Codex retains its separate rate ledger, candidate lookup and priority rules.

Raw complete Claude rows capture an extraction-time nanocost before dedupe,
including losing copies. Temporal repricing retains a previously priced
zero and falls back to a stored nanocost if current lookup is unresolved,
as `claudeTemporalPricing` does. The raw-unit fields
`claude_price_snapshot`, `claude_cost_priced`, and `claude_cost_nanos` are
owned by each Claude row and copied to authored units; the separate Claude
codec must persist them. Incomplete rows have no priced snapshot.
Current rates and fast policies enter report-owned transient periods under
`claude:bundled/<model>` or `claude:<provider>/<model>`. `priced_by` roles
are `rates` and `fast`; Claude periods add `fast.multiplier` and
`cache_write_1h_multiplier`. Codex period serialization stays unchanged.

The legacy `meta.costs` object and `meta.counts` remain Codex-only.
`meta.sources.<provider>.costs` describes each engine's availability;
unknown Claude models remain unpriced while the engine stays available.
Mixed views show known costs with an unavailable-provider indication and
withhold comparisons when a provider's subtotal is unavailable. Reader,
list, model, calendar and live-cost displays use their own providers.

## Beyond the references

The pinned CodexBar implementation is authoritative for Claude counting
and pricing; ccusage supplies advisor entries (D2) and fast pricing (D4)
where CodexBar has no handling. Colophon omits the upstream day-range
limit, retains deleted transcripts, adds history-only activity and
diagnostics, and enumerates resolved symlink roots (owner-approved
deviation dated 2026-10-14). Web search requests are outside this pricing
implementation. For ccusage comparisons, its copy preference, sidechain
selection and long-context behavior do not replace the primary-reference
rules; parity is required only where those rules agree. The inherited
Spec §15 difference 5 above applies solely to Codex model lookup.

## OpenCode recorded usage

`src/opencode/compose.c::opencode_compose` consumes the accepted v2 session
projection from `src/opencode/db.h`; database facts remain unchanged. It counts
non-inherited assistants and completed/failed compactions as requests. Missing,
invalid and explicit all-zero token tuples count as missing usage by provider.
A valid positive recorded cost without usable tokens remains a cost-only unit;
zero-token/zero-cost rows need no unit. Positive-token recorded-zero rows are
priced. OpenCode costs are catalog estimates recorded by OpenCode, independent
of Colophon's Codex ledger and Claude pricing; no model catalog is consulted.

Raw fresh input, cache read and cache write sum into unit input. Cache read and
write also retain their separate fields; one-hour write is zero. Raw output
plus reasoning becomes output, with reasoning also retained separately. Models
retain `provider/model` identities or `opencode/unattributed`. Valid payload
completion time wins for usage dating; otherwise valid payload creation falls
back to SQLite row creation. Request starts and message-end fallback share
that effective creation clock without changing raw clocks or row-only fork
ownership. Leading usage and residuals have no display turn.
Priority, fast and rate-period fields remain unset.

Messages sum in sequence order in checked wide raw-component space. Invalid
session rollup tokens disable token residuals; invalid rollup cost disables cost
residuals. Negative component/cost differences are diagnosed as shortfalls and
never remove message usage. Cost differences within absolute `1e-9` are zero.
Positive differences become one unattributed residual dated at session start
solely as a display convention (`date_basis=session_start`); an absent start
stays untimed. Diagnostic residuals preserve raw components, nullable cost and
the same display date. A positive cost difference has known cost. A token-only
residual has known zero cost only with a valid matching rollup cost, valid
eligible message costs and complete token attribution. Malformed/unknown rows,
invalid/missing token tuples and cost-only units make attribution incomplete.
An explicit valid zero tuple with recorded zero cost still counts as missing
usage, but those exact facts do not make attribution incomplete.

A nonfinite aggregate of otherwise finite message costs makes all costs in
that session unavailable and suppresses its cost residual; tokens and raw facts
survive. Typed report contexts in `src/opencode/compose.h` identify invalid
rollups, component sums, cost sums and residual arithmetic. Shared refresh in
`src/price/compose.c` independently guards session, turn and bucket cost sums,
keeps each failed summary unavailable, and emits `cost_aggregate_overflow` with
its schema context. Independently valid summaries and units remain available.
Report resources live with the OpenCode store; its map nodes are destroyed
before its arena. Integration owns diagnostic JSON and final cost refresh.

`tests/unit/test_opencode_usage.c` covers these policies, including named
mapping, compaction, missing usage, residual, rounding, overflow, inheritance and
ledger-independence regressions. Rebuilding from surviving rollups can recover
removed-message residuals; deleted sessions contribute nothing. Rollup equality
holds for complete valid synthetic inputs without shortfalls and is not an
assertion about malformed or incomplete sources.
