# Colophon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Colophon, a single-file, standard-library-only uv launcher that compiles OpenAI Codex session logs into one self-contained, offline HTML explorer, with token and cost accounting ported from CodexBar.

**Architecture:** One Python launcher, `colophon/colophon`, has two halves:
- A compiler: stream-parse each log into a cached per-file record; assemble sessions, turns, subagents and workspaces; account tokens with a behavioral port of CodexBar; price them against a dated price history; embed one JSON document in an HTML page and write the page atomically.
- An embedded page: plain JavaScript, CSS and a subset Martian Mono font, stored in the launcher as string constants. The page computes every aggregate in the browser, in the viewer's time zone.

**Tech Stack:**
- Python ≥ 3.12, standard library only at runtime: `json`, `sqlite3`, `http.client`, `threading`, `argparse`, `hashlib`, `tempfile`.
- uv PEP 723 launcher.
- Plain ES2020 JavaScript, with no framework and no build step.
- Development only: pytest, Python Playwright (Chromium), fontTools with brotli.

**Spec:** [`colophon/docs/colophon_design_spec.md`](colophon_design_spec.md), branch `colophon`, last commit `74130b0`. The executor reads both the spec and this plan. Where they differ, the section [Decisions that amend the spec](#decisions-that-amend-the-spec) wins.

---

## How to execute this plan

1. **Branch.** Work on the existing `colophon` branch in the main checkout `~/source/utilities-public`.
   - The repository rule (PKM: "Use feature branches, not git worktrees") forbids worktrees unless the user asks for one for this task.
   - If the user does ask for a worktree, follow the user.
2. **Read first.** Before Task 1, read:
   - the repo root `README.md` and `agents.md`;
   - the whole spec;
   - this plan.
3. **Read the project files each task needs.** Before any task, read `colophon/README.md` (from Task 1 on) and `colophon/docs/LESSONS_LEARNED.md`.
4. **Upstream code is normative for ported rules.** Rules marked *port* come from `steipete/CodexBar` at commit `3bbf6bc48` (`origin/main`).
   - Read the upstream function itself before writing the Python, for example with `git -C ~/source/CodexBar show 3bbf6bc48:<path>`. Never read the working tree: that checkout is on a custom branch.
   - The prose in the spec and in this plan is orientation only. Where prose and upstream code disagree, upstream wins. Record the disagreement in `colophon/docs/token_rules.md`, and report it in the task's review notes.
   - Never invent an alternative semantic for a ported rule. Every deviation must already be listed in this plan or the spec. A new one needs the user's approval.
   - If `~/source/CodexBar` is missing, run `git clone https://github.com/steipete/CodexBar ~/source/CodexBar`.
5. **Tests are ours.**
   - The suite never reads another repository's code, tests or fixtures, and never needs a CodexBar checkout or binary.
   - **The token port (Task 14) is checked against stored CodexBar reference outputs that the planner already built:** 35 synthetic cases in `colophon/tests/fixtures/token_cases/` and 7 scrubbed real cases in `colophon/tests/fixtures/scrubbed/`, each with an `expected.json` from a CodexBar CLI built at the pinned commit. They are fixtures like any other. Never edit or regenerate one to make a test pass; if an expectation looks wrong, stop and report it.
   - Every other expected value in token and pricing tests (Tasks 7, 13, 15, 16) is derived by hand from the ported rules, with a short derivation comment citing the upstream function and line range it follows. A hand-derived value may also note that it matches a reference case, but no test before Task 14 reads the fixture files.
   - Never derive an expected value by running Colophon's own code; that would be circular.
   - CodexBar itself runs only in the maintainer tools (`colophon/tests/tools/codexbar_expected.py`, `scrub_codex_logs.py`, and Task 24's tools) and in Task 26's user-approved acceptance. No task before Task 24 needs it.
6. **Test-driven, task by task.**
   - Write the listed failing tests, run them and see them fail, implement, then run the project suite.
   - Every task ends with the complete Colophon suite passing.
   - Before you commit a task that touches the launcher header, run `uv run --script tools/check_uv_headers.py` from the repository root.
7. **Commits.** One or more commits per task. Each has an imperative subject and a body that says what changed, why, and what validation ran. End each body with:
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
   Before each commit:
   - Inspect the full staged diff and file list for sensitive data. This is a public repository.
   - Afterwards, run `git show --stat HEAD` and confirm that every intended file is tracked.
8. **Lessons.** After any bug fix, append an entry to `colophon/docs/LESSONS_LEARNED.md` saying what went wrong and what to do instead. Add a regression test that would fail if the bug came back.
9. **No placeholders.** Do not leave TODOs, stubs or skipped tests. If a task cannot be finished as written, stop and report the evidence.

## Global Constraints

These apply to every task. Values are copied from the spec unless an amendment says otherwise.

- **Form.** A single-file launcher at `colophon/colophon`, executable (mode 0755 in git).
  - First line: `#!/usr/bin/env -S uv run --script`.
  - PEP 723 block with `requires-python = ">=3.12"` and `dependencies = []`.
  - Imports come from the standard library only, at every scope. The fleet guard enforces this.
- **Version.** `__version__ = "0.1.0"`, printed by `--version` and stored in `meta.version`.
- **Flags.** `--no-open`, `--rebuild`, `--offline`, `--refresh-prices`, `--output PATH`, `--codex-home PATH` (default `~/.codex`), `--version`, and argparse `--help`.
  - The `--help` epilog documents both environment variables and the runtime files.
  - `--offline` together with `--refresh-prices` exits with status 2.
- **Environment.**
  - `COLOPHON_HOME`, default `~/.colophon`.
  - `COLOPHON_PRICING_URL`, default `https://models.dev/api.json`.
  - There are no other settings. Never add an undocumented environment variable, including a test-only one.
- **Runtime home.** Directory mode `0700`. Every file Colophon writes is mode `0600`, including a page written with `--output`.
- **Exit codes.**
  - `0`: success. This includes skipped files, zero sessions, and a browser that could not be opened.
  - `1`: fatal. The Codex home is missing or unreadable, or the page cannot be written. It also covers an interrupt (Ctrl-C) and any unexpected error (Task 18).
  - `2`: usage error.
- **Read-only.** Colophon never writes under the Codex home. SQLite databases are opened with the URI `file:<path>?mode=ro`.
- **Network.** The only request is the price-catalog GET.
  - 3 s to connect and receive the response headers; 30 s to download the body.
  - It is skipped with `--offline`.
  - No session data is ever sent.
- **Live sessions.** `LIVE_QUIET_HOURS = 2` is a constant, not a setting.
- **Atomic writes.** The page, the cache, the user ledger, the catalog cache and `priority-turns.json` are written to a temp file in the same directory and then renamed into place.
- **The page.**
  - Self-contained: no external request of any kind.
  - Text is inserted as text, never as HTML.
  - `<html data-theme="dark">`. Every color is a CSS custom property in one `:root[data-theme="dark"]` token block. JavaScript holds no color literals.
  - Martian Mono (SIL OFL 1.1) is embedded as subset WOFF2, with system monospace as the fallback.
- **Costs.** Labelled "API-equivalent estimate (not billed)" everywhere.
- **Upstream citation.** `steipete/CodexBar` `origin/main` @ `3bbf6bc48`. Never cite the user's custom CodexBar build.
- **Public repository.**
  - Only conspicuously synthetic fixtures: paths under `/synthetic/...`, hosts under `example.invalid`, nicknames such as `Agent-Alpha`, text such as `Synthetic request 1`.
  - Parity output, real-data output and mockups never enter the repo.
- **Fleet.** Register the launcher in the guard (Task 1), the root README and `agents.md` (Task 25), and, with the first deployment, the deployment audit and its documentation (Task 26).
- **Tests.** Every category belongs to the project suite (`colophon/.venv/bin/python -m pytest -q` from `colophon/`), with no skips and no xfails. The only exceptions are the local acceptance scripts the spec names (§12.4, §11 throughput). Those are separate commands, not pytest tests.

## Decisions that amend the spec

**User decisions (2026-10-03).** These take precedence over the spec. Task 1 also writes them into the spec, so the two documents agree.

**A1. The priority tier comes from upstream's trace database, plus sticky memory.** The user's choice: "Port the upstream trace-DB detection and priority pricing exactly. Colophon also remembers detected priority turn ids in its runtime home, so a turn stays priority after its trace rows are pruned." This replaces the spec's `thread_settings_applied` tier source.

- *Detection (port).*
  - A turn is a **priority turn** when Codex's trace database `<codex-home>/logs_2.sqlite` (table `logs`) has a priority request row for that turn id. The database is `logs_2.sqlite` under the `--codex-home` directory (default `~/.codex`). That is the user's decision (A4 item 4). Upstream's `CodexPriorityDatabasePath.defaultURL` always uses `~/.codex` and ignores `CODEX_HOME`. Tests point `--codex-home` at a synthetic home.
  - Port the cold-scan semantics of `resolveCodexPriorityTurns`, from `Sources/CodexBarCore/Vendored/CostUsage/CostUsageScanner+CodexPriority.swift`:
    - `accumulateCodexPriorityTurns` (lines 922–971), including `storePendingCodexCompletedModels` and the FIFO retention cap `codexPriorityCompletedModelRetentionLimit = 4096` (lines 153, 889–921);
    - `filteredResolvedCodexPriorityTurns` and `latestCodexCompletedModel` (lines 440–459);
    - the row parsers `parseCodexPriorityTraceRow`, `parseCodexPrioritySubmissionRow`, `parseCodexCompletedTraceRow`, `value(named:in:)` and `quotedValue(named:in:)` (lines 1020–1098);
    - the non-indexed query form from `codexPriorityAccumulationPlan` (lines 973–1005), with `rowid > 0` and `ts >= 0`.
  - Drop the memo, persisted cursor, anchors and pruning. They only carry state between scans. A cold scan with an empty memo is exactly what Colophon runs on every invocation.
  - The resulting per-turn model is the model of the highest-rowid `response.completed` row retained for that turn; otherwise it is the latest priority row's request `model`.
  - Open with `sqlite3.connect("file:…?mode=ro", uri=True, timeout=0.25)`. This matches upstream's `sqlite3_busy_timeout(db, 250)`.
- *Sticky memory (user-requested Colophon addition).*
  - Detected priority turns are merged into `$COLOPHON_HOME/priority-turns.json` and are never removed.
  - For a turn id present in the database, the database entry replaces the stored entry, except `first_seen_ms`, which is kept.
  - Stored entries absent from the database are kept.
  - Usage older than both the trace database and the first Colophon run stays standard-priced. The README states this limitation.
- *Matching.* A usage unit is priority when its turn id is a priority turn. This is upstream's `row.turnID.flatMap { priorityTurns[$0] }`. The same rule applies on both token paths.
- *Pricing (port of `codexResolvedCostUSD` and `codexPriorityPricingModel`, `CostUsageScanner+PricingRows.swift` lines 4–45 and 87–95).*
  - **Priced model.** For a priority unit, the priced model is the priority turn's **raw** model when `codex_api_fast_multiplier(model)` is not `None`; otherwise it is the unit's own model.
    - `codex_api_fast_multiplier` is a direct port of `codexAPIFastMultiplier` (`CostUsagePricing.swift` lines 682–688): a fixed model set behind `normalizeCodexModel`.
    - It is used **only** for this override decision. The multiplier value comes from the price history (A4 item 2).
  - **Cost** = `max(priority cost, standard cost)` when a priority cost exists; otherwise the standard cost.
  - The input cap (`max_input_tokens`) and the "no multiplier" diagnostic follow spec §5.6 step 7.
- *Spec text this changes.*
  - §2 runtime-home table: add `priority-turns.json`.
  - §3: add `logs_2.sqlite` as a source. The `thread_settings_applied` row becomes "Known; ends an inherited prefix (§5.3). Not a tier source."
  - §5.5 "Service tier": replaced by this decision.
  - §5.6 step 7: "tier in force" becomes "priority turn".
  - §12.1: the priority fixtures use a synthetic `logs_2.sqlite`.
  - §15: the "priority tier comes from `thread_settings_applied`" deviation is replaced by "the priority tier comes from upstream's trace database, plus sticky memory of detected priority turns (a Colophon addition)".

**A2. Tests and data are Colophon's own.**
- The user's words: "If we need tests and data, we build our own."
- The suite never reads another repository's tests, fixtures or checkout, and never needs CodexBar to run.
- Upstream's sanitized fixtures (for example `Issue2037`) are not used.
- **Real data** may be read for reporting and for the local acceptance tools. It never goes into the repository as-is.
- Where realistic data is genuinely needed (the fork and subagent token tests), the planner scrubbed seven small real log families into `colophon/tests/fixtures/scrubbed/` (Task 14, "Reference cases"): an allowlist scrub, generated ids, synthetic paths and names, every time shifted by whole days, and token counts doubled. Each was validated by running CodexBar on the private original and on the scrubbed copy and requiring identical rows after the same mapping. Their expected values are stored with them; afterwards they are Colophon's own test data. The user approved them on 2026-10-03; Task 14 Step 1 commits them.
- **Maintainer tools** (Task 24) may use the local CodexBar CLI and source. They are never part of the suite.

**A3. Mockups.**
- The approved mockups live privately at `~/Downloads/colophon-mockups/`: `overview-layout.html`, `sessions-reader.html` and `visual-direction.html`. They contain the user's real session titles, so they never enter the repo.
- Their design tokens and layout values are restated in [Visual tokens](#visual-tokens-from-the-approved-mockups).

**A4. CodexBar is the reference for all token and cost calculation.**
- The user's words: CodexBar's approach "is THE reference guide for the token calculations… We should not be deviating from its implementation."
- Colophon may **add** things that CodexBar, a "right now" tool, does not do, such as dated price history. It does not change CodexBar's calculations, except where the user has explicitly approved it. A maintainer re-checks for drift with the Task 24 drift tool when CodexBar changes.
- **Approved differences**, the complete list:
  1. **Per-response records where present** (spec §5.5, confirmed by the user on 2026-10-03 after analysis). A turn that has `token_usage_record` usage is counted from those records; other turns use the ported `token_count` accounting.
     - *Evidence* (the user's logs, 2026-09-04 to 2026-10-03, compared with `codexbar cost` daily totals): the records exceed CodexBar by 22.24M input tokens (0.65%) and 387K output tokens. Almost all of that is **context-compaction calls**, which Codex logs only as a `token_usage_record` directly before a `compacted` record, never as a `token_count`. Adding those 94 calls reproduces the record totals exactly on 19 of 25 days; 4 more days differ by one call counted across midnight.
     - About 1.26M input tokens on two days (2026-09-04 and 09-06), under 0.04% of the period, are not explained by compaction. The user set this aside on 2026-10-03; revisit it only if parity shows the gap growing.
  2. **Dated price history** (spec §5.6): a price change never reprices earlier usage. The priority multiplier lives in that history and is seeded from `codexAPIFastMultiplier`.
  3. **Sticky priority-turn memory** (A1). Upstream already keeps priority on its cached rows (`pricingMode == "priority"` and `pricingModel` persist; `CostUsageScanner+CacheHelpers.swift` lines 351–367). Colophon's memory plays the same role, keyed by turn id, because Colophon has no row cache.
  4. **The trace database follows `--codex-home`** (A1). CodexBar ignores `CODEX_HOME` for that file.
  5. **OpenAI models only.**
     - Only the `openai` provider subset of the models.dev catalog is kept.
     - An `openai/` prefix is stripped, as CodexBar's `normalizeCodexModel` does.
     - Any other `provider/model` id is never priced from another provider. It is shown as unpriced, with a diagnostic.
     - The user's logs contain only plain `gpt-*` model names.
     - Colophon reads nothing else from CodexBar: no cache, settings or data.
  6. **Duplicate-id fork parents** use the newest-mtime copy (see "Files sharing a session id" below).
  7. **Fork-of-fork chains resolve regardless of file order** (approved by the user on 2026-10-03: "resolve them anyway").
     - CodexBar's production refresh visits files newest first and retries a pending parent only one level deep. A fork of a fork whose grandchild file is newer than both parents therefore stays unresolved permanently (reference case `b10`), while the same logs with the parents written last resolve (case `b04`). Verified by reordering only the mtimes.
     - Colophon resolves parents on demand, with no scan budget, so it resolves both. No fork-of-fork chain exists in the user's 1,174 logs.
     - The alternative, porting CodexBar's scan-order machinery (`CodexSessionFileIndex`, the pending-parent queue and retry; `CostUsageScanner.swift` lines 1172–1321, 1885–1895, 6659–6676), was declined.
- **Spec items that change to follow CodexBar** (Task 1 Step 6 rewrites them in the spec):
  - **Cache-write tokens** are billed as zero, as CodexBar passes zero for Codex. The logged count is still kept in the payload's `cache_write` field, for display only.
  - **Logs with no `session_meta` are counted.** Their tokens count, as in CodexBar. Each one is its own accounting unit, keyed `file:<path>` as CodexBar's row key does (`CostUsageScanner+CacheHelpers.swift` line 503). It is never merged with another file, and it never enters the fork-parent index. For display only, the session is named from the trailing UUID in the file name, else the file stem, and flagged `no_session_meta`.
  - **Files sharing a session id.** Fallback rows are de-duplicated across those files by CodexBar's `uniqueCodexRows` / `codexCrossFileRowKey`, so the union of distinct rows counts. Primary records are de-duplicated by `(thread_id, response_id)`.
    - **Parent lookup (user-approved deviation, 2026-10-03).** When files share a session id that is a fork parent, the parent's inherited totals come from the copy with the newest mtime (ties broken by path, ascending). That is normally the same copy the page displays.
      - Duplicates are detected by the **pre-pass** id, which is the id the parent index uses. When a file's first `session_meta` is over 256 KiB, the pre-pass id can differ from the display id; the diagnostic lists both.
      - CodexBar's choice depends on its incremental scan state (`CodexSessionFileIndex`: `remember`, the head scan with a persistent cursor, budget deferral and a retry pass; `CostUsageScanner.swift` lines 1172–1321, 1885–1895, 6659–6676). Matching it exactly would mean porting that machinery.
      - No session id appears in more than one of the user's 1,174 files today.
      - A diagnostic, `duplicate_session_ids`, lists every id found in more than one file, so a maintainer sees the case when it happens. The token union across copies (`uniqueCodexRows`) still follows CodexBar exactly.
    - **Display facts** (turns, requests, title, live state) come from the file with the newest mtime, so a live session is never shown from a stale copy. CodexBar has no display semantics, so this is Colophon's own choice.
  - **Priority-override pricing** follows upstream's `resolvedCodexPricing(model: m)` structure, with the raw trace model `m` and `n = normalize_codex_model(m)` (`CostUsagePricing.swift` lines 562–620, 682–688):
    1. If `n` has a historical rate (`HISTORICAL_CUTOFFS`, a constant ported from `codexHistoricalPricing`) and the unit is before the cutoff: rates are `history.pick(n, t)`.
    2. Otherwise, run the ported lookup chain for `m`: the first of `codex_models_dev_pricing_targets(m)`, through `ModelsDevIndex.pricing` with its normalizer candidates, gives a matched catalog model `c_m`. Run it for `n` too, giving `c_n`.
       - If `c_m` exists and `c_m != c_n`, the numbers can differ from `n`'s. Upstream merges `c_m`'s catalog numbers with the bundled entry for `n` (lines 584–616), so the ledger key names both: `catalog:<c_m>|<n>`. Rates are `history.pick(key, t)`, or a transient `resolve_rates(m)` when that key has no entries at all.
       - When the key has entries but the unit is before the first one (`before_first`), use step 3 instead. Before the catalog listed `m`'s own entry, upstream also priced it by `n` (`c_m == c_n`), so a later catalog change never reprices earlier override usage (A4 item 2). Test this: record override usage, then change the catalog so that it adds `m`; the old units keep `n`'s rates and new units use the key.
       - Recording receives `(key, source_model)` pairs: here `source_model` is `m`, and for every ordinary key it is the key itself. It computes `resolve_rates(source_model)`, and applies the "priceable catalog entry" filter to `source_model`.
       - This is the only case that records entries under a non-normalized key.
       - If `c_m == c_n`, the numbers are identical; continue with step 3.
    3. Otherwise: rates are `history.pick(n, t)`, with every normal rule, including the bundled fallback.
    - The multiplier and its cap come from the **priced** model, as upstream's `codexPriorityCostUSD(model: pricedModel)` does (`PricingRows.swift` lines 17 and 33–42): `history.pick(n_priced, t).priority`, where `n_priced = normalize_codex_model(priced model)`. For an override the priced model is `m`, so `n_priced = n`. For a priority unit without an override it is the unit's own model.
    - Ordinary (non-override) units are priced under `n`. That is the normalized row model upstream passes.
  - **No rounding of rates.** Per-million values from models.dev are stored as given. A per-token `CURATED_BUNDLED` value becomes per million via `float(Decimal(repr(x)).scaleb(6))`. `cost_usd` uses `per_million / 1_000_000` as the per-token rate and follows `codexCostUSD`'s operation order.
    - For catalog-sourced rates this is exactly upstream's arithmetic (`P / 1_000_000.0`, `ModelsDevPricing.swift` lines 237–250).
    - For bundled-sourced rates the per-token double can differ from upstream's Swift literal by one ulp. Six bundled literals (`1.8e-6`, `2.5e-8`, `2e-7`, `4e-7`, `5e-8`, `8e-7`) and two historical literals (`1e-7`, and `2e-7`, which is also bundled) do not round-trip.
    - Per-row costs therefore agree with CodexBar to within a few ulps. Parity sums in a different order, so its per-day tolerance is `|Δcost| ≤ 1e-9 × cost + 1e-9` USD, which is far below one cent and far above summation error. This is an *adapted* row (representation only).

**Spec correction C1 (factual, verified against upstream).**
- Spec §5.6 ("Deviation. Upstream first tries the raw logged id…"), §12.1 and §15 list three "raw-alias" pricing deviations. They do not exist.
  - Upstream stores every Codex usage row with `model: normModel` (`CostUsageScanner.swift` line 4637 for token counts, line 4288 for bare usage).
  - It prices with `row.pricingModel ?? row.model` (`CostUsageScanner+CacheHelpers.swift` lines 362–366, `PricingRows.swift` lines 15–19).
  - The only raw-id price is the priority override, which Colophon now ports exactly (A4).
- Task 1 Step 6 rewrites those passages.

## Plan decisions that fill spec gaps

The spec leaves these points open. They are decided here so that the executor does not have to invent them. A reviewer may challenge any of them; each is local and can be changed independently.

| # | Gap | Decision |
|---|---|---|
| D1 | Period membership | A period is a half-open window `[from, to)` in the viewer's local time.<br>• Time metrics clip turn intervals to the window.<br>• Tokens and cost count the 15-minute buckets whose start is in the window.<br>• Turn counts count the turns whose start is in the window.<br>• A session is in the period if its owned span `[start_ms, end_ms]` overlaps the window, or any of its buckets starts in the window.<br>• "Now" is always `meta.generated_at_ms`, never the browser clock; chip windows end at `now + 1 ms`, so they stay half-open. |
| D2 | Default period | `90D`, as in the approved mockups. |
| D3 | Previous period for MTD | From the first day of the previous month, for the same elapsed duration as the current MTD window, clipped to the end of that month. |
| D4 | List grouping under other sorts | Day headers appear only under the `newest` sort. The other sorts show one flat ranked list. |
| D5 | Heat-map levels | Level 0 for zero. Non-zero cells are split into four levels by quartiles of the non-zero values in the displayed grid. |
| D6 | Calendar range for ALL | From the Monday of the week of the first activity to the snapshot week. Past 53 weeks, the grid scrolls inside its `data-scroll-region`. |
| D7 | Tool calls outside any turn | Not counted. The precedence rule is per turn, so they have no category context. |
| D8 | "Its turn" for a usage unit | The turn whose `turn_id` equals the unit's turn id: `payload.turn_id` on the primary path, and upstream's row turn id (`record.turnID ?? currentTurnID`) on the fallback path. |
| D9 | `CollabAgentToolCall` | Its `receiver_thread_ids` count as interaction evidence: "also used in turn n". This resolves the spec's §3 ("Used: subagent linking") against §5.3's shorter list in favor of §3. |
| D10 | Follow-up `target` matching | A target matches a child when it equals the child's `agent_path`. A target without a leading `/` also matches when `<parent path>/<target>` equals it. The parent path is the child's `agent_path` without its last segment. When several children share one `agent_path` (a repeated task name), the target matches all of them. |
| D11 | User-message request assembly | One request per user message. Its text is the kept parts joined with a blank line. It is marked `answer` if any kept part was an answer part. A message with no kept text but with images is kept, showing "+ n images". The image count is the number of image-typed content parts. |
| D12 | Legacy `event_msg agent_message` | A final-answer candidate only when the payload's `phase` is `final_answer`. Otherwise it is not stored, because it may be commentary. |
| D13 | Origin URL normalization | Becomes `https://<host-lowercased>/<path>`. The port, userinfo, a trailing `/` and the `.git` suffix are removed. The SSH forms `git@host:path` and `ssh://[user@]host[:port]/path` map to the same string. |
| D14 | Rate representation | Per million, as given or decimal-converted, with no rounding. Per-row costs agree with CodexBar within a few ulps; the parity tolerance is in A4. |
| D15 | `effective_from` precision | RFC 3339 UTC at whole seconds, `YYYY-MM-DDTHH:MM:SSZ`. The recording time *T* is the catalog's fetch time, truncated to the second. |
| D16 | Progress output | A cold run writes a live `\r` progress line with an ETA to stderr only when stderr is a TTY. A non-TTY run prints only the final summary lines. |
| D17 | Bucket model | Buckets are keyed by the logged model, normalized. The A1 priority priced-model override changes only the cost, never the bucket's model. |
| D18 | Session id | Taken in upstream `codexSessionMetadata` order: `payload.id`, then the root `id`, then `payload.session_id`, `payload.sessionId`, the root `session_id`, the root `sessionId`. Real subagent logs carry a different `payload.session_id` (the tree root); it is not the session's id. |

## Upstream reference map (CodexBar @ `3bbf6bc48`)

Paths are relative to `Sources/CodexBarCore/Vendored/CostUsage/`. Line numbers were checked at the commit. Read the whole function, not just these lines.

| Port target | File | Lines |
|---|---|---|
| `CodexForkBaseline`, totals helpers (`codexTotalsEqual` … `codexPostLatchEventDelta`) | `CostUsageScanner.swift` | 431–667 |
| `CodexTotalsTracker` (`seenRawTotalsLimit = 64`) | `CostUsageScanner.swift` | 669–723 |
| `CodexSnapshotAccumulator` | `CostUsageScanner.swift` | 725–855 |
| `CodexInheritedTotalsResolver.inheritedTotals(for:atOrBefore:)`, private `inheritedTotals(from:…)`, `snapshotResolution(for:)` | `CostUsageScanner.swift` | 1611–1950 |
| Fast-line types (`CodexSessionMetadata`, `CodexTurnContextMetadata`, `CodexTokenCountRecord`, `CodexFastLine`) | `CostUsageScanner.swift` | 3341–3410 |
| `codexModelEvidence`, `codexTurnContextModel` | `CostUsageScanner.swift` | 3453–3475 |
| Fork parent, history base, subagent flag, session id, project path, totals extraction | `CostUsageScanner.swift` | 3476–3700 |
| `codexBareUsage`, `codexBareUsageInt`, `codexFastLineTimestampValidity`, `codexLineOrdinal`, `codexSessionMetadata(from:)` | `CostUsageScanner.swift` | 3914–4012 |
| `parseCodexFileCancellable` (all nested functions, the line routing in `onLine`, the end-of-file subagent classification) | `CostUsageScanner.swift` | 4177–5264 |
| Truncated-line helpers (`extractCodexTruncatedSessionMetadata`, `extractCodexTruncatedTurnContext`); called at 4783 and 4800 | `CostUsageScanner+CodexTruncatedPrefix.swift` | from line 4 |
| `parseCodexFastLine` (the byte-level fast path) | `CostUsageScanner.swift` | 3700–3913 |
| Byte extractors used by the fast path (`extractJSONByteStringField`, `extractJSONByteStringFieldAllowingEmpty`, and the related helpers in that file) | `CostUsageScanner+CodexFastJSON.swift` | whole file |
| `JSONTailState` and `hasCompleteJSONTail()` (the unterminated-tail rule) | `CostUsageJsonl.swift` | 45–270, 383–392, 400–406, 411–417 |
| Session-metadata pre-pass `parseCodexSessionMetadata(fileURL:)`, with `codexSessionMetadataMaxLineBytes = 256 * 1024` | `CostUsageScanner.swift` | 3992, 4013–4106 |
| Dictionary `codexTurnID(from:)` | `CostUsageScanner.swift` | 5266–5274 |
| `dateFromTimestamp`, `dayKeyFromTimestamp`, `dayKeyFromParsedISO` | `CostUsageScanner+Timestamp.swift` | 87–200 |
| Private `modelsDevLookup(providerID:model:catalog:cacheRoot:)` | `CostUsagePricing.swift` | from 840 |
| `ModelsDevPricingTargetResolver.targets(providerID:modelID:)` (slash-qualified ids) | `ModelsDevPricingTargetResolver.swift` | whole file |
| `uniqueCodexRows`, `codexUsageRowKey`, `codexCrossFileRowKey` | `CostUsageScanner+CacheHelpers.swift` | 497–555 |
| `sortedCodexSessionFilesNewestFirst`; `CodexSessionFileIndex.remember` | `CostUsageScanner.swift` | 6717–6731; 1172–1178 |
| `CodexSubagentRolloutShape` (`classify`, `sameConcreteSessionID`, `totalsContainUsage`) | `CodexSubagentRolloutShape.swift` | 1–228 |
| Bundled `codex` table, the `gpt56Pricing` helper and `codexPriorityInputTokenLimit = 272_000` | `CostUsagePricing.swift` | 84–208, 4, 47–61 |
| Historical rates and cutoffs (`codexGPT56PricingCutoff`, `codexSolPricingCutoff`, `codexHistoricalPricing`) | `CostUsagePricing.swift` | 394–407 |
| `codexModelsDevPricingTargets`, `normalizeCodexModel`, `resolvedCodexPricing`, `codexModelsDevLookup` | `CostUsagePricing.swift` | 453–645 |
| `codexPriorityCostUSD`, `codexAPIFastMultiplier`, `codexAPIFastAllowsLongContext`, `codexCostUSD(pricing:…)`; the model-level `codexCostUSD(model:…)` | `CostUsagePricing.swift` 646–731; `CostUsagePricing+Overlay.swift` from line 4 |
| `ModelsDevPricingInfo`, `ModelsDevCatalog.pricing(providerID:modelID:)`, `ModelsDevProvider` (incl. `normalizeProviderID`, `pricing(modelID:exactModelID:)`), `ModelsDevModel.pricing(providerID:providerName:)`, `ModelsDevCost`, `ModelsDevContextOver200KCost`, `ModelsDevModelIDNormalizer` | `ModelsDevPricing.swift` | 6–395 |
| `codexResolvedCostUSD`, `codexPriorityPricingModel` | `CostUsageScanner+PricingRows.swift` | 4–95 |
| Priority trace rows | `CostUsageScanner+CodexPriority.swift` | 153, 289–521, 889–1005, 1020–1098 |

**Not ported, and why:**
- Upstream's append-resume parameters (`startOffset`, `initial*`, `jsonlResumeState`) and its token-index checkpoints exist only to scan incrementally. Colophon reparses a changed log from the beginning (spec §4). For a parent's inherited totals it follows upstream's **production** path, `cachedSnapshotResolution` (lines 1957–2003). The direct-parse branch is marked test-only upstream (comment at lines 1897–1898). Colophon replays the parent's snapshots from the first one, without checkpoints; the result is the same.
- `CostUsageDayRange` filtering: Colophon accounts all history.
- The budgeted, incremental refresh (scan budget, pending-parent queue, newest-first visiting). Colophon resolves a parent on demand. Its only observable effect in the reference cases is `b10` (A4 item 7).
- Custom pricing overlays: the price history replaces them.

Each item above becomes one *adapted* row in `token_rules.md`.

## Repository layout

```
colophon/
  colophon                      # the launcher (only runtime artifact)
  README.md
  OFL.txt                       # Martian Mono license (verbatim from the release)
  requirements-dev.txt          # pytest, playwright, fonttools, brotli
  pytest.ini
  docs/
    colophon_design_spec.md     # existing
    colophon_implementation_plan.md   # this file
    token_rules.md              # upstream provenance table (Tasks 7, 13–17, 25)
    font.md                     # font provenance and regeneration recipe (Task 19)
    LESSONS_LEARNED.md          # created in Task 1
  tests/
    conftest.py                 # loads the launcher; shared fixtures
    fixturegen.py               # synthetic Codex-home generator (Task 2)
    catalogs.py                 # synthetic models.dev catalogs (Task 13)
    expected.py                 # independent KPI oracle over the payload (Task 20)
    test_*.py                   # unit and integration tests, per task
    browser/
      conftest.py               # Playwright fixtures (Task 19)
      test_*.py
    perf/
      measure_throughput.py     # local acceptance; not collected by pytest (Task 23)
    parity/
      compare_codexbar.py       # local acceptance (Task 24)
      check_upstream_tables.py  # maintainer verification (Task 24)
      check_upstream_drift.py   # maintainer drift check against newer CodexBar (Task 24, A4)
    token_cases.py              # test helper: load a reference case, account it, compare (Task 14)
    fixtures/
      token_cases/              # PREBUILT: 35 synthetic cases, expected.json each, index.json, catalog.json
      scrubbed/                 # PREBUILT: 7 scrubbed real fork/subagent cases, expected.json each (A2)
    tools/
      subset_font.py            # dev-only font subsetting (Task 19)
      seed_price_history.py     # dev-only curated-seed generator (Task 16)
      build_token_cases.py      # PREBUILT maintainer tool: writes token_cases inputs (wipes expected.json)
      codexbar_expected.py      # PREBUILT maintainer tool: writes expected.json with the pinned CodexBar CLI
      scrub_codex_logs.py       # PREBUILT maintainer tool: scrubs private logs into fixtures/scrubbed
```

`pytest.ini` sets `testpaths = tests` and `norecursedirs = perf parity tools`, so local acceptance scripts are never collected. It also sets `addopts = --import-mode=importlib -p no:cacheprovider`.

Scripts under `tests/perf`, `tests/parity` and `tests/tools` have **no shebang**, and are run as `colophon/.venv/bin/python <script>`. They must not begin with the canonical uv shebang, because the fleet guard's launcher discovery would then demand that they be registered.

## Launcher internal layout

The launcher is one file, ordered top to bottom into the sections below. Each section begins with a banner comment of the exact form `# ===== <n>. <NAME> =====`. Tests load the launcher with `tools.testkit.load_launcher` and call functions by name, so the names below are the contract between tasks.

| § | Section | Key names (introduced in task) |
|---|---|---|
| 1 | Header, imports, constants | `__version__`, `PARSER_VERSION = 1`, `CACHE_SCHEMA = 1`, `PAYLOAD_SCHEMA = 1`, `LIVE_QUIET_HOURS = 2`, `LIVE_QUIET_MS`, `DEFAULT_PRICING_URL`, `CONNECT_TIMEOUT_S = 3`, `BODY_TIMEOUT_S = 30`, `UPSTREAM_COMMIT = "3bbf6bc48"`, `TAIL_FINGERPRINT_BYTES = 4096`, `UPSTREAM_MAX_LINE_BYTES = 262144`, `PAGE_SIZE_WARN_BYTES = 20 * 1024 * 1024` (T1); `OPEN_IN_CODEX_SUPPORT`, `CONTINUE_IN_CLI_SUPPORT` (T18) |
| 2 | Text and tool rule lists | `REQUEST_HEADINGS`, `CONTEXT_WRAPPERS`, `INJECTED_PREFIXES`, `ANSWER_TAG`, `ORCHESTRATION_FUNCTIONS`, `ORCHESTRATION_JS`, `KNOWN_RECORD_KEYS` (T3, T5, T6) |
| 3 | Curated pricing data | `# >>> CURATED_BUNDLED` / `# <<< CURATED_BUNDLED` and `# >>> CURATED_PRICE_HISTORY` / `# <<< CURATED_PRICE_HISTORY`, each delimiting one `json.loads(r"""…""")` assignment (T13, T16) |
| 4 | Utilities | `now_ms`, `parse_rfc3339_ms`, `format_rfc3339`, `epoch_to_ms`, `atomic_write_bytes`, `atomic_write_json`, `ensure_runtime_home`, `runtime_home`, `abbreviate_home` (T1) |
| 5 | Log reading | `iter_log_lines`, `decode_line`, `RawLine`, `DecodedLine` (T3) |
| 6 | Per-file parse | `parse_log_file`, `event_time`, `classify_user_part`, `TurnBuilder`, `ToolTally`, `TokenStreamBuilder` (T3–T7) |
| 7 | Parse cache and scan | `ParseCache`, `discover_logs`, `scan_logs`, `ScanResult` (T8) |
| 8 | Codex metadata | `load_codex_metadata`, `CodexMetadata`, `select_title`, `humanize_agent_path` (T9) |
| 9 | Assembly | `build_corpus`, `Corpus`, `SessionModel`, `TurnModel`, `classify_open_turns` (T10) |
| 10 | Subagents | `link_subagents` (T11) |
| 11 | Workspaces | `normalize_origin_url`, `find_git_root`, `load_workspace_aliases`, `resolve_workspaces` (T12) |
| 12 | Token accounting (port) | `Totals`, `CodexTotalsTracker`, `CodexSnapshotAccumulator`, `classify_subagent_rollout`, `parse_codex_usage`, `CodexUsageResult`, `InheritedTotalsResolver` (T14) |
| 13 | Usage composition | `load_priority_turns`, `compose_usage`, `UsageUnit` (T15) |
| 14 | Pricing (port) | `normalize_codex_model`, `codex_models_dev_pricing_targets`, `ModelsDevIndex`, `resolve_rates`, `cost_usd`, `priority_cost_usd`, `codex_api_fast_multiplier` (T13) |
| 15 | Price history | `validate_ledger`, `PriceHistory`, `record_catalog_rates`, `append_user_ledger` (T16) |
| 16 | Catalog fetch | `fetch_catalog`, `CatalogResult` (T17) |
| 17 | Compile | `price_units`, `build_payload`, `render_page`, `write_page` (T18) |
| 18 | Page assets | `PAGE_TEMPLATE`, `PAGE_CSS`, `PAGE_JS`, `FONT_CSS` (T18–T22) |
| 19 | CLI | `build_arg_parser`, `run`, `main` (T1, T18) |

**Rules for the embedded assets.**
- `PAGE_CSS` and `PAGE_JS` are raw triple-quoted strings (`r"""…"""`) and must not contain `"""`. A test asserts this.
- The page is assembled by concatenating literal parts at named placeholders, never with `str.format` or `%`.
- The data JSON is inserted last, so that text inside the data can never be mistaken for a placeholder (Task 19 gives the exact code).

## Persistent formats

### Parse cache (`$COLOPHON_HOME/cache/`)

Layout:
- `cache/FORMAT`: the text `CACHE_SCHEMA:PARSER_VERSION`, for example `1:1`.
- One file per log: `cache/<sha256(abs path utf-8) hex>.json`.

`--rebuild` writes a fresh `cache.rebuild-<pid>/` next to `cache/`. When every log has parsed, it renames `cache/` to `cache.old-<pid>/`, renames the new directory to `cache/`, then deletes `cache.old-<pid>/`. A crash leaves either the old `cache/` intact, or a stray `cache.rebuild-<pid>` or `cache.old-<pid>` directory. A later run removes a stray directory only when its `<pid>` is no longer alive (`os.kill(pid, 0)` raises `ProcessLookupError`), so a concurrent `--rebuild` is never disturbed. If `cache/` is missing but `cache.old-<pid>` exists from a dead process, rename it back to `cache/` first.

A mismatched `FORMAT` discards the whole cache. An entry that fails to decode, or whose `parser_version` differs, is discarded and reparsed.

Each entry is a **FileRecord**: a JSON object holding only time-independent facts. The keys below are the contract between Tasks 3–14. All times are UTC epoch milliseconds (`*_ms`). Line numbers are 0-based **physical** line indexes. Token-stream observations also carry `uidx`: upstream's `lineIndex`, which counts only non-empty lines (`CostUsageScanner.swift` lines 4773–4774; `CostUsageJsonl.swift` lines 358–359 never call `onLine` for an empty line). The port (Task 14) uses `uidx` everywhere upstream uses `lineIndex`, including `CodexSubagentRolloutShape`'s adjacency test at line 129. Attribution, `model_timeline` positions and `inherited_lines` use the physical `line`. `rec` is the 0-based index among successfully decoded records, the "record index" used by spec §5.3.

```text
FileRecord = {
  "parser_version": int,
  "key": {"path": str, "size": int, "mtime_ns": int, "tail_sha256": str},
  "archived": bool,                       # path is under archived_sessions/
  "status": "ok" | "empty" | "header_only", "no_session_meta": bool,
  "lines": {"malformed": int, "recovered": int, "partial_final_line": bool},
  "unknown_types": {str: int},            # key "<type>" or "<type>/<payload.type>" (T3)
  "meta": SessionMeta | null,             # the true first session_meta (T3); the pre-pass id lives in token_stream "P"
  "extra_meta_count": int,                # later session_meta records
  "wrapper_ts": {"count": int, "distinct": int},  # distinct capped at 3
  "history": {"path": "A" | "B" | "none",
              "boundary_rec": int | null,
              "method": "own_lifecycle" | "synthetic_start_verified_by_completion"
                        | "unresolved" | null,
              "inherited_recs": [[start, end_exclusive], ...],    # rec space (T4)
              "inherited_lines": [[start, end_exclusive], ...]},  # same ranges, physical-line space (T4)
  "owned_span": {"first_ms": int | null, "last_ms": int | null},
  "turns": [TurnFact],                    # owned turns only, file order (T4)
  "messages": [MessageFact],              # deduplicated (T5)
  "voice": {"requests": [VoiceRequest], "replies": [VoiceReply]},  # placed (T5)
  "tools": {turn_key: ToolCounts},        # precedence already applied (T6)
  "links": {"activities": [...], "spawn_calls": [...], "targets": [...],
            "collab_receivers": [...]},   # (T6)
  "usage_records": [UsageRecord],         # token_usage_record, all thread ids (T6)
  "token_stream": {"observations": [Observation], "unconsumed_tail": bool}   # (T7)
}

SessionMeta = {"id", "created_at_ms", "timestamp_raw", "cwd", "originator", "cli_version",
  "forked_from_id", "is_subagent": bool, "parent_thread_id", "depth", "agent_path",
  "agent_nickname", "agent_role", "git": {"branch", "origin_url", "sha"},   # from payload.git.{branch, repository_url, commit_hash}
  "rollout_title"}                        # payload.thread_name or payload.title

TurnFact = {"key", "turn_id" | null, "start_ms", "start_src", "end_ms", "end_src",
  "end_kind": "completed" | "aborted" | "interrupted" | "open",
  "reported_ms" | null, "ttft_ms" | null, "start_rec", "last_ms"}

MessageFact = {"role": "user" | "assistant", "kind": "text" | "answer" | "final",
  "text", "images": int, "at_ms", "ts_src", "turn_key" | null, "rec"}

VoiceRequest = {"text", "at_ms", "turn_key" | null, "before_turn": bool,
  "follow_up": bool, "reply": str | null}

VoiceReply = {"text", "at_ms", "turn_key" | null}   # session-level replies only

ToolCounts = {"shell": int, "shell_failed": int, "file_edits": int, "mcp": {server: int},
  "web": int, "image": int, "other": {name: int}}

UsageRecord = {"line", "rec", "response_id", "thread_id", "turn_id", "root_turn_id",
  "ts", "at_ms", "timestamp_unix_ms", "input", "cached_input", "cache_read_input", "cache_write",
  "output", "reasoning"}   # raw values; reasoning may be null; Task 15 applies the tokenTotals mapping
```

`Observation` is a compact list. Totals are `[input, cached, output, reasoning_or_null]`.

| Tag | Shape | Upstream counterpart |
|---|---|---|
| `"M"` | `["M", line, uidx, ordinal, {"session_id", "forked_from_id", "fork_ts", "project_path", "is_subagent", "history_start_ordinal", "history_base_thread_id"}]` | `.sessionMeta` |
| `"C"` | `["C", line, uidx, ordinal, ts, model]`. `model` is `{"set": str}`, `{"clear": true}` or `null` (unchanged); see the `codexTurnContextModel` tri-state | `.turnContext` |
| `"I"` | `["I", line, uidx, ordinal, trigger_turn]` | `.interAgentCommunication` |
| `"S"` | `["S", line, uidx, ordinal, turn_id]` | `.taskStarted` |
| `"T"` | `["T", line, uidx, ordinal, ts, model_evidence, turn_id, last, total]` | `.tokenCount` |
| `"B"` | `["B", line, uidx, ts, model_evidence, totals]` | bare usage (`handleBareUsage`) |
| `"XC"` | `["XC", line, uidx, model]` | truncated `turn_context` (line > 256 KiB) |
| `"XM"` | `["XM", line, uidx, session_id]` | truncated `session_meta`; only consumed in subagent pending mode |
| `"P"` | `["P", {meta fields as "M"}]`, always first when present | the `parseCodexSessionMetadata` pre-pass |

The stream holds exactly the lines upstream would route, in file order, after upstream's own filters, including timestamp validity and the 256 KiB truncation. Task 7 ports those filters.

### Other runtime files

| File | Format |
|---|---|
| `pricing-cache.json` | `{"schema": 1, "etag": str or null, "fetched_at_ms": int, "url": str, "catalog": {"openai": {...}}}` |
| `price-history.json` | Ledger format, spec §5.6. Created on first run as `{"schema": 1, "entries": []}` plus a trailing newline, indented 2 spaces. |
| `priority-turns.json` | `{"schema": 1, "turns": {turn_id: {"thread_id": str or null, "model": str or null, "timestamp": str or null, "first_seen_ms": int}}}` (A1) |
| `workspaces.json` | `{"schema": 1, "aliases": [{"name": str, "origins": [str], "paths": [str]}]}`. The first matching alias in file order wins. |
| `workspaces.example.json` | Written on first run when absent. It holds one alias named `Example Tools`, with origin `https://example.invalid/synthetic/tools.git` and path `/synthetic/deployed/tools`. It is never read. |
| `colophon.html` | The page. |
| `perf-baseline.json` | Written only by `tests/perf/measure_throughput.py`. |
| `parity/` | Written only by `tests/parity/compare_codexbar.py`. |

## Embedded data contract (`PAYLOAD_SCHEMA = 1`)

The page embeds `<script type="application/json" id="colophon-data">…</script>`. The field names below are fixed. Task 18's schema-lock test asserts this exact key set at every level, so any change must update the test and this section together.

```text
Payload = {"schema": 1, "meta": Meta, "sessions": [SessionRow], "subagents": {id: SubagentRow},
           "workspaces": {key: Workspace}, "models": {model: ModelPricing},
           "diagnostics": Diagnostics}

Meta = {"version", "generated_at_ms", "generated_tz", "codex_home",
  "counts": {"logs", "parsed", "cached", "sessions", "subagents", "orphans"},
  "catalog": {"status": "fetched" | "not_modified" | "cached" | "offline" | "unavailable",
              "fetched_at_ms" | null, "checked_at_ms" | null, "source_host"},
  "costs": {"available": bool, "reason" | null},
  "live_quiet_ms": 7200000,
  "links": {"open_in_codex": {"live", "archived", "subagent"},
            "continue_in_cli": {"live", "archived", "subagent"}}}   # booleans

SessionRow = {"id", "kind": "session" | "orphan", "title", "title_full", "title_source",
  "archived", "log_path", "workspace", "subfolder" | null, "cwd" | null, "branch" | null,
  "originator" | null, "forked_from" | null, "start_ms" | null, "end_ms" | null,
  "idle_ms" | null, "user_span_ms" | null,
  "flags": [Flag], "turns": [Turn],
  "session_voice": {"requests": [Request], "replies": [{"at_ms", "text"}]},
  "own_usage": Usage, "outside_usage": Usage,
  "buckets": [[bucket, model, tier, input, cached_input, cache_write, output, reasoning,
               cost_usd_or_null], ...],
  "tools": ToolCounts, "children": [subagent id, ...]}

SubagentRow = SessionRow minus "kind", plus {"parent_id", "depth", "agent_path", "label",
  "nickname" | null, "forked": bool, "spawn_turn" | null, "interaction_turns": [turn id],
  "link_method": "activity" | "spawn_call" | "root_turn_id" | "inferred" | null}

Turn = {"id", "n", "status": "completed" | "aborted" | "interrupted" | "running" | "abandoned",
  "start_ms" | null, "end_ms" | null, "duration_ms" | null, "ttft_ms" | null,
  "flags": [TurnFlag], "requests": [Request], "final_answer": {"text", "voice": bool} | null,
  "tools": ToolCounts, "usage": Usage, "spawned": [id], "used": [id]}

Request = {"at_ms" | null, "text", "kind": "text" | "answer" | "voice",
  "before_turn": bool, "images": int, "time_unreliable": bool}

Usage = {"input", "cached_input", "cache_write", "output", "reasoning",
  "cost_usd" | null, "unpriced_tokens", "priced_by": [[model_key, period_index, "rates" | "priority"], ...]}

Workspace = {"name", "kind": "alias" | "origin" | "git_root" | "cwd", "keys": [str], "alias": str | null}

ModelPricing = {"priced": bool, "periods": [{"effective_from_ms" | null,
  "source": "curated" | "catalog" | "manual" | "transient",
  "per_million": {...}, "long_context": {...} | null, "priority": {...} | null}]}

Diagnostics = {
  "skipped_files": [{"path", "reason": "empty" | "header_only" | "unreadable"}],
  "malformed_lines": {"total", "files": [{"path", "count"}]},
  "truncated_lines": {"total", "files": [{"path", "count"}]},
  "recovered_lines": {"total", "files": [{"path", "count"}]},
  "unknown_record_types": {type: count},
  "db_threads_without_logs": int, "metadata_errors": [str],
  "orphaned_subagents": [id], "inferred_links": [id],
  "unresolved_history_boundaries": [id], "fork_baseline_unavailable": [id], "duplicate_session_ids": [{"id", "paths": [str]}],
  "unpriced_models": [{"model", "tokens"}], "history_begins": [{"model", "from_ms"}],
  "priority_without_multiplier": [{"model", "input_tokens"}],
  "unrecorded_catalog_rates": [model], "ledger": [{"level": "error" | "warning", "message"}],
  "workspaces_file": [str], "catalog": [str], "trace_db": [str],
  "page_size_bytes": int, "page_size_over_limit": bool}
```

**Notes.**
- `idle_ms` is the owned span minus the union of the session's active intervals (spec §5.2, "Span and idle gaps are reported separately"). `user_span_ms` runs from the first to the last kept user request, and is `null` when any user request time is unreliable (spec §5.2, collapsed timestamps).
- `Workspace.keys` lists the normalized origins and paths that map to it. `alias` is the alias name when an alias matched.
- `bucket` is `floor(instant_ms / 900000)`. `tier` is `"priority"` or `"standard"`.
- `Flag` ∈ {`live`, `aborted`, `interrupted`, `abandoned`, `uncertain_timing`, `collapsed_timestamps`, `history_unresolved`, `orphaned`, `forked`, `fork_baseline_unavailable`, `no_session_meta`}.
- `TurnFlag` ∈ {`live`, `collapsed`, `reported_duration`, `unknown_duration`, `start_from_completion`}.
- `priced_by` entries are `[model_key, period_index, role]`, where `role` is `"rates"` or `"priority"`. A priority unit lists both the rates period and the period that supplied its multiplier, `history.pick(n_priced, t)`. They differ for A4 override step 2.
- `models` may contain `catalog:<c_m>|<n>` keys (A4). The page labels them `<c_m> (catalog rate used for priority turns of <n>)`.
- `sessions` holds your sessions plus orphaned subagents (`kind: "orphan"`), sorted by `start_ms` descending, nulls last.
- `children` holds direct children only. Descendants are reached through `subagents[*].children`.
- `page_size_bytes` is the final page's byte length. It is computed as a fixed point: render, measure, write the number, re-measure, and stop when stable (at most 3 iterations).
- **Invariants** (asserted in Tasks 15, 18 and 21):
  - for every session, the sum of `turns[*].usage` plus `outside_usage` equals `own_usage`, component by component;
  - the sum over `buckets` equals `own_usage`;
  - spec §5.5's second equality: a session's overall total is its `own_usage` plus the `own_usage` of every descendant, reached through `children` and `subagents`.

## Visual tokens (from the approved mockups)

The token block in `PAGE_CSS` defines these custom properties. Values marked † were adjusted from the mockup to meet WCAG AA. Task 22's contrast test is authoritative: if it fails, adjust the lightness of the offending text token and keep its hue.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0c100e` | page background |
| `--grid-line` | `#ffffff04` | faint 16 px grid: `linear-gradient` on the page |
| `--panel` | `#111714` | panels, turn cards |
| `--line` | `#1f2a25` | borders |
| `--line-soft` | `#18211d` | turn-card section dividers |
| `--dim` | `#7a9486` † (mockup `#5f7a6c`, which is 4.1:1 on `--bg`) | secondary text, axis labels |
| `--muted` | `#7d978a` | chips, meta lines |
| `--ws` | `#7f998b` † (mockup `#6f897b`) | workspace line in list rows |
| `--txt` | `#c9d6cf` | body text |
| `--hi` | `#e9fff3` | figures, titles |
| `--g` | `#8dffbf` | phosphor green: data, highlights, active chip |
| `--amb` | `#ffb547` | section labels, warnings, failures |
| `--sel` | `#16241d` | selected list row |
| `--hover` | `#121a16` | hovered row |
| `--chip-line` | `#2a3a33` | chip border |
| `--tag-line` | `#3a4a43` | ARCHIVED and other tags |
| `--fchip-bg` / `--fchip-line` | `#18261f` / `#2a7a52` | active filter chips |
| `--tool-bg` / `--tool-line` | `#16201b` / `#24322b` | tool chips |
| `--heat-0` … `--heat-4` | `#141c18`, `#1c4a33`, `#2a7a52`, `#4dbb83`, `#8dffbf` | heat-map ramp |
| `--bar-from` / `--bar-to` | `#2a7a52` / `var(--g)` | bar gradient |
| `--tl-turn` / `--tl-sub` | `#2a7a52` / `#4dbb83` | timeline blocks |
| `--focus` | `var(--g)` | focus ring |

**Typography.**
- `font: 300 12px/1.5 'Martian Mono', ui-monospace, monospace`.
- Weights: 300 (body and figures), 400 (titles), 500 (labels, brand).
- Brand mark: weight 500, `letter-spacing: .35em`, 14–15 px, `--g`.
- Section labels: 9.5 px, `letter-spacing: .25em`, `--amb`, weight 500, uppercase, prefixed `// `.
- KPI value: 22 px weight 300 `--hi`. KPI label: 9 px, `letter-spacing: .12em`, uppercase.

**Layout values.**
- Overview: a KPI row of 7 equal columns, falling back to `repeat(auto-fit, minmax(128px, 1fr))` at narrow widths. Main grid `1.75fr 1fr`, gap 16 px. Panels have padding 12×14 px and radius 3 px.
- Calendar cells: 13 px with a 3 px gap; the minimum cell is 9 px. Hour×weekday grid: `28px repeat(24, 1fr)`, cell height 13 px.
- Bars: `120px 1fr 64px`, bar height 9 px.
- List/reader body: `minmax(330px, .9fr) 1.35fr`.
- List row grid: `42px 1fr auto`. The metrics column has a fixed width of 92 px, right-aligned.
- Overview recent-session row: `98px 1fr 150px 190px`. Reader subagent row: `14px 1fr auto`.
- Reader: title 17 px weight 400. The stats strip is 6 columns that wrap. Timeline: height 74 px, lane height 14 px, block height 12 px, labels 8.5 px.

## Test infrastructure and commands

Set up once, from `colophon/`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
```

| Purpose | Command (from `colophon/` unless noted) | Expected |
|---|---|---|
| Full Colophon suite (unit, integration, CLI, browser, scaling) | `.venv/bin/python -m pytest -q` | all pass, 0 skipped |
| One file while iterating | `.venv/bin/python -m pytest tests/test_reader.py -q` | pass |
| Fleet guard (repo root) | `uv run --script tools/check_uv_headers.py` | `check_uv_headers: OK (19 launchers verified)` |
| Guard unit tests (repo root) | `colophon/.venv/bin/python -m pytest tools/tests/test_check_uv_headers.py -q` | pass |
| Deployment audit fixture test (repo root) | `zsh tools/tests/test_check_local_deployments.zsh` | pass |
| Static deployment test (repo root) | `node --test tools/tests/check_static_deployments.test.mjs` | pass |
| Rebuild token-case inputs (maintainer only; deletes every `expected.json`) | `.venv/bin/python tests/tools/build_token_cases.py` | `wrote 35 cases to …/token_cases` |
| Regenerate expectations (maintainer only; CodexBar app quit) | `.venv/bin/python tests/tools/codexbar_expected.py --cli ~/Downloads/colophon-prebuilt/codexbar-cli-3bbf6bc48/CodexBarCLI` (add `--cases tests/fixtures/scrubbed` for the scrubbed set) | `real CodexBar cache and preferences unchanged; 35/35 cases written` |

**Shared test rules.**
- **No network.** `tests/conftest.py` has an autouse fixture that patches `socket.socket.connect` and `socket.create_connection` in-process, raising on any non-loopback address. Subprocess CLI runs pass `--offline`, or set `COLOPHON_PRICING_URL` to a local test server; the `run_cli` helper defaults it to `http://127.0.0.1:9/catalog.json`, which refuses connections.
- **Isolation.** Every test uses a fresh `tmp_path` for both `COLOPHON_HOME` and the Codex home. No test reads `~/.codex` or `~/.colophon`.
- **Frozen time.** In-process tests pass `snapshot_ms` explicitly. CLI tests that depend on the quiet threshold set fixture file mtimes with `os.utime` relative to `time.time()`, and assert classifications with at least 10 minutes of margin on either side of the 2-hour threshold.
- **Loading.** `tests/conftest.py` puts both the repo root and `colophon/tests` on `sys.path`; with `--import-mode=importlib`, `fixturegen`, `catalogs` and `expected` would not import otherwise. It exposes:
  - a session-scoped fixture `colophon`, from `tools.testkit.load_launcher(LAUNCHER)`;
  - `run_cli(*args, home, codex_home, env=None)`, a wrapper over `tools.testkit.run_launcher` that sets `COLOPHON_HOME` and the default pricing URL.

---

## Phase 1 — Foundation

### Task 1: Project scaffold, CLI skeleton, runtime home, fleet guard registration, spec amendments

**Files:**
- Create: `colophon/colophon`, `colophon/README.md`, `colophon/requirements-dev.txt`, `colophon/pytest.ini`, `colophon/tests/conftest.py`, `colophon/tests/test_cli_basics.py`, `colophon/docs/LESSONS_LEARNED.md`
- Modify: `tools/check_uv_headers.py` (add `"colophon/colophon"` to `LAUNCHERS`, and add the `DEPENDENCY_MANIFESTS` dict item `"colophon/colophon": ("requirements", "colophon/requirements-dev.txt", frozenset({"brotli", "fonttools", "playwright", "pytest"}))`)
- Modify: `colophon/docs/colophon_design_spec.md` (apply A1–A4 and C1; see Step 6)

**Interfaces:**
- Produces:
  - `__version__: str`, and the §1 constants listed in [Launcher internal layout](#launcher-internal-layout).
  - `runtime_home() -> Path`: honors `COLOPHON_HOME`, otherwise `~/.colophon`; expands `~`.
  - `ensure_runtime_home(path: Path) -> Path`: creates the directory with mode 0700, and re-applies `chmod 0o700` on every run.
  - `atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None`.
  - `atomic_write_json(path: Path, obj, *, indent: int | None = 2) -> None`.
  - `build_arg_parser() -> argparse.ArgumentParser`.
  - `main(argv: list[str] | None = None) -> int`.
  - `run(args: argparse.Namespace) -> int`, which later tasks extend.

**Steps:**

- [ ] **Step 1: Write failing tests** in `tests/test_cli_basics.py`:
  - `--version` prints `colophon 0.1.0` and exits 0.
  - `--help` exits 0. Its output contains `COLOPHON_HOME`, `COLOPHON_PRICING_URL`, `price-history.json`, `workspaces.json` and `priority-turns.json`. It creates no runtime home.
  - `--offline --refresh-prices` exits 2, and stderr names both flags.
  - An unknown flag exits 2.
  - A missing `--codex-home` exits 1, and stderr contains the path.
  - A Codex home that exists but is unreadable (`chmod 000`, restored in teardown) exits 1.
  - **First run** against an empty synthetic Codex home (a directory with empty `sessions/`), with `--offline --no-open`:
    - the runtime home has mode 0700;
    - `price-history.json` exists, mode 0600, and equals `{"schema": 1, "entries": []}`;
    - `workspaces.example.json` exists, mode 0600, and holds the synthetic alias from [Other runtime files](#other-runtime-files);
    - a second run does not rewrite either file, which you can check through an unchanged mtime and inode.
  - `atomic_write_bytes`:
    - writes mode 0600 even under `umask 0`;
    - leaves no temp file behind after a forced failure (monkeypatch `os.replace` to raise, then assert the directory listing is unchanged);
    - replaces an existing file atomically: the inode changes and the content is complete.
- [ ] **Step 2: Run the tests** and see them fail (`.venv/bin/python -m pytest tests/test_cli_basics.py -q`).
- [ ] **Step 3: Implement** the header, constants, utilities, parser and `run`.
  - `run()` performs these steps, in order:
    1. validate the Codex home (`is_dir()` and `os.access(R_OK | X_OK)`);
    2. `ensure_runtime_home`;
    3. create the first-run files;
    4. return 0.
  - Later tasks insert the compile steps between steps 3 and 4.
  - Use this load-bearing implementation for atomic writes:

```python
def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
```

- [ ] **Step 4: Register the launcher in the fleet guard**, then run `uv run --script tools/check_uv_headers.py` from the repo root. Expected: `OK (19 launchers verified)`. Also run `colophon/.venv/bin/python -m pytest tools/tests/test_check_uv_headers.py -q`.
- [ ] **Step 5: Create `README.md`** with these sections, which Task 25 completes: Name, Install, Usage, Flags, Environment variables, Runtime files, Privacy.
  - Create `docs/LESSONS_LEARNED.md` with a heading and the first entry: "Port upstream verbatim. Cite the code, verify every restated rule against the function, never invent variants" (from the spec-review history).
- [ ] **Step 6: Apply A1–A4 and C1 to the spec text.**
  - A1: the sections listed under it.
  - A2: §5.6's "A test checks every value…" names the maintainer script; §12.1 mentions the scrubbed fixtures.
  - A4: §5.5 records the compaction evidence for the primary path; §5.6 drops the cache-write deviation, rewrites the formula block (cache write is zero, and the per-token rate is `per_million / 1_000_000` in upstream's operation order), and states the conversion rule and the priority-override pricing rule; §3 replaces the `rollout-*.jsonl` pattern with upstream's discovery; §4 and §5.1 count logs without `session_meta` and handle files sharing an id as CodexBar does; §15's deviation list is replaced by A4's approved list.
  - C1: §5.6's raw-alias "Deviation" paragraph, its §15 bullet and the §12.1 fixture line.
  - Update the spec's `Status:` line to say that it was amended by the implementation plan on 2026-10-03.
  - Re-read every edited region as rendered Markdown. Check for lazy-continuation merges and lost lines.
- [ ] **Step 7: Run the full Colophon suite.** Commit with the subject `Scaffold Colophon launcher and register it with the fleet guard`.

### Task 2: Synthetic Codex-home generator

**Files:**
- Create: `colophon/tests/fixturegen.py`, `colophon/tests/test_fixturegen.py`

**Interfaces:**
- Produces, for every later test:

```text
uuid7(at_ms: int, seq: int = 0) -> str          # valid UUIDv7 whose first 48 bits are at_ms
iso(ms: int) -> str                              # "YYYY-MM-DDTHH:MM:SS.mmmZ"
class CodexHome:
    __init__(root: Path)
    log(session_id: str | None = None, *, archived: bool = False, day: str = "2030-01-07",
        name: str | None = None) -> LogBuilder   # path sessions/YYYY/MM/DD/rollout-<day>T..-<id>.jsonl
    state_db(threads: list[dict], *, version: int = 5, spawn_edges: list[tuple[str, str]] | None = None)
    session_index(entries: list[dict])           # {"id", "thread_name", "updated_at"}
    global_state(titles: dict[str, str])         # writes .codex-global-state.json "thread-titles"
    trace_db(rows: list[TraceRow])               # logs_2.sqlite with table logs(id, ts, ts_nanos, level,
                                                 #   target, feedback_log_body, thread_id, ...)
    priority_request_row(turn_id, *, thread_id, model, ts) -> TraceRow
    submission_priority_row(turn_id, *, thread_id, ts) -> TraceRow
    completed_row(turn_id, model, ts) -> TraceRow
class LogBuilder:            # every method appends one JSONL record and returns self
    meta(...), turn_context(...), task_started(...), task_complete(...), turn_aborted(...),
    thread_settings(...), user_item(...), user_response(...), user_event_legacy(...),
    agent_item(...), agent_response(...), agent_event_legacy(...), command(...),
    file_change(...), mcp(...), web_search(...), extension(...), image_view(...),
    subagent_activity(...), collab_wait(...), function_call(...), function_output(...),
    custom_tool_call(...), web_search_call(...), local_shell_call(...), tool_search_call(...),
    reasoning(...), token_count(...), usage_record(...), bare_usage(...), realtime_segment(...),
    inter_agent(...), agent_message_ia(...), world_state(...), compacted(...), unknown(...),
    raw(line: bytes)
    write(*, partial_tail: bytes | None = None, mtime: float | None = None) -> Path
```

- The builder tracks a monotonic synthetic clock (`at=` overrides it) and an `ordinal` counter, which it writes into every record as Codex does.
- The trace-database helpers write rows whose `feedback_log_body` uses the exact textual forms that the upstream parsers in A1 match:
  - a request: `… turn.id=<id> thread_id=<tid> … websocket request: {"type":"response.create","service_tier":"priority","model":"<m>",…}`;
  - a submission: `… thread_id=<tid> … Submission sub=Submission { id: "<turn>", … service_tier: Some(Some("priority")) … }`;
  - a completion: `… turn.id=<id> … websocket event: {"type":"response.completed","response":{"model":"<m>"}}`.
  - Read the upstream parsers before writing these helpers, and make sure the bodies satisfy them exactly.

**Record templates.**
- Key names and nesting are copied from real Codex logs. The executor must keep them exactly.
- Every value here is synthetic. `…` means "builder parameter".
- Every record has `"timestamp": iso(at)` and `"ordinal": n`.

```text
session_meta      {"type":"session_meta","payload":{"id":…,"session_id":…,"timestamp":iso,"cwd":"/synthetic/projects/alpha",
                   "originator":"Codex Desktop","cli_version":"0.0.0-synthetic","model_provider":"openai",
                   "history_mode":"…","thread_source":"user",
                   "base_instructions":{"text":"Synthetic instructions."},
                   "git":{"branch":"main","commit_hash":"0000000","repository_url":"https://example.invalid/synthetic/alpha.git"},
                   "source":"vscode"  | {"subagent":{"thread_spawn":{"parent_thread_id":…,"depth":1,
                        "agent_path":"/root/code_review","agent_nickname":"Agent-Alpha","agent_role":null}}},
                   "agent_path"?, "agent_nickname"?, "parent_thread_id"?, "forked_from_id"?,
                   "subagent_history_start_ordinal"?, "history_base"?: {"thread_id": …}}}
turn_context      {"type":"turn_context","payload":{"turn_id":…,"cwd":…,"model":"gpt-synthetic-1",
                   "effort":"medium","summary":"auto","collaboration_mode":{"mode":"default","settings":{"model":…}},
                   "model_name"?, "info"?: {"model"?, "model_name"?}, "title"?}}
task_started      {"type":"event_msg","payload":{"type":"task_started","turn_id":…,"started_at":<epoch s>,
                   "started_at_ms"?, "collaboration_mode_kind":"default","model_context_window":272000}}
task_complete     {"type":"event_msg","payload":{"type":"task_complete","turn_id":…,"completed_at":<s>,
                   "completed_at_ms"?, "started_at"?: <s>, "duration_ms"?, "time_to_first_token_ms"?,
                   "last_agent_message":"Synthetic final answer."}}
turn_aborted      {"type":"event_msg","payload":{"type":"turn_aborted","turn_id":…,"completed_at":<s>,
                   "duration_ms":…,"reason":"interrupted","started_at"?}}
thread_settings   {"type":"event_msg","payload":{"type":"thread_settings_applied","thread_id"?:…,
                   "thread_settings":{"model":…,"service_tier"?:"default"|"priority","cwd":…}}}
UserMessage item  {"type":"event_msg","payload":{"type":"item_completed","thread_id":…,"turn_id":…,
                   "completed_at_ms":…,"item":{"type":"UserMessage","id":…,
                   "content":[{"type":"text","text":…,"text_elements":[]} | {"type":"local_image","path":"/synthetic/a.png"}]}}}
AgentMessage item {"type":"event_msg","payload":{"type":"item_completed","thread_id":…,"turn_id":…,"completed_at_ms":…,
                   "item":{"type":"AgentMessage","id":…,"phase":"final_answer"|"commentary",
                   "content":[{"type":"Text","text":…}]}}}
message (resp.)   {"type":"response_item","payload":{"type":"message","role":"user"|"assistant"|"developer",
                   "phase"?:…,"content":[{"type":"input_text"|"output_text","text":…} | {"type":"input_image","image_url":"data:,"}],
                   "internal_chat_message_metadata_passthrough":{"turn_id":…}}}
legacy messages   {"type":"event_msg","payload":{"type":"user_message","message":…}} and
                  {"type":"event_msg","payload":{"type":"agent_message","message":…,"phase"?:…}}
CommandExecution  item {"type":"CommandExecution","id":…,"command":["/bin/zsh","-lc","ls"],"cwd":…,
                   "exit_code":0,"status":"completed"|"failed","aggregated_output":"","stdout":"","stderr":"",
                   "duration":{"secs":0,"nanos":0},"source":"unified_exec_startup","process_id":"1","parsed_cmd":[]}
FileChange        item {"type":"FileChange","id":…,"status":"completed",
                   "changes":{"/synthetic/projects/alpha/a.txt":{…},"/synthetic/projects/alpha/b.txt":{…}},"stdout":""}
McpToolCall       item {"type":"McpToolCall","id":…,"server":"synthetic_server","tool":"lookup","arguments":{},
                   "result":{"content":[]},"status":"completed","duration":{"secs":0,"nanos":0}}
WebSearch         item {"type":"WebSearch","id":…,"query":"synthetic","action":{"type":"search"}}
Extension         item {"type":"Extension","id":…,"kind":"web.search"|"clock.sleep"|"image_gen.generation"}
ImageView         item {"type":"ImageView","id":…,"path":"/synthetic/a.png"}
SubAgentActivity  item {"type":"SubAgentActivity","id":…,"kind":"started"|"interacted"|"completed"|"interrupted",
                   "agent_thread_id":…,"agent_path":"/root/code_review"}
CollabAgentToolCall item {"type":"CollabAgentToolCall","id":…,"tool":"wait","status":"completed",
                   "sender_thread_id":…,"receiver_thread_ids":[…],"receiver_agents":[],"agents_states":{}}
function_call     {"type":"response_item","payload":{"type":"function_call","name":…,"namespace"?:…,
                   "arguments":"<json string>","call_id":…,"internal_chat_message_metadata_passthrough":{"turn_id":…}}}
                  collaboration names: spawn_agent {"task_name":"code_review","message":"…","fork_turns":"none"},
                  followup_task / send_message {"target":…,"message":"…"}, interrupt_agent {"target":…},
                  wait_agent, list_agents
function_output   {"type":"response_item","payload":{"type":"function_call_output","call_id":…,
                   "output":"{\"task_name\":\"/root/code_review\"}"}}
custom_tool_call  {"type":"response_item","payload":{"type":"custom_tool_call","name":"exec"|"apply_patch",
                   "input":…,"call_id":…,"status":"completed"}}
token_count       {"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":U,"last_token_usage":U,
                   "model_context_window":272000, "model"?, "model_name"?},"model"?, "rate_limits":{}} , "model"?}
                  U = {"input_tokens","cached_input_tokens","cache_write_input_tokens","output_tokens",
                       "reasoning_output_tokens","total_tokens"}
token_usage_record {"type":"token_usage_record","payload":{"response_id":…,"thread_id":…,"session_id":…,
                   "turn_id":…,"root_turn_id":…,"usage":U,"turn_token_usage":U,"thread_token_usage":U}}
bare usage        a line with NO "type": {"timestamp"?:…,"model"?:…,"usage":{"input_tokens",…}} (see upstream codexBareUsage)
realtime segment  {"type":"realtime_item","payload":{"type":"transcript_segment","id":…,"realtime_session_id":…,
                   "role":"user"|"assistant","text":…}}
inter-agent       {"type":"inter_agent_communication_metadata","payload":{"trigger_turn":true}} and
                  {"type":"response_item","payload":{"type":"agent_message","author":…,"recipient":…,
                   "content":[{"type":"encrypted_content","encrypted_content":"c3ludGhldGlj"}]}}
```

**Steps:**
- [ ] **Step 1: Write failing tests** in `test_fixturegen.py`:
  - every builder method emits valid JSON with the template's keys;
  - `uuid7` embeds `at_ms`, and its version nibble is `7`;
  - `write(partial_tail=b'{"timestamp":"2030')` leaves the file without a final newline;
  - `state_db` creates a `threads` table with the columns that Task 9 reads;
  - `trace_db` rows satisfy the documented body shapes;
  - archived logs land under `archived_sessions/`.
- [ ] **Step 2: Run them**, see them fail, implement, then run the suite.
- [ ] **Step 3: Commit** with the subject `Add synthetic Codex home generator for Colophon tests`.

## Phase 2 — Parsing

**The per-file parse is one streaming pass with two phases.** Tasks 3–7 together build `parse_log_file`.
- *Phase 1 (streaming):* decode each line. Feed **every physical line** to the `TokenStreamBuilder` (Task 7): its raw bytes, its `terminated` flag, and `obj` when it decoded cleanly. This includes malformed, glued and unterminated lines, because upstream's routing decides on the bytes. Append compact **fact events** (lifecycle, message, tool, link, usage, voice), each tagged with its `rec`, `line`, event time, provenance, own `turn_id` and payload `thread_id`. Record the per-record headers that path A needs.
- *Phase 2 (in memory, after the read):* compute the inherited ranges (path A or B, Task 4), then build turns, messages, tools and links from the fact events, skipping inherited records.

This keeps one read per file (spec §4) while allowing path A's retroactive boundary. Raw records are never kept after phase 1.

### Task 3: Log reading, damage handling, record classification, event times, session identity

**Files:**
- Modify: `colophon/colophon`, sections 2, 5 and 6
- Test: `colophon/tests/test_reader.py`, `colophon/tests/test_records.py`

**Interfaces:**
- Produces:
  - `iter_log_lines(fh, size: int) -> Iterator[RawLine]`, where `RawLine(index: int, data: bytes, terminated: bool)`. It reads at most `size` bytes, in 1 MiB chunks.
  - `decode_line(data: bytes) -> DecodedLine`, where `DecodedLine(obj: dict | None, status: "ok" | "recovered" | "malformed" | "blank")`.
  - `event_time(record: dict, payload: dict) -> tuple[int | None, str]`, returning `(ms, provenance)`.
  - `record_type_key(record: dict) -> str`.
  - `KNOWN_RECORD_KEYS: frozenset[str]`.
  - `parse_log_file(path: Path, *, size: int, mtime_ns: int, archived: bool) -> dict`. In this task it fills `key`, `archived`, `status`, `lines`, `unknown_types`, `meta`, `extra_meta_count` and `wrapper_ts`. Later tasks fill the remaining FileRecord keys, including `owned_span` (Task 4).

**Rules:**
- **Consistent read.** Only `size` bytes are read; the caller passes the scan-start `st_size`.
- **The tail fingerprint** is the SHA-256 of bytes `[max(0, size - 4096), size)`, read from the same open handle before streaming.
- **Line handling.**
  - A terminated line that is empty or all whitespace is `blank` and ignored.
  - Otherwise, try `json.loads`. A dict means `ok`.
  - On failure, or when the result is not a dict, search for the next occurrence at index > 0 of `b'{"timestamp"'` or `b'{"type"'`. Try `json.loads` from each occurrence in turn. The first dict wins and is `recovered`, and the fragment before it is dropped. With no success the line is `malformed`.
  - The final unterminated segment is tried with `json.loads` only, with no recovery. If it parses to a dict it is used. Otherwise set `lines.partial_final_line = true`; it is not malformed.
- **Status.**
  - `empty`: no decoded records.
  - `header_only`: the only decoded records are `session_meta` records.
  - `ok`: anything else. This includes files with **no** `session_meta` (A4): `meta` is `null`, and `no_session_meta: true` is set in the FileRecord.
  - Files with status `empty` or `header_only` are skipped by assembly and listed in `diagnostics.skipped_files` (spec §4.1 item 6).
- **Two identities, by purpose.**
  - Colophon's session identity (`meta`, the display id, Path A/B and `created_at`) comes from the **true first** `session_meta` in the file, as spec §3 says.
  - Token accounting and the parent index use upstream's pre-pass rule: the first `session_meta` of 256 KiB or less (`parseCodexSessionMetadata`, lines 3992–4106), carried as the `P` observation.
  - They differ only when the first `session_meta` is longer than 256 KiB. Then the pre-pass may pick an embedded ancestor's id. That id never merges sessions in Colophon, because sessions are keyed by the true first id. A test covers this case.
- **Type keys.**
  - `record_type_key` returns `"<type>/<payload.type>"` for `event_msg` and `response_item`, and `"event_msg/item_completed/<item.type>"` for item records. Otherwise it returns `"<type>"`.
  - A line with no `type` whose object has `usage`, `data.usage`, `result.usage` or `response.usage` is `"bare_usage"`, matching upstream's `codexBareUsage` containers (lines 3914–3923).
  - `KNOWN_RECORD_KEYS` lists exactly the spec §3 table. It covers:
    - the top-level types `session_meta`, `turn_context`, `token_usage_record`, `world_state`, `compacted`, `inter_agent_communication_metadata` and `realtime_item`;
    - the `event_msg/*` payload types: `task_started`, `task_complete`, `turn_aborted`, `thread_settings_applied`, `token_count`, `user_message`, `agent_message`;
    - the item types: `UserMessage`, `AgentMessage`, `CommandExecution`, `FileChange`, `McpToolCall`, `WebSearch`, `ImageView`, `Extension`, `SubAgentActivity`, `CollabAgentToolCall`, `Reasoning`, `ContextCompaction`, `Plan`;
    - the `response_item/*` payload types: `message`, `function_call`, `custom_tool_call`, `local_shell_call`, `web_search_call`, `tool_search_call`, `function_call_output`, `custom_tool_call_output`, `local_shell_call_output`, `reasoning`, `tool_search_output`, `agent_message`;
    - `bare_usage`.
  - Any other key is counted in `unknown_types`.
- **Event time** (spec §5.2, restated exactly):

| Payload `type` | Keys checked, in order |
|---|---|
| `task_started` | `started_at_ms`, `started_at` |
| `task_complete`, `turn_aborted` | `completed_at_ms`, `completed_at` |
| anything else | `completed_at_ms` |

  - `_ms` keys are epoch milliseconds; the others are epoch seconds. A key is valid when it is an `int` or `float`, not a `bool`, and convertible.
  - The first valid key wins, and its name is the provenance.
  - For a seconds key whose value is strictly less than 2 s from the wrapper `timestamp`, use the wrapper time with provenance `record_timestamp`.
  - With no valid key, use the wrapper `timestamp`, provenance `record_timestamp`. If it is unparseable, the time is `None`.
- **Collapsed.** `wrapper_ts.count > 1 and wrapper_ts.distinct == 1`. Keep `distinct` capped at 3, so that acceptance can measure the logs with two distinct wrapper times (spec §15 item 6).
- **Identity.**
  - The first `session_meta` owns the session. Its id follows D18.
  - `created_at_ms` is `payload.timestamp` parsed, else that record's event time.
  - `rollout_title` is `payload.thread_name`, else `payload.title`.
  - For subagents, the subagent fields come from `payload.source.subagent.thread_spawn`.
  - Git fields map as follows: `payload.git.branch` → `git.branch`, `payload.git.repository_url` → `git.origin_url`, `payload.git.commit_hash` → `git.sha`. A test asserts the mapping.
  - The later `session_meta` records only increment `extra_meta_count`; Task 4 uses them for path B.

**Steps:**
- [ ] **Step 1: Write failing tests** for each rule above:
  - bytes beyond `size` are ignored;
  - a recent partial tail is not counted as malformed;
  - a glued fragment, `<partial>{"timestamp":…full record…}`, is recovered, and the full record is used;
  - a line that cannot be recovered is malformed;
  - blank lines are ignored;
  - each status case, including a file with no `session_meta` (status `ok`, `no_session_meta` true) and a file whose `session_meta` is not its first record;
  - every key in `KNOWN_RECORD_KEYS` is asserted as one full literal set, and an unknown type is counted;
  - every embedded-clock key, including the 1.9 s and 2.0 s boundary cases of the within-2-s rule;
  - collapsed detection, including one wrapper time only (not collapsed) and 3 identical times (collapsed);
  - D18 session-id order;
  - first-meta ownership with a later ancestor `session_meta` present.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Parse Codex logs with crash-damage handling and record classification`.

### Task 4: Inherited-prefix detection, turn construction and turn duration

**Files:**
- Modify: `colophon/colophon`, section 6
- Test: `colophon/tests/test_history_and_turns.py`

**Interfaces:**
- Consumes: the Task 3 phase-1 fact events.
- Produces:
  - FileRecord `history`, `turns` and `owned_span`;
  - `TurnBuilder`, used internally;
  - `is_inherited(record_facts, rec: int) -> bool`, used internally by Tasks 5–6.

**Rules (normative: spec §5.3 "Inherited-prefix detection", restated here; implement exactly):**
- **Setup.** A record whose event time is earlier than `created_at` is always inherited.
- **Path A** (the first `session_meta` has `forked_from_id`). Scan the `event_msg` `task_started` and `task_complete` records in order, as decoded records:
  1. A `task_started` whose `turn_id` starts with `rollout-` is remembered as `(rec, started_at)` and skipped.
  2. Otherwise a record is **owned** when its `turn_id` is a UUIDv7 whose creation time is `≥ created_at − 1 s`. The creation time is the first 48 bits in ms; the regex is `^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$`, case-insensitive.
     - Then: **not** owned if its `started_at` (epoch seconds) is `< created_at − 1 s`.
     - Then: a `task_started` whose `turn_id` is not a UUIDv7 **is** owned if its wrapper time is `≥ created_at + 1 s`. This overrides the previous adjustment.
  3. **Boundary.** At the first owned record: if it is a `task_complete` whose `started_at` equals a remembered synthetic `started_at`, the boundary is the **last** matching synthetic start's `rec` (method `synthetic_start_verified_by_completion`). Otherwise the boundary is this record's `rec` (`own_lifecycle`).
     User clarification (2026-10-03): both clocks must be finite JSON numbers (`int` or `float`, not `bool`) of epoch seconds, compared numerically. Missing, null, non-numeric, boolean or non-finite values never match, including each other. With no valid match, use the completion's own `rec` and method `own_lifecycle`.
  4. Records with `0 < rec < boundary` are inherited.
  5. If no record is owned, the method is `unresolved` and the boundary is the record count, so every record after the first is inherited.
- **Path B** (no `forked_from_id`).
  - A `session_meta` with a different id starts an inherited run.
  - The run ends at the first of: a `thread_settings_applied`; a record whose `payload.thread_id` equals the session id; or an own `task_started`. A `task_started` is own when its `started_at` is `≥ created_at − 1 s`, or, with no `started_at`, when its event time is `≥ created_at + 1 s`.
  - The record that ends the run is itself owned. Several runs may occur.
- `inherited_recs` stores the inherited ranges as merged, half-open `[start, end)` intervals over `rec`. `inherited_lines` holds the same records as intervals over physical line numbers, built from the phase-1 `rec → line` mapping. Records inherited only because they are dated before `created_at` appear in both as one-record intervals.
- **Turn construction** (spec §5.2):
  - A `task_started` opens a turn keyed by its `turn_id`, else by `turn-<n>`, where `n` is the number of turns so far plus 1.
  - A record without its own `turn_id`, between a start and that turn's end, belongs to the current turn.
  - A `task_complete` closes the turn as `completed`, and a `turn_aborted` as `aborted`. When the turn has no start, an embedded `started_at` on the end becomes the start, with provenance `started_at` and the flag `start_from_completion`.
    User clarification (2026-10-03): completion-only recovery requires no `task_started` record. A start record with no usable clock still opens the turn with its key, `rec` and `turn_id`; preserve its `start_rec`, leave its logged start time unknown, and do not flag `start_from_completion`. Apply the duration rules normally, including reported duration when present.
  - Keep `duration_ms` and `time_to_first_token_ms` when they are numbers ≥ 0.
  - When the end record's turn equals the current turn, the current turn is cleared.
- **Open turns at parse time.** A turn with a start and no end, where some later turn started, is `interrupted`. Its `end_ms` is the latest event time among the records attributed to it before that later turn's start. Otherwise the turn is `open`, and Task 10 classifies it as running or abandoned.
- **Duration** (spec §5.2 "Turn duration"), for completed, aborted and interrupted turns:
  1. If the log is collapsed, there is no reported duration, and both the start and end provenances are `record_timestamp`: unknown, with the flag `collapsed`.
  2. Else, if a reported duration exists and the turn has an end, and (there is no start, or the log is collapsed, or the end provenance is `completed_at`): `start = end − reported`, the duration is the reported value, and the flag is `reported_duration`.
  3. Else, if start and end both exist and `end ≥ start`: `end − start`.
  4. Else unknown, with the flag `unknown_duration`.
- **Owned span.** The first and last event times over the owned records.
- **A session flagged `history_unresolved`** has no owned turns, by construction. Assembly withholds its time and request metrics.

**Steps:**
- [ ] **Step 1: Write failing tests**, one fixture per case:
  - **Path A:** own lifecycle; a synthetic `rollout-` start verified by a completion (the boundary moves back to the last matching start); unresolved (every record after the first is inherited, no turns); the `started_at < created_at − 1 s` override; the non-UUID `task_started` override.
  - **Path B:** each of its three end conditions; two inherited runs.
  - A record dated before `created_at` is inherited.
  - The `turn-<n>` key when `turn_id` is absent.
  - The completion-only start.
  - Every duration rule, including reported duration with a `completed_at` end, and unknown duration in a collapsed log.
  - Interrupted end time.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Detect inherited history and build turns for Colophon`.

### Task 5: Requests, final answers, message deduplication and voice

**Files:**
- Modify: `colophon/colophon`, sections 2 and 6
- Test: `colophon/tests/test_messages.py`

**Interfaces:**
- Produces:
  - `REQUEST_HEADINGS = ("## My request:", "## My request for Codex:")`;
  - `CONTEXT_WRAPPERS = ("# Files mentioned by the user", "# Files pasted by the user", "# Browser comments", "<in-app-browser-context")`;
  - `INJECTED_PREFIXES = ("# AGENTS.md", "<environment_context>", "<INSTRUCTIONS>", "<external_codex_apps_open_page>", "<permissions instructions>", "<recommended_plugins>", "<skills_instructions>", "<codex_apps_open_page_instructions>", "<realtime_delegation>", "<skill>", "<turn_aborted>")`;
  - `ANSWER_TAG = "send_user_message_question_reply"`;
  - `classify_user_part(text: str) -> tuple[str, str] | None`, returning `("text" | "answer", kept_text)`, or `None` when the part is dropped;
  - FileRecord `messages` and `voice`.

**Rules:**
- **Sources.** Messages come from:
  - `item_completed` `UserMessage`/`AgentMessage` (family `item`, priority 2);
  - legacy `event_msg` `user_message`/`agent_message` (family `event`, priority 1);
  - `response_item` `message` with role `user` or `assistant` (family `response`, priority 0). `developer` and `system` roles are never stored.
  - A response message is used only in turns that have no `item_completed` message items. Apply this per turn before deduplication.
- **User part classification** (spec §5.1, in order). Parts are text-typed content items: `text`, `input_text`, or the legacy `message` string. For each part, left-stripped:
  1. **Wrapped request.** The part starts with a `CONTEXT_WRAPPERS` entry. If some line, stripped, equals a `REQUEST_HEADINGS` entry, keep the text after the first such line (stripped). Otherwise drop the part.
  2. The part starts with an `INJECTED_PREFIXES` entry: drop it.
  3. The part starts with `<send_user_message_question_reply>`: keep it as `answer`, with the opening and closing tags removed and the text stripped.
  4. The part starts with `<image` or equals `</image>`: drop it.
  5. Otherwise keep it as `text`.
- **Assembly** follows D11. The image count is the number of `local_image`, `image` and `input_image` content items.
- **Assistant messages.** Keep only `phase == "final_answer"` (D12 for legacy messages), as kind `final`. Commentary is never stored.
- **Deduplication** (spec §4; n·log n). Process the messages in priority order, high to low, stable by `rec`. A message is a duplicate when some **kept** message has:
  - the same role and text;
  - a **different** family;
  - a compatible turn id (not both set and different);
  - and `|Δat| ≤ 10 000 ms`.

  The survivor is the higher-priority copy. Identical messages of the same family are both kept. Messages whose time is `None` match only kept messages that also have no time.

  Use this index:
  - Key: `(role, sha1(text), family)`. Value: a bucket map with `"*"` (every kept message of that family), plus one entry per turn id, plus `None` (kept messages without a turn id).
  - Each entry holds a sorted list of `at_ms` values (`bisect.insort`) and a count of kept messages with no time.
  - To test a message with turn id `t`, look only at the **other two** families. If `t` is `None`, check bucket `"*"`; otherwise check buckets `t` and `None`.
  - Each check is an existence test: `bisect_left(list, at − 10000)` and compare the element found with `at + 10000`. With no time, check the no-time count instead.
  - Same-family copies are never compared, so 20 000 identical same-family messages cost O(n log n).
- **Voice** (spec §5.1 "Voice", time-independent, resolved at parse time).
  - Segments come from `realtime_item` `transcript_segment` records in file order. Consecutive `user` segments form one request; consecutive `assistant` segments form one reply. Join texts with a single space.
  - Placement is by **record position**: the turn whose start..end record span contains the first segment's record.
  - A request before the first turn, or between turns, goes to the next turn that starts, with `before_turn = true`.
  - A request after the last turn goes to that turn, with `follow_up = true`.
  - In a session with no turns, requests and replies stay at session level.
  - A reply is attached to the voice request immediately before it (`reply` field). With no preceding request, it goes to the most recent turn started before it, as a session-level `VoiceReply` with that `turn_key`. With no such turn, it is dropped, unless the session has no turns.
- **Final answer per turn** (used by Task 10), spec §5.1: the last `final` message of the turn. If there is none, use the **last reply placed with a request inside that turn**: a request with `before_turn = false`, including follow-ups, in placement order. It is marked `voice`. A reply attached to a "before this turn" request is never used. Otherwise there is no final answer.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - every wrapper with and without a heading, both headings;
  - every injected prefix;
  - an answer part;
  - image parts and their count;
  - a message with only images;
  - multiple requests per turn, including mid-turn follow-ups;
  - the response family used only when a turn lacks item messages;
  - dedup: cross-family duplicates within 10 s collapse to the item copy; same-family repeats both survive; different turn ids are not duplicates; the 10.0 s versus 10.001 s boundary;
  - a linearity guard as a **ratio**, not an absolute time: build an input of n = 10 000 identical same-family messages inside one 10 s window plus n cross-family copies, and the same shape at 2n. The median of 3 timings must satisfy `t(2n) ≤ 3.0 × t(n)` (n·log n gives about 2.1, quadratic about 4);
  - legacy `agent_message` with and without `phase`;
  - commentary is never stored;
  - voice: alternating segments, before and between turns, after the last turn, a turn without a `final_answer` that uses the voice reply, a turn whose last request has no reply but an earlier request does (the earlier reply is used), a "before this turn" reply never used as the answer, and a session with no turns.
  - Assert each of the lists `REQUEST_HEADINGS`, `CONTEXT_WRAPPERS` and `INJECTED_PREFIXES` in full.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Extract requests, final answers and voice for Colophon`.

### Task 6: Tool summary, subagent link evidence and usage records

**Files:**
- Modify: `colophon/colophon`, sections 2 and 6
- Test: `colophon/tests/test_tools_links.py`

**Interfaces:**
- Produces:
  - `ToolTally`, with `add_structured(item)`, `add_raw(record)` and `result() -> ToolCounts`.
  - `ORCHESTRATION_FUNCTIONS: frozenset[str]` and `ORCHESTRATION_JS: frozenset[str]`.
  - FileRecord `tools`, `links` and `usage_records`.

**Rules:**
- **Precedence** (spec §5.4). Per turn, if the turn has **any** structured tool item, count only structured items. Structured items are `CommandExecution`, `FileChange`, `McpToolCall`, `WebSearch`, `ImageView` and `Extension`, including `clock.sleep`. Otherwise count the raw forms. Calls outside any turn are not counted (D7).
- **Structured:**
  - `CommandExecution`: shell +1. Also failed +1 when `exit_code` is an int ≠ 0.
  - `FileChange`: file edits + the number of keys in `changes`.
  - `McpToolCall`: `mcp[server]` +1.
  - `WebSearch`: web +1.
  - `Extension`: `web.search` → web +1; `clock.sleep` → nothing; any other kind → `other[kind]` +1.
  - `ImageView`: image +1.
- **Raw.**

| Raw form | Counts as |
|---|---|
| `function_call` named `exec_command` or `shell` with no namespace; a `local_shell_call` payload | shell |
| `custom_tool_call` named `apply_patch` | file edits +1 |
| `function_call` whose namespace starts with `mcp__` | `mcp[<namespace minus "mcp__">]` |
| a `web_search_call` payload; a `function_call` with namespace `web` and name `run` | web |
| `function_call` named `view_image` | image |
| `function_call` in the namespaces `collaboration` or `clock`; `function_call` named `update_plan`, `request_user_input`, `request_user_input_async`, `write_stdin`, `wait`, `wait_agent`, `list_agents`, `spawn_agent`, `followup_task`, `send_message` or `interrupt_agent`; `tool_search_call` | not counted (orchestration) |
| any other `function_call` | `other["<namespace>:<name>"]`, or `other[name]` without a namespace |

  - **JS `exec` cells.** A `custom_tool_call` named `exec` is never a file edit. Scan its `input` text for the occurrences of `tools.<ident>(`, where `ident` matches `[A-Za-z_][A-Za-z0-9_]*`:

| `ident` | Counts as |
|---|---|
| `exec_command` | shell |
| `apply_patch` | file edits |
| `mcp__<server>__<tool>` | `mcp[server]` |
| `web__run` | web |
| `view_image` | image |
| in `ORCHESTRATION_JS` = {`write_stdin`, `update_plan`, `wait`, `request_user_input`, `request_user_input_async`, `clock__sleep`}, or starting with `collaboration__` | not counted |
| anything else | `other[ident]` |

    A standalone `web.run(` occurrence counts as web.
- **Link evidence** (from owned records only), with `turn_key` taken from the turn attribution:
  - `activities`: each `SubAgentActivity` item as `{"kind", "child_id": agent_thread_id, "agent_path", "turn_key"}`.
  - `spawn_calls`: a `function_call` with namespace `collaboration` and name `spawn_agent`, joined by `call_id` with its `function_call_output`, whose `output` JSON contains `task_name` (the full path). Stored as `{"task_name", "turn_key", "at_ms"}`. A spawn without a parsable output is kept with `task_name: null`.
  - `targets`: `followup_task` and `send_message` calls as `{"target", "turn_key"}` (spec §5.3 lists only these; `interrupt_agent` is orchestration and is not interaction evidence).
  - `collab_receivers`: `CollabAgentToolCall` `receiver_thread_ids` as `{"child_id", "turn_key"}` (D9).
- **Usage records.** Every `token_usage_record`, from all thread ids and all records (inherited ones included), with the raw `payload.usage` components: `input_tokens`, `cached_input_tokens`, `cache_read_input_tokens`, `cache_write_input_tokens`, `output_tokens` and `reasoning_output_tokens`. Store them unmodified: a missing value is `null`, never 0. `timestamp_unix_ms` is the record's `round(ms)`, or `null` if unparseable. Task 15 applies the `tokenTotals` mapping. Thread filtering and `response_id` deduplication happen in Task 15.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - a turn recorded in both forms is counted once;
  - the raw-only legacy turn;
  - every raw row of the table;
  - JS markers, including `mcp__srv__tool` server extraction, an `exec` that is not a file edit, and `apply_patch` inside an exec cell;
  - every orchestration name not counted, with the sets asserted in full;
  - `Extension` `clock.sleep` not counted but still triggering structured precedence;
  - `image_gen.generation` counted under Other;
  - `tool_search_call` not counted;
  - the failed count;
  - the spawn call–output join, and a spawn without output;
  - targets and collab receivers;
  - usage records keep foreign thread ids.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Summarize tool use and collect subagent link evidence`.

### Task 7: Upstream token observation stream (port of the line routing)

**Files:**
- Modify: `colophon/colophon`, section 6
- Test: `colophon/tests/test_token_stream.py`

**Interfaces:**
- Produces:
  - `TokenStreamBuilder`, with `feed(line_index: int, data: bytes, obj: dict | None, *, terminated: bool)` and `result() -> TokenStream`, where `TokenStream = {"observations": [Observation], "unconsumed_tail": bool}`;
  - `uidx`: the builder counts the lines before the current one that are **not zero bytes long**. Upstream skips only zero-byte lines (`CostUsageJsonl.swift` line 359, `guard lineBytes > 0`), so whitespace-only and `\r`-only lines count, even though Task 3 treats them as blank. It writes `uidx` into every observation directly after `line`. A Task 7 test asserts the `uidx` values around an empty line and a whitespace-only line; reference case `c04_subagent_boundary_empty_line` (Task 14) tests the adjacency consequence;
  - FileRecord `token_stream`.

**Port.** `parseCodexFileCancellable`'s `onLine` closure (lines ~4772–5005) plus the helpers it calls: `parseCodexFastLine`, `codexFastLineTimestampValidity`, `codexLineOrdinal`, `codexSessionMetadata(from:)`, `codexTurnContextModel`, `codexBareUsage`, the truncated-line extractors, and the `tokenTotals` mapping. The stream must contain exactly the observations upstream would route, in order. Specifically:
- **Lines longer than `UPSTREAM_MAX_LINE_BYTES`** (256 KiB) follow upstream's truncated path. Only an `XC` (`turn_context` model, when the canonical root discriminator validates) and an `XM` (`session_meta` id) can be emitted from them. The accounting decides whether `XM` applies (subagent pending mode only).
- **The `"usage"` substring check** happens before the type checks; a bare object with `type == nil` routes to `B`.
- **The fast-path filters.** The `"event_msg"` lines that are neither `token_count` nor `task_started` are dropped. Only `session_meta`, `turn_context`, `inter_agent_communication_metadata`, `task_started` and `token_count` produce observations.
- **Timestamps.** Lines whose kind requires a valid timestamp, and whose timestamp is invalid, are dropped as upstream does. `session_meta` never requires one.
- **`tokenTotals` mapping:**
  - `cached = max(max(0, cached_input_tokens), max(0, cache_read_input_tokens))`;
  - `reasoning = min(max(0, reasoning_output_tokens), output)` when present, else `null`;
  - every component is clamped at ≥ 0.
- **`turn_context` model.** The tri-state comes from `codexTurnContextModel(payloadModel:payloadModelName:infoModel:infoModelName:)`:
  - the first non-blank trimmed value among the four sets the model;
  - if every **present** string value is blank, the model is cleared;
  - if all four are absent or non-strings, it is unchanged.
  Read the upstream function to confirm this before coding; spec §5.5 says the same.
- **`token_count` model evidence** is the first non-blank of `info.model`, `info.model_name`, `payload.model` and the root `model`.
- **The unterminated final segment** (port of `CostUsageJsonl.scanBounded`'s tail rule, `CostUsageJsonl.swift` lines 383–392, called from about lines 401 and 412):
  - It is routed only when upstream's `hasCompleteJSONTail()` holds (`CostUsageJsonl.swift` lines 383–392; called from lines 400–406 and 411–417).
    - "Structurally complete" is `JSONTailState.isStructurallyComplete` (lines 45–270). Port `JSONTailState` byte for byte: do not substitute "is valid JSON". Its edge cases include:
      - a tail whose first non-whitespace byte cannot start JSON is `.invalid`, which counts as complete;
      - a bare number such as `123` is **not** complete (`canCommitAtEOF`);
      - a whitespace-only tail is never complete.
    - A non-truncated tail must also be accepted by `JSONSerialization` with fragments allowed. The Python stand-in is `json.loads(text, parse_constant=_reject)`, where `_reject` raises, because `json.loads` accepts `NaN` and `Infinity` and `JSONSerialization` does not. It must also reject an unpaired surrogate escape (`\\ud800` without a low surrogate), which Foundation rejects. Check the decoded strings recursively, and add a test.
    - A truncated (> 256 KiB) tail needs structural completeness only.
  - Otherwise it is not routed, and `unconsumed_tail` is `true`. This happens with a live session caught mid-write, or with crash debris.
  - This is a fact of the bytes read, so it is cache-safe.
- **Raw bytes, not Colophon's decoding.** `feed` receives each physical line's raw bytes, and `obj` is only an optimization when Colophon decoded the line cleanly. The builder applies upstream's own logic to the bytes: `parseCodexFastLine` first, then the `JSONSerialization` fallback. It routes exactly what upstream would route.
  - A glued or recovered line is therefore treated exactly as upstream treats those bytes, independent of Colophon's Task 3 recovery. Colophon's own recovery feeds only the non-token facts.
  - A test feeds a glued line to both paths and asserts that the token stream equals what the ported upstream routing produces for those bytes.
- **The bare-usage check consumes the line.** A line that contains `"usage"` goes through the bare-usage branch. If it is not a valid bare-usage object, it is dropped and never routed further (lines 4822–4835).
- **Truncated lines.** The truncated-line extractors receive only the first 256 KiB of the line.
- **The session-metadata pre-pass.** Upstream runs `parseCodexSessionMetadata(fileURL:)` before streaming (lines 4698–4709). That selects the first line of 256 KiB or less that yields a `session_meta`, anywhere in the file, including an unterminated final segment. It calls `handleSessionMetadata` on it, and enables subagent pending mode when it is a subagent thread.
  - The builder reproduces this with a header observation `["P", {…session meta fields as in "M"…}]`, emitted at stream position 0 and computed with the same selection rule, over the bytes read.
  - Task 14 calls `handle_session_metadata` on it before any other observation, exactly as upstream does.
- **Bare-usage input is billed input.** `codexBareUsage` subtracts cached input from input. Keep that: the `B` totals' `input` is already `input − cached`, and later tasks must not "fix" it.

**Steps:**
- [ ] **Step 1: Write failing tests**, with expected observations written by hand from the upstream code, each with a derivation comment citing upstream lines:
  - each observation tag;
  - the turn-context tri-state: a blank field followed by a non-blank one sets the model; all present fields blank clears it; all omitted leaves it unchanged; non-string values count as omitted;
  - `token_count` model-evidence order;
  - `cache_read_input_tokens` versus `cached_input_tokens` taking the max;
  - reasoning clamped to output;
  - negative values clamped;
  - an invalid timestamp drops a `token_count` but not a `session_meta`;
  - a bare line with `data.model`;
  - a > 256 KiB `turn_context` yields `XC`;
  - a > 256 KiB `session_meta` yields `XM`;
  - an `event_msg` `agent_message` yields nothing;
  - an unterminated tail that is complete JSON is routed; an incomplete one sets `unconsumed_tail`; the edge tails `123`, whitespace-only, a truncated tail with an invalid first byte, and `{"a":NaN}` each follow `JSONTailState` and the `JSONSerialization` stand-in;
  - a line containing `"usage"` that is not a bare object yields nothing;
  - the `P` pre-pass picks the first eligible `session_meta`, skipping one longer than 256 KiB;
  - ordinals are carried through.
- [ ] **Step 2: Implement.** Create `docs/token_rules.md` with this table header, and add one row per ported or adapted rule in this task:
  `| Rule | Upstream file | Function | Commit | Decision | Notes |`
- [ ] **Step 3: Run the suite and commit** with the subject `Port CodexBar line routing into a cached token stream`.

### Task 8: Parse cache and log scan

**Files:**
- Modify: `colophon/colophon`, section 7
- Test: `colophon/tests/test_cache_scan.py`

**Interfaces:**
- Produces:
  - `discover_logs(codex_home: Path) -> list[LogFile]`, where `LogFile(path: Path, archived: bool, size: int, mtime_ns: int)`. It is a port of upstream's `listCodexSessionFiles(…, includeRecursive: true)` for the roots `[sessions, archived_sessions]`, in that order, over the all-time range (`CostUsageScanner.swift` lines 2151–2187, 3283–3330).
    - It collects date-partitioned files, flat `*.jsonl` in each root, and legacy recursive files. Files are non-hidden, `.jsonl` case-insensitive, and de-duplicated by path key and then by file identity (`st_dev`, `st_ino`), as at lines 5320–5323.
    - `includeRecursive` is `true` because Colophon always performs a full cold scan, which corresponds to upstream's `forceRescan` (line 5959).
    - Order: each root's files are sorted by path separately, the `sessions` root first.
    - CodexBar's **processing** order, used where order matters (primary-record de-duplication across files), is `sortedCodexSessionFilesNewestFirst` on **millisecond** mtimes (`mtime_ns // 1_000_000`).
    - This replaces the spec's `rollout-*.jsonl` pattern (A4).
  - `class ParseCache`:
    - `open(home: Path, *, rebuild: bool) -> ParseCache`;
    - `get(log: LogFile) -> dict | None`, which validates path, size and `mtime_ns`, then the tail fingerprint, read from `[size - 4096, size)` now;
    - `put(record: dict)`, which only buffers in memory; nothing is written until `commit`;
    - `commit(live_paths: set[str])`, which writes the buffered entries, prunes vanished and moved paths and, under rebuild, performs the swap;
    - `abort()`.
  - `scan_logs(codex_home: Path, cache: ParseCache, *, progress: Callable[[int, int], None] | None) -> ScanResult`, where `ScanResult(records: list[dict], parsed: int, cached: int, unreadable: list[tuple[str, str]], bytes_parsed: int)`.

**Rules:**
- Cache layout, `FORMAT` handling and the rebuild swap follow [Parse cache](#parse-cache-colophon_homecache). Stray directories are handled at open by the dead-pid rule in [Parse cache](#parse-cache-colophon_homecache).
- An unreadable file (an `OSError` on open or read) is listed and skipped; the run continues.
- A changed file is reparsed from byte 0.
- A record whose JSON fails to decode, or whose `parser_version` differs, is discarded and reparsed.
- Entry files are written with `atomic_write_json` (mode 0600, no indent).
- `progress(done_bytes, total_bytes)` is called after each parsed file. Only cache misses count toward the total.
- **An interrupted `--rebuild`** (exception or `KeyboardInterrupt` during the scan) calls `abort()`. That removes `cache.rebuild-<pid>/` and leaves `cache/` untouched.
  - The CLI prints the rebuild sentence, in the format defined in Task 18 "Errors and exit codes".
  - It exits 1 (spec §2 allows only 0, 1 and 2). Task 18 wires this into `main`.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - a hit on an unchanged file;
  - a same-size, same-mtime rewrite caught by the fingerprint (rewrite the bytes, then `os.utime` back to the original `mtime_ns`);
  - a grown file is reparsed;
  - a log moved into `archived_sessions` is reparsed under its new path, and the old entry is pruned;
  - a deleted log's entry is pruned;
  - a `FORMAT` mismatch discards everything;
  - a corrupt entry is reparsed;
  - a file that grows **during** the scan keeps its scan-start key, so the next run misses (simulate by appending in a `progress` callback);
  - rebuild success replaces the cache;
  - an interrupted rebuild leaves the old cache byte-identical;
  - a stray rebuild directory of a dead pid is cleaned, a live pid's directory is left alone (use the test process's own pid), and an orphaned `cache.old-<deadpid>` is restored when `cache/` is missing;
  - an unreadable file is reported.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Cache per-log parse records with scan-start keys`.

### Task 9: Codex metadata and titles

**Files:**
- Modify: `colophon/colophon`, section 8
- Test: `colophon/tests/test_metadata.py`

**Interfaces:**
- Produces:
  - `load_codex_metadata(codex_home: Path) -> CodexMetadata`, a dataclass with `threads: dict[str, dict]`, `index_titles: dict[str, str]`, `desktop_titles: dict[str, str]`, `spawn_parents: dict[str, str]`, `rollout_paths: dict[str, str]` and `errors: list[str]`.
  - `select_title(meta: dict | None, info: dict, first_request: str | None, *, cwd: str | None, session_id: str | None, path: Path) -> tuple[str, str]`, returning `(title, source)` for your sessions.
  - `humanize_agent_path(path: str | None) -> str`, and `subagent_title(meta) -> tuple[str, str]`.

**Rules (restated from the research extractor; implement exactly):**
- **Databases.**
  - Sort `state_*.sqlite` by the integer suffix, descending, and use the first database whose `threads` table has an `id` column.
  - Open it as `file:<path>?mode=ro` with `timeout=1`.
  - Read whichever of these columns exist: `id`, `name`, `title`, `cwd`, `git_branch`, `git_origin_url`, `git_sha`, `source`, `originator`, `archived`, `first_user_message`, `agent_nickname`, `agent_role`, `agent_path`, `rollout_path`.
  - Values that are `NULL` or `''` are ignored.
  - If a `thread_spawn_edges` table exists, read child → parent edges. Inspect its columns with `PRAGMA table_info`; accept the column pairs (`child_thread_id`, `parent_thread_id`) or (`child_id`, `parent_id`). Otherwise record an error and ignore the table.
  - A `sqlite3.Error` appends to `errors` and moves to the next database. If every database fails, the run continues without metadata.
- **`session_index.jsonl`.** Per `id`, keep the non-blank `thread_name` with the latest `updated_at`; ties go to the later line.
- **`.codex-global-state.json`.** `["thread-titles"]["titles"]` maps id → desktop title. Ignore anything malformed.
- **Title priority.** The first non-blank of:
  1. `info.name` (`database_name`);
  2. `index_titles[id]` (`session_index`);
  3. `desktop_titles[id]` (`desktop_title`);
  4. `meta.rollout_title` (`rollout_title`);
  5. `info.title` (`database_title`);
  6. the first user request (`first_user_message`);
  7. `info.first_user_message` (`database_first_user_message`).
  
  Without a title, the label is the cwd's final component, else the session id, else the file stem. The `title_source` is respectively `folder`, `session_id` or `filename`.
  - **Which rows use this chain:** your sessions, meaning the non-subagent sessions (spec §5.1 "Your sessions"). Those are never agents, so the chain has no agent branch. The spec's "(non-agent)" qualifier on the database title is honored by never applying the chain to subagent rows.
- **Display title.** The first line of the title, cut at the last word boundary at or before 80 characters, with `…` appended when cut. `title_full` keeps the full text.
- **Subagent and orphan rows** (spec §5.1 "Subagents"): the title is `"<label> · <nickname>"`, or just `<label>` without a nickname, and `title_source` is `agent_path`. The label is `humanize_agent_path(agent_path)`: the last `/` segment, with `_` and `-` replaced by spaces, or `"subagent"` when empty. For example, `"/root/code_review"` gives `"code review"`. Orphans are subagents, so they use this rule too.
- **Truncation without a word boundary:** cut at exactly 80 characters and append `…`.
- **Database threads without a log.** The ids in `threads` with no matching parsed session are counted in `diagnostics.db_threads_without_logs`; assembly computes this count.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - every title source in priority order, one fixture each;
  - subagent and orphan titles from the agent path and nickname;
  - each fallback;
  - truncation at 80 characters, with `title_full` preserved;
  - the newest readable database wins when an older one exists, and a corrupt newest database falls back to the older one, recording an error;
  - a locked database: hold an `EXCLUSIVE` transaction from another connection; the result is an error plus a fallback to log titles, with no crash;
  - `thread_spawn_edges` present and absent;
  - the session index latest-wins rule;
  - malformed global state is ignored;
  - the database is never modified: compare its bytes and mtime before and after.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Read Codex metadata read-only and select display titles`.

## Phase 3 — Assembly

### Task 10: Session assembly and live-state classification

**Files:**
- Modify: `colophon/colophon`, section 9
- Test: `colophon/tests/test_assembly.py`

**Interfaces:**
- Consumes: FileRecords (Tasks 3–7), `CodexMetadata` and `select_title` (Task 9).
- Produces:
  - `build_corpus(records: list[dict], metadata: CodexMetadata, snapshot_ms: int) -> Corpus`.
  - `Corpus(sessions: dict[str, SessionModel], skipped: list[dict], skipped_records: list[dict], file_diagnostics: dict, db_threads_without_logs: int)`. `skipped` holds the diagnostic entries, `{path, reason}`. `skipped_records` holds the skipped FileRecords themselves; header-only ones still feed the parent resolver (Task 14).
  - `SessionModel`, a dataclass with these fields:
    - `id`, `record` (the FileRecord supplying display facts), `records` (every FileRecord with this session id, in CodexBar's processing order), `archived`, `log_path`, `meta`;
    - `title`, `title_full`, `title_source`;
    - `turns: list[TurnModel]`, `flags: set[str]`;
    - `session_voice`, `tools: ToolCounts`;
    - `start_ms`, `end_ms`;
    - `is_subagent: bool`;
    - filled by later tasks: `parent_id`, `children`, `workspace`, `subfolder`, `units`, `link`.
  - `TurnModel`, a dataclass:
    - `id` (the turn key), `n`, `status`, `start_ms`, `end_ms`, `duration_ms`, `ttft_ms`, `flags: set[str]`;
    - `requests: list[dict]` (Request shape), `final_answer: dict | None`, `tools: ToolCounts`;
    - filled later: `spawned: list[str]`, `used: list[str]`.
  - `classify_open_turns(turns: list[dict], *, mtime_ms: int, snapshot_ms: int) -> list[TurnModel]`.

**Rules:**
- **Skip.** Records whose `status` is not `ok` go into `skipped`, with their status as the reason.
- **A file without `session_meta`** (A4) is its own session, keyed internally `file:<abs path>`, and never merged.
  - Its display id is the trailing UUID of the file stem (regex `([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$`, case-insensitive), else the stem. Flag it `no_session_meta`.
  - If that display id collides with a real session id, or with another meta-less file's display id, the meta-less row's payload `id` is `file:<path relative to the Codex home>`, which is unique.
- **Files sharing a session id** (A4): one `SessionModel` per session id.
  - Its display facts and live state come from the file with the newest mtime (A4).
  - `SessionModel.records` lists every file with that id, in CodexBar's processing order. Task 15 accounts tokens across all of them.
- **Quiet.** `quiet = snapshot_ms − mtime_ms > LIVE_QUIET_MS`, where `mtime_ms = key.mtime_ns // 1_000_000`. A gap of exactly 2 h therefore counts as *within* the threshold.
- **Open turns** (end kind `open`):
  - Not quiet: `running`. `end_ms = snapshot_ms`; `duration_ms = snapshot_ms − start_ms` when the start is known, otherwise unknown. Flag the turn `live`.
  - Quiet: `abandoned`, flagged, and excluded from time.
- **Partial final line.** Quiet: increment `truncated_lines` for that file. Not quiet: no diagnostic.
- **Turn numbering.** `n` is 1-based, in order of `start_ms`; a missing start sorts by `end_ms`, then by the turn's file order.
- **Requests** come from the user `messages` attributed to the turn, plus the voice requests placed on it (`kind: "voice"`, with `before_turn` as placed). `time_unreliable` is true when the log is collapsed and `ts_src == "record_timestamp"`.
- **Final answer.** Apply Task 5's rule.
- **Session flags:**
  - `live` if any turn is running;
  - `aborted`, `interrupted` or `abandoned` when any turn has that status;
  - `uncertain_timing` when any turn is flagged `unknown_duration` or `collapsed`, or any request time is unreliable;
  - `collapsed_timestamps` when the log is collapsed;
  - `history_unresolved` when `history.method == "unresolved"`.
- **Withholding.** For a `history_unresolved` session, `turns`, requests and the session voice are empty, and its time metrics are null.
- **Span.** `start_ms` and `end_ms` are the owned span.
- **Idle and user span** (spec §5.2):
  - `idle_ms = (end_ms − start_ms) − |union of the session's active intervals|`; `null` when the span is unknown.
  - `user_span_ms` is the time from the first to the last kept user request; `null` when any user request time is unreliable or there are fewer than two requests.
  - Both are fields on `SessionModel`.
- **Title.** Call `select_title`, passing the earliest kept user request text as the first user request.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - running versus abandoned on either side of 2 h, with 10-minute margins, plus the exact 2 h boundary (within);
  - **the cache-hit flip:** build one FileRecord, then call `build_corpus` with `snapshot_ms = mtime + 1 h` and again with `mtime + 3 h`. The same record yields running then abandoned, and the partial line yields "still being written" then truncated;
  - interrupted turns are unchanged by snapshot time;
  - two files sharing a session id produce one session, whose display facts and live state come from the newest-mtime file;
  - a file with no `session_meta` becomes its own session, named from its file UUID, and is not merged with a real session that has the same UUID;
  - a skipped empty log, a header-only log and a log without metadata;
  - session flags;
  - `idle_ms` for a session with two turns and a gap;
  - `user_span_ms` is `null` in a collapsed log;
  - a history-unresolved session has no turn or request metrics but keeps its title and links;
  - `time_unreliable` on collapsed logs;
  - requests labelled before-turn come first in their own group (Task 21 renders the order; here, assert the field).
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Assemble sessions and classify live turns at snapshot time`.

### Task 11: Subagent linking, forks and orphans

**Files:**
- Modify: `colophon/colophon`, section 10
- Test: `colophon/tests/test_subagents.py`

**Interfaces:**
- Produces:
  - `link_subagents(corpus: Corpus, metadata: CodexMetadata, snapshot_ms: int) -> None`. It sets `parent_id`, `children`, `link` (`{"spawn_turn", "interaction_turns", "method"}`) and the `forked` flag, and records orphans and inferred links in `corpus` diagnostics.

**Rules (spec §5.3):**
- **Parent.** `metadata.spawn_parents[child]` first, else `meta.parent_thread_id` (from `source.subagent.thread_spawn`).
  - A subagent (`meta.is_subagent`) whose parent id is missing, or not in `corpus.sessions`, is an **orphan**. Its `kind` is `orphan`, it is flagged `orphaned`, and it is listed in `orphaned_subagents`.
- **Your sessions** are the non-subagent sessions plus the orphans.
- **Depth** is `meta.depth` when present, otherwise the parent's depth + 1. `children` lists the direct children, sorted by `start_ms`.
- **Forked badge.** A subagent's `forked_from_id` equals its parent id: badge `forked`.
  - A non-subagent session with `forked_from_id` gets `forked_from` set; the reader shows "forked from <title>" when that session exists, else the id.
- **Spawn turn.** The first method that succeeds, recorded as `method`:
  1. `activity`: a parent `activities` entry with kind `started` and `child_id == child.id`. Use that entry's turn.
  2. `spawn_call`: the parent `spawn_calls` with `task_name == child.agent_path`. Take the latest whose `at_ms ≤ child.created_at_ms` (spec §5.3). If none qualifies, this method fails and the next one is tried.
  3. `root_turn_id`: only when the child's depth is 1. The first `root_turn_id` among the child's own usage records (those whose `thread_id == child.id`) that names a parent turn id.
  4. `inferred`: the parent turn whose interval contains `child.created_at_ms`. The interval is `[start_ms, end_ms]`; running turns end at the snapshot, and abandoned turns end at their last record time. These links are listed in `inferred_links`.
  - If no method succeeds, `spawn_turn` is null and `method` is null.
- **Interaction turns.** Every other parent turn that contains any of:
  - an `activities` entry for the child with kind `interacted`;
  - a `targets` entry matching the child under D10;
  - a `collab_receivers` entry with `child_id == child.id` (D9).

  Exclude the spawn turn, de-duplicate, and order by turn `n`.
- On the parent's `TurnModel`, the `spawned` list gets the child id for the spawn turn, and the `used` list for each interaction turn.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - all four link methods, each with a fixture where the earlier methods fail;
  - `root_turn_id` is ignored at depth 2;
  - the latest-spawn rule with a repeated task name;
  - a subagent used in several parent turns, through activity, target and collab evidence;
  - D10 relative and absolute targets, including a target `/root` that must not match a child;
  - depth-2 nesting;
  - an orphan whose parent log is missing;
  - the edge table taking precedence over the metadata parent;
  - forked badge versus forked-from link;
  - the spawn-call method failing over to `root_turn_id` when every matching spawn is later than the child's start.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Link subagents to parent turns and flag orphans`.

### Task 12: Workspaces

**Files:**
- Modify: `colophon/colophon`, section 11
- Test: `colophon/tests/test_workspaces.py`

**Interfaces:**
- Produces:
  - `normalize_origin_url(url: str | None) -> str | None` (D13);
  - `find_git_root(cwd: str) -> Path | None`: walks up from `cwd` looking for a `.git` entry (file or directory); memoized per run; returns `None` when `cwd` does not exist;
  - `load_workspace_aliases(path: Path) -> tuple[list[dict], list[str]]`;
  - `resolve_workspaces(corpus, aliases) -> dict[str, dict]`, which sets `session.workspace` and `session.subfolder` and returns the payload `workspaces` map.

**Rules (spec §5.7):**
- **Origin.** `meta.git.origin_url`, else the database `git_origin_url`. The normalized form never contains userinfo; a test asserts that `user:token@` is stripped.
- **Key**, the first that applies:
  1. `alias:<name>` when an alias matches. Matching compares origins after normalization, and paths by whole path components, so `/a/b` matches `/a/b/c` but not `/a/bc`.
  2. `origin:<normalized url>`.
  3. `git:<git root path>`.
  4. `cwd:<cwd>`.
  5. `cwd:` for an unknown cwd, named `(unknown)`.
- **Name:**
  - the alias name;
  - for an origin, the last path segment of the normalized URL;
  - for a git root or cwd, the folder name with the home directory shown as `~`;
  - a cwd equal to the home directory is `~ (home)`; a non-git cwd is shown as `<abbreviated path> (no repo)`.
- **Subfolder.** The cwd relative to the git root, when the root exists and differs from the cwd. Otherwise `null`. For alias path matches, it is relative to the matching alias path.
- **Alias file errors.**
  - JSON syntax errors report `JSONDecodeError.lineno`. Schema errors report the alias index and the field.
  - On any error the whole file is ignored and the message goes to stderr and to `diagnostics.workspaces_file`. The run continues.
  - A missing file is not an error.
- **Subagents** take their own cwd's workspace. Drill-down filtering applies §5.9 in the page.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - every URL form: `git@`, `ssh://` with a port, `https` with credentials, uppercase host, `.git` and a trailing slash;
  - git-root detection with a `.git` file (worktree style) and a `.git` directory;
  - a missing cwd falls back to the `cwd:` key;
  - alias by origin and by path prefix;
  - the component-boundary rule;
  - invalid alias JSON (line reported) and an invalid alias schema (index reported), both ignored with the run continuing;
  - home naming;
  - the subfolder chip.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Resolve Colophon workspaces with aliases and subfolders`.

## Phase 4 — Tokens and cost

### Task 13: Pricing port: normalization, catalog lookup, resolver, formula

**Files:**
- Modify: `colophon/colophon`, sections 3 and 14
- Create: `colophon/tests/catalogs.py` (synthetic models.dev catalogs as Python dicts)
- Test: `colophon/tests/test_pricing_port.py`
- Modify: `colophon/docs/token_rules.md`

**Interfaces:**
- Produces:
  - `CURATED_BUNDLED: dict` (the JSON block in §3);
  - `normalize_codex_model(raw: str) -> str`;
  - `codex_models_dev_pricing_targets(raw: str) -> list[tuple[str, str]]`;
  - `class ModelsDevIndex`, with `from_catalog(catalog: dict) -> ModelsDevIndex` (openai provider only) and `pricing(provider_id: str, model_id: str) -> dict | None` (the port of `ModelsDevCatalog.pricing` → `ModelsDevProvider.pricing(modelID:)` → `ModelsDevModel.pricing`, including `ModelsDevModelIDNormalizer.candidates` and `isPriceable`);
  - `resolve_rates(model_key: str, index: ModelsDevIndex | None) -> dict | None`, the full port of `resolvedCodexPricing(model: model_key)` minus its historical branch. It returns `{"per_million": {...}, "long_context": {...} | None}` with every field filled, converted exactly (A4). It accepts a raw key: the catalog lookup tries the raw key first, while the bundled table and normalization use `normalize_codex_model(model_key)`;
  - `cost_usd(entry: dict, *, input: int, cached: int, output: int) -> float`, with cache write fixed at zero (A4);
  - `priority_cost_usd(rates_entry: dict, priority: dict | None, *, input: int, cached: int, output: int) -> float | None`;
  - `codex_api_fast_multiplier(model: str) -> float | None`: a direct port of `codexAPIFastMultiplier` (lines 682–688), used only for A1's priced-model override.
  - `HISTORICAL_CUTOFFS: dict[str, int]`: model → cutoff epoch ms, ported from `codexHistoricalPricing` (lines 394–407). Used by A4's override step 1 and by the curated seed.

**Rules:**
- **`CURATED_BUNDLED`.** Transcribe upstream's `codex` table (lines 84–208) into JSON, keyed by model id, with upstream field names and per-token units:
  `inputCostPerToken`, `outputCostPerToken`, `cacheReadInputCostPerToken`, `cacheWriteInputCostPerToken`, `thresholdTokens`, `inputCostPerTokenAboveThreshold`, `outputCostPerTokenAboveThreshold`, `cacheReadInputCostPerTokenAboveThreshold`, `cacheWriteInputCostPerTokenAboveThreshold`.
  - Omit `nil` fields.
  - Add `displayLabel` only if upstream has it; it is unused.
  - Write the numbers exactly as the Swift literals (for example `1.25e-06`).
  - Task 24's maintainer script checks this against upstream (A2). The suite checks the schema, plus a hand-written spot table of three entries that the resolver tests use.
- **`normalize_codex_model`.** Port the function line by line, with `CURATED_BUNDLED` keys standing in for `self.codex`.
- **`resolve_rates`.** The port of `resolvedCodexPricing`, minus its historical branch. A key equal to `unknown` resolves to nothing.
  - Its output is converted to per-million fields with the fill order in spec §5.6, "Fill order", and is authoritative in upstream `codexCostUSD`:
    - `longInput = inputAbove ?? input`;
    - `longOutput = outputAbove ?? output`;
    - `longCached = cacheReadAbove ?? cacheRead ?? longInput`;
    - `longCacheWrite = cacheWriteAbove ?? cacheWrite ?? longInput`;
    - then `cached = cacheRead ?? input` and `cache_write = cacheWrite ?? input`.
  - `long_context` is present only when a threshold exists.
  - Convert as A4 states. A per-token value becomes per million via `float(Decimal(repr(x)).scaleb(6))`, and per-million values from models.dev are used as given.
  - A test asserts that `per_million / 1_000_000` is within one ulp of every `CURATED_BUNDLED` per-token literal (`math.ulp`). It also asserts that the catalog path reproduces `P / 1_000_000` exactly.
- **`cost_usd`.** A port of `codexCostUSD(pricing:…)` (lines 694–731), in its exact operation order. Per-token rates are `per_million / 1_000_000`. Cache-write tokens are passed as **zero**, as upstream passes zero for Codex rows (A4). Use the long-context rates when `long_context` is present and `input > threshold`.
- **`priority_cost_usd(rates_entry, priority, …)`.** `priority` is passed separately: A4 takes it from `history.pick(n, t).priority`, which may differ from the rates entry in override step 2. Returns `None` when `priority` is `None`, or when `max_input_tokens` is not null and `input > max_input_tokens`. Otherwise it returns `multiplier × cost_usd(rates_entry, …)`.

**Tests**, using catalogs built in `tests/catalogs.py` from the models.dev shape (`cost.input`, `cost.output`, `cost.cache_read`, `cost.cache_write`, `cost.context_over_200k`, `cost.tiers`), with synthetic ids such as `gpt-synthetic-1`:
- normalization:
  - aliases: `gpt-5.6` → `gpt-5.6-sol`, `gpt-reserve`, both Daybreak aliases;
  - the `openai/` prefix;
  - bundled ids kept;
  - a dated suffix stripped only when the base is bundled;
  - compact-date (`-YYYYMMDD`), `-vN:N` and `@` spellings not folded;
- the lookup chain:
  - a dated or versioned id priced through the normalizer candidates;
  - a model with no input or output is not priceable;
  - a model with no `cost`;
  - a provider-qualified id for another provider is unpriced;
  - an `openai/…` id is priced;
- the resolver:
  - catalog models with and without `cache_read`, with and without `cache_write`, and with and without a `context_over_200k` block;
  - bundled models with and without a bundled threshold;
  - a bundled model missing from the catalog;
  - the threshold precedence: bundled, then catalog 200 000, then none;
  - a `tiers` shape does **not** change the threshold;
- the formula:
  - cached clamped to input;
  - logged cache-write tokens do not change the cost;
  - long context at 200 001 and not at 200 000;
  - the 200k–272k band;
  - `output_tokens` used as reported;
- priority: under and over the cap; `gpt-6-astra` with no cap; no multiplier;
- `codex_api_fast_multiplier`: every listed model, a dated spelling folding to a listed model, and an unlisted model returning `None`.

Each expected number has a derivation comment, for example `# 1000 uncached × 1.25/1e6 + … per codexCostUSD L700-L720`.

One of these checks also matches a CodexBar reference value. A `catalogs.py` catalog whose `gpt-5.4` entry has `cost.input` 1.5 and `cost.output` 9 gives `cost_usd(resolve_rates("gpt-5.4", index), input=1000, cached=0, output=100) == 0.0024` within 1e-12. Derive it by hand (`1000 × 1.5/1e6 + 100 × 9/1e6`); the derivation comment notes that CodexBar computed the same value for reference case `a10` (Task 14). The test reads no fixture file, because the reference cases are committed only in Task 14.

**Steps:**
- [ ] **Step 1: Write the tests**, then run them and see them fail.
- [ ] **Step 2: Implement.** Add the `token_rules.md` rows:
  - ported: normalization, lookup chain, resolver, formula, priority;
  - adapted: per-million storage with exact conversion, and no historical branch (history lives in the ledgers);
  - recorded deviation: OpenAI-only catalog and provider-qualified ids (A4 item 5). Per C1, the raw-alias cases are *ported, matches upstream*.
  - the note about the models.dev `tiers` threshold of 272 000 versus upstream's 200 000.
- [ ] **Step 3: Run the suite.** Commit with the subject `Port CodexBar model normalization and Codex pricing`.

### Task 14: Token accounting port (fallback path)

This is the highest-risk task. Port; do not redesign. Read every upstream function in the reference map's token rows **before** writing Python. Keep upstream's structure: one Python function per Swift function, with the same name in snake_case. Keep the nested closures as inner functions or a small class holding the same mutable locals. Give each ported function a header comment naming its upstream file, function and commit.

**Files:**
- Modify: `colophon/colophon`, section 12
- Create: `colophon/tests/token_cases.py` (harness), `colophon/tests/test_token_port.py`
- Commit (prebuilt, already in the working tree): `colophon/tests/fixtures/token_cases/`, `colophon/tests/fixtures/scrubbed/`, `colophon/tests/tools/build_token_cases.py`, `colophon/tests/tools/codexbar_expected.py`, `colophon/tests/tools/scrub_codex_logs.py`
- Modify: `colophon/docs/token_rules.md`

**Interfaces:**
- Consumes: FileRecord `token_stream` (Task 7), and `normalize_codex_model` with `CURATED_BUNDLED` (Task 13). Upstream normalizes every row's model.
- Produces:
  - `Totals`: a frozen dataclass `(input: int, cached: int, output: int, reasoning: int | None)`.
  - The ported helpers: `codex_totals_equal`, `codex_totals_at_least`, `codex_looks_like_stale_regression`, `codex_should_prefer_total_delta`, `codex_add_totals`, `codex_total_delta`, `codex_divergent_total_delta`, `codex_contained_total_delta`, `codex_post_latch_event_delta`, and the optional-int helpers.
  - `CodexTotalsTracker` (with `SEEN_RAW_TOTALS_LIMIT = 64`) and `CodexSnapshotAccumulator`.
  - `classify_subagent_rollout(leaf_session_id: str | None, observations: list, has_explicit_parent: bool) -> RolloutShape`, the port of `CodexSubagentRolloutShape.classify`.
  - `ForkBaseline`: `("resolved", Totals | None)` or `("unresolved", None)`.
  - `class InheritedTotalsResolver(streams: dict[str, TokenStream])`: one stream per session id, the newest-mtime file for ids shared by several files (A4 item 6). Meta-less files never enter. It provides `inherited_totals(session_id: str, cutoff_ts: str) -> ForkBaseline`, holds a recursion guard of 64 and a per-session memo, and parses a parent with `parse_codex_usage(parent_stream, resolver=self)`.
  - `parse_codex_usage(stream: TokenStream, *, resolver: InheritedTotalsResolver | None) -> CodexUsageResult`, where `CodexUsageResult` has:
    - `rows: list[UsageRow]`;
    - `token_snapshots: list[tuple[str, Totals | None, Totals | None]]`;
    - `session_id`, `forked_from_id`;
    - `has_unresolved_fork_baseline: bool`;
    - `fork_accounting_state: dict | None`;
    - `model_timeline: list[tuple[float, str | None]]`;
    - `buffered_unresolved_fork_lines: list | None`;
    - `buffered_subagent_lines_retained: bool` (a non-empty `bufferedSubagentLines` list was returned);
    - `depends_on_parent: bool`.
  - `UsageRow(file: int, line: int, event_index: int, turn_id: str | None, ts: str, at_ms: int, timestamp_unix_ms: int | None, day_key: str, model_raw: str, model: str, input: int, cached: int, output: int, reasoning: int | None, kind: "token_count" | "bare")`.
    - `file` indexes `SessionModel.records`.
    - `event_index` is upstream's per-file `codexUsageRowIndex`, shared by bare and token-count rows (lines 4290–4291, 4635–4636).
    - `timestamp_unix_ms` is upstream's `unixMilliseconds` (lines 4262–4267): `round(date × 1000)` where `date = dateFromTimestamp(ts)` (`CostUsageTimestampParser.parseISO`). It is `None` when `parseISO` rejects a string that the lenient `dayKeyFromTimestamp` (`CostUsageScanner+Timestamp.swift`, line 104) still accepts, for example a space instead of `T` (case `a12`).
    - `at_ms` is `timestamp_unix_ms` when that is not `None`; otherwise it is the instant `dayKeyFromTimestamp` builds from the string's components (time zeroed when byte 10 is not `T`, zone from the last `Z`, `+` or `-` at index 11 or later). Port that function as `day_key_from_timestamp(text) -> tuple[str, int] | None` returning both the day key and that instant.
    - `day_key` is upstream's local-calendar day key (`Timestamp.swift`: `dayKeyFromTimestamp` lines 104–182, `dayKeyFromParsedISO` 184–187), computed in the compiling machine's local zone, as upstream's `Calendar.current`.
  - `account_logs(records: Iterable[FileRecord]) -> dict[str, CodexUsageResult]`, keyed by absolute log path: builds `streams` by the parent-resolution rule below, one `InheritedTotalsResolver`, and calls `parse_codex_usage` for every record. It is the only place that logic lives; the Task 14 harness and Task 15's `compose_usage` both call it. Pass every record, including skipped header-only ones, because they feed parent resolution.

**Port notes (load-bearing):**
- The line routing (`routeFastLine`, the pending-subagent buffer and the unresolved-fork buffer) runs over the cached stream instead of over file bytes. The buffering semantics stay exactly as upstream: subagent files buffer until end of file, then classify, then replay.
  - Port the end-of-file gate exactly (lines 5016–5028). When `stream.unconsumed_tail` is true, upstream's `parsedBytes` stops at the last committed line, so `hasUnconsumedPhysicalTail` is true. A subagent file in pending mode then skips the end-of-file classification and replay, and its buffered lines produce **no rows** (the returned `bufferedSubagentLines` stay buffered).
  - When `unconsumed_tail` is false, the classification runs.
- **The pre-pass.** The `P` observation (Task 7) is handled first, with `handle_session_metadata`. A subagent thread switches on pending mode from the start, as upstream lines 4698–4709 do.
- `tokenSnapshots` collects every `T` observation with a `last` or a `total`, in route order. The resolver uses it for a parent.
- **Snapshot resolution** (`snapshotResolution(for:)`, adapted):
  - **Parent resolution:** `streams` holds every discovered file whose pre-pass (`P` observation) yields a session id, keyed by that id, **including header-only files**, which upstream maps and parses to an empty snapshot list. For an id shared by several files it holds the newest-mtime file (A4 item 6). Meta-less files never enter.
  - A parent id missing from `streams` is unresolved, and reported as `missing` in diagnostics.
  - Upstream also marks a parent incomplete when its parsed session id is `nil` or differs from the requested one (lines 1909–1932). Here every stream's key is the file's own parsed session id, so neither case can occur. Assert this in the resolver.
  - **The production path is normative:** `cachedSnapshotResolution` (lines 1957–2003) together with `isUnresolvedMissingParentFork` (`CostUsageScanner+ForkCoverage.swift` lines 43–46). It is not the test-only direct-parse branch.
    - `isComplete = not stream.unconsumed_tail and not (parent_result.buffered_subagent_lines_retained or parent_result.buffered_unresolved_fork_lines)`. That mirrors `hasBufferedCodexForkRetryLines` (`CostUsageCacheModels.swift` lines 381–391), which tests for **non-empty** lists: buffered subagent lines (lines 5253–5258) or buffered unresolved-fork lines (line 5259).
    - `CodexUsageResult` carries `buffered_subagent_lines_retained: bool` and `buffered_unresolved_fork_lines: list | None`, each set exactly as the upstream return values.
    - **Withheld snapshots** (port of `isUnresolvedMissingParentFork`, `CostUsageScanner+ForkCoverage.swift` lines 43–46, with `codexForkBaselineDependencyKey`, `CostUsageScanner+CacheHelpers.swift` lines 1297–1308). A parent's snapshots are withheld (`indexedEvents = nil`, line 1995) when it has a `forked_from_id`, its `depends_on_parent` is true, **and** its own parent baseline did not resolve or its parent is missing.
      - A lineage-only fork (`depends_on_parent` false, key `mode:lineage-only:v1`) always offers its snapshots, even when its own parent is missing.
      - Withheld snapshots make `inherited_totals` return **unresolved** immediately (`hasSnapshotSource`, lines 1646–1648 and 1710–1714).
      - The completeness check (lines 1716–1723), the `inherited == nil` rule (lines 1725–1731) and the `forkOrigin` fallback (line 1789) apply only when snapshots are offered.
    - An incomplete parent triggers the cutoff-coverage check.
  - `isFork` is `parent_result.forked_from_id is not None`.
  - `forkOrigin` is `parent_result.fork_accounting_state`.
  - Checkpoints are omitted: replay from the first snapshot, which gives the same result.
  - Keep the cutoff logic exactly: an unparseable cutoff falls back to lexical comparison, an empty cutoff is unresolved, and the coverage check applies when the parent is incomplete.
- **Timestamps.** A row is produced only when upstream would produce a day key from the timestamp (`dayKeyFromTimestamp ?? dayKeyFromParsedISO`); case `a12` shows a date-only string being dropped. Port `dateFromTimestamp` (`parseISO`) and `dayKeyFromTimestamp` for the formats upstream accepts; `at_ms` follows the `UsageRow` rule above.
- **The day range** (`CostUsageDayRange`) is not ported: every row is in range.
- **`model_timeline`** lists every assignment to `currentModel` as `(position, value)`, in processing order:
  - `position` is the observation's line for `C` and `XC`;
  - the reset to `None` at an owned suffix happens at end of file and has no line of its own, so it is recorded at the **physical** line of the observation whose `uidx` equals `ownedSuffix.startLineIndex`, minus 0.5;
  - a pre-suffix entry recorded before the reset is dropped from the timeline, because upstream never replays it.
  
  Task 15 looks up the last entry with `position < record line`.
- `UsageRow.turn_id` is upstream's `record.turnID ?? currentTurnID` for token counts, and `currentTurnID` for bare usage.

**The port notes above say what to adapt; the semantics are upstream's.** Where a note and the upstream function disagree, upstream wins, and the reference cases below decide. Do not restate upstream logic in comments or docs beyond a pointer to the function.

**Reference cases (prebuilt; they are the expected values).** The planner built these on 2026-10-03. They are in the working tree, uncommitted, when Task 14 starts.
- `colophon/tests/fixtures/token_cases/`: 35 synthetic cases, each written on its own calendar day from 2025-03-01 (CodexBar's own parsing buckets `a12`'s space-separated timestamp on the previous day), plus `index.json` (case order) and `catalog.json` (the pinned, synthetic models.dev-shaped catalog every case was priced with). Each case is `<name>/codex-home/` (the logs), `case.json` (`name`, `description`, `day_utc`, `files`, `mtimes_ms`) and `expected.json`. `colophon/tests/tools/build_token_cases.py` writes the inputs; read a case's builder function there to see exactly what its logs contain.
- `colophon/tests/fixtures/scrubbed/`: 7 scrubbed real cases in the same per-case layout, plus `index.json`. Their `case.json` has no `day_utc` and records the scrub (token scale 2). There is no second catalog: every case in both sets was run with `token_cases/catalog.json` (each `expected.json` records its sha256).
- `expected.json` comes from `colophon/tests/tools/codexbar_expected.py`, which runs the CodexBar CLI built at `3bbf6bc48` (`cost --provider codex --period all --format json`) in an isolated fake home until three consecutive results are identical. Its keys:
  - `files`: one entry per log CodexBar indexed, sorted by `file` (the path relative to `codex-home`): `{file, session_id, scan_complete, rows}`. `rows` are the file's emitted usage rows in emission order (CodexBar's `usage_rows`), each `{row_index, eventIndex, day, timestampUnixMs, turnID, model, rawModel, pricingModel, pricingMode, input, cached, output, reasoning}`.
  - `day_aggregates`: CodexBar's totals per `(day, model)`: `input_tokens`, `cached_tokens`, `output_tokens`, `reasoning_tokens`, `request_count`, the standard and priority splits, `authoritative_cost_nanos`.
  - `report`: the CLI's `daily`, `totals`, `coverage`, `provenance`, `historyCoverageIsEstablished` and `error`. CodexBar omits zero-valued token keys (for example no `cacheReadTokens` when it is 0), and a day with no tokens can appear as `{"date": …}` alone.
  - `bucket_tz`: the zone CodexBar used for day keys (`America/New_York`; it comes from the maintainer's CodexBar settings and is recorded so tests can match it).
  - `generator`: tool, upstream commit, CLI sha256, catalog sha256, command. Floats are rounded to 12 significant digits, because CodexBar's own cost sums vary by about one ulp between runs.
- Already verified for every case: rows sum to `day_aggregates`, which sum to `report.daily`; regeneration is byte-identical; and no result depends on file order except `b10` (A4 item 7). For each scrubbed case, CodexBar's rows on the scrubbed copy equal its rows on the private original after mapping ids, days and the token scale.
- `s04` and `s07` pin a CodexBar behavior that the user decided on 2026-10-03 to keep ("for now I'm fine withy July/August being short matching CodexBar", verbatim). In 168 subagent logs from July and August 2026, `subagent_history_start_ordinal` equals the file's record count, so no record reaches it, and CodexBar suppresses the whole file as an unowned copied prefix (`hasExplicitBoundary` → `suppressUnownedCopiedPrefix` in `parseCodexFileCancellable`). Those totals do not appear in the parent logs. Removing the ordinal makes CodexBar's own fallback count about 3.1 billion input tokens, roughly three times the sum of the files' per-response `last` usage, so no verifiable correction exists. Do not "fix" it in the port.
- A case's `description` names the behavior it pins. The cases that end unresolved do so by design (`historyCoverageIsEstablished` false, `coverage.unmetered` > 0, a child file with no rows): `b02`, `b03`, `b05`, `b08`, `c07`, `c09`, `c11`, and `b10` for CodexBar only.

**Harness (`colophon/tests/token_cases.py`, no test functions):**
- `load_case(root: Path, name: str, tmp: Path) -> Case` copies `codex-home` into `tmp` and applies `case.json` `mtimes_ms` with `os.utime(path, ns=(ms * 1_000_000, ms * 1_000_000))`. Git does not keep mtimes, and the duplicate-id rule depends on them.
- `account_case(colophon, home: Path) -> dict[str, list[UsageRow]]` enumerates the logs with Task 8's `discover_logs(home)` (the `sessions` and `archived_sessions` roots, with the size, mtime and `archived` flag `parse_log_file` needs), parses each with `parse_log_file`, calls `colophon.account_logs` on the records, and keys the rows by path relative to `home`.
- Day keys follow `expected["bucket_tz"]`: a fixture sets `TZ` to it and calls `time.tzset()`, and restores both afterwards.
- Compare, for each entry of `expected["files"]`, the rows in order and field by field:

| Colophon `UsageRow` | `expected` row |
|---|---|
| `event_index` | `eventIndex` |
| `day_key` | `day` |
| `timestamp_unix_ms` | `timestampUnixMs` (absent or null means `None`) |
| `turn_id` | `turnID` (absent means `None`) |
| `model` / `model_raw` | `model` / `rawModel` |
| `input`, `cached`, `output` | same names |
| `reasoning` | `reasoning` (absent means `None`) |

  - An expected file with `rows: []` must produce no rows. A file Colophon accounts that `expected["files"]` does not list fails the test.
  - `row_index`, `pricingModel` and `pricingMode` are not compared: no case has a trace database, so every row is standard, and Task 15 owns priority.
  - Then compare the `(day, model)` sums of input, cached and output with `day_aggregates`, and the per-day sums with `report.daily` (`inputTokens`, `cacheReadTokens`, `outputTokens`). In `report.daily` an absent key counts as 0, so an entry with only a `date` means no tokens that day. Compare over the union of days and keys from both sides, treating anything missing as 0. (Cases `a09`, `a10`, `b02`, `b05` and `c09` rely on this.)
  - Costs are not compared in Task 14. Colophon prices with its dated history (A4 item 2), so its cost for 2025 usage can legitimately differ from CodexBar's current rates; Task 24's parity tool owns cost.
  - On a mismatch, the assertion message shows the case description, the first differing row from both sides, and the stage's upstream pointer.
- **`b10` under A4 item 7** replaces the generic checks for that one case:
  - files `…1000` and `…2000` must match `expected.json` row by row;
  - the grandchild `…3000` must yield the same `(input, cached, output, model)` sequence as `b04`'s expected grandchild rows (the two cases have identical token content; only the dates, ids and mtimes differ), with b10's own day and timestamps;
  - the `(day, model)` and per-day sums must equal `b10`'s `day_aggregates` and `report.daily` **plus** the sums of those grandchild rows (CodexBar's numbers leave them out).

**Staged checks.** One parametrized test per stage over the stage's cases, so each stage is one command (from `colophon/`):

| Stage | Cases | What to port for it | Start reading upstream at | Command → expected |
|---|---|---|---|---|
| A, single file | `a01`–`a12` | totals helpers, `CodexTotalsTracker`, `CodexSnapshotAccumulator`, the `parse_codex_usage` core: token counts, bare usage, model in force and its normalization (`a11`), turn ids, lenient timestamps (`a12`) | reference map rows for lines 431–855 and `parseCodexFileCancellable` (4177–5264) | `.venv/bin/python -m pytest tests/test_token_port.py -q -k stage_a` → `12 passed` (plus the deselected count) |
| B, forks | `b01`–`b11` | `InheritedTotalsResolver`, `snapshotResolution` via `cachedSnapshotResolution`, `resolveForkBaseline`, `raiseInheritedBaselineIfContinuedCounter`, the incomplete-parent coverage check | lines 1611–2003; `resolveForkBaseline` and `raiseInheritedBaselineIfContinuedCounter` inside `parseCodexFileCancellable` | `… -k stage_b` → `11 passed`, as above |
| C, subagents | `c01`–`c12` | `classify_subagent_rollout`, the pending buffer and replay, the owned suffix, the end-of-file gate, withheld snapshots (`isUnresolvedMissingParentFork`) | `CodexSubagentRolloutShape.swift`; the end-of-file block of `parseCodexFileCancellable` (from line 5016); `CostUsageScanner+ForkCoverage.swift` lines 43–46 | `… -k stage_c` → `12 passed`, as above |
| D, scrubbed real | `s01`–`s07` | nothing new; real shapes (thread settings records, compaction, long logs, Jul/Aug 2026 start ordinals past the last record) | the stage that owns the failing behavior | `… -k stage_d` → `7 passed`, as above |

Two hand-written unit tests stay in `test_token_port.py`, because the reference cases cannot see them:
- the `model_timeline` reset position: a record on the first owned-suffix line sees no model in force (Task 15 depends on it);
- the resolver's assertion that every stream key is that file's own parsed session id.

**Steps:**
- [ ] **Step 1: Check and commit the prebuilt files.**
  - Confirm the inputs are reproducible: `.venv/bin/python tests/tools/build_token_cases.py --out "$TMPDIR/tc"`, then `diff -r -x expected.json "$TMPDIR/tc" tests/fixtures/token_cases` prints nothing.
  - Commit `tests/fixtures/token_cases/` and the three tools with the subject `Add CodexBar reference cases for the token port`.
  - Commit `tests/fixtures/scrubbed/` in the same commit. The user approved the scrubbed fixtures on 2026-10-03, after the planner's privacy review (generated ids only, synthetic paths and names, no free text; a search for the user's name, home paths, hostnames, emails and URLs found nothing). Still inspect the staged diff for sensitive data, as every commit requires.
- [ ] **Step 2: Write the harness and the staged tests.** Run them: every case fails (the functions do not exist yet).
- [ ] **Step 3: Stage A.** Port, run stage A until it passes.
- [ ] **Step 4: Stage B.** Port, run stages A and B.
- [ ] **Step 5: Stage C.** Port, run stages A–C.
- [ ] **Step 6: Stage D.** Run it; fix the port (never the fixtures) until it passes.
- [ ] **Step 7: Add `token_rules.md` rows** for every ported function and every adaptation (stream instead of bytes, no checkpoints, no day range, no resume state, no scan budget; A4 item 7).
- [ ] **Step 8: Run the full suite.** Commit with the subject `Port CodexBar token accounting for Codex logs`.

### Task 15: Usage composition, priority turns and attribution

**Files:**
- Modify: `colophon/colophon`, section 13
- Test: `colophon/tests/test_usage.py`, `colophon/tests/test_priority.py`

**Interfaces:**
- Consumes: Tasks 10, 11, 13 and 14.
- Produces:
  - `load_priority_turns(codex_home: Path, home: Path) -> PriorityTurns`, where `PriorityTurns(turns: dict[str, dict], messages: list[str])`. This is the A1 port plus the sticky merge. It writes `priority-turns.json` atomically when it changes.
  - `UsageUnit`, a dataclass:
    - `session_id`, `file`, `line`, `turn_id`, `display_turn: str | None`, `at_ms`, `timestamp_unix_ms: int | None` (upstream's `pricingDate`; from `UsageRow` or the record);
    - `model_raw`, `model` (normalized via `normalize_codex_model`, Task 13);
    - `priority: dict | None` (the priority-turn metadata), `tier: "priority" | "standard"`;
    - `input`, `cached`, `cache_write`, `output`, `reasoning`;
    - `source: "record" | "token_count" | "bare"`;
    - `cost_usd: float | None = None` and `period: tuple[str, int] | None = None`, which Task 18 sets.
  - `compose_usage(corpus: Corpus, priority: PriorityTurns) -> None`. It sets `session.units`, computes the fallback results with Task 14's `account_logs` over every record (including `corpus.skipped_records`), accounts every file of every session, and flags `fork_baseline_unavailable`. It assigns `UsageRow.file` as the index of the row's file in `SessionModel.records`.

**Rules:**
- **Priority detection (A1).**
  - Open `<codex-home>/logs_2.sqlite` as `file:…?mode=ro`. A missing database is not an error; leave the sticky entries only.
  - Run one query, ordered by `rowid`:

```sql
select rowid, ts, feedback_log_body from logs
where rowid > 0 and ts >= 0
  and (feedback_log_body like '%websocket request:%'
       or feedback_log_body like '%response.completed%'
       or feedback_log_body like '%service_tier: Some(Some("priority"))%')
order by rowid
```

  - For each row:
    - a completed-trace row (port of `parseCodexCompletedTraceRow`) records `completed[turn_id][rowid] = model`;
    - else a priority row (port of `parseCodexPriorityTraceRow`, which falls back to `parseCodexPrioritySubmissionRow`) sets `turns[turn_id] = {thread_id, model, timestamp}`, where `timestamp` is the row's `ts`, as upstream reads it.
  - Completed rows for turns that are not yet priority are held in the pending FIFO, with upstream's 4,096-turn eviction (A1). They move to the turn when its priority row arrives.
  - Finally, for every priority turn with completed rows, set its model to the model at the maximum rowid.
  - A `sqlite3.Error` adds a message to `diagnostics.trace_db`, and the sticky entries alone are used.
- **Sticky merge.** Stored entries plus the database entries; the database wins per turn id. `first_seen_ms` is set when an id is first stored. The file is written only when the content changes.
- **Primary path** (A4 item 1). The usage records with `thread_id == session.id` from every file of the session, de-duplicated by `(thread_id, response_id)`. The first one in CodexBar's processing order, then by `line`, wins.
  - A record without a `response_id` is never de-duplicated.
  - Components are clamped at ≥ 0. `cached = max(cached_input_tokens, cache_read_input_tokens)`, and `reasoning` is clamped to output, using the same mapping as upstream's `tokenTotals` (Task 7).
  - Context-compaction records (a `token_usage_record` directly followed by a `compacted` record) are ordinary primary units. Test this explicitly.
  - Each record's model is the model in force at its line, in **its own file's** `model_timeline`: the last entry whose `position < line`, or `unknown` when there is none or its value is `None`.
  - When a pending subagent file was not replayed (`unconsumed_tail`), its `model_timeline` is empty. For that file only, the model in force is taken from its `C`/`XC` observations in order, with no owned-suffix reset. This is a Colophon primary-path rule, since the primary path is Colophon's own (A4 item 1). Test it.
- **Source selection.**
  - `primary_turns` is the set of `turn_id`s of the primary units.
  - A fallback row (token count or bare) is used when its `turn_id is None` or not in `primary_turns`.
  - Fallback rows from several files of one session are de-duplicated with the ported `uniqueCodexRows` / `codexCrossFileRowKey` (A4), processing the files in CodexBar's order.
    - Rows of one file are never de-duplicated against each other: keys are checked against the seen set, and the file's own keys are added after its loop (lines 514–531).
  - `cache_write` is kept from the record for display (0 on the fallback path). It is never billed (A4).
- **Attribution (D8).** `display_turn` is the turn id when that turn is displayed and owned in the session (in `session.turns`) **and** the unit's record is not inherited. The inherited status comes from checking the unit's `line` against `history.inherited_lines` of **its own file** (`records[unit.file]`). Units from a non-display file are attributed by turn id alone. Otherwise `None`, which is the "tokens outside displayed turns" line.
- **Tier.** `priority` when `priority.turns` contains the unit's `turn_id`, else `standard`.
- **Fork baseline unavailable.** When `CodexUsageResult.has_unresolved_fork_baseline` is true, add the session id to `fork_baseline_unavailable`.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - a priority request row with a later completed row overrides the model;
  - a submission-form priority row;
  - a completed row **before** the priority row still overrides the model (maximum rowid);
  - pending eviction at the boundary: upstream evicts when the retained count is `> 4096` (line 898).
    - The priority turn's own completion comes first, followed by the completions of 4,095 other turns: nothing is evicted, and the completed model is used.
    - With 4,096 other turns, the priority turn's pending entry is evicted, and the request model is used;
  - non-priority request rows are ignored;
  - a missing trace database leaves the sticky entries only;
  - a locked database records a diagnostic and continues;
  - sticky persistence: a turn seen in run 1 is still priority in run 2 after its rows are deleted from the synthetic database;
  - database fields override stored ones;
  - primary records counted once per `response_id`;
  - a foreign-thread record is ignored;
  - a turn with only `token_count` inside a file whose other turns have records uses fallback deltas for that turn only;
  - a bare line in a turn with records is discarded, and a bare line outside any turn is counted;
  - a forked log whose counted deltas fall on inherited records lands in "outside displayed turns";
  - **the invariants**, over a fixture with several turns, an inherited prefix and depth-1 and depth-2 subagents:
    - the sum of `display_turn` units plus the outside units equals the session's own units, for every component;
    - the session's overall total (own plus every descendant's own, computed through `children` recursively) equals the sum of all units of the session and its descendants, each unit counted once (spec §5.5, §5.9);
  - tier switching between turns of one session;
  - `fork_baseline_unavailable` when the parent log is missing;
  - a fork whose parent id is shared by two files resolves against the newest-mtime copy, and `duplicate_session_ids` lists the id;
  - two files of one session with overlapping fallback rows count each distinct row once (`uniqueCodexRows`), and their primary records once per `response_id`;
  - a compaction record is counted on the primary path;
  - a non-zero logged cache write changes no cost.
- [ ] **Step 2: Implement**, then run the suite. Add the A1 rows to `token_rules.md`: ported (trace detection, pending FIFO); adapted (cold scan only, no memo or cursor; the `--codex-home` database location (A4 item 4)); Colophon addition (sticky memory).
- [ ] **Step 3: Commit** with the subject `Compose Codex usage units with priority-turn detection`.

### Task 16: Price history: ledgers, validation, resolution, recording, curated seed

**Files:**
- Modify: `colophon/colophon`, sections 3 and 15
- Create: `colophon/tests/tools/seed_price_history.py`
- Test: `colophon/tests/test_price_history.py`

**Interfaces:**
- Produces:
  - `CURATED_PRICE_HISTORY: dict` (the JSON block);
  - `validate_ledger(doc, *, curated: bool) -> LedgerCheck`, where `LedgerCheck(entries: list[dict], errors: list[str], warnings: list[str])`. Errors name the entry index and the problem;
  - `class PriceHistory`, constructed with `PriceHistory(curated: list[dict], user: list[dict])`, providing:
    - `pick(model: str, at_ms: int) -> Pick | None`, where `Pick(entry: dict, period_index: int, before_first: bool)`;
    - `entries_for(model) -> list[dict]`;
    - `has_any(model) -> bool`;
  - `record_catalog_rates(history: PriceHistory, index: ModelsDevIndex, fetched_at_ms: int, recording_ids: set[str], now_ms: int) -> list[dict]`;
  - `append_user_ledger(path: Path, new_entries: list[dict], start_mtime_ns: int | None) -> tuple[bool, str | None]`, returning `(appended, warning)`.

**Rules (spec §5.6 is normative; restated here for the load-bearing points):**
- **Validation** follows the spec table and the bullet list exactly. The user ledger rejects `source: curated` and a `null` `effective_from`. The curated block requires `source: curated` and allows `null`.
  - Exact duplicates collapse with a warning.
  - Conflicting duplicates are errors. They share model, `effective_from` and `source`, and differ in a field other than `note` and `recorded_at`.
  - An invalid user ledger means: no costs, no recording, and the error to stderr and `diagnostics.ledger`.
- **Pick.**
  - Merge both ledgers. The `model` field is the **pricing key**, matched exactly with no re-normalization. It is the normalized id, except for A4's override step 2, where it is `catalog:<c_m>|<n>`.
  - Pick the latest `effective_from ≤ at`; `null` sorts first.
  - On ties, `manual` beats `catalog`, which beats `curated`.
  - Usage before a model's first entry uses its **earliest** entry, with `before_first = True`, and reports `history_begins` with that entry's `effective_from`. Only dated entries can produce this, because a `null` entry precedes everything.
- **Transient entries.** When a model has no entry in either ledger but the catalog index prices it (whether recording ran or was skipped this run), price it with `resolve_rates(id, index)` as a transient period, and report `unrecorded_catalog_rates`. Otherwise the model is **unpriced**; this is the single definition.
- **Recording** runs only when a catalog is available **and** the user ledger is valid.
  - `T = fetched_at_ms` truncated to the second (D15).
  - The recording set is the union of: the normalized id of every priceable `openai` catalog model; the run's pricing keys, passed in as `recording_ids` and defined in Task 18's `run()` step 9; and every key in either ledger.
  - `recording_ids` is a mapping `key → source_model` (A4 override step 2). Keep only the keys whose `source_model`'s lookup chain finds a priceable catalog entry, and compute `resolve_rates(source_model)` for them.
  - For each id:
    - skip it if any entry for that model has `effective_from == T`;
    - compute `resolve_rates`;
    - copy `priority` from `pick(id, T)` when that pick exists;
    - compare with the latest **non-manual** entry at or before T, on the standard rates and on the long-context threshold and rates;
    - append when no such entry exists or any compared field differs.
  - New entries carry `source: "catalog"`, `effective_from: T`, `recorded_at: now`, `approximate_date: true`.
  - Never use the catalog's `last_updated`.
- **Writing.** Stat `price-history.json` at the start of the run and keep its `mtime_ns`. Before appending, re-read and re-stat it. If `mtime_ns` changed, skip, warn `price-history.json changed during the run; recording skipped`, and price with transient entries. Otherwise parse, append to `entries`, and write with `atomic_write_json` (indent 2). Existing entries must stay JSON-equal.
- **The curated seed** (maintainer procedure):
  1. `tests/tools/seed_price_history.py --snapshot <models.dev api.json> --snapshot-date <YYYY-MM-DD>` loads the launcher and prints the `CURATED_PRICE_HISTORY` JSON.
  2. Its content follows spec §5.6 "Curated data", with the historical rates from upstream `codexHistoricalPricing` (lines 394–407):
     - `gpt-5.6-sol`, `gpt-5.6-terra` and `gpt-5.6-luna` get an entry with `effective_from: null` carrying the historical rate, and an entry at their cutoff instant carrying `resolve_rates(id, snapshot)`;
     - every other seeded id gets one `null` entry;
     - the seeded ids are the `CURATED_BUNDLED` keys plus the normalized id of every priceable openai model in the snapshot, resolved against the snapshot and `CURATED_BUNDLED` only;
     - `priority` comes from upstream `codexAPIFastMultiplier`: ×2 for `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.6-sol`, `gpt-5.6-terra` and `gpt-5.6-luna`, capped at 272 000; ×2 for `gpt-6-astra` with a `null` cap; ×2.5 for `gpt-5.5`, capped at 272 000;
     - every seed entry has `source: curated`, and the note `seed from models.dev snapshot <date>`.
  3. The executor downloads the current models.dev catalog once, runs the tool, pastes the output between the markers, and records the snapshot date, its SHA-256 and the method in `token_rules.md`. The snapshot file is **not** committed.
  - The tool must be deterministic: sorted ids, entries in a stable order, `indent=2`.

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - every invalid-ledger case from spec §5.6, one per test;
  - exact versus conflicting duplicates;
  - curated plus user merge;
  - manual and catalog correcting a curated entry on the same date;
  - a `null` entry precedes everything;
  - the earliest-entry rule and its diagnostic;
  - a transient entry when recording is skipped (ledger edited during the run), plus its diagnostic;
  - unpriced only when there is no entry and no catalog rate;
  - recording:
    - first sight of a model;
    - a detected rate change;
    - idempotence: a second run with the same T appends nothing;
    - recording from a catalog with an older `fetched_at_ms`, which is how a 304, a cached or an `--offline` catalog reaches recording. The status paths themselves are tested in Task 18;
    - a model with only manual entries gets a catalog entry when it appears;
    - a manual entry is never compared against;
    - `priority` is copied forward;
    - a bundled-only id is never recorded;
    - a priceable catalog model added after the snapshot and not yet used is recorded;
    - a seeded but unused model is recorded when repriced;
  - **seed effect:** a ledger seeded from a synthetic snapshot records nothing on first fetch of that same snapshot;
  - an unfolded dated spelling gets its own key, a catalog entry and the "begins" diagnostic;
  - writing: an edited ledger is detected through the mtime; existing entries are unchanged after appends;
  - the curated block passes `validate_ledger(curated=True)`;
  - the historical cutoff boundary: usage 1 ms before the cutoff is priced at the historical rate, and usage at the cutoff at the snapshot rate;
  - a `manual` entry that adds a multiplier from a date D, for a model that has none;
  - C1: a logged alias that has its own catalog entry (for example `gpt-5.6` beside `gpt-5.6-sol`) is priced from the canonical id, as upstream does;
  - a `catalog:<c_m>|<n>` key is recorded only in A4's override step 2 case (`c_m != c_n`), computed from its source model `m`, and picked under its exact key;
  - a catalog that later lists a dated spelling itself at different rates records a rate change, and past usage is unchanged;
  - a catalog-only model (not in `CURATED_BUNDLED`) is priced from its `null` seed entry;
  - the seed tool output for a synthetic snapshot equals a hand-written expected JSON.
- [ ] **Step 2: Implement.** Generate the real seed as described, then run the suite.
- [ ] **Step 3: Add the `token_rules.md` rows** (the seed method, and the historical rates ported). Commit with the subject `Add dated price history with catalog rate recording`.

### Task 17: Catalog fetch

**Files:**
- Modify: `colophon/colophon`, section 16
- Test: `colophon/tests/test_catalog_fetch.py`

**Interfaces:**
- Produces:
  - `fetch_catalog(url: str, cache_path: Path, *, offline: bool, refresh: bool, now_ms: int) -> CatalogResult`;
  - `CatalogResult(status: str, catalog: dict | None, fetched_at_ms: int | None, checked_at_ms: int | None, messages: list[str])`.

**Rules:**
- **Transport.** `http.client.HTTPConnection` or `HTTPSConnection`, chosen by the URL scheme, with `timeout=CONNECT_TIMEOUT_S`. Any other scheme is an error, reported in the messages.
  - Send `If-None-Match: <etag>` only when there is a cached ETag, the cache's `url` equals the configured URL, and `refresh` is false. A cache from a different URL is still a fallback, and its message names both URLs.
  - **Total deadlines enforced by a watchdog.** This is load-bearing. Call `conn.connect()` explicitly and keep `sock = conn.sock`; `http.client` sets `conn.sock = None` when a response will close.
    - A shared `state` holds `sock` (initially `None`) and a `fired` flag, guarded by a `threading.Lock`.
    - The watchdog function sets `fired`, and, if `state.sock` is not `None`, calls `state.sock.shutdown(socket.SHUT_RDWR)` with `OSError` suppressed.
    - Start `threading.Timer(CONNECT_TIMEOUT_S, watchdog)` before `connect()`.
    - Immediately after `connect()` returns, under the lock, store `state.sock = conn.sock`, and if `fired` is already set, raise a timeout.
    - Check `fired` again after `getresponse()` returns. A raised `OSError` or `http.client` error while `fired` is set is also reported as a timeout. Then cancel the timer.
    - For the body, reset `fired`, start `threading.Timer(BODY_TIMEOUT_S, watchdog)`, read, and cancel the timer after the last chunk. The same `fired` rule applies.
    - Read the body with `resp.read(65536)` until it returns `b""`.
  - Redirects are not followed: a 3xx other than 304 is a failure.
  - DNS resolution happens inside `connect()` and is not interruptible. `run()` bounds it from outside (see Concurrency).
- **Outcomes:**
  - `304`: status `not_modified`; the cached catalog; `fetched_at_ms` unchanged.
  - `200`: parse JSON, keep `{"openai": data["openai"]}`, store `{schema, etag, fetched_at_ms: now_ms, url, catalog}` atomically. Status `fetched`.
  - A failure (timeout, connection error, non-2xx, bad JSON, missing `openai`): with a cache, status `cached`; otherwise `unavailable`. The message is added to `diagnostics.catalog`.
  - `offline`: no socket is opened; status `offline` with a cache, `unavailable` without.
  - `checked_at_ms` is `now_ms` when a request was attempted.
- **Concurrency.** `run()` starts `fetch_catalog` in a `threading.Thread(daemon=True)` before the scan. After assembly and before recording, it joins with `timeout = CONNECT_TIMEOUT_S + BODY_TIMEOUT_S + 5` seconds.
  - If the thread is still alive, Colophon continues with the cached catalog and records the diagnostic "catalog fetch did not finish; using cached catalog". The daemon thread never delays exit or Ctrl-C.
  - A daemon thread killed at exit can leave a `.pricing-cache.json.*.tmp` file. At the start of each run, `ensure_runtime_home` removes any `.*.tmp` file in the runtime home older than one hour; younger ones may belong to a concurrent run.

**Steps:**
- [ ] **Step 1: Write failing tests** against a local `http.server.ThreadingHTTPServer` on `127.0.0.1:0`:
  - 200 with an ETag;
  - a conditional request answered 304;
  - `refresh` sends no `If-None-Match`;
  - a header timeout: the server sleeps longer than the constant before responding; patch `CONNECT_TIMEOUT_S` to 0.5 in-process;
  - a body timeout: the server trickles the body; patch `BODY_TIMEOUT_S` to 0.5;
  - a 500 with a cache falls back to the cache;
  - no cache and failure gives `unavailable`;
  - offline opens no socket (assert through the no-network guard);
  - only the openai subset is stored, at mode 0600;
  - a 302 is not followed;
  - an HTTP/1.0 server (the `BaseHTTPRequestHandler` default) that closes after the response works: this guards the saved-socket rule;
  - headers drip-fed slowly, each line within the per-operation timeout but in total longer than `CONNECT_TIMEOUT_S`, time out;
  - a cache whose `url` differs sends no `If-None-Match`.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Fetch the models.dev catalog with conditional requests and budgets`.

## Phase 5 — Compile and CLI

### Task 18: Pricing application, payload, page writing and full CLI pipeline

**Files:**
- Modify: `colophon/colophon`, sections 17 and 19
- Test: `colophon/tests/test_payload.py`, `colophon/tests/test_cli_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1–17.
- Produces:
  - `price_units(corpus, history: PriceHistory, index: ModelsDevIndex | None, *, costs_available: bool) -> PricingReport`. It sets `cost_usd: float | None` and `period: tuple[str, int] | None` (model, period index) on every unit; Task 15's `UsageUnit` declares both fields with default `None`. It returns `PricingReport(periods: dict[str, list[dict]], unpriced: dict[str, int], history_begins: dict[str, int], priority_without_multiplier: dict[str, int], unrecorded: set[str])`.
  - `build_payload(corpus, workspaces, pricing: PricingReport, meta_inputs: dict) -> dict`, matching the [Embedded data contract](#embedded-data-contract-payload_schema--1) exactly.
  - `render_page(payload: dict) -> bytes`.
  - `write_page(path: Path, page: bytes) -> None`.
  - `run(args, *, now_ms: int | None = None, stderr_tty: bool | None = None) -> int`, now complete. `now_ms` and `stderr_tty` are in-process keyword parameters for tests: the snapshot time and the TTY decision. They are not CLI flags or environment variables, and default to the wall clock and `sys.stderr.isatty()`.

**Pricing per unit** (spec §5.6 plus A1). For each unit:
1. Choose the priced model.
   - Standard unit: `unit.model_raw`.
   - Priority unit: price the turn's priority model `m` when `m` is set and `codex_api_fast_multiplier(m)` is not `None` (A1); otherwise price `unit.model_raw`.
2. Choose the rates.
   - Ordinary price: `n_unit = normalize_codex_model(unit.model_raw)`. If `n_unit == "unknown"`, the unit is unpriced. Otherwise use `pick = history.pick(n_unit, at)`; without a pick, a transient entry from `resolve_rates(n_unit, index)`; otherwise the unit is unpriced.
   - Priority override: follow A4's three-step "Priority-override pricing" rule exactly, with `m` the trace model and `n = normalize_codex_model(m)`.
   - Let `n_priced` be `n` for an override, and `n_unit` otherwise.
   - The historical step uses upstream's `pricingDate`, which is `timestamp_unix_ms`. When that is `None`, upstream skips the historical branch, and so does Colophon: for a model in `HISTORICAL_CUTOFFS`, the history is picked at `max(at_ms, cutoff_ms)`. This applies to ordinary units too.
3. The chosen entry supplies the rates (`per_million`, `long_context`).
4. `base = cost_usd(entry, …)`.
5. For a priority unit, `prio = history.pick(n_priced, at).priority` (A4), and `p = priority_cost_usd(entry, prio, …)`:
   - when `p` is not `None`: cost = `max(p, base)`;
   - when `prio` is `None`, including when `history.pick(n_priced, at)` itself is `None`: cost = `base`, and add the unit's input tokens to `priority_without_multiplier` for `n_priced`;
   - otherwise (over the cap): cost = `base`.
6. When `costs_available` is false (an invalid ledger), every cost is `null`, `meta.costs.reason` names the ledger error, and tokens are still emitted.

**Payload rules.**
- **Buckets:** group the units by `(floor(at_ms / 900000), model, tier)`, summing every component and the cost. A bucket's cost is `null` if any of its units is unpriced or costs are unavailable. Unpriced tokens are summed into `Usage.unpriced_tokens`.
- **Usage objects:** each turn's `usage` sums its units with `display_turn == turn.id`; `outside_usage` sums the units with `display_turn is None`; `own_usage` sums both.
- `models[model].periods` lists every period actually used for that model, plus every ledger entry for the model. Units point at periods by index (`priced_by`).
- `meta.links` comes from the constants `OPEN_IN_CODEX_SUPPORT` and `CONTINUE_IN_CLI_SUPPORT`. They start as `{"live": True, "archived": True, "subagent": True}`; Task 26 may change them after the §8.4 verification.
- `generated_tz` comes from `time.strftime("%Z")`. It is informational only.
- `codex_home` is shown through `abbreviate_home`.

**Page assembly** (load-bearing). The template has exactly four placeholders, each appearing once: `/*@@CSS@@*/`, `/*@@FONTS@@*/`, `/*@@JS@@*/` and `@@DATA@@`. Use this code:

```python
def render_page(payload: dict) -> bytes:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    data = data.replace("<", "\\u003c")          # no "</script>" or "<!--" inside the JSON
    before_data, after_data = PAGE_TEMPLATE.split("@@DATA@@")
    head = (before_data
            .replace("/*@@CSS@@*/", PAGE_CSS)
            .replace("/*@@FONTS@@*/", FONT_CSS)
            .replace("/*@@JS@@*/", PAGE_JS))
    return (head + data + after_data).encode("utf-8")
```

  - `ensure_ascii=True` keeps any lone surrogate from a damaged log as a `\udXXX` escape, which `JSON.parse` accepts. With `ensure_ascii=False`, UTF-8 encoding would fail on it.
  - `PAGE_JS` is inserted into the part before the data, so the data is never scanned for placeholders.
  - A test asserts that each placeholder occurs exactly once in `PAGE_TEMPLATE`, and that none of `PAGE_CSS`, `FONT_CSS` or `PAGE_JS` contains a placeholder string.

**`run()` order:**
1. Validate the arguments and the Codex home.
2. `ensure_runtime_home`; create the first-run files.
3. Stat `price-history.json`.
4. Start the `fetch_catalog` thread.
5. `ParseCache.open`, then `scan_logs` with progress.
6. `load_codex_metadata`, `build_corpus`, `link_subagents`, `resolve_workspaces`.
7. Join the catalog fetch.
8. `load_priority_turns`. This is detection only, not token accounting.
9. Validate the user ledger, then `record_catalog_rates` and `append_user_ledger` when allowed. This is spec §4's order: recording comes before token accounting.
   - "The run's pricing keys" are:
     - the normalized form of every model string in the token streams and usage records (the `C` and `XC` set values, and the `T` and `B` model evidence);
     - for every priority turn whose `codex_api_fast_multiplier` is not `None`, its normalized model, plus `catalog:<c_m>|<n>` (with source model `m`) when A4's override step 2 applies.
     - `unknown` is excluded.
10. `compose_usage`.
11. `price_units`, then `build_payload`, then `render_page`, computing `page_size_bytes` as a fixed point. If it is not stable after 3 iterations, use the largest value measured.
12. Write the page to `--output` or the default path.
13. Commit the cache, only after the page is written. A failed page write leaves the old cache, and the next run parses the changed logs again.
14. Open the browser unless `--no-open`.
15. Print the summary.

**Errors and exit codes.**
- A page that cannot be written: `colophon: cannot write <path>: <error>`, exit 1.
- `KeyboardInterrupt`: abort the cache (rebuild-safe), and print one stderr line: `colophon: interrupted`, followed by `; rebuild did not complete; previous cache kept` under `--rebuild`. Exit 1, because spec §2 allows only 0, 1 and 2. Other errors during a rebuild print the error line and then the rebuild sentence.
- Any other unexpected exception: print a one-line error naming the exception type and message, and exit 1.

**Browser.** `webbrowser.open(page.resolve().as_uri())`. Returning `False` or raising prints `colophon: open <path> in a browser`. The exit code stays 0.

**Summary** (stdout, one line):

```
colophon: <n> sessions · <m> subagents · <logs> logs (<parsed> parsed, <cached> cached) · <tokens> tokens · <$cost or "costs unavailable"> est. · page <MB> MB → <path>
```

When any diagnostic is non-zero, also print one line to stderr: `colophon: diagnostics: <comma-separated non-zero counts>; see the page footer`. Invalid-ledger and alias-file errors are also printed in full to stderr, naming the file, the entry index or line, and the problem.

**Steps:**
- [ ] **Step 1: Write the failing payload tests** (`test_payload.py`):
  - **A schema lock:** recursively assert the exact key sets of `Payload`, `Meta`, `SessionRow`, `SubagentRow`, `Turn`, `Request`, `Usage`, `Workspace`, `ModelPricing` and `Diagnostics` against literal sets copied from this plan.
  - The bucket invariants and the Usage invariants, including spec §5.5's second equality: for a depth-2 fixture, a session's `own_usage` plus the `own_usage` of all descendants equals the reader's "total (yours + subagents)". Assert it directly on the payload: sum `own_usage` recursively through `children` and `subagents`, and compare it with the sum of all units of the session tree.
  - A priority unit priced with the override model.
  - Priority override, one test per A4 step:
    - a trace model that is a historical model before its cutoff uses the historical rate;
    - a dated trace model (for example `gpt-5.5-2026-04-23`, with no own catalog entry) uses `n`'s rates and gets the ×2.5 multiplier;
    - an alias whose matched catalog model differs from `n`'s (`c_m != c_n`) uses the `catalog:<c_m>|<n>` key's rate, with the multiplier from `n`;
    - a dated trace model whose candidates fold to the same catalog model as `n` (`c_m == c_n`) uses `n`'s history;
    - an `openai/`-prefixed alias resolves its first target from the part after the slash;
    - a unit logged as one model whose trace model has a different multiplier is charged the trace model's multiplier (for example, logged `gpt-5.4` with trace `gpt-5.5` gives ×2.5);
    - an `openai/`-prefixed trace model normalizes and gets its multiplier.
  - `max(priority, standard)`.
  - Over the cap, and no multiplier (diagnostic).
  - Invalid ledger: costs null, tokens present.
  - A transient period appears in `models`.
  - The escaping: a request text containing `</script><script>alert(1)</script>`, a lone surrogate (`"\ud800"`) and `@@DATA@@` round-trips through `render_page` and `json.loads` of the extracted script text, and the page contains no raw `</script>` before the real closing tag.
  - The fixed-point page size.
  - `PAGE_JS` and `PAGE_CSS` contain no `</script` or `</style`, case-insensitive.
  - The over-20 MB diagnostic, with `PAGE_SIZE_WARN_BYTES` patched small.
- [ ] **Step 2: Write the failing CLI integration tests** (`test_cli_integration.py`), using subprocesses with `--offline --no-open` unless stated:
  - Every row of spec §9 has a test, using the table at the end of this task.
  - File modes: the home 0700; every file 0600, including `--output` into another directory.
  - Atomic writes: run once, then add a new fixture log so that the cache would be written. In-process, wrap `os.replace` so that it raises only when the destination is the page path. The run exits 1; the old page is unchanged; no temp file remains; and the cache directory is byte-identical to before the run, because `put` buffers.
  - No network under `--offline`: a local server counts requests; expect zero.
  - `--offline --refresh-prices` exits 2.
  - First-run file creation.
  - `--rebuild` replaces the cache. An interrupted rebuild (in-process, raising `KeyboardInterrupt` from the progress callback) keeps the old cache byte-identical and returns 1.
  - **Growth:** a second run, after a fixture log gains a new completed turn, shows the new totals.
  - **User ledger entries survive:** run three times with catalog changes between runs (local server). Earlier entries stay JSON-equal and only new ones are added.
  - The `--refresh-prices` CLI path against the local server, and `--rebuild --refresh-prices` together.
  - Recording through each catalog status: 200 (`fetched`), 304 (`not_modified`), failure with a cache (`cached`) and `--offline`. Each records against the catalog's own `fetched_at_ms`, and repeating a run appends nothing.
  - The summary line format.
  - The browser-open failure path, in-process with a monkeypatched `webbrowser.open`.

  | §9 condition | Test |
  |---|---|
  | Codex home missing or unreadable | exit 1; the message names the path |
  | Malformed JSONL line | `malformed_lines` counts it per file |
  | Unreadable or empty log | in `skipped_files`, named |
  | Unrecognized record type | in `unknown_record_types`; the footer text is checked in Task 19 |
  | Metadata SQLite locked or unreadable | titles fall back to the logs; `metadata_errors` is set |
  | Database thread without a log file | `db_threads_without_logs` counts it |
  | Catalog unreachable or timed out | `catalog` diagnostic; the cached catalog is used |
  | Model with no history and no catalog rate | in `unpriced_models`; tokens are present |
  | Usage before the first dated entry | `history_begins`; the earliest rate is used |
  | Invalid `price-history.json` | stderr names the file, the index and the problem; costs are null; the ledger is unchanged |
  | Ledger changed during the run | a warning; no append (patch the mtime check in-process) |
  | Orphaned subagent | a top-level row with `kind: "orphan"` |
  | Priority usage with no multiplier | `priority_without_multiplier` |
  | Model priced from an unrecorded catalog rate | `unrecorded_catalog_rates` |
  | Fork history boundary unresolved | `unresolved_history_boundaries`; the row has no turns |
  | Truncated final line or glued fragment | `truncated_lines` and `recovered_lines` |
  | Invalid `workspaces.json` | stderr names the line; ignored; diagnostic |
  | Cache version mismatch or corruption | reparsed; no crash |
  | Zero sessions | exit 0; the page has `sessions: []` |
  | Browser cannot be opened | exit 0; the path is printed |
  | Concurrent runs | two simultaneous runs on one home both exit 0, and the final page parses |

- [ ] **Step 3: Implement.** Add a minimal `PAGE_TEMPLATE` with the final head and body skeleton, and the data `<script>`. Make `PAGE_CSS` and `PAGE_JS` minimal: the JS parses the data and renders the empty state only. Task 19 replaces them. Run the suite.
- [ ] **Step 4: Add the `token_rules.md` row** for the priced-model override and `max(priority, standard)` (`codexResolvedCostUSD`, `codexPriorityPricingModel`): *ported*. Commit with the subject `Compile Colophon pages end to end with priced usage`.

## Phase 6 — The page

All page JavaScript lives in `PAGE_JS`, as one IIFE with `"use strict"`.
- Structure it into named, ordered blocks: `// --- data`, `// --- time`, `// --- state`, `// --- filters`, `// --- aggregates`, `// --- format`, `// --- dom`, `// --- views/overview`, `// --- views/list`, `// --- views/reader`, `// --- boot`.
- Expose pure functions for tests as `window.__colophonTest = {time, filters, aggregates, format}`.
- **DOM insertion:** use only `el(tag, props, ...children)`, which sets `textContent`, attributes and listeners. A test greps `PAGE_JS` for `innerHTML`, `outerHTML`, `insertAdjacentHTML` and `document.write`, and fails on any of them.

**Browser test harness** (`tests/browser/conftest.py`):
- a session-scoped `sync_playwright` Chromium;
- a `page_for(payload_or_codex_home, *, tz="UTC", width=1440)` helper that builds the page and calls `page.goto(file_uri)`;
- the page is built in-process with `run(args, now_ms=FIXTURE_NOW_MS)` against a `tmp_path` home, with the `--offline --no-open --output` flags. Fixture logs are dated relative to `FIXTURE_NOW_MS`, a constant in the harness (for example 2030-01-15 12:00 UTC), and their file mtimes are set relative to it with `os.utime`. This keeps windows, deltas and running turns deterministic;
- every page is wrapped in `tools.testkit.guard_browser_errors(page)`;
- `page.route("**/*", ...)` fails the test on any request whose URL is not the page's own `file://` URL;
- `context = browser.new_context(timezone_id=tz, viewport={"width": width, "height": 900})`.

### Task 19: Page shell: template, tokens, font, time helper, URL state, top bar, empty state, diagnostics footer

**Files:**
- Modify: `colophon/colophon`, section 18
- Create: `colophon/tests/tools/subset_font.py`, `colophon/OFL.txt`, `colophon/docs/font.md`, `colophon/tests/browser/conftest.py`, `colophon/tests/browser/test_shell.py`, `colophon/tests/test_page_assets.py`

**Interfaces:**
- Produces:
  - `FONT_CSS: str`: three `@font-face` rules (weights 300, 400 and 500, family `Martian Mono`), each with `src: url(data:font/woff2;base64,…) format("woff2")`. It is preceded by a CSS comment reproducing `OFL.txt` verbatim.
  - The final `PAGE_TEMPLATE`.
  - The JS blocks `data`, `time`, `state`, `format`, `dom` and `boot`, plus the top bar and footer views.
  - JS `time` functions:
    - `localDayKey(ms)`, `localDayStart(ms)`, `addLocalDays(dayStartMs, n)`;
    - `mondayIndex(ms)` (Mon = 0 … Sun = 6), `localHour(ms)`;
    - `splitByLocalDay(startMs, endMs) -> [{day, ms}]`;
    - `periodWindow(period, nowMs, custom) -> {from, to}`;
    - `previousWindow(period, window, nowMs) -> {from, to} | null`.
  - JS `state` functions: `readState() -> State` and `writeState(next, {replace})`.

**Rules:**
- **Font.**
  - Source: the Martian Mono **v1.1.0** release, asset `martian-mono-1.1.0-ttf.zip` from `https://github.com/evilmartians/mono/releases/tag/v1.1.0`. Use the standard-width static Light, Regular and Medium TTFs.
  - Subset with `pyftsubset --flavor=woff2 --layout-features='*' --unicodes=<range>`. The range is U+0020–007E, U+00A0–00FF, U+2010–2027, U+2030–203A, U+2190–2193, U+2197, U+2212, U+2264–2265, U+2315, U+2318, U+25B2–25BC and U+2713.
  - `tests/tools/subset_font.py` performs the whole recipe deterministically and prints `FONT_CSS`.
  - `docs/font.md` records the release, the asset SHA-256, the exact file names, the weights, the range and the command.
  - `OFL.txt` is copied verbatim from the release zip.
  - A test asserts that the license text in `FONT_CSS` equals `OFL.txt` and contains no `*/`.
- **Tokens.** `PAGE_CSS` starts with `/* tokens:start */ :root[data-theme="dark"] { … } /* tokens:end */`, holding the full table from [Visual tokens](#visual-tokens-from-the-approved-mockups).
- **Theme lint** (`test_page_assets.py`):
  - outside the token block in `PAGE_CSS`, and anywhere in `PAGE_JS`, no match for the regexes `#[0-9a-fA-F]{3,8}\b`, `\brgba?\(` and `\bhsla?\(`;
  - no CSS named color among `{white, black, red, green, blue, yellow, orange, purple, gray, grey, silver, lime, navy, teal, aqua, fuchsia, maroon, olive}` as a whole word in a CSS value or a JS string;
  - `transparent`, `currentColor` and `inherit` are allowed;
  - JS reads the ramp colors through `getComputedStyle(document.documentElement).getPropertyValue("--heat-<n>")`.
- **Time** (D1, D3, spec §5.2). Use the local `Date` getters and the constructor `new Date(y, m, d)`; these follow the viewer's zone and DST.
  - Windows are half-open `[from, to)` (D1). `7D`, `30D` and `90D` run from `localDayStart(now)` minus N−1 days, to `now + 1`. `MTD` runs from the first of the month to `now + 1`. `ALL` is `[-Infinity, now + 1)`. `CUSTOM` is `[localDayStart(from), localDayStart(to + 1 day))`.
  - The previous window is the same length, immediately before; MTD follows D3. ALL and CUSTOM have none.
- **URL state.** The hash has the form `#v=overview|list|session&p=90d&from=YYYY-MM-DD&to=YYYY-MM-DD&a=1&q=…&day=YYYY-MM-DD&how=<mon0-6>-<hour>&ws=<key>&sub=<path>&model=<id>&st=aborted|interrupted|abandoned&sort=newest|longest|subtime|tokens|cost&s=<sessionId>`.
  - Every value is `encodeURIComponent`-encoded, and unknown keys are dropped.
  - User actions push a full entry. Normalization, defaults and debounced search typing use `history.replaceState` (PKM: "Canonicalize URL state without polluting navigation history").
  - Back and reload restore the state.
- **Top bar.**
  - The brand `COLOPHON` and a breadcrumb.
  - "data as of <local time> · <n> logs · prices <source host> <fetch time>", or "prices unavailable".
  - Search, with a 200 ms debounce, matching the full title and every request text, case-insensitive, through the §5.9 match rule.
  - The period chips 7D, 30D, 90D, MTD, ALL and CUSTOM. CUSTOM opens two `<input type="date">`.
  - The archived toggle, labelled `archived: shown/hidden`.
  - Active drill filters as removable chips (`fchip`).
- **Empty state.** With zero sessions, show "No Codex sessions found in <codex_home>".
- **Diagnostics footer.**
  - Rendered whenever any diagnostic count is non-zero. Each non-zero category is a collapsible row with its list.
  - Unknown record types add the sentence "Codex's log format may have changed".
  - The cost label "API-equivalent estimate (not billed)" is always present in the footer.

**Steps:**
- [ ] **Step 1: Write the failing tests.**
  - Python (`test_page_assets.py`): the theme lint; placeholder uniqueness; no `"""` in the assets; the no-`innerHTML` grep; the OFL check; `FONT_CSS` has three faces whose base64 decodes to bytes starting with `wOF2`.
  - Browser (`test_shell.py`):
    - the page loads from `file://` with no errors and no requests;
    - the empty state names the Codex home;
    - the top bar values;
    - period chips update the hash;
    - Back restores the previous state; reload keeps it;
    - search filters;
    - the archived toggle hides archived sessions everywhere;
    - the diagnostics footer appears for a fixture with a malformed line and an unknown type, including the format sentence;
    - **time helper under `America/New_York` and `Asia/Kolkata`:** day keys around midnight; a turn from 23:30 to 00:30 local splits into two days of 30 minutes each; a DST spring-forward day has 23 h (New York, 2030-03-10) and fall-back has 25 h (2030-11-03); 15-minute buckets map to whole local hours in Kolkata (+05:30);
    - the computed font family of `body` resolves to `Martian Mono` (check `document.fonts.check("12px 'Martian Mono'")`).
- [ ] **Step 2: Run the font subsetting tool** and paste its output.
- [ ] **Step 3: Implement**, then run the suite.
- [ ] **Step 4: Commit** with the subject `Build the Colophon page shell with embedded font and URL state`.

### Task 20: Overview screen

**Files:**
- Modify: `colophon/colophon`, section 18 (`PAGE_CSS`, `PAGE_JS` `filters`, `aggregates`, `views/overview`)
- Test: `colophon/tests/browser/test_overview.py`, `colophon/tests/expected.py` (an independent Python oracle over the payload)

**Interfaces:**
- Produces:
  - JS `filters.matchSession(session, state, subagentsById) -> {match: bool, matchedSubagents: Set}`, implementing §5.9 and D1;
  - JS `aggregates`: `kpis`, `calendar`, `hourWeekday`, `workspaces`, `models`, `notable`, `recent`, each taking `(sessions, state, nowMs)`;
  - `tests/expected.py`: Python functions computing the same KPIs and panels from the payload JSON, independently written from the definitions below.

**Definitions** (normative for both the JS and the oracle):
- **Sessions:** your sessions (including orphans) that match the filters and are in the period (D1).
- **Your active time:** the union of the clipped intervals of the turns (statuses completed, aborted, interrupted and running, with a known duration) of the matching sessions.
- **Agent time:** the sum over their descendant subagents of each subagent's own clipped union.
- **Turns:** the count of your sessions' turns starting in the window. Average turn time is the mean of their known durations, excluding abandoned turns.
- **Tokens:** input plus output, from the buckets in the window, of the matching sessions **and** their descendants. Each unit is counted once. Cached share is cached input ÷ input.
- **Estimated cost:** the bucket costs in the window. When any bucket in scope is unpriced, append "+ unpriced". Show "costs unavailable" when `meta.costs.available` is false.
- **Aborted turns:** your turns in the window with status aborted. The sub-line reads "n interrupted · n abandoned"; each is a separate link.
- **LIVE:** a tile whose figure includes running turns shows `LIVE · includes n running`.
- **Deltas:** for 7D, 30D, 90D and MTD only, the same computation over `previousWindow`, shown as `▲ n` or `▼ n vs prior <period>`.
- **Calendar:** one cell per local day in the window, with D6 for ALL. The metric toggle offers sessions (count with a turn start that day), active time, tokens and cost. Levels follow D5. Cells shrink from 13 px down to 9 px to fit the panel width; beyond that, the grid sits in `data-scroll-region` and starts scrolled to the far right.
- **Hour × weekday:** your turn starts in the window by `mondayIndex` and `localHour`.
- **Workspaces:** bars by active time or tokens; the top 6, then "+ N more", which expands in place.
- **Models:** tokens and cost per model, with "unpriced" shown in amber. A tooltip lists the rate periods used (`effective_from`, `source`).
- **Notable:**
  - busiest day: most sessions with a turn start;
  - longest active day: largest union of your active time on one local day;
  - biggest subagent fan-out: most descendants for one session;
  - longest streak: consecutive local days with at least one turn start, with dates.
- **Recent sessions:** the 5 most recent by `start_ms`, then "view all N →".
- **Drill-down:** a click on any tile, cell, bar, notable item or recent row writes the matching filter and opens the list (spec §8.2 table). A day sets `day`, a heat-map cell sets `how`, a workspace sets `ws`, a model sets `model`, a status link sets `st`, a session row sets `s` with view `session`. The tile-to-sort mapping follows the spec §8.2 table.

**Steps:**
- [ ] **Step 1: Write a fixture corpus** with hand-chosen numbers:
  - three workspaces, two models, one priority turn;
  - a subagent that is the only user of one model, to exercise the §5.9 drill-down;
  - an archived session;
  - a running turn (mtime 30 minutes before the snapshot);
  - an aborted, an interrupted and an abandoned turn;
  - a turn crossing local midnight;
  - activity in the previous period, so the deltas are non-zero.
- [ ] **Step 2: Write the failing browser tests:**
  - every KPI equals the `expected.py` value under UTC, ALL and 90D;
  - the deltas are hidden under ALL and CUSTOM;
  - each tile opens the list with the expected session ids and sort;
  - the calendar cell for the midnight-crossing day shows the split time;
  - a heat-map cell opens the expected sessions;
  - a workspace bar and a model row drill down; the model filter matches the parent of the subagent-only user, and the reader highlights that subagent;
  - the LIVE marker is present;
  - the aborted, interrupted and abandoned links;
  - the notable items and their drill-downs;
  - the recent list;
  - the archived toggle changes every panel.
- [ ] **Step 3: Implement**, then run the suite.
- [ ] **Step 4: Commit** with the subject `Add the Colophon overview with drill-down panels`.

### Task 21: Session list and session reader

**Files:**
- Modify: `colophon/colophon`, section 18 (`views/list`, `views/reader`)
- Test: `colophon/tests/browser/test_list_reader.py`

**Rules:**
- **List** (spec §8.3, D4):
  - Your sessions only.
  - Under the `newest` sort, grouped under amber local-day headers (for example `SAT OCT 3`).
  - Each row shows: the start time `HH:MM`; the title with an ellipsis, a `title` tooltip and an ARCHIVED tag; `workspace › subfolder`; active time; "n sub"; and the flags LIVE, aborted, interrupted, abandoned and uncertain timing (amber where they are warnings).
  - Sorts: newest, longest, subagent time, tokens, cost.
  - Clicking a row sets `s` and `v=session`.
  - At ≥ 900 px the reader opens in the right pane. Below 900 px it is a single pane with a `← sessions` back control.
- **Reader** (spec §8.4):
  - **Header:** the title, expandable to `title_full`; `workspace › subfolder`; branch; time range; originator; the short id (first 8 characters plus `…` plus the last 8); and the forked-from link when it applies.
  - **Buttons:**
    - **Open in Codex** is an `<a href="codex://threads/<id>">`, shown only when `meta.links.open_in_codex[<live | archived | subagent>]` is true.
    - **Copy "Continue in CLI"** copies `codex resume <id>`, with a label saying it continues the session. It follows the same visibility rule with `continue_in_cli`.
    - **Copy session ID** and **Copy log path**.
  - **Clipboard:** use `navigator.clipboard.writeText` when it exists and succeeds. Otherwise show a read-only `<input>` with the text selected and the hint "press ⌘C".
  - **Stats strip:** active time, span (sub-line `idle <idle_ms>`), turns, subagents (with agent time), tokens, and cost with the yours/subagents split. The header time range shows the user-request span as a tooltip when `user_span_ms` is not null.
  - **Mini timeline:**
    - turns are solid `--tl-turn` blocks; idle time is a hairline;
    - each subagent gets its own sub-lane with its label;
    - inferred links have a dashed border; forked subagents carry a badge;
    - a label that would collide moves to a second label row, and if it still collides it becomes a `title` tooltip on the block;
    - the x-axis spans the session span with five ticks.
  - **Turn cards** (header, YOU ASKED, IT USED, SUBAGENTS and FINAL ANSWER, exactly as spec §8.4):
    - "before this turn" requests appear first in their own group, outside the "first two" count;
    - follow-ups beyond the first two collapse under "+ n follow-ups sent while it worked";
    - text longer than 6 lines is clamped behind "more";
    - voice requests are marked; a voice-reply answer is marked "voice reply";
    - failures in tool chips are amber;
    - a subagent row expands to a miniature card with its timing, tools, tokens and final answer;
    - interaction-only turns show "also used: <label>";
    - the cost tooltip names the rate periods and their sources.
  - **Outside tokens:** below the last card, "tokens outside displayed turns: …" appears whenever `outside_usage` is non-zero.
  - A history-unresolved session shows its header, links and tokens, with the note "history boundary unresolved — turn metrics withheld".

**Steps:**
- [ ] **Step 1: Write the failing browser tests:**
  - the list grouping and flat sorts;
  - each sort order;
  - search;
  - row selection;
  - <900 px single pane with back, and ≥900 px split;
  - every reader element above;
  - follow-up expansion;
  - the before-turn group order;
  - subagent expansion;
  - the forked badge and the inferred dashed style (assert the computed `border-style`);
  - "also used";
  - the outside-tokens line, using the Task 15 fixture;
  - the stats strip's "total (yours + subagents)" equals the `expected.py` overall total for a depth-2 fixture;
  - the clipboard fallback: override `navigator.clipboard` to undefined through `page.add_init_script`, click Copy, then assert the selected input and the hint;
  - the Open-in-Codex `href`, and the button hidden when the constant is false (in-process patch);
  - the history-unresolved note;
  - the archived toggle in the list.
- [ ] **Step 2: Implement**, then run the suite.
- [ ] **Step 3: Commit** with the subject `Add the Colophon session list and reader`.

### Task 22: Layout, overflow, keyboard and contrast hardening

**Files:**
- Modify: `colophon/colophon` (`PAGE_CSS`, `PAGE_JS`)
- Test: `colophon/tests/browser/test_layout.py`, `colophon/tests/test_contrast.py`

**Rules:**
- Spec §8.5 layout rules apply: `min-width: 0` on grid and flex children, ellipsis titles with tooltips, the fixed metrics column, wrapping strips and buttons, and the non-overlapping timeline labels.
- **The overflow check** runs through `page.evaluate` at 360, 390, 899, 901, 1024 and 1440 px, on the overview, the list and a reader. It must return an empty list. Use this algorithm:
  1. The page: `document.scrollingElement.scrollWidth ≤ innerWidth + 1`.
  2. For every rendered element that is not inside `[data-scroll-region]`:
     - with `overflow-x: visible`, `scrollWidth ≤ clientWidth + 1` whenever `clientWidth > 0`;
     - with clipped overflow, the overflow is allowed only when `text-overflow: ellipsis` is set and the element has a non-empty `title`;
     - `auto` and `scroll` are not allowed outside scroll regions.
  3. **Overlap:** for each element with a non-blank direct text node, collect **per-line fragment rects**: `range.getClientRects()` of a `Range` over each direct text node. Intersect each fragment with the rects of the element's clipping ancestors, and drop any that become empty. Two fragments from elements where neither contains the other must not intersect by more than 1 px in both axes.
  4. **Scroll regions:** every `[data-scroll-region]` has `overflow-x: auto` or `scroll`. When its content is wider than its box, it starts scrolled to the far right.
- **The stress fixture:**
  - a 400-character unbroken title;
  - a 200-character workspace name and subfolder;
  - 12-digit token counts;
  - 300 subagents on one session, with labels that collide in the timeline;
  - 40 models;
  - 10 years of ALL history, which forces the calendar to scroll.
- **Keyboard:**
  - Tab reaches the period chips, search, the toggle, every tile, every heat cell (cells are buttons, with `aria-label` stating the date and value), the list rows, the reader buttons and the expanders.
  - Enter and Space activate them.
  - Focus is visible: assert that the computed `outline-style` is not `none` on `:focus-visible`.
- **Contrast** (`test_contrast.py`, pure Python):
  - Parse the token block from `PAGE_CSS`.
  - Compute the WCAG relative luminance of each token.
  - Assert ≥ 4.5:1 for every (text token, background token) pair the CSS uses. Declare these pairs in the test:
    - `--txt`, `--hi`, `--dim`, `--muted`, `--ws`, `--g` and `--amb` on each of `--bg`, `--panel`, `--sel` and `--hover`;
    - `--bg` on `--g` (the active chip);
    - `--g` on `--fchip-bg`.
  - For a token with an alpha channel, composite it over `--bg` first.
  - Where a pair fails, adjust the text token's lightness only, and update the plan's token table in the same commit.

**Steps:**
- [ ] **Step 1: Write the failing tests**, then run them.
- [ ] **Step 2: Fix the layout and the tokens** until every test passes. Run the suite.
- [ ] **Step 3: Commit** with the subject `Harden Colophon layout, keyboard access and contrast`.

## Phase 7 — Performance, acceptance tooling, documentation

### Task 23: Performance

**Files:**
- Modify: `colophon/colophon` (progress output)
- Test: `colophon/tests/test_scaling.py`, `colophon/tests/test_progress.py`
- Create: `colophon/tests/perf/measure_throughput.py`

**Rules:**
- **Linear scaling** (a hard test, spec §11).
  - `fixturegen` builds two corpora: S, and 2S with twice as many sessions of the same per-session shape. Each session has 40 turns with token counts, usage records, tool items, requests and one subagent.
  - Calibrate S so that the cold `time(S)` is at least 2 s on the development machine, and record the S used in a constant in the test.
  - A measurement is a CLI subprocess run with `--rebuild --offline --no-open` against a fresh temporary `COLOPHON_HOME`.
  - Take the median of 3 runs for each size, and assert `median(2S) ≤ 2.5 × median(S)`.
- **Progress** (D16): `format_progress(done, total, elapsed_s) -> str` returns `parsing <done>/<total> MB · ETA <n>s`. It is printed with `\r` only when `sys.stderr.isatty()`. Test the formatter, and `run(args, now_ms=…, stderr_tty=True)` with `capsys`. Assert that a `\r` progress line appears for a cold run, and that none appears with `stderr_tty=False`.
- **Cold throughput** is local acceptance and not collected.
  - `tests/perf/measure_throughput.py [--codex-home PATH]` runs a cold `--rebuild` into a temporary home against the real logs and computes MB/s from `ScanResult.bytes_parsed`.
  - It writes or compares `$COLOPHON_HOME/perf-baseline.json` (`{"mb_per_s", "measured_at", "logs", "bytes"}`), and reports a regression when MB/s falls below baseline ÷ 1.5.
  - It prints the page size and the diagnostics summary. `colophon` itself never reads this file.

**Steps:**
- [ ] **Step 1: Write the tests**, implement, and run the suite.
- [ ] **Step 2: Commit** with the subject `Add Colophon scaling test and progress output`.

### Task 24: Local acceptance tooling: CodexBar parity and upstream table check

**Files:**
- Create: `colophon/tests/parity/compare_codexbar.py`, `colophon/tests/parity/check_upstream_tables.py`, `colophon/tests/parity/check_upstream_drift.py`, `colophon/tests/test_acceptance_tools.py`

**Rules:**
- **`compare_codexbar.py`** (spec §12.4). It is never collected by pytest, and its output never enters the repo.
  1. Before writing the comparison, inspect the real JSON shape of `codexbar cost --provider codex --format json --period all` with `--group-by session` and `--group-by project`, and of the default per-day output.
  2. It runs those commands with the prebuilt pinned CLI, `~/Downloads/colophon-prebuilt/codexbar-cli-3bbf6bc48/CodexBarCLI` (its `PROVENANCE.md` has the sha256), or, when asked, the installed one. It records which build in the report. A custom build's pricing patches are reported as a separate class, (d) custom-build difference, never as explained.
     - **Isolation:** import these functions from `colophon/tests/tools/codexbar_expected.py`; do not copy or re-implement them:
       - `profile_text(allow_real_codex_read=…)` and `self_test_guard(profile, expect_real_codex_read_denied=…)`: the `sandbox-exec` profile (network denied, every write under the real home denied, reads of the real CodexBar cache denied) and its self-test;
       - `seed_fake_home(fake, catalog)` and `guarded_env(fake, codex_home)`: the fake home and the only environment CodexBar may run with (`HOME` **and** `CFFIXED_USER_HOME` at the fake home; plain `HOME` does not move CodexBar's cache, and that mistake once rewrote the user's real cache);
       - `run_until_stable(cli, profile, fake, codex_home, commands, snapshot, max_runs=…, stable_runs=…)`: runs every command in `commands` (argument lists, for example `COST_COMMAND` plus the `--group-by session` and `--group-by project` variants) once per attempt, keeping the fake home, until `snapshot(stdouts)` is identical for `stable_runs` consecutive attempts;
       - `real_state_fingerprint()` and `app_running()`: compare the fingerprint before and after, and refuse to run while the CodexBar app runs.
       - Real data needs CodexBar to read the real `~/.codex`: use `profile_text(allow_real_codex_read=True)` and `self_test_guard(profile, expect_real_codex_read_denied=False)`. Writes stay denied, and reads of the real CodexBar cache stay denied and self-tested.
       - Put a consistent copy of the real trace database at `<fake home>/.codex/logs_2.sqlite`, where this CodexBar build looks for it. The live database has a `-wal` file, so copying the main file alone gives a stale database. Use `sqlite3.connect('file:<real>?mode=ro', uri=True).backup(dst)` with `dst = sqlite3.connect(<copy>)`, then close both connections. Take the copy right before the CodexBar run, and run Colophon (step 3) immediately afterwards. The CodexBar run and the fallback-only recomputation use the copy, while Colophon's own run reads the live `~/.codex/logs_2.sqlite`. A difference confined to priority turns whose trace rows are newer than the copy's last row is class (a), trace-database timing; the report lists those turns.
       - **One catalog on both sides.** Take `pricing-cache.json["catalog"]` (shape `{"openai": …}`, which is what `seed_fake_home` expects) from the temporary copy of Colophon's home, fetching it first if needed. Seed CodexBar with it through `seed_fake_home(fake, catalog)`, and run Colophon with `--offline`, so both price from the same snapshot. Never use the synthetic `token_cases/catalog.json` for parity.
     - **Settings that still leak:** CodexBar reads its app preferences through `cfprefsd`, so pass `--period all` explicitly and record the bucket zone from the scan metadata, as the runner does.
     - **Complete history:** CodexBar's refreshes are budgeted (512 MiB per refresh; `CostUsageScanner.swift` lines 190–193 and 269–289), so a cold run over a large corpus is partial. `run_until_stable` repeats until three consecutive results are identical; pass a `max_runs` sized to the corpus (the default of 10 is for the small cases). Record the run count and `historyCoverageIsEstablished` in the report. A pure helper classifies the final report: **partial** when `run_until_stable` did not reach a stable result, or when `historyCoverageIsEstablished` is false while `coverage.unmetered` is 0 (a partial result fails the run); **complete with unresolved forks** when it is false and `coverage.unmetered` is above 0 (CodexBar's unresolved fork baselines, as in reference cases `b02` and `c09`; listed in the report, not a failure); otherwise **complete**. `test_acceptance_tools.py` tests the helper on synthetic JSON for all three classes.
  3. It runs Colophon in-process, with `--no-open --output <tmp>`, against `--codex-home` (default `~/.codex`). It uses a temporary copy of `$COLOPHON_HOME` (the ledger, the pricing cache and `priority-turns.json`), so that the real home is not modified.
  4. It compares tokens (input, cached, output) and cost per local day, per project (CodexBar's project path against Colophon's session `cwd`) and per session id.
  5. It classifies each difference as one of:
     - (a) explained by a recorded deviation or confirmed decision: the primary path, dated history, the A1 sticky turns, the trace-database location, OpenAI-only pricing (A4 item 5), duplicate-id parents (A4 item 6), fork-of-fork chains CodexBar leaves unresolved because of file order (A4 item 7), priority turns newer than the trace-database copy, and cost differences within the A4 tolerance;
     - (b) an unexplained token difference;
     - (c) an unexplained cost difference.
  6. It writes `$COLOPHON_HOME/parity/<UTC timestamp>.md` and `.json`. It exits non-zero when any (b) or (c) remains.
  - Sessions present in Colophon but missing from CodexBar's report, and the reverse, are listed in their own section (spec §15 item 2). Each one is either explained by a CodexBar rule identified in its source, or reported as a gap. They count as (b) until explained.
  - To make (a) checkable, the script also recomputes Colophon's tokens with **only** the fallback path (token counts for every turn), through the in-process functions. Tokens must then match CodexBar exactly per day and per session, except sessions in a fork-of-fork chain that CodexBar reports unresolved (A4 item 7, class (a)).
    - For costs, this recomputation prices every row **as CodexBar does**, not through Colophon's ledger, so that A4 items 2 and 3 cannot cause differences. The normative function is upstream `codexResolvedCostUSD` (`CostUsageScanner+PricingRows.swift` lines 4–45); a helper in `compare_codexbar.py` follows it using Task 13–16 functions:
      - **priced model:** A1's override (the priority turn's raw trace model when `codex_api_fast_multiplier` knows it, else the row's model). Both the base cost and the priority cost use it (PricingRows lines 17–42).
      - **pricing date:** the row's `timestamp_unix_ms`. When it is `None` (a lenient timestamp, case `a12`), the historical branch is skipped and current rates apply (`CostUsagePricing.swift` lines 573–575); never use `at_ms` here.
      - **rates:** when `HISTORICAL_CUTOFFS` has the normalized priced model and the pricing date is before that cutoff, the curated seed's historical period, from `PriceHistory(validate_ledger(CURATED_PRICE_HISTORY, curated=True).entries, []).pick(normalize_codex_model(priced_model), pricing_date).entry`; otherwise `resolve_rates(priced_model, ModelsDevIndex.from_catalog(snapshot))` with the catalog snapshot CodexBar was seeded with.
      - **priority turns:** `load_priority_turns(codex_home=<fake home>/.codex, home=<empty temporary dir>)`, so only the trace-database copy counts, with no sticky memory.
      - **priority gate:** only a row whose `turn_id` is in the loaded priority turns gets a priority cost (PricingRows lines 15–16 and 31). Every other row costs its base cost. Upstream's other gate, `row.pricingMode == "priority"`, comes from its cached rows and does not apply here, because this recomputation has no sticky memory.
      - **priority cost** (priority rows only): the multiplier and input cap as upstream `codexPriorityCostUSD` builds them (`CostUsagePricing.swift` 646–678: `codex_api_fast_multiplier`, and `codexPriorityInputTokenLimit` unless `codexAPIFastAllowsLongContext`), passed to `priority_cost_usd`.
      - **combination** (priority rows only): `max(priority cost, base cost)`, or the base cost when the priority cost is `None` (over the cap, or no multiplier).
    - Costs from this recomputation must then match CodexBar within A4's tolerance; anything else is (c).
- **`check_upstream_drift.py --codexbar ~/source/CodexBar [--to origin/main]`** (maintainer tool, A4):
  - For every row of `token_rules.md`, it extracts the cited Swift function from both the pinned commit and `--to`, and reports which functions changed, with a unified diff.
  - It also lists any new `CostUsage*`/`Codex*` source files.
  - It exits non-zero when anything changed, so the maintainer knows to re-port, and to update the pinned commit after re-verifying.
- **`check_upstream_tables.py --codexbar ~/source/CodexBar`** (maintainer verification, run when `CURATED_BUNDLED` or the curated seed is created or changed).
  - It reads `git show 3bbf6bc48:Sources/CodexBarCore/Vendored/CostUsage/CostUsagePricing.swift`.
  - It parses the `codex` dictionary literal (lines 84–208), `codexHistoricalPricing` (with the `gpt56Pricing` tuple order taken from the helper at lines 47–61) and `codexAPIFastMultiplier`.
  - It compares them with `CURATED_BUNDLED`, the historical `null` seed entries (per million, converted exactly as A4) and the seed `priority` fields, and exits non-zero on any mismatch.
- **`test_acceptance_tools.py`** tests only the **pure** helpers of these scripts, with synthetic inputs: difference classification, the Swift literal parser (on a synthetic Swift snippet) and report formatting. It never runs `codexbar` and never reads `~/source/CodexBar`.

**Steps:**
- [ ] **Step 1: Write the pure-helper tests**, implement, and run the suite.
- [ ] **Step 2: Run `check_upstream_tables.py`.** It must pass. Fix `CURATED_BUNDLED` or the seed until it does.
- [ ] **Step 3: Commit** with the subject `Add Colophon parity and upstream table verification tools`.

### Task 25: Documentation and fleet registration

**Files:**
- Modify: `colophon/README.md`, `colophon/docs/token_rules.md`, `README.md` (root), `agents.md`

**Rules:**
- **`colophon/README.md`** covers everything listed in spec §13. It also states:
  - the A1 priority source, the sticky memory and its limitation (usage older than both the trace database and the first run stays standard-priced);
  - how to edit `price-history.json`, with a worked `manual` entry that copies a period's rates and adds `priority`;
  - detection lag and its `manual` correction;
  - manual entries being superseded by later catalog changes;
  - the promotion procedure;
  - the verified link behavior (completed in Task 26);
  - the quiet threshold, and the ported end-of-file gate's visible effect: a live **subagent** log caught mid-write withholds its fallback (`token_count`) usage until its final line completes, exactly as in CodexBar. Turns with per-response records and bare-usage lines still count. While the replay has not run, the primary path's model in force comes from the file's own `C`/`XC` observations in order, without the owned-suffix reset (a Colophon primary-path rule, Task 15), so those records stay priced;
  - the parity and table-check commands;
  - the full test commands;
  - attribution: CodexBar (MIT, © 2026 Peter Steinberger), models.dev (MIT), Martian Mono (SIL OFL 1.1).
- **`token_rules.md`**: every ported function in the reference map has a row, with file, function, commit `3bbf6bc48` and decision. Every deviation in spec §15 and A1 has a row with its reason.
- **Root `README.md`**:
  - add `- \`colophon\` – …` to the alphabetical project list, after `cognitive_switchyard`;
  - change "Eighteen Python launchers" to "Nineteen Python launchers".
- **`agents.md` Validation Matrix:**

```
- `colophon`:
  - `.venv/bin/python -m pytest -q` from `colophon/` (unit, CLI, browser and scaling tests; no skips).
  - After launcher header edits: `uv run --script tools/check_uv_headers.py`.
  - Local acceptance (real data, outputs never committed): `colophon/tests/perf/measure_throughput.py`,
    `colophon/tests/parity/compare_codexbar.py`, and after curated pricing changes
    `colophon/tests/parity/check_upstream_tables.py`.
```

- **Deployment mapping:** not in this task. The audit would report an undeployed `colophon` as missing, so the mapping is added in Task 26 Step 6, together with the first deployment.

**Steps:**
- [ ] **Step 1: Make the edits.**
- [ ] **Step 2: Run the fleet suites:**
  - `uv run --script tools/check_uv_headers.py`;
  - `colophon/.venv/bin/python -m pytest tools/tests/test_check_uv_headers.py -q`;
  - `zsh tools/tests/test_check_local_deployments.zsh`;
  - `node --test tools/tests/check_static_deployments.test.mjs`.
  
  Then run the full Colophon suite.
- [ ] **Step 3: Commit** with the subject `Document Colophon for users and the fleet`.

### Task 26: Final verification, real-data acceptance and handoff

Every step that touches real data or the user's desktop is read-only, except the documented `$COLOPHON_HOME` outputs. **Ask the user before Steps 3 and 4** (real-data runs and opening Codex links), and **before Step 6** (deployment).

- [ ] **Step 1: Run the complete Colophon suite and every fleet suite** listed in Task 25. Report every failure by name, with its output. Do not continue with any failure.
- [ ] **Step 2: Audit the branch:**
  - `git status`, `git ls-files colophon`, and `git diff --stat main...colophon`;
  - confirm that every file in the repository layout is tracked;
  - scan the whole diff for sensitive content (real paths, names, titles);
  - confirm that every commit on the branch has a non-empty body.
- [ ] **Step 3: Real-data acceptance** (with the user's go-ahead):
  1. Run `./colophon --no-open` against the real `~/.codex`.
  2. Record the timing, the page size and the diagnostics.
  3. Run `tests/perf/measure_throughput.py`.
  4. Run `tests/parity/compare_codexbar.py`, with the user's approval and the CodexBar app quit (Task 24's guarded runner). Resolve every (b) and (c) difference by porting the missing rule, or by recording a justified deviation in `token_rules.md` **with the user's approval**. Rerun until it is clean.
  5. **Re-confirm the reference cases** (with the user's approval). Copy `tests/fixtures/token_cases` and `tests/fixtures/scrubbed` to a temporary directory, run `codexbar_expected.py --cases <copy>` on each (the tool applies each case's recorded `mtimes_ms`, so a plain copy or a fresh clone is fine), and confirm every regenerated `expected.json` is byte-identical to the committed one. Store nothing new in the repository, and investigate every difference.
  6. Measure the logs that have only two distinct wrapper timestamps (spec §15 item 6). Report the counts and a recommendation, and record the user's decision in spec §15.
- [ ] **Step 4: Verify the §8.4 links** (with the user's go-ahead). Confirm that "Open in Codex" opens a live, an archived and a subagent session without un-archiving anything, and check what `codex resume <id>` does to an archived session.
  - Set `OPEN_IN_CODEX_SUPPORT` and `CONTINUE_IN_CLI_SUPPORT` from the results.
  - Write the verified behavior into the README.
  - Rerun the suite.
- [ ] **Step 5: Visual check.** Open the real page and compare it with `~/Downloads/colophon-mockups/` at 1440 px and 390 px. Report any visible divergence from the approved mockups as a finding.
- [ ] **Step 6: Deploy** only with the user's explicit approval.
  - Add `'colophon/colophon|colophon'` to `copy_mappings` in `tools/check_local_deployments.zsh` and to `COPY_MAPPINGS` in `tools/tests/test_check_local_deployments.zsh`, in alphabetical position after the `abacus usage` entry.
  - Add `- \`colophon\` <- \`colophon/colophon\`` to the `~/Library/Scripts` list in `docs/local_deployment_sync.md`.
  - Run `zsh tools/tests/test_check_local_deployments.zsh` and commit.
  - Then follow `docs/local_deployment_sync.md`: validate, back up, copy, byte-compare, run the installed `colophon --version`, and run the read-only audit.
- [ ] **Step 7: Hand off.**
  - Update `LESSONS_LEARNED.md` and the PKM.
  - Report the results, leading with problems: failing or unexplained items first, then the measurements, then what passed.

## Spec coverage map

| Spec section | Tasks |
|---|---|
| §1 Scope | all; non-goals enforced by Task 5 (no commentary or reasoning stored) and Task 9 (read-only database test) |
| §2 Delivery, flags, environment, runtime home, exit codes | 1, 8 (`--rebuild`), 17 (`--offline`, `--refresh-prices`), 18 |
| §3 Data sources, record table | 3 (classification), 4–7, 9 (SQLite, index, global state), 15 (`logs_2.sqlite`, A1) |
| §4 Pipeline, cache, live and crash damage (§4.1), deduplication | 3 (read, damage), 4 (open turns), 5 (dedup), 8 (cache), 10 (live classification), 17 (overlapping fetch), 18 (atomic writes) |
| §5.1 Sessions, titles, text, voice | 5, 9, 10 |
| §5.2 Turns and time | 3 (event time), 4, 10 (`idle_ms`, `user_span_ms`), 19 (time zones), 20 (time totals), 21 (span and idle in the stats strip) |
| §5.3 Subagents, forks, inherited prefix | 4, 11, 14 (fork tokens) |
| §5.4 Tool summary | 6 |
| §5.5 Tokens | 7, 14, 15 (A1 replaces the service-tier paragraph) |
| §5.6 Pricing and price history | 13, 16, 17, 18; 24 (A2 maintainer check) |
| §5.7 Workspaces | 12 |
| §5.8 Archived | 3 (`archived` flag), 19 (toggle) |
| §5.9 Roll-up rules | 15 (invariants), 18 (payload), 20 (`matchSession`) |
| §6 Embedded data contract | 18 (schema lock), contract section of this plan |
| §7 Visual direction | 19, 22; tokens section of this plan; A3 |
| §8.1–§8.4 Screens | 19, 20, 21; 26 (link verification) |
| §8.5 Layout rules | 22 |
| §8.6 Theming | 19 (theme lint) |
| §8.7 Page constraints | 18 (escaping), 19 (font, no external requests), 22 (accessibility) |
| §9 Errors and diagnostics | 18 (one test per row), 19 (footer) |
| §10 Privacy and security | 1 (modes), 12 (credential stripping), 17 (single request), global constraints |
| §11 Performance | 8 (cache hits keep warm runs to changed logs), 23 |
| §12 Testing | every task; 2 (fixtures), 19–22 (browser), 24 (local acceptance) |
| §13 Repository integration and deployment | 1 (guard), 25, 26 |
| §14 Attribution | 13–16 (header comments), 25 (README) |
| §15 Decisions and open items | A1–A3; 24 and 26 resolve items 1–4 and 6; item 5 (the light theme) is out of scope for v1 |

## Handoff note for the executor

When this plan is approved for implementation, follow superpowers:subagent-driven-development, one task at a time. Run the reviewer between tasks.

Prebuilt by the planner (2026-10-03), in the working tree and outside it:
- `colophon/tests/fixtures/token_cases/` and `colophon/tests/fixtures/scrubbed/` with their `expected.json` files, and the three maintainer tools under `colophon/tests/tools/` (committed in Task 14 Step 1);
- the pinned CodexBar CLI at `~/Downloads/colophon-prebuilt/codexbar-cli-3bbf6bc48/` (outside the repo; maintainer tools only). Read its `PROVENANCE.md` before running it.

User decisions already made (2026-10-03): A4 item 7 is approved (`b10`); the July/August start-ordinal behavior follows CodexBar (`s04`, `s07`); the scrubbed fixtures are approved for commit.

The tasks are ordered so that each one ends with a green suite. Do not reorder Task 13 after Task 14: the token port normalizes models through Task 13. Writing this plan is not approval to implement it; wait for the user's explicit go-ahead.
