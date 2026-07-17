# Single-Pass Scan Implementation Plan

**Project:** `storage_monitor` (single-file uv launcher at `storage_monitor/storage_monitor`)
**Goal:** Replace the multi-walk `du`/`find` scan architecture with one parallel `os.scandir` traversal of `/System/Volumes/Data` that feeds every scan consumer, cutting full-scan wall time from ~128s to ~35s and fixing unbounded SQLite growth.
**Executor notes:** All work happens inside the single launcher file plus `tests/`. No new PEP 723 dependencies — the walker is stdlib (`os`, `threading`, `concurrent.futures`). The code is the source of truth: verify every function/behavior named here against the current file before changing it.

## Revision history

- **Rev 6** — addresses a stale-snapshot race: two overlapping subtree refreshes could commit in reverse order of their filesystem walks, regressing the index to an older state even with serialized decision phases (Rev 5's "concurrent overlapping walks are never incorrect" claim was wrong — it guaranteed internal consistency, not freshness). Fix: a module-level `SUBTREE_REFRESH_LOCK` serializes every subtree operation end-to-end, acquired *before* the filesystem walk and held through commit; the missing-ancestor fallback releases both locks before re-invoking; a lock-ordering rule prevents deadlock (§WI-6, §6). A generation/retry scheme that would keep walks concurrent is documented as a rejected-for-now alternative.
- **Rev 5** — addresses two concurrency findings: (1) all subtree-refresh decision-making — old-total read, ownership resolution, attribution/rollup, and chain resolution — now happens inside the `DB_WRITE_LOCK` critical section, with only the filesystem walk outside it, so concurrent refreshes cannot commit decisions computed against the same stale registry or a stale delta baseline; a new guard treats an `st_nlink == 1` candidate with no registry row as an ordinary file (§WI-1b, WI-6); (2) on-demand subtree persistence no longer targets a running scan: `choose_scan_id_for_path` drops its `fetch_running_scan_id()` preference (obsolete once the full walk indexes the entire volume), the locked section revalidates the scan is still active before writing, full-scan node persistence uses upsert SQL as defense in depth, and `api_breakdown`'s no-scan fallback branch is explicitly replaced with an ephemeral non-persisting walk (§WI-3, WI-6).
- **Rev 4** — addresses three hard-link consistency findings: (1) files whose inode is registered in `hardlink_inodes` are emitted as candidates even when their current `st_nlink == 1`, so an owner deletion that collapses the link count no longer bypasses reconciliation (§WI-1 item 4, WI-1b); (2) the registry stores `dev` and owner validity is checked with `os.lstat` comparing `(dev, ino)` — never bare `os.path.exists` — guarding against path recreation (and inode reuse on non-APFS volumes; APFS file IDs are 64-bit monotonic and not reused, but the recreated-path case makes identity validation necessary regardless) (§WI-1b); (3) subtree persistence, ownership changes, and *both* ancestor-delta chains now commit in a single transaction, with chain resolution done read-only beforehand under `DB_WRITE_LOCK`, so a crash or concurrent reader can never observe a transferred ownership without its paired adjustments (§WI-6).
- **Rev 3** — addresses three review findings on subtree-refresh correctness: (1) subtree persistence is now transactional delete-then-insert over a *stored-prefix set*, so descendants deleted on disk disappear from the index (§WI-6); (2) large-file persistence semantics are split — full scans write into a fresh `scan_id` (no delete needed), subtree walks delete-within-prefix-set + insert in the same transaction, never replace-by-root-key (§WI-3, WI-6); (3) hard-link ownership transfer now pairs every reassignment with a negative adjustment through the former owner's ancestor chain, and `walk_subtree_and_store` always propagates its own delta, keeping volume-root totals invariant under transfers (§WI-1b, WI-6).
- **Rev 2** — addresses two review findings: (1) subtree walks arrive in *canonical* path space (`store_breakdown_for_path` and `api_rescan_path` canonicalize before scanning), so the translation table now includes canonical identity mappings and the "boundary parent" rule is replaced by uniform `dirname` parents plus alias bridge rows (§WI-2); (2) hard-link dedup is now backed by a persisted, deterministic inode-ownership registry so subtree refreshes reconcile against full-scan attribution instead of corrupting ancestor totals via delta propagation (§WI-1b, WI-6).
- **Rev 1** — initial plan.

---

## 1. Motivation — measured, not estimated

From the real scan report (`~/.storage_monitor/latest_scan.json`, `checks[]` durations; 128s total wall):

| Phase | Time | Problem |
|---|---|---|
| `du -x -k -d 1 /System/Volumes/Data` | 64.8s | Walks the entire volume, single-threaded |
| `du -x -k ~` (home index) | 63.3s | Re-walks home, which is *on* the Data volume |
| Data-volume prefetch (`scan_directory_index` × top 6 children) | ~40s | Re-walks trees just walked |
| `find -size +1024M` over home buckets | 19.3s | Third walk of the same files |
| Watchlist `du -xsk` × 20 paths | 2.5s | Fourth walk of cache dirs |

The same files are statted 3–5×, every walk is single-threaded, and home is *stored twice* in the nodes table (once under `/Users/<user>/...` from the home index, once under `/System/Volumes/Data/Users/example` from the prefetch) — a major contributor to the 1.1 GB `storage_monitor.db`.

**Validated probe (2026-07-12, this machine):** an 8-thread `os.scandir` walker over all of `/System/Volumes/Data` (392,797 dirs, 2,527,993 files) completed in **27.9s** mostly-cold, plus **0.2s** for bottom-up subtree rollup. Byte totals matched `du` **exactly** (−0.00% overall; every top-level child within ±0.01%) with hard-link dedup enabled. The same warm-cache `du -d 1` took 48.9s. Separately benchmarked on `~/Library` (572k files, warm): `du` 16.1s vs 8-thread walker 5.9s. Hard-link dedup is mandatory for parity: without it the walker over-counted `~/Library` by ~3 GB.

Projected new scan: metadata probes (~0.3s) + walk (~28s) + rollup (~0.2s) + DB persistence (~5–10s) ≈ **~35s**, replacing 128s, with the entire volume drill-down-indexed (today only home, `/Applications`, and 6 prefetched Data children are indexed).

## 2. Non-goals

- No FSEvents incremental rescan (future work; this plan makes it possible by producing a complete persisted index).
- No new cleanup features (snapshot sizing, brew/docker providers, growth diff — separate plans).
- No UI/React template changes except where a backend-supplied string must change (noted in WI-4). The frontend only special-cases `phase === 'initializing'`; all other phase names are display-only.
- No change to the report JSON schema, SSE event types, or action-token flows. These are hard constraints (§6).

## 3. Current architecture inventory (verify against code before editing)

Scan pipeline (all in the launcher):
- `collect_scan_report(scan_id)` — orchestrates phases, weights, SSE events.
- `list_root_breakdown(root, limit)` — `du -d 1` wrapper; also used by on-demand endpoints.
- `scan_directory_index(root, root_key)` — full-depth `du`, one row per directory; calls `Path(path_str).resolve()` per output line (expensive; goes away with `du`).
- `scan_immediate_child_breakdown(...)` — parallel `du_bytes` per child (check callers; remove if unused after rewiring).
- `scan_watchlist()` / `scan_watchlist_entry(spec)` — `du_bytes` per `WATCHLIST_SPECS` path.
- `scan_large_files(roots)` / `scan_large_files_in_root(root)` — `find -size +1024M` (apparent-size semantics).
- `select_data_prefetch_plan(items)`, `mark_alias_path_cached(...)`, `alias_target_for_data_child(path)`, `canonicalize_breakdown_path(path)` — firmlink/alias handling between Data-volume paths and canonical roots. Note carefully: `canonicalize_breakdown_path` maps `/System/Volumes/Data/Users/<user>/**` → `/Users/<user>/**` and `/System/Volumes/Data/Applications` → `/Applications` (via `ALIASABLE_ROOT_TARGETS` + `samefile`), and **the on-demand endpoints canonicalize before scanning** — so any subtree scan entry point receives canonical-space paths, not data-space paths.
- `du_bytes(path)` — `du -xsk` wrapper; also used by `execute_trash_path` for the pre-move size estimate.
- Persistence: `upsert_node_rows`, `store_immediate_breakdown`, `replace_large_file_rows`, `upsert_large_file_rows`, `remove_cached_subtree`, `fetch_breakdown_from_db`, `fetch_large_files_from_db`.
- Endpoints/refresh: `api_breakdown`, `api_rescan_path`, `store_breakdown_for_path`, `refresh_directory_chain` (re-runs a full subtree `du` for **every ancestor** up to the root — replace, see WI-6), `refresh_large_files_for_paths`, `refresh_after_action`, `rebuild_and_publish_report`, `choose_scan_id_for_path` (currently prefers `fetch_running_scan_id()` — a preference WI-6 removes).
- Path guards: `ALLOWED_BREAKDOWN_ROOTS`, `ROOT_PATHS`, `ALIASABLE_ROOT_TARGETS`, `EXCLUDED_BREAKDOWN_PATHS`, `validate_breakdown_path`, `root_key_for_path`.
- Constants: `SCAN_WORKER_COUNT`, `DATA_VOLUME_PREFETCH_CHILD_COUNT`, `LARGE_FILE_THRESHOLD_BYTES`, `MAX_TOP_ITEMS`.

Tests: `tests/test_smoke.py` loads the launcher in-process via `tools.testkit.load_launcher` — use the same mechanism for new tests. Dev deps: `requirements-dev.txt` (fastapi, uvicorn, pytest).

## 4. Work items

### WI-1: Volume walker core

Add to the launcher:

- `@dataclass WalkResult` with fields: `dir_local: Dict[str, int]` (per-directory bytes in *walked* path space: ordinary files directly inside + the directory entry's own blocks), `hardlink_candidates: List[Tuple[int, str, str, int, int]]` (`(ino, walked_path, walked_parent, allocated_bytes, st_nlink)` — **not** yet counted in `dir_local`; see WI-1b), `large_files: List[Dict[str, Any]]` (each: `path`, `parent_path`, `name`, `apparent_bytes`, `allocated_bytes`, walked space), `dir_count: int`, `file_count: int`, `error_count: int`, `duration_ms: int`.
- `walk_tree(root: Path, *, workers: int, excluded_paths: List[Path], registered_inodes: Optional[Set[int]] = None, progress_callback: Optional[Callable[[int], None]] = None) -> WalkResult` — parallel traversal. `registered_inodes` is the active scan's `hardlink_inodes` ino set, loaded once before a subtree walk (read-only, shared across threads without locking); `None` for full scans (fresh registry).
- `rollup_subtree_totals(dir_local: Dict[str, int], root: str) -> Dict[str, int]` — bottom-up aggregation: iterate paths sorted by descending `/`-count; add each path's running total to its `os.path.dirname` parent when the parent is present. Pure function, no I/O. Called **after** hard-link resolution has added owned bytes into `dir_local` (WI-1b). (Probe: 0.2s for 393k dirs.)

Walker semantics — these define `du` parity and each needs a test (WI-9):
1. `os.scandir` per directory; `entry.stat(follow_symlinks=False)` per entry. Never follow symlinks (a symlink counts only its own blocks, as a file).
2. Skip any entry whose `st_dev` differs from the root's (replicates `du -x`; handles nested mounts and firmlink targets on other volumes).
3. Allocated bytes = `st_blocks * 512`. Also capture `st_size` (apparent) for large-file records.
4. Non-directory entries with `st_nlink > 1` **or whose `st_ino` is in `registered_inodes`** are recorded as `hardlink_candidates` and contribute **nothing** to `dir_local` during the walk; ownership resolution (WI-1b) decides attribution afterwards. The registry check is what catches a link whose sibling (the registered owner) was deleted, collapsing `st_nlink` to 1 — without it, such a file would be counted as an ordinary file while its bytes remain persisted in the former owner's ancestor totals, and reconciliation would never run. Directories are never treated as hard links.
5. A directory's own entry blocks belong to its **own** `dir_local` total (parent passes them down when submitting the child), matching how `du` attributes directory blocks.
6. `OSError` on `scandir` or `stat` (permission, disappeared-mid-walk): increment `error_count`, skip, continue — same effective behavior as `du`'s stderr complaints. Probe saw 425 such errors; that is normal.
7. Prune descent into any path in `excluded_paths` (compare resolved strings) — pass `EXCLUDED_BREAKDOWN_PATHS` (`/System/Volumes/Data/Volumes`).
8. Large-file capture in-pass: record entries with `apparent_bytes >= LARGE_FILE_THRESHOLD_BYTES` (apparent, not allocated — preserves the current `find -size +1024M` semantics; sparse files like `Docker.raw` rank by their apparent size exactly as today). Hard-linked large files are captured at every sighting; persistence dedupes by path.
9. `progress_callback(dirs_completed)` invoked roughly every 2,000 completed directories.

Concurrency: one `ThreadPoolExecutor` (bounded workers), each directory is one task that submits its subdirectories as new tasks. Threads release the GIL during `scandir`/`stat`, so stdlib threading is sufficient. Completion detection is the one load-bearing pattern — a naive "wait for futures" deadlocks because tasks spawn tasks:

```python
# under a shared lock: pending starts at 1 for the root submission
pending += len(subdirs)      # before submitting children
...
pending -= 1                 # at the end of each task
if pending == 0:
    done.set()               # threading.Event the caller waits on
```

Per-task work (accumulating local bytes, collecting subdirs) happens without the lock; only the shared-state merge (dir_local write, counters, pending) takes it.

### WI-1b: Deterministic hard-link ownership

**Why this exists (review finding 2):** in-walk first-seen dedup is thread-timing-nondeterministic within a full scan, and a later subtree-only walk would re-count links whose bytes the full scan attributed elsewhere — comparing that against the stored subtree total and delta-propagating would corrupt ancestor totals. Fix: every multi-link inode has exactly one deterministic *owner path*, persisted per scan, and all walks (full and subtree) attribute its bytes only at the owner.

- New table in `initialize_scan_db` (idempotent `CREATE TABLE IF NOT EXISTS`):
  `hardlink_inodes (scan_id INTEGER NOT NULL, ino INTEGER NOT NULL, dev INTEGER NOT NULL, owner_path TEXT NOT NULL, allocated_bytes INTEGER NOT NULL, PRIMARY KEY (scan_id, ino))`
  — `owner_path` in **stored** (translated) path space; `dev` from the owning entry's `st_dev`. Pruned with `nodes` in WI-7.
- **Owner identity validation** (used wherever the rules below say "valid"): an existing registry row's owner is valid iff `os.lstat(owner_path)` succeeds and its `(st_dev, st_ino)` equal the row's `(dev, ino)`. Never use bare `os.path.exists` — a file recreated at the owner's path is a *different* file (new inode) and must be treated as a stale owner, or the surviving link's bytes end up counted nowhere. (On APFS, file IDs are 64-bit monotonic and not reused, so literal inode recycling cannot produce a false-positive candidate match on the target volume; the `dev`+`ino` check nevertheless makes the registry safe against path recreation and against any future non-APFS or multi-volume use.)
- New function `resolve_hardlink_ownership(scan_id, candidates, translate, *, full_scan: bool)` returning `(attributions, transfer_adjustments, pending_registry_changes)` — the third element is the list of registry inserts/updates/deletes for the caller to commit (see the row-persistence note below):
  - Translate each candidate's `walked_path` to stored space (WI-2). Group candidates by `ino`.
  - **Full-scan mode:** prior table contents for this scan are empty/replaced. Owner = lexicographically smallest stored path in the group (deterministic across runs and thread schedules). Persist one row per ino (batch `executemany`). `transfer_adjustments` is always empty (everything is being recomputed).
  - **Subtree mode:** bulk-`SELECT` existing rows for the candidate inos (chunked `IN` queries, active scan id). Per ino group:
    - existing owner_path **is one of this walk's candidate stored paths** → still owned inside the walked subtree; keep that owner, count it.
    - existing owner_path is not among the candidates and is **valid** (identity check above) → owned elsewhere; do **not** count. (A candidate with `st_nlink == 1` cannot reach this branch with a truthful registry — a valid external owner implies `st_nlink ≥ 2` — but code it defensively; the lstat is authoritative.)
    - existing owner_path is **stale** (lstat fails, or `(dev, ino)` mismatch — deleted or recreated externally) → **transfer**: reassign owner = min(candidate stored paths), count it, `UPDATE` the row, and — **only if the old owner_path lies outside the walked subtree's stored-prefix set (WI-6)** — emit `(os.path.dirname(old_owner_path), -allocated_bytes)` into `transfer_adjustments`. If the old owner was inside the walked subtree, the fresh walk already computed that directory's totals without the vanished link; an adjustment there would undercount.
    - no existing row **and the candidate group has any member with `st_nlink > 1`** (new hard-linked file) → owner = min(candidate stored paths), count, `INSERT`.
    - no existing row and **all** candidates report `st_nlink == 1` → treat as ordinary files: attribute each to its own parent, create **no** registry row. This happens when the walker's `registered_inodes` snapshot was stale — e.g. a concurrent refresh performed the nlink-collapse cleanup between our snapshot load and our resolution — and without the guard we would mint registry rows for files that are not hard links.
    - **Registry cleanup:** after resolving a group, if every candidate in it reported `st_nlink == 1` (the file is no longer hard-linked anywhere), emit a `DELETE` for the registry row instead of keeping/updating it — the survivor's bytes were attributed via the transfer above, and on subsequent walks the file is correctly handled as an ordinary file.
  - `attributions` is `(walked_parent, allocated_bytes)` pairs for the caller to add into `dir_local` **before** `rollup_subtree_totals` runs. Row persistence: in full-scan mode the resolver may write its rows directly (the `scan_id` is fresh and private until `finalize_scan_run` flips the active flag — full-scan publishing is inherently atomic); in subtree mode the resolver is invoked *inside* `walk_subtree_and_store`'s locked decision phase (WI-6 step 3) — its registry reads and lstat validations run against current committed state, never a pre-lock snapshot — and it returns pending row changes (inserts, updates, and the nlink-collapse deletes) that the step-4 transaction persists, so ownership updates, node updates, and both ancestor-delta chains commit atomically. `transfer_adjustments` is consumed by `walk_subtree_and_store` (WI-6): each entry is applied as an `allocated_bytes` delta up the former owner's ancestor chain, so the bytes stop being counted at the old location the moment they start being counted at the new one. Combined with the subtree's own delta propagation, the volume-root total is invariant under a transfer (+bytes up the rescanned chain, −bytes up the old owner's chain; common ancestors net to zero because both chains are applied independently) — which is correct, since the file still exists exactly once.
- Consequences to document in code comments and tests: volume-level totals are attribution-independent and still match `du` exactly; *subtree-level* distribution may differ from a standalone `du` of that subtree when links span subtrees (both the old architecture and `du` itself have this ambiguity — ours is now at least deterministic and internally consistent, which is what makes WI-6 delta propagation valid).

### WI-2: Path-space translation, root keys, and alias bridge rows

The full walk sees Data-volume paths (`/System/Volumes/Data/...`), but the on-demand endpoints canonicalize first, so **subtree walks are typically rooted at canonical paths** (`/Users/<user>/...`, `/Applications/...`) — and a subtree walk rooted in data space (e.g. `/System/Volumes/Data/Users`) can *cross* into canonical territory at `<user>`. Translation must therefore be per-row and space-agnostic.

- `build_walk_translation() -> List[Tuple[str, str, str]]` of `(walked_prefix, stored_prefix, root_key)`, matched **longest prefix first**, built once and cached:
  1. `(str(DATA_VOLUME / 'Users' / HOME_DIR.name), str(HOME_DIR.resolve()), 'home_root')`
  2. `(str(HOME_DIR.resolve()), str(HOME_DIR.resolve()), 'home_root')` — **canonical identity mapping** (review finding 1: without this, canonical-rooted subtree walks fall through to `data_root` with wrong keys/depths)
  3. `(str(DATA_VOLUME / 'Applications'), str(APPLICATIONS_DIR.resolve()), 'applications_root')`
  4. `(str(APPLICATIONS_DIR.resolve()), str(APPLICATIONS_DIR.resolve()), 'applications_root')` — canonical identity mapping
  5. default: path unchanged, `'data_root'`
  Verify mappings 1 and 3 with `os.path.samefile` before enabling them (mirror `canonicalize_breakdown_path`); if `samefile` fails, drop that mapping (its identity twin still stands). Prefix matching must be segment-aware (`path == prefix or path.startswith(prefix + '/')`), not raw `startswith`.
- Rows under the home prefix (including `~/Library/**`) get `root_key='home_root'` — matches today's behavior where Library rows carry `home_root` and `library_root` is only a fetch path, not a row key.
- **`parent_path = os.path.dirname(stored_path)` uniformly. No boundary exceptions.** (Rev 1 had a "boundary parent" rule — home row keeping a data-space parent — which both risked duplicate listings and broke down for canonical-rooted subtree walks. Discarded.)
- **Alias bridge rows** make data-space drill-down cross into canonical space, replacing that rule. After persisting a full scan (and after any subtree persist rooted at or above a boundary), call the existing `mark_alias_path_cached(scan_id, source_path, target_path, 'data_root')` for each boundary:
  - `source=DATA_VOLUME / 'Users' / HOME_DIR.name`, `target=HOME_DIR` — so listing `/System/Volumes/Data/Users` shows the user's home (alias row carries the canonical total, `children_indexed=1`; a click canonicalizes to `/Users/<user>` and lists canonical children).
  - `source=DATA_VOLUME / 'Applications'`, `target=APPLICATIONS_DIR` — so the data-root breakdown shows Applications (this is what the current prefetch's alias marking does; preserve it).
  Note `mark_alias_path_cached` sets the alias row's `parent_path` from the source path's dirname, which is exactly the data-space parent needed for these listings. Canonical rows (`/Users/<user>` with parent `/Users`, `/Applications` with parent `/`) are never listed from data-space parents, so no duplicates appear.
- `depth` per row: compute with the existing `path_depth(root, path)` against the `ROOT_PATHS` entry for the row's `root_key` (data rows relative to `DATA_VOLUME`, home rows relative to `HOME_DIR`, etc.), matching current stored values. With the identity mappings this is correct for both walk entry spaces.

### WI-3: Persistence of the walk

- `persist_walk_result(scan_id: int, result: WalkResult, subtree: Dict[str, int], translation) -> None`:
  - One node row per directory in `subtree`: translated path, `parent_path = dirname(stored path)`, `name`, `root_key`, `depth`, `allocated_bytes = subtree[walked path]`, `children_indexed=1`, shared `updated_at`.
  - Insert in batches (~20k rows per `executemany`/commit chunk) under `DB_WRITE_LOCK`, reusing the upsert SQL shape from `upsert_node_rows`. ~400k rows expected; target < 10s. Do not build one giant list-of-tuples beyond the chunk size.
  - Large files: translate paths, dedupe by stored path (hard-linked files appear once), then insert. **Persistence semantics differ by mode and must never use per-root_key replacement** (a subtree walk replacing all of `home_root` would erase large-file records for the rest of the home tree): a *full scan* writes into a brand-new `scan_id` whose namespace no other writer targets (WI-6 removes the running-scan routing that used to allow this), so no delete-first step is needed; a *subtree walk* deletes only the rows within the walked prefix set and inserts the fresh records inside the same transaction (WI-6). Keep `fetch_large_files_from_db` output shape identical.
  - Full-scan node and large-file inserts nevertheless use the `ON CONFLICT ... DO UPDATE` upsert SQL shape rather than plain `INSERT` — defense in depth so a routing regression surfaces as overwritten rows, not a `UNIQUE`-constraint crash mid-scan. Stale-row cleanup remains exclusively a subtree-walk concern (WI-6).
  - Add module constant `LARGE_FILE_EXCLUDED_PREFIXES = [str(DATA_VOLUME / 'private/var/vm')]` (swap/sleepimage — not user-actionable) and filter large files against it. Update the hardcoded description string `"Large user file found in targeted home-directory scan."` (it appears in **two places** — `fetch_large_files_from_db` and `scan_large_files_in_root`'s successor; define it once) to reflect a volume-wide scan.
  - Hard-link ownership rows are persisted inside WI-1b's resolver (full-scan mode replaces the scan's table contents), sequenced before `rollup_subtree_totals`.
  - After node persistence, write the alias bridge rows (WI-2).

### WI-4: Rewire `collect_scan_report`

New phase list (weights tuneable; frontend displays names verbatim and only special-cases `initializing`):
`[("Metadata probes", 0.06), ("Volume walk", 0.70), ("Index persistence", 0.14), ("Report assembly", 0.10)]`

- Keep the metadata probe block, `metadata_ready` event, and `snapshot_found` events unchanged.
- Replace the `root_scan_tasks` fan-out, the data prefetch block (`select_data_prefetch_plan` and its `DATA_VOLUME_PREFETCH_CHILD_COUNT` config), and the `scan_large_files` phase with: `walk_tree(DATA_VOLUME.resolve(), ...)` → `resolve_hardlink_ownership(full_scan=True)` → `rollup_subtree_totals` → `persist_walk_result` → alias bridge rows.
- Walk-phase progress: no known denominator, so use the previous scan's dir count as the estimate — `SELECT COUNT(*) FROM nodes WHERE scan_id = <active id>` at scan start, default 400,000 if none — and report `min(0.95, dirs_completed / estimate)` within the phase, with a detail string like `"312,000 directories scanned"`.
- Watchlist: from the index (WI-5), after persistence.
- All four `breakdown_ready` events, `finding_added`, `large_file_found`, and the final report assembly keep their current payload shapes and ordering; breakdowns come from `fetch_breakdown_from_db` on the four `ROOT_PATHS` (as `build_breakdowns_from_db` already does). `visible_data_bytes` = the walk's Data-volume root total.
- `checks[]` keeps its shape (`label`/`command`/`ok`/`duration_ms`/`summary`); update entries to describe the walk (e.g. command `"parallel scandir walk of /System/Volumes/Data"`, summary with dir/file/error counts). Keep one check per former label so the UI's checks tab stays meaningful; the Library check's `ok` can key off the Library node being present in the index.

### WI-5: Watchlist from the index

Rework `scan_watchlist_entry(spec)`:
- File paths: `stat_file_sizes` as today.
- Directory paths: look up the path in the fresh scan's nodes (watchlist specs expand to canonical `~` paths, which is the stored space for home rows — no translation needed at lookup). Missing from index + `path.exists()` false → `exists=False` as today. Missing but exists (e.g. excluded subtree): fall back to a bounded `walk_tree` on that path.
- Output dict shape and `scan_watchlist()` sorting stay identical. No `du_bytes` calls remain.
- Note: `rebuild_and_publish_report` (post-action refresh) also calls `scan_watchlist()` — it must keep working *outside* a full scan; there the DB lookup path (against the active scan) is the one exercised.

### WI-6: On-demand breakdown, rescan, and action-refresh paths

All subtree entry points receive **canonical-space** roots (they call `canonicalize_breakdown_path` first) except drill-downs into non-firmlinked Data-volume paths (e.g. `/System/Volumes/Data/private/...`), which stay in data space. The WI-2 translation table handles both; nothing at these call sites needs to know which space it is in.

**The single subtree-refresh primitive.** All subtree operations go through one function so delete/insert/ownership/propagation semantics cannot diverge between call sites:

`walk_subtree_and_store(scan_id, path) -> breakdown` executes these steps in order:
0. **Acquire `SUBTREE_REFRESH_LOCK`** — a new module-level `threading.Lock` held from before the walk until after step 4's commit. Serialization must begin *before* the filesystem walk, not at the decision phase: walk data is a point-in-time filesystem snapshot, and if refresh A walks, the filesystem changes, refresh B walks-and-commits the newer state, and A then commits, A's delete+insert and delta chains would regress the index to the older snapshot — internally consistent, factually wrong. Exact-path dedup cannot prevent this (ancestor and descendant walks overlap too), so the lock is global to all subtree operations. The full-scan path never takes this lock (it writes a private `scan_id`, per Rev 5), and the ephemeral no-scan walk doesn't either (no writes). *Rejected alternative, documented for the future:* a generation counter + overlapping-prefix detection with walk retry would keep walks concurrent at the cost of retry/livelock machinery — revisit only if serialized drill-down latency ever becomes a real problem; with the volume fully indexed, on-demand walks are rare.
1. **Stored-prefix set:** compute `prefixes = {translate(path)} ∪ {stored_prefix of every WI-2 translation entry whose walked_prefix is at or under path}`. This is the set of path namespaces the walk's rows land in — a canonical-rooted walk yields one prefix; a data-space walk rooted at e.g. `/System/Volumes/Data/Users` yields two (itself, plus canonical home), because the walk crosses the boundary.
2. **Walk:** load the active scan's registered-inode set (an advisory snapshot; see the nlink-1 guard in WI-1b), then `walk_tree(path, registered_inodes=...)`. Bulk filesystem I/O ends here.
3. **Decision phase (inside `DB_WRITE_LOCK` — held from here through step 4's commit, nested inside `SUBTREE_REFRESH_LOCK`; lock ordering is always SUBTREE → DB_WRITE, never the reverse):**
   - **Revalidate the scan id:** confirm `scan_id` still equals `fetch_active_scan_id()`. `finalize_scan_run` and its pruning also run under `DB_WRITE_LOCK`, so this check cannot race; if a full scan finalized while we walked, abandon the write entirely and serve the response from the new active scan's index (which the full walk just populated volume-wide) — otherwise we would insert rows into a pruned, dead scan_id.
   - **Read the old stored total** for `translate(path)` (0 if absent) — read under the lock, because a concurrent refresh of an overlapping subtree may have changed it since the walk started; a stale baseline would double- or under-apply deltas to shared ancestors.
   - `resolve_hardlink_ownership(full_scan=False)` (WI-1b) — registry reads, owner lstat validation, and transfer decisions all happen *here*, against current committed registry state; two concurrent refreshes therefore cannot both act on the same stale ownership row (the loser of the lock re-reads the winner's committed rows). The lstats are bounded by the number of registry-hit inode groups — small — so holding the lock is acceptable. Apply `attributions` to `dir_local` → `rollup_subtree_totals` (pure CPU, subtree-sized).
   - **Chain resolution (read-only):** compute, as plain data, every `UPDATE` the commit will apply: (a) the subtree's own delta chain — `delta = new_total − old_total`, following `parent_path` links from the walk root's parent up to `ROOT_PATHS[root_key]`, then the **cross-space step**: if the chain ends at `HOME_DIR` or `APPLICATIONS_DIR`, the same delta continues onto the alias bridge row and up the *data-space* dirname chain (`/System/Volumes/Data/Users` → `/System/Volumes/Data`), keeping treemap top-level numbers consistent (an improvement over today, where data-root figures go stale after actions); (b) one negative chain per `transfer_adjustment` `(old_owner_dir, -bytes)`, starting at the old owner's directory row itself — this is what prevents double-counting when ownership migrates away from an externally-deleted link. Extract chain computation as a shared helper (e.g. `resolve_ancestor_delta_updates(connection, scan_id, start_path, delta) -> List[Tuple[int, str]]`). **If a required ancestor row is missing**, abandon the delta approach for this call: release **both** locks (`DB_WRITE_LOCK`, then `SUBTREE_REFRESH_LOCK` — a plain `threading.Lock` is not reentrant, and re-invoking while holding it would self-deadlock), then `walk_subtree_and_store` that ancestor instead as a fresh, fully-locked invocation whose result this call returns. The fallback does filesystem I/O and must never run inside the locked section. Missing ancestors are rare: full scans index every directory, so they arise only in never-indexed areas.
4. **One write transaction** (single connection, single commit, same `DB_WRITE_LOCK` hold; precomputed writes only, no I/O): delete existing `nodes` **and** `large_files` rows whose path equals or is prefix-contained in any entry of `prefixes` (reuse the `sql_like_prefix` escape helper; this is what removes descendants deleted on disk since the last scan — upsert alone would leave ghost rows in breakdowns); insert the fresh node rows (per-row translation, full depth); insert the walk's large-file records; apply the pending registry row changes (inserts/updates/deletes from WI-1b); apply **all** ancestor-delta `UPDATE`s from step 3 — both the positive chain and every negative chain; re-mark alias bridge rows for any boundary inside `prefixes`; apply the files-only fallback (below). Commit once. Atomicity is the point: a crash rolls back to the previous consistent state, and a WAL-mode reader either sees the old state or the new state — never a transferred ownership without its paired adjustments, and never a half-empty subtree.
5. Return `fetch_breakdown_from_db(scan_id, translate(path))`.

Steps 3–5 always run, for drill-down as well as rescan. Always-propagate is correct in every reachable case: a directory absent from the index is either newly created (ancestors don't yet include its bytes), inside an excluded subtree (ancestors never included it), or there is no scan at all (different, ephemeral code path) — and for stale-but-indexed directories it heals the ancestors instead of leaving them wrong. It is also load-bearing for the transfer-adjustment invariant: adjustments assume the positive side of the move is propagated in the same commit. Delta propagation as a whole is only valid because WI-1b makes stored and re-walked subtree totals use the same hard-link attribution — do not reorder these work items.

- `store_breakdown_for_path(scan_id, path)`: replace the `list_root_breakdown` call with `walk_subtree_and_store(scan_id, path)`.
- Files-only directories: currently `list_root_breakdown` falls back to listing immediate files so leaf dirs don't render empty, and `store_immediate_breakdown` persists them. Preserve this inside step 4 (the file listing itself comes from the step-2 walk data, keeping the transaction I/O-free): when the walked subtree has no child *directories*, persist immediate file items the way `store_immediate_breakdown` does (`fetch_breakdown_from_db` already tags non-dirs with `is_file`).
- **Scan routing (`choose_scan_id_for_path`):** remove the `fetch_running_scan_id()` preference — the function returns only the active *completed* scan (or `None`). The running-scan preference existed so mid-scan drill-downs could seed the incomplete new index; with the full walk indexing the entire volume that value is gone, and keeping it would let subtree persistence write into a running scan's half-built namespace concurrently with full-scan persistence. Mid-scan drill-downs now serve from the previous completed index (staleness is already surfaced by per-section timestamps); the moment the scan finalizes, every path is covered by the fresh volume-wide index. Any drill-down rows written to the *old* scan during the scan are removed by WI-7's prune at finalize — nothing of value is lost.
- **`api_breakdown` no-scan fallback:** the `else` branch that currently calls `list_root_breakdown(validated)` directly (no scan has ever run) is replaced with an ephemeral, non-persisting `walk_tree(validated)` + immediate-children breakdown of the same response shape — no scan_id, no DB writes, no delta propagation.
- `refresh_directory_chain(scan_id, directory)`: today it re-runs a full subtree `du` for the target *and every ancestor* (after this plan, an ancestor chain to the volume root would mean re-walking the volume). It reduces to a thin wrapper around `walk_subtree_and_store` (or is deleted outright, callers invoking the primitive directly — executor's choice after checking callers: `refresh_after_action`, `api_rescan_path`). Note `refresh_after_action`'s explicit `remove_cached_subtree` call for the trashed path likely becomes redundant — step 4's prefix delete on the parent walk removes those rows; verify and delete `remove_cached_subtree` if no callers remain.
- `refresh_large_files_for_paths`: replace the `scan_large_files_in_root` (`find`) call with large-file records from the subtree walk in the same refresh.
- `execute_trash_path` size estimate: replace `du_bytes(path)` with: index lookup for the path if present, else a subtree walk total. Keep the returned dict shape. (Trashing a hard-link owner makes its registry row stale; the WI-1b stale-owner rule self-heals on the next walk that sees another link.)
- After rewiring, **delete** the dead functions: `du_bytes`, `list_root_breakdown`, `scan_directory_index`, `scan_immediate_child_breakdown` (verify no remaining callers first), `scan_large_files`, `scan_large_files_in_root`, `select_data_prefetch_plan`, and the `DATA_VOLUME_PREFETCH_CHILD_COUNT` constant. `run_command` stays (diskutil/tmutil/osascript). Exit check: `rg '"du"|"find"' storage_monitor/storage_monitor` must return no matches.

### WI-7: DB pruning and size recovery

- In `finalize_scan_run` (or a helper it calls after marking the new scan active): `DELETE FROM nodes WHERE scan_id != ?`, `DELETE FROM large_files WHERE scan_id != ?`, and `DELETE FROM hardlink_inodes WHERE scan_id != ?` (the new active id); delete `scan_runs` rows beyond the newest 30 (dated report JSONs also live in `history/` on disk, so nothing is lost).
- After pruning, check `PRAGMA freelist_count` × `PRAGMA page_size`; if > 100 MB, run `VACUUM` — still inside the scan thread and `DB_WRITE_LOCK`, after the report has been published so the UI isn't blocked. This shrinks the existing 1.1 GB DB on the first post-upgrade scan.
- The existing `remove_cached_subtree` LIKE-prefix deletes now operate on much larger row sets; confirm `idx_nodes_parent` still serves the queries used (add an index only if measured to be slow — the PK already covers path equality).

### WI-8: Configuration defaults

- `SCAN_WORKER_COUNT`: default 6 → **8** (benchmarked optimum on this machine; 16 was slower), raise the clamp ceiling from 8 to 16, keep the `STORAGE_MONITOR_SCAN_WORKERS` override. It now sizes both the walker and the remaining parallel probe map.

### WI-9: Tests and validation

**Entry (before any code change):** create the venv per README (`python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`), run `.venv/bin/python -m pytest -q`, and record the baseline result. Also run the fleet drift guard once: `uv run --script tools/check_uv_headers.py`.

**New unit tests** (new file `tests/test_walker.py`, loading the launcher via `tools.testkit.load_launcher` like `test_smoke.py`; build fixture trees under `tmp_path`):
1. **du parity:** construct a tree with nested dirs, files of known sizes, a hard-link pair (`os.link`), a symlink to a directory, and a files-only leaf dir; assert walk + ownership resolution + rollup total equals `du -xsk <tmp>` output bytes exactly, and that the hard-linked file is counted once.
2. **Symlink non-follow:** the symlinked directory's contents are not double-counted.
3. **Rollup:** synthetic `dir_local` → expected subtree totals, including a parent whose own local bytes are zero.
4. **Large-file semantics:** a sparse file (`os.ftruncate` to >1 GiB apparent, near-zero blocks) is captured by apparent size — pins the `find`-parity semantics.
5. **Translation (Rev-2 finding regression):** with patched `DATA_VOLUME`/`HOME_DIR`/`APPLICATIONS_DIR` pointing into a fixture tree, (a) data-space walked paths map to canonical stored paths with correct root keys and depths; (b) **canonical-space walked paths (as `store_breakdown_for_path`/`api_rescan_path` produce) map identically via the identity entries** — never to `data_root`; (c) prefix matching is segment-aware (`/Users/example` does not match the home prefix).
6. **Alias bridge rows:** after a full persist, listing the data-space parent (`fetch_breakdown_from_db` on the fixture's "Users" dir) returns the alias row exactly once (no duplicate canonical sibling), with the canonical total and `children_indexed` set.
7. **Deterministic hard-link ownership (Rev-2 finding regression):**
   (a) full-scan mode assigns the inode to the lexicographically-smallest stored path regardless of candidate insertion order;
   (b) a subtree walk over the *non-owner* link's directory does not count the file, and delta computation yields delta 0 for an unchanged tree (ancestor totals unchanged);
   (c) a subtree walk over the *owner's* directory counts it exactly once;
   (d) stale-owner transfer: delete the owner link on disk, re-walk the other link's subtree via `walk_subtree_and_store`; ownership moves, the bytes are counted in the new subtree, **the former owner's directory row and its ancestors are decremented by the same amount, and the tree-root total is unchanged** (the file still exists once) — the Rev-3 finding-3 regression;
   (e) old owner *inside* the walked subtree: no transfer adjustment is emitted (the fresh walk already excludes the vanished link), and totals remain exact;
   (f) **nlink collapse (Rev-4 finding-1 regression):** two links, registered owner deleted so the survivor's `st_nlink` is 1; re-walk the survivor's subtree with `registered_inodes` supplied; the survivor is still emitted as a candidate, the transfer + negative adjustment fire, the tree-root total is unchanged, and the registry row is deleted (no longer multi-link);
   (g) **recreated owner (Rev-4 finding-2 regression):** delete the registered owner and create a *new* file at the same path; re-walk the other link's subtree; the `(dev, ino)` lstat check classifies the owner as stale (bare-existence would not), the transfer fires, and the surviving link's bytes are counted exactly once;
   (h) **commit atomicity (Rev-4 finding-3 regression):** force an exception inside the step-4 transaction (e.g. monkeypatch one of the write helpers to raise after the deletes); assert the DB still holds the complete pre-walk state — old subtree rows present, ancestor totals unchanged, ownership rows unchanged — i.e. the transaction rolled back as a unit and no partial transfer is observable;
   (i) **locked-phase revalidation (Rev-5 finding-1 regression):** simulate two sequential refreshes where the second's walk candidates were gathered *before* the first committed an ownership transfer for the same inode (drive the internals directly with pre-captured candidate data); assert the second's resolution — run in its locked phase — sees the first's committed owner and emits no duplicate transfer or second negative adjustment, and the tree-root total is unchanged;
   (j) **stale registered-inode snapshot guard:** a candidate with `st_nlink == 1` and no registry row (row deleted between snapshot and resolution) is attributed as an ordinary file and no registry row is created.
8. **Persistence round-trip:** persist a small `WalkResult` into a tmp runtime home's DB; `fetch_breakdown_from_db` returns size-sorted items with `children_indexed` set; files-only fallback stores `is_file` items.
9. **Subtree delete-then-insert (Rev-3 finding-1 regression):** persist a fixture tree; delete a nested directory and a large file on disk; `walk_subtree_and_store` the subtree; assert the deleted directory's node rows and the deleted file's `large_files` row are gone, the breakdown listing contains no ghost entries, and ancestor totals reflect the removal. Include a two-space variant: a walk rooted at the fixture's data-space "Users" dir also purges stale rows stored under the canonical home prefix (prefix-set coverage).
10. **Subtree large-file isolation (Rev-3 finding-2 regression):** with large-file rows persisted for two sibling home subdirectories, `walk_subtree_and_store` on one sibling; assert the other sibling's large-file rows survive (per-root_key replacement would have erased them).
11. **Pruning:** create two scan runs with node/hardlink rows; finalize the second; assert the first run's `nodes`, `large_files`, and `hardlink_inodes` rows are gone and `scan_runs` capping works.
12. **Regression guard (per repo testing discipline):** read the launcher source text and assert the strings `'"du"'` and `'"find"'` (as `run_command` argument literals) do not appear — if a future change reintroduces a `du`/`find` scan path, this fails.
13. **Watchlist without subprocess:** monkeypatch `run_command` to raise if invoked; `scan_watchlist_entry` for a directory spec resolves from a provided index.
14. **Scan routing (Rev-5 finding-2 regression):** with both a `running` scan run and an active completed run in `scan_runs`, `choose_scan_id_for_path` returns the active completed id (never the running one); and `walk_subtree_and_store`'s locked revalidation abandons its write when the chosen scan is no longer active (simulate by finalizing a newer scan between walk and decision phase), leaving zero rows attributed to the stale scan_id.
15. **Stale-snapshot serialization (Rev-6 regression):** (a) mechanism — monkeypatch `walk_tree` to assert `SUBTREE_REFRESH_LOCK` is already held (non-blocking `acquire` must fail) whenever it is invoked from `walk_subtree_and_store`; (b) behavior — thread 1 starts a refresh whose walk is artificially slowed (monkeypatched sleep inside the walk), mutate the fixture tree, thread 2 refreshes an overlapping path; assert thread 2's walk did not begin until thread 1's commit completed and the final DB state reflects the post-mutation filesystem — the older snapshot never overwrites the newer one.

**Exit (all mandatory, report every failure):**
1. Full suite: `.venv/bin/python -m pytest -q` — all green.
2. `uv run --script tools/check_uv_headers.py` — launcher header unchanged, still must pass.
3. `./storage_monitor --help` exits clean without creating runtime state.
4. Smoke server: `UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473` starts and serves `/api/state`.
5. **Real-scan acceptance** (against the real runtime home): trigger `POST /api/scan`, wait for `scan_complete`; verify (a) wall time ≤ 45s, (b) `summary.visible_data_bytes` within 0.5% of a fresh `du -xsk /System/Volumes/Data`, and `applications_total_bytes` within 0.5% of `du -xsk /Applications` (run `du` immediately after the scan; small drift is live churn), (c) `GET /api/breakdown?path=<some deep, previously-unindexed directory>` returns from the DB without triggering an on-demand walk, (d) the large-files section is populated and excludes `/private/var/vm`, (e) after deleting a file inside a subdirectory in Finder, `POST /api/rescan-path` on that subdirectory removes the entry from its listing (no ghost rows) and updates its ancestor totals **and** the data-root treemap totals (cross-space propagation), (f) DB file size after the scan < 300 MB (pruning + vacuum worked, down from 1.1 GB).
6. UI verification: load the dashboard in a browser (Playwright) and confirm treemap renders, all four breakdown accordions populate, drill-down works into both a home path and a Data-volume path (`/System/Volumes/Data` → Users → home crosses the alias bridge), scan progress text updates during a scan, and drill-down issued *while* a scan is running still returns data (served from the previous completed index, per the WI-6 routing change).

### WI-10: Documentation

- README: update "Progressive scan streaming" / capabilities wording for the single-pass walk, note the ~35s scan, the volume-wide drill-down index and large-file inventory, and DB self-pruning under Runtime State.
- If `docs/` gains this plan as its first file, no other doc chains exist to update (verified: project has no DESIGN.md).

## 5. Suggested implementation order

WI-1 → WI-1b → WI-2 → WI-3 (walker + ownership + translation + persistence, with tests 1–8 passing) → WI-4 (scan rewiring) → WI-5 (watchlist) → WI-6 (subtree primitive + endpoints, tests 7d–7j/9/10/14/15, then delete dead code + regression guard test 12) → WI-7 (pruning, test 11) → WI-8 → WI-9 exit validation → WI-10. Work on a feature branch; commit per work item with imperative subjects.

## 6. Hard constraints

- Report JSON schema, SSE event types/payload shapes (`scan_status`, `metadata_ready`, `snapshot_found`, `breakdown_ready`, `finding_added`, `large_file_found`, `action_result`, `report`, `scan_complete`), and action-token flows are frozen.
- Single-file launcher architecture and the PEP 723 header (fastapi, uvicorn only) are frozen; walker must be stdlib.
- Quote all paths in shell commands (this repo has paths with spaces).
- `Path(...).resolve()` per-row calls must not reappear in the persistence hot path; resolve roots once and derive children by string operations.
- Byte-total parity with `du` within 0.5% on live trees (exact on quiescent fixture trees) is the correctness bar — the probe achieved −0.00%; large deviations mean a semantics bug (most likely hard links, symlinks, or `st_dev`), not acceptable drift.
- Hard-link attribution must be deterministic (lexicographic owner rule) and identical between full-scan and subtree-walk code paths; delta propagation is forbidden unless both totals were computed against the same ownership registry, and every ownership transfer must be paired with its negative adjustment on the former owner's chain (WI-1b/WI-6).
- Subtree persistence is always transactional delete-then-insert over the walk's stored-prefix set — never upsert-only (ghost rows), never per-root_key replacement (collateral deletion). All subtree call sites must route through `walk_subtree_and_store`.
- Subtree operations are serialized end-to-end by `SUBTREE_REFRESH_LOCK`, acquired **before** the filesystem walk and released after commit — a walk snapshot must never be committed after a newer overlapping commit. Lock ordering is always `SUBTREE_REFRESH_LOCK` → `DB_WRITE_LOCK`; no code path may acquire them in reverse, and the missing-ancestor fallback releases both before re-invoking.
- The subtree commit phase is exactly one transaction containing node rows, large-file rows, ownership changes, and both ancestor-delta chains, with all bulk filesystem I/O completed beforehand and `DB_WRITE_LOCK` held across the entire decision phase (scan-id revalidation, old-total read, ownership resolution, chain resolution) + commit. Owner validity is always the `(dev, ino)` lstat identity check, never path existence; registered inodes are candidate-eligible regardless of current `st_nlink`.
- On-demand subtree persistence targets only the active *completed* scan; a running full scan's `scan_id` is private to the scan thread until `finalize_scan_run`. `choose_scan_id_for_path` must not regain a running-scan preference.
