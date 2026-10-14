# Token and pricing rules

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
| Spec §15 difference 5 | `ModelsDevPricingTargetResolver.swift`: `targets` | Keep only OpenAI catalog; strip `openai/`, diagnose other provider-qualified models as unpriced. Never read CodexBar settings/cache. |
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
