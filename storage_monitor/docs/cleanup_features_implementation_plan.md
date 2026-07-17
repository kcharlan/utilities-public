# Cleanup Features Implementation Plan

**Project:** `storage_monitor` (single-file uv launcher at `storage_monitor/storage_monitor`, post-#82 single-pass-walk architecture)
**Goal:** Add five cleanup-intelligence features on top of the volume-wide index: (F1) growth diff view, (F2) command-based cleanup providers, (F3) Time Machine snapshot manager upgrades, (F4) auto-discovered caches, (F5) orphaned app-data detection.
**Executor notes:** All work happens in the launcher plus `tests/`. No new PEP 723 dependencies (`plistlib`, `shutil.which` are stdlib). The code is the source of truth — the function names below were verified against the post-#82 file, but re-verify before editing. The embedded React template is part of the launcher; per project experience, **always load the rendered page via Playwright after template edits** (a `\'` in a Python string becomes a bare `'` in the rendered JS and breaks the page silently).

## Probe-verified facts (probed 2026-07-12 on this machine — formats and API shapes are stable facts to build on; the *quantities* are point-in-time and will drift, see acceptance notes)

- `brew cleanup -n` ends with a line of the form `==> This operation would free approximately 6.8GB of disk space.` (currently 6.8 GB reclaimable).
- `docker system df --format '{{json .}}'` emits one JSON object per line with string fields `Type`, `TotalCount`, `Active`, `Size`, `Reclaimable` (e.g. `"1.173GB (48%)"`, `"0B"`). Fails when the daemon is down — the provider must degrade to "unavailable".
- `uv cache prune` has **no dry-run flag**; `uv cache dir` prints the cache path (`~/.cache/uv`). The estimate must come from the scan index and be labeled an upper bound.
- **(validated during implementation, 2026-07-12):** Storage Monitor itself runs under `uv run --script`, and the parent uv process holds the uv cache lock for the app's entire lifetime — a nested `uv cache prune` **blocks indefinitely** waiting for that lock. `--force` is forbidden: it bypasses in-use protections, and uv script environments live inside the cache, so it could delete the running app's own environment. **No uv cache mutation may ever be executed from inside the app** — the uv provider is therefore `manual` (below).
- `diskutil apfs listSnapshots -plist /System/Volumes/Data` returns a plist with a `Snapshots` array; each entry has `SnapshotName`, `SnapshotUUID`, `SnapshotXID` (int), `Purgeable` (bool), `LimitingContainerShrink` (bool), `RevertTo`, `RootTo`. Parse with `plistlib`, not text.
- `tmutil thinlocalsnapshots` usage: `tmutil thinlocalsnapshots <mount_point> [purgeamount] [urgency]`.
- There is **no macOS API for per-snapshot unique size**; mount-and-diff estimation is deferred (likely needs elevation, unverified) — measured-reclaim-on-delete is the honest substitute.
- `~/Library/Containers` has 813 entries; all but 5 are bundle-id-named (`com.vendor.app`). The 5 UUID-named dirs have permission-locked `.com.apple.containermanagerd.metadata.plist` files — **skip UUID dirs**; name-based matching covers the rest. `~/Library/Group Containers` entries are a **mix of naming forms** (observed here: 40 team-id-prefixed `TEAMID.name`, 108 `group.`-prefixed, 14 other, including stacked forms like `243LU875E5.groups.com.apple.podcasts`) — see F5 for the normalization rules this requires.
- Sizing for the growth-history table against the live index (393,522 nodes): `depth <= 5 AND allocated_bytes >= 10 MiB` → **3,174 rows/scan**; `depth <= 3` unfloored → 11,677. The chosen criteria are cheap.
- Cache-name query over the live index (`name IN ('Cache','Caches','.cache') OR LIKE '%.cache'`, ≥100 MiB) → 23 dirs, 44 GB (includes nested parents — ancestor dedup required).

## Current architecture (post-#82; verify before editing)

- Scan: `collect_scan_report(scan_id)` — phases `[("Metadata probes", .06), ("Volume walk", .70), ("Index persistence", .14), ("Report assembly", .10)]`; runs metadata probes via `run_parallel_call_map`, `collect_snapshot_section()` (currently `tmutil listlocalsnapshots` + name parsing), `walk_tree` → `resolve_hardlink_ownership` → `rollup_subtree_totals` → `persist_full_walk`, then `scan_watchlist(scan_id)`, `build_breakdowns_from_db`, `build_findings_section`, `fetch_large_files_from_db`, SSE events (`metadata_ready`, `snapshot_found`, `breakdown_ready`, `finding_added`, `large_file_found`), assembles `report` dict with sections `summary/breakdowns/watchlist/large_files/findings/snapshots/checks`.
- `finalize_scan_run(scan_id, report)` — marks active, then **deletes** `nodes`/`large_files`/`hardlink_inodes` rows of other scans, caps `scan_runs` at 30, conditional `VACUUM`. F1's history capture must be inserted in this transaction **before** those deletes.
- Actions: `resolve_action` validates a token against `findings` + `snapshots` items of the loaded report; `api_execute_action` dispatches `trash_path` / `delete_snapshot`; `record_action` appends to `action_log.jsonl`; `refresh_after_action` → `walk_subtree_and_store` + `rebuild_and_publish_report(scan_id, collect_metadata())`.
- Rebuilds: `build_updated_report(scan_id, base_report, metadata, watchlist, snapshots)` reconstructs the report after actions — new sections must be carried through it.
- Subtree refresh: `walk_subtree_and_store(scan_id, path)` under `SUBTREE_REFRESH_LOCK`; `_apply_delta_chain` helper.
- Legacy code retained by #82 (`_legacy_collect_scan_report`, `du_bytes`, `scan_directory_index`, `list_root_breakdown`, `scan_large_files*`, `select_data_prefetch_plan`): **out of scope** — do not extend it; if it is provably unreferenced, deleting it is a welcome free-standing commit, otherwise leave it.
- Frontend: single embedded React template (`HTML_TEMPLATE`), tabbed action panel, SSE-driven state, dark mode. Old persisted reports will lack the new sections — every new UI element must tolerate a missing section (render empty state, never crash; `ErrorBoundary` exists but is a last resort).

Version: bump `VERSION` to `0.3.0`.

---

## F1: Growth diff view

**Why first:** post-#82 pruning keeps only the latest scan's node rows, so cross-scan per-directory diffs need a compact aggregate captured before each prune.

**Schema** — add to `initialize_scan_db` (idempotent):

```sql
CREATE TABLE IF NOT EXISTS scan_dir_history (
    scan_id INTEGER NOT NULL, completed_at TEXT NOT NULL,
    path TEXT NOT NULL, root_key TEXT NOT NULL, depth INTEGER NOT NULL,
    allocated_bytes INTEGER NOT NULL, PRIMARY KEY (scan_id, path));
CREATE INDEX IF NOT EXISTS idx_dir_history_path ON scan_dir_history (path, scan_id);
```

**Capture** — inside `finalize_scan_run`'s existing transaction, *before* the `DELETE FROM nodes...` statements: insert from the finalizing scan's nodes where `depth <= 5 AND (allocated_bytes >= 10485760 OR depth <= 1)` (≈3.2k rows on this machine), stamping the scan's completion time. Retention in the same transaction: keep rows only for the 60 most recent distinct `scan_id`s in `scan_dir_history` (independent of the 30-run `scan_runs` cap — history intentionally outlives pruned runs). Constants: `GROWTH_HISTORY_MAX_DEPTH = 5`, `GROWTH_HISTORY_MIN_BYTES = 10 * 1024 * 1024`, `GROWTH_HISTORY_MAX_SCANS = 60`.

**API** — `GET /api/growth?baseline_scan_id=<int>&limit=<int>` (both optional):
- Response: `{"baselines": [{"scan_id", "completed_at"}...newest first], "baseline_scan_id": <resolved>, "current_scan_id": <active>, "items": [...], "updated_at"}`.
- Default baseline = the most recent history scan_id before the active one; no history or no active scan → `items: []` plus `baselines` (UI shows empty state prompting a second scan).
- Items: full-outer join of the active scan's history rows vs the baseline's on `path` (a path missing on one side contributes 0 and is flagged `"status": "new"` / `"removed"`; both present → `"changed"`); each item `{path, root_key, depth, baseline_bytes, current_bytes, delta_bytes, status}`; order by `abs(delta_bytes)` desc; drop `delta_bytes == 0`; `limit` default 50.
- Note in code why the join uses history-vs-history (not live nodes): both sides must come from the same depth/floor domain or floored-out dirs masquerade as growth.

**UI** — new "Growth" tab in the action panel: baseline picker (dropdown of `baselines`, labeled by relative date, default "previous scan"), gainers/shrinkers toggle, table of path / delta (signed, colored) / current size / status badge (`new`/`removed`); clicking a row opens the existing breakdown drill-down at that path (reuse the existing drill-down invocation the treemap uses). Empty state explains that two completed scans are required.

## F2: Command-based cleanup providers

**Model** — module constant `PROVIDER_SPECS`, one entry per provider: `slug`, `label`, `description`, `binary` (for `shutil.which` detection), `risk`, probe + execute definitions. Providers: 

| slug | probe (estimate) | execute | estimate_kind | risk |
|---|---|---|---|---|
| `brew-cleanup` | `brew cleanup -n` (timeout 180s); parse final `approximately X of disk space` line, regex `approximately\s+([\d.]+)\s*([KMGT]?B)` | `brew cleanup` | `approximate` (brew's own wording — do not present it as exact) | low |
| `docker-prune` | `docker system df --format '{{json .}}'` (timeout 60s); sum `Reclaimable` leading values (regex `^([\d.]+)\s*([KMGT]?B)`) over the `Type` rows **`Images`, `Containers`, and `Build Cache` only — exclude `Local Volumes`** (`prune -f` never removes volumes without `--volumes`, which this provider must not pass) | `docker system prune -f` | `upper_bound` (the Images row counts *all unused* images while `prune -f` removes only *dangling* ones, so even volume-excluded the sum can exceed what is freed — say so in `description`) | medium |
| `uv-cache` | `uv cache dir` → look the path up in the active scan index (canonical `~/.cache/uv`) | **manual — no in-process execution.** Render `uv cache prune` as a copyable command with the instruction to quit Storage Monitor first (the app's parent uv process holds the cache lock; a nested prune deadlocks, and `--force` could delete the running script environment) | `upper_bound` (prune keeps in-use entries) | low |

Deliberately excluded: `npm`/`pip` caches (already trash-actionable via the watchlist — do not duplicate); providers requiring elevation.

**Functions** — `probe_providers(scan_id) -> {"items": [...], "updated_at"}` running probes via the existing `run_parallel_call_map`; per item: `{slug, label, description, available (bool), unavailable_reason, estimate_bytes, estimate_kind, risk, duration_ms, action_token, actions}`. `estimate_kind` is one of exactly two values — `"approximate"` (a best-effort figure, e.g. brew's own "approximately") or `"upper_bound"` (a ceiling the execute command may not reach) — there is deliberately no `"exact"` kind, because no provider can promise one. Each spec also carries `execution: "action" | "manual"`: `action` providers get an `action_token` and an execute command; `manual` providers get `action_token: None` plus a `manual_command` string and instruction text for the user to run outside the app (uv is the first — see the lock finding above). `available=False` when the binary is missing or the probe fails (e.g. docker daemon down → put stderr's first line in `unavailable_reason`). Token payload: `{"kind": "provider_execute", "slug": ...}`. Share one unit parser `parse_size_token(value: str, unit: str) -> int` (KB/MB/GB/TB, decimal 1000-based to match brew/docker display units — document the choice) — the No-Duplicate-Logic rule applies across both parsers.

**Scan integration** — new phase between persistence and assembly: phases become `[("Metadata probes", .05), ("Volume walk", .65), ("Index persistence", .13), ("Cleanup intelligence", .10), ("Report assembly", .07)]` (the frontend renders phase names verbatim; only `initializing` is special-cased). Run `probe_providers` there (brew's ~10s runs parallel with F4/F5 collection); publish each item via a new SSE event `provider_ready`; add report section `"providers"`. `build_updated_report` carries the section from `base_report` unchanged **except** when the refresh follows a `provider_execute` action, in which case only that provider is re-probed (never re-run all probes on unrelated actions — brew is slow).

**Execution** — extend `api_execute_action`/`resolve_action`: add `providers` items to the allowed-token set (alongside `findings` and `snapshots`) — only `execution == "action"` items carry tokens, so `manual` providers are structurally excluded; `execute_provider(slug)` must additionally reject a `manual` slug defensively (400) even if a token were forged. The executor runs the spec's execute command (timeout 600s), wraps it in the measured-reclaim helper (F3), returns `{ok, label, slug, stdout tail, estimated vs observed bytes}`; `record_action` as usual; refresh = re-probe that provider + `collect_metadata` + rebuild/publish report.

**UI** — "Providers" group at the top of the actions/findings tab (or its own tab — match existing tab ergonomics): row per provider with estimate (prefix "up to " when `estimate_kind == "upper_bound"`, "~" when `"approximate"`), risk badge, run button with confirm dialog for `action` providers, and for `manual` providers a copyable command with its instruction text ("quit Storage Monitor, then run …") instead of a run button; unavailable rows greyed with reason; completion toast shows observed free-space change.

## F3: Snapshot manager upgrades

**Enrichment** — rewrite `collect_snapshot_section()` to run `diskutil apfs listSnapshots -plist /System/Volumes/Data`, parse with `plistlib` (`parse_snapshot_plist(stdout_bytes) -> List[dict]`; note `run_command` returns text — either add a bytes mode or encode back, executor's choice), and merge onto the existing item shape: keep `snapshot_name`, `token`, `parsed_date`, `action_token` exactly as today (the delete flow and UI depend on them), add `uuid`, `xid`, `purgeable` (bool), `limiting_container_shrink` (bool). If `diskutil` fails, fall back to the current `tmutil listlocalsnapshots` path with the new fields `None` — the section must never come back empty just because enrichment failed.

**Measured reclaim** — shared helper `measure_free_space_delta(operation: Callable) -> Tuple[result, Optional[int]]`: capture `collect_metadata()["container_free_bytes"]` before and after the operation and return the observed delta (None if either read fails). Wrap `execute_delete_snapshot` and F2's `execute_provider` with it; add `observed_reclaimed_bytes` to the action result and the `record_action` log entry. Label it in the UI as *observed free-space change* — APFS frees purgeable space lazily and other processes churn, so it can be low or even negative; never present it as an exact measurement.

**Thin endpoint** — `POST /api/snapshots/thin` with body `{"bytes": <int > 0>, "urgency": <1-4, default 2>}` → validate, run `tmutil thinlocalsnapshots / <bytes> <urgency>` (timeout 600s), parse thinned snapshot names from stdout (lines beginning `com.apple.TimeMachine.`), wrap in the measured-reclaim helper, `record_action` (`kind: "thin_snapshots"`), then rebuild: fresh `collect_snapshot_section` + `collect_metadata` + `rebuild_and_publish_report`. Response: `{ok, thinned: [names], observed_reclaimed_bytes}`. This does not use the action-token flow (no per-item token) — it's a first-class endpoint like `rescan-path`.

**UI** — snapshot manager gains: relative age column, `Purgeable` badge, a highlighted "limits container shrink — deleting this frees the floor" badge on `limiting_container_shrink` items, default sort oldest-first, and a "Reclaim space…" button opening a dialog (GB amount + urgency radio, explanation that macOS chooses which snapshots to thin) wired to the thin endpoint; delete/thin completion toasts show observed reclaim.

**Deferred (do not build):** per-snapshot size via snapshot mounting — no public API, elevation requirement unverified; revisit only if measured-reclaim history proves insufficient.

## F4: Auto-discovered caches

**Function** — `discover_cache_candidates(scan_id) -> List[dict]` (finding-shaped), pure SQL over the active scan's `nodes` plus post-filtering:
- Match: `name IN ('Cache', 'Caches', '.cache') OR name LIKE '%.cache'`, `allocated_bytes >= CACHE_DISCOVERY_MIN_BYTES` (new constant, 100 MiB), `root_key = 'home_root'` only (never propose trashing system-managed paths).
- Exclusions (post-filter in Python, order matters):
  1. for every **actionable** `WATCHLIST_SPECS` entry (`actionable: True` — e.g. `~/Library/Caches/Homebrew`, `~/Library/Caches/ms-playwright`, `~/.npm/_cacache`): exclude the expanded path **and all descendants** — the watchlist already offers the trash action there, and listing a subtree of it would double-count reclaim;
  2. for every **non-actionable** `WATCHLIST_SPECS` entry (e.g. the `~/Library/Caches` aggregate, `~/Downloads`): exclude **only the exact path**, never its descendants — these entries are aggregates or review-manually markers, and their large qualifying children are precisely what discovery exists to surface (e.g. `~/Library/Caches/<vendor>` dirs that no watchlist entry names). Do not special-case `~/Library/Caches` by path; key the two behaviors off the spec's `actionable` flag so future watchlist edits inherit the right semantics;
  3. any path component ends with a bundle suffix from a new constant `CACHE_DISCOVERY_BUNDLE_SUFFIXES = ('.app', '.photoslibrary', '.musiclibrary', '.tvlibrary', '.aplibrary')` (never reach inside bundles);
  4. under `~/.Trash`;
  5. **ancestor dedup**: if another surviving candidate is an ancestor, drop the descendant (keep the topmost — probe showed 23 raw matches at 44 GB with nested parents).
- Risk: `low` when under `~/Library/Caches` or `~/.cache`, else `medium` (e.g. a `Caches` dir inside Application Support). Category `discovered_cache`, `cleanup_kind: "trash_path"`, actionable, token + actions via the existing `encode_action_token`/`build_finding_actions` machinery, description like `"Cache-named directory discovered by index scan. Apps rebuild caches; verify the owner before trashing."`
- Integration: call during the "Cleanup intelligence" phase; merge the returned items into `build_findings_section`'s input (they sort into the existing findings list by reclaim size and respect `MAX_FINDINGS`); each publishes the existing `finding_added` SSE event — **zero new UI** beyond a category badge for `discovered_cache`. Because the merge happens in `build_findings_section`, post-action rebuilds (`build_updated_report` → `build_findings_section`) must re-run discovery against the index — it's a fast SQL query; pass `scan_id` through.
- Trash execution already works via the existing `trash_path` flow, including subtree-refresh — no new action code.

## F5: Orphaned app-data detection (report-only)

**Functions:**
- `collect_installed_bundle_ids() -> Set[str]` — enumerate `*.app` in `/Applications`, one subdirectory level below it, `/System/Applications`, and `~/Applications`; read each `Contents/Info.plist` with `plistlib` and collect `CFBundleIdentifier` (unreadable/missing → skip silently). Runs once per scan in the "Cleanup intelligence" phase.
- `collect_orphan_candidates(scan_id, installed_ids) -> {"items": [...], "updated_at"}`:
  - Enumerate immediate children of `~/Library/Containers` and `~/Library/Group Containers` (names via `iterdir`, sizes via index lookup on the stored path; size `None` if the index lacks the row).
  - Skip UUID-named dirs first (regex `^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$` — verified: 5 of 813 here, metadata unreadable).
  - **Normalize before any exclusion or matching.** Group Containers names come in several observed forms (on this machine: 40 team-id-prefixed, 108 `group.`-prefixed, 14 other; plus stacked forms like `243LU875E5.groups.com.apple.podcasts`): strip a leading team-id (regex `^[A-Z0-9]{10}\.`) if present, **then** strip a leading `group.` or `groups.` prefix if present. Both strips may apply to one name.
  - Only **after** normalization, skip any id starting `com.apple.` (OS-owned). Ordering is load-bearing: without the `group.` strip, `group.com.apple.*` would bypass the Apple exclusion and be falsely reported as orphaned, and `group.com.vendor.app` would never match installed `com.vendor.app`.
  - **Match rule (conservative — a false "orphan" is worse than a miss):** the candidate id `c` is *matched* if any installed id `b` satisfies `c == b`, `c.startswith(b + '.')`, `b.startswith(c + '.')`, **or** `c` and `b` share their first two dot-components (vendor match, e.g. `com.1password.*` helpers survive if any 1Password app is installed). Unmatched → orphan candidate.
  - Items sorted by size desc, cap 40: `{name, path, allocated_bytes, source: 'containers'|'group_containers', actions: [Reveal in Finder only], risk: 'high', actionable: False}`.
- Report section `"orphans"`; SSE event `orphan_found` per item (mirroring `large_file_found`); carried through `build_updated_report` unchanged (recomputing on every action is wasteful and the data is slow-moving).

**UI** — "App Leftovers" tab: banner stating this is a heuristic (an app distributed outside `/Applications`, e.g. via `brew` casks in other locations or launchd-only tools, will look orphaned — verify before deleting anything manually), table of name / size / source / Reveal button. Deliberately **no trash action** in this iteration.

## Cross-cutting

- **Report schema:** additions are strictly additive (`providers`, `orphans` sections; new snapshot item fields; `discovered_cache` findings category). Existing section shapes are frozen. The UI must tolerate all new sections being absent (old `latest_scan.json`).
- **`resolve_action`** gains `providers` as a token source; nothing else about token validation changes.
- **SSE:** new event types `provider_ready`, `orphan_found`. Existing event payloads unchanged.
- **`refresh_after_action`** learns `provider_execute` (re-probe that provider only + metadata + rebuild). `trash_path` for a discovered cache needs no new code.
- **Ordering:** F1 (schema + capture first — every scan without it loses history forever) → F3 (isolated) → F2 → F4 → F5 → UI polish. Commit per feature; feature branch. This plan file is currently untracked — include it in the documentation commit (precedent: the single-pass-scan plan was committed with #82).

## Tests (`tests/test_cleanup_features.py`, launcher loaded via `tools.testkit.load_launcher`; embed the probe-captured outputs as fixtures)

**Entry:** run the existing full suite first and record the baseline (`.venv/bin/python -m pytest -q` per README; also `uv run --script tools/check_uv_headers.py`).

1. **Size parser:** `("6.8", "GB")`, `("1.173", "GB")`, `("0", "B")`, `("34.6", "MB")` → bytes; garbage → None/raise per chosen contract.
2. **brew probe parser:** fixture with the real `==> This operation would free approximately 6.8GB of disk space.` line → estimate with `estimate_kind == "approximate"`; fixture without the line → `available=False` or estimate `None` (pick one, assert it).
3. **docker probe parser:** the four captured JSON lines → estimate = Images (1.173 GB) + Containers (0 B) + Build Cache (0 B), and explicitly assert Local Volumes' 16.24 MB is **excluded** from the sum (regression for the prune/volumes semantics); malformed line skipped; nonzero-exit probe → `available=False` with `unavailable_reason`.
4. **uv manual provider:** fixture nodes row for the cache dir → `estimate_bytes` equals it (missing row → available with `estimate_bytes=None`); `execution == "manual"`, `action_token is None`, `manual_command == "uv cache prune"` — and a regression assertion that the provider item's execute path cannot be reached: `execute_provider("uv-cache")` raises/400s even when called directly (the uv-lock deadlock must never be reintroducible via a forged token).
5. **Provider token flow (brew fixture):** report containing an `action` provider item → its token resolves; a forged token absent from the report → 400; a forged token naming a `manual` slug → 400. Execute path with `run_command` monkeypatched: correct command, `record_action` written, only that provider re-probed.
6. **Snapshot plist parser:** embedded captured plist → items with `purgeable=True`, `limiting_container_shrink=True` on the first entry, names/UUIDs/XIDs correct; `diskutil` failure → tmutil fallback with new fields `None`.
7. **Thin endpoint:** rejects `bytes<=0` and `urgency` outside 1–4; command constructed as `tmutil thinlocalsnapshots / <bytes> <urgency>`; thinned names parsed from fixture stdout.
8. **Measured reclaim:** monkeypatched `collect_metadata` returning decreasing free space → positive delta; failed metadata read → `None`, never an exception.
9. **Growth capture & retention:** fixture nodes for a scan → `finalize_scan_run` writes exactly the rows meeting `depth<=5 AND (>=10MiB OR depth<=1)`; rows survive the node prune (regression: capture ordered before deletes); 61st scan's finalize evicts the oldest history scan.
10. **Growth API join:** baseline + current fixtures with a grown dir, a shrunk dir, a new dir, a removed dir, an unchanged dir → deltas, statuses, ordering by `abs(delta)`, unchanged dropped; no baseline → empty items + baselines list.
11. **Cache discovery:** fixture index reproducing the probe shape → exactly the expected candidates survive, pinning both watchlist behaviors: a large child of the non-actionable `~/Library/Caches` aggregate (e.g. `~/Library/Caches/Google`) **survives** with risk `low` while `~/Library/Caches` itself is excluded; a descendant of an actionable entry (e.g. a `Caches` dir under `~/Library/Caches/Homebrew`) is **excluded**; plus a nested `Caches` parent+child pair (ancestor dedup keeps the topmost), a `.cache` under a `.photoslibrary` component (excluded), a sub-threshold dir (excluded), and a `data_root` match (excluded); a non-`~/Library/Caches`/`~/.cache` survivor gets risk `medium`; resulting findings carry trash tokens.
12. **Orphan classification:** installed set `{com.1password.1password, ai.perplexity.mac}` against candidates `com.1password.browser-support` (vendor match → kept out of orphans), `at.obdev.littlesnitchmini` (orphan), `com.apple.Safari` (skipped), UUID name (skipped), `2BUA8C4S2C.com.1password` (team-id stripped → vendor match), **`group.com.1password.family` (`group.` stripped → vendor match), `group.com.apple.notes` (`group.` stripped → Apple exclusion applies — regression for the bypass), `243LU875E5.groups.com.apple.podcasts` (both prefixes stripped → Apple exclusion applies)**, and `group.net.whatsapp.family` (stripped, no installed match → orphan); sizes pulled from fixture index.
13. **Additive report:** `build_updated_report` preserves `providers`/`orphans` from base and re-runs cache discovery; a base report *without* the new sections rebuilds without KeyError.

**Exit (all mandatory, report every failure):**
1. Full suite green; drift guard; `./storage_monitor --help`; `UTILITIES_TESTING=1` smoke boot (per README).
2. Real-scan acceptance: run **two** full scans; total scan time still ≤ 60s (new probes run parallel; brew adds ~10s worst case); report contains `providers` with the brew provider `available` and a well-formed non-negative estimate (it was 6.8 GB when probed on 2026-07-12, but brew's periodic auto-cleanup may have shrunk it by implementation time — assert shape and availability, not a magnitude), enriched `snapshots` (purgeable flags present), `orphans`, and `discovered_cache` findings; `GET /api/growth` returns baselines from both scans and a coherent diff.
3. Provider execute-path coverage is **mock-only** (test 5) — no provider is executed live during validation. The uv provider is `manual` (the app cannot prune the uv cache from inside a uv-managed process — see the lock finding in probe facts), so validation for it is: the Playwright step confirms the manual row renders its instruction text and copyable `uv cache prune` command, and test 4 pins that its execute path is unreachable. Do not execute brew/docker cleanup as part of validation; live execution of those remains the user's call after delivery.
4. Thin end-to-end is **user-judgment**: verify the dialog and command construction via tests/mocks; only run a real thin if the user approves losing snapshot restore points.
5. Playwright UI walkthrough (per project feedback memory — template edits must be verified in a rendered browser): page loads with no console errors, Growth tab renders a diff after the two scans, Providers rows render with estimates and an unavailable-state row if docker is stopped, snapshot badges visible, App Leftovers tab renders, a `discovered_cache` finding is visible and its Reveal action works, dark mode still renders every new element.
6. README: update capabilities (growth view, providers, snapshot enrichment + thin, discovered caches, app leftovers) and Runtime State (`scan_dir_history` retention).

## Hard constraints

- Existing report section shapes, SSE payloads, and the action-token flow are frozen; every addition is additive and optional for the UI.
- Stdlib only; single-file launcher; PEP 723 header unchanged.
- Providers never run elevated commands and never execute anything not user-triggered; probes are read-only (`-n` / `df` / `dir`). The app never mutates the uv cache in-process (nested `uv cache prune` deadlocks on the parent uv's lock; `--force` could destroy the running environment) — `manual` execution is the only permitted form for uv, now and in future revisions.
- Orphans are report-only in this iteration — no trash action, however tempting.
- `finalize_scan_run` ordering: history capture **before** node pruning, same transaction — a scan that prunes before capturing destroys that scan's growth data permanently.
- Estimates must be labeled honestly: `estimate_kind` is only ever `approximate` ("~" in UI) or `upper_bound` ("up to" in UI) — no `exact` kind exists; measured deltas are "observed free-space change", never "freed exactly".
