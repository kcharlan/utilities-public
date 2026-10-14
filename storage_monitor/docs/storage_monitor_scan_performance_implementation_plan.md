# Storage Monitor Scan Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut a full Storage Monitor scan from about 42 s to about 17 s (measured on a 320k-directory scope) without changing the dashboard, server, API, or database schema.

**Architecture:** Phase A removes Python-side waste: a pathlib hot spot, provider probes that run serially after the walk, and an oversubscribed walker. Phase B replaces only the directory walk with a small native C helper, `storage_monitor_walk`, which uses macOS `getattrlistbulk`. The helper streams NUL-delimited records to the unchanged Python pipeline, which keeps rollup, hardlink ownership, path translation, SQLite, FastAPI and the React UI. The helper is never built at runtime. A Node deployment tool checks toolchain prerequisites, rebuilds the helper only when its tracked source changed or the installed copy drifted, installs launcher and helper together with a receipt, and joins the fleet's read-only drift audit.

**Tech Stack:** Python 3.12+ uv launcher (FastAPI/uvicorn, sqlite3); C17 with Apple clang, pthreads and `getattrlistbulk(2)`; GNU-compatible `make`; Node.js (`node:test`) for the deployment tool; zsh for the fleet audit.

**Spec:** No separate design document exists. The [Background](#background-measured-evidence) section below records the measurements and decisions this plan argues from. The owner approved Phase A and Phase B, a deployment-built native helper, and no dynamic building, on 2026-10-14.

## Global Constraints

- Public repository: no real paths, usernames, scan outputs, timings tied to private paths, or volume contents in source, tests, fixtures, docs or commit messages. Real-disk measurements go only to a private directory outside the checkout (see Task A0).
- The front end (`HTML_TEMPLATE`), FastAPI routes, response shapes and SQLite schema do not change.
- `walk_tree(root, *, workers, excluded_paths, registered_inodes, progress_callback) -> WalkResult` keeps its exact signature and result semantics. Every existing caller stays unchanged.
- The native helper is **never compiled by the running application**. It is built only by an explicit `make` (development and tests) or by `tools/deploy_storage_monitor.mjs` (deployment).
- There is no Python walker fallback after Phase B. One walker implementation exists.
- Native build prerequisites: macOS, Apple clang from the Xcode Command Line Tools (`xcode-select --install`), and `make`. Deployment additionally needs Node.js. The helper has no third-party libraries.
- Python runs only inside `storage_monitor/.venv` (`storage_monitor/.venv/bin/python`). Run uv launchers as `UV_PYTHON_DOWNLOADS=never ./storage_monitor …`.
- Thresholds stay single-sourced in Python: `LARGE_FILE_THRESHOLD_BYTES` and the 2,000-directory progress interval are passed to the helper as arguments, never duplicated in C.
- `STORAGE_MONITOR_SCAN_WORKERS` remains the only worker knob and stays clamped to 1–16.
- Sequencing: tasks run in order A0 → B6. No external work blocks any of them (see [Starting state](#starting-state)).
- Branching: create `storage-monitor-native-walker` from `main` in the existing checkout (not a worktree). Move this plan onto that branch as the first commit (it is currently untracked on `main`). Commit per task with an imperative subject and a body. Do not push or open a PR unless the owner asks.
- Deployment state outside this project (the Colophon receipt and `tax2` drift; see Starting state) is not part of this work. Do not redeploy, edit or "fix" it to make an audit pass. Report it by name wherever an audit result is reported, and stop and ask if it changes.

## Starting state

This state was verified on 2026-10-14 on `main` at `cc21e50` ("Make native Colophon the sole implementation (#40)"). The Colophon cutover is merged, and every file and line reference in this plan was checked against that commit. The cutover did not touch `storage_monitor/`.

| Item | State at `cc21e50` |
|---|---|
| Deployed `~/Library/Scripts/storage_monitor` | Direct copy; byte-identical to `storage_monitor/storage_monitor`. No `storage_monitor_walk` and no `.storage_monitor.json` exist. B4 migrates from this state. |
| `zsh tools/check_local_deployments.zsh` | Exit 1. `OK: storage_monitor`. **Pre-existing failures:** `FAIL: colophon native deployment unverified (source, binary or receipt drift)` and `FAIL: tax2 deployment drift (… byte differences: 2 …)`. |
| `node tools/deploy_colophon.mjs --audit` | Exit 1: `Colophon native deployment failed: Native build source drift`. The installed receipt predates the `colophon-native/` → `colophon/` move; `docs/local_deployment_sync.md` documents that this persists until a separately authorized Colophon redeploy. |
| Colophon `sourceInventory(repo).sourceHash` | `6137ad7c21b312398bc4aeee2030287c77a3a3419d720c15e0149de24beb7462` (B3's no-change check) |
| `tools/deploy_colophon.mjs` | Defines `sha`, `exists`, `atomicFile` and `sourceInventory` locally; `deployment_files.mjs` exports only `regular`, `inspectAncestors` and `externalDirectory`. |
| `tools/tests/deploy_colophon.test.mjs` | Its `preCutoverInstaller` rewrites `deploy_colophon.mjs` source text with `replaceAll` and copies `deployment_files.mjs` next to it unmodified. This constrains B3. |

If any of this differs when execution starts (for example, the owner has redeployed Colophon), re-record the row and use the new value as the baseline. The rule is "no change caused by this work," not "these exact failures."

## Review Focus

These are inputs no happy-path test touches but a real Mac will. Each one has a pinning test in the owning task.

1. **Filenames containing newline, tab, or bytes that need `surrogateescape`.** Record framing must not split or merge records, and paths must round-trip exactly as `os.scandir` would have produced them. Pinned in B1 (`test_names_with_control_characters_round_trip`).
2. **A mounted volume inside the walked tree.** `getattrlistbulk` may report the covered directory's device rather than the mounted one. The mount must be skipped exactly as the Python walker skipped it (`st_dev != root_dev`). Pinned in B1 (`test_mounted_volume_is_skipped`, using an `hdiutil` disk image).
3. **A directory with more entries than one `getattrlistbulk` buffer holds.** Every entry must be counted once. Pinned in B1 (`test_directory_larger_than_one_bulk_buffer`).
4. **A missing, stale or crashing helper.** Startup must fail with an actionable message instead of starting a scan that fails 0.1 s later. A crash mid-walk must mark the scan failed and leave the previous index active. Pinned in B2 (`test_startup_rejects_missing_or_mismatched_walker`, `test_truncated_stream_raises_and_persists_nothing`).
5. **Deploying when only one side changed** (launcher only, native source only, or neither), or when the toolchain is missing. The installer must rebuild only when needed, refuse a launcher/helper protocol mismatch before replacing anything, and leave the prior deployment intact on any failure. Pinned in B4 (`launcher-only change does not rebuild`, `native change rebuilds`, `protocol mismatch is refused`, `missing toolchain fails before backup`).

---

## Background: measured evidence

The measurements were taken on 2026-10-14 on an Apple M4 Max with warm caches. The measuring process lacked Full Disk Access, so it saw about 320k directories and 2.6M files. The app itself sees about 517k directories and 3.1M files: in its own history, a typical walk takes 26–34 s and a full scan 36–48 s. Prototype sources were throwaway and are not in the repository; the decisive excerpts are reproduced in the tasks below.

| Phase (current code, 8 workers) | Time |
|---|---|
| `walk_tree` | 27.8–28.1 s |
| `persist_full_walk` | 8.8–8.9 s, of which **7.5 s is `path_depth()`** (pathlib `relative_to`); `upsert_node_rows` is 1.7–1.8 s |
| `probe_providers` (`brew cleanup -n` and others), serial after the walk | 3.5–3.9 s |
| `finalize_scan_run` | 1.7 s |
| **Total** | **40.7–43.1 s** |

| Walker | Wall | User CPU | System CPU |
|---|---|---|---|
| Python, 1 / 4 / 8 / 16 workers | 65.9 / 24.2 / 28.1 / 31.8 s | 5.9–14.7 s | 27.6 / 40.2 / 76.8 / 95.2 s |
| Python, directory-fd-relative stat, 4 / 8 workers | 24.1 / 33.9 s | | |
| C, `readdir` + `fstatat`, 4 / 8 / 16 workers | 17.7 / 13.6 / 15.6 s | | |
| C, `getattrlistbulk`, 1 / 4 / 6 / 8 / 10 / 12 / 16 workers | 41.2 / 14.0 / 11.0 / 9.6–12.2 / 11.2 / 12.9 / 13.7 s | ≤0.5 s | |

| End-to-end scan | Total |
|---|---|
| Current | 40.7–43.1 s |
| Phase A without probe overlap (4 workers, string depth) | 29.9–32.4 s |
| Phase B (native walker, 8 workers, string depth) | 16.6–18.4 s |

Conclusions this plan relies on:

- The walk is bound by kernel time, not Python. Per-file `lstat` path lookups contend in the kernel, which is why `du` (also one `lstat` per file) is no faster. `getattrlistbulk` returns attributes for many entries per system call. Its sweet spot is 6–10 workers.
- `ATTR_FILE_ALLOCSIZE == st_blocks * 512`, `ATTR_FILE_DATALENGTH == st_size` and `ATTR_FILE_LINKCOUNT == st_nlink` for all 2,599,508 non-directory entries checked (0 mismatches). `ATTR_FILE_DATAALLOCSIZE` differed on 505 entries, so do not use it.
- Python-side ingest of the helper's output (parse 0.13 s, rollup 0.19 s, translate 0.12 s) is negligible. Writing SQLite from C would save at most 2–3 s but would duplicate the schema, hardlink ownership and path translation that the refresh and cleanup code paths also use. This plan keeps the boundary at the walk.
- The string-based depth computes the same values as pathlib on all 332,921 rows (0 mismatches) in 0.08 s instead of 7.47 s.
- Indexes built by the Python and native walks were identical in large files (9) and hardlink registry rows (2,543). Total differences were confined to directories that changed between runs.

Out of scope, recorded so nobody re-derives them: FSEvents-based incremental rescans (needs its own spike, because replaying long history gaps was slow); replacing `finalize_scan_run`'s 1.7 s `DELETE` with a table swap; offline vendoring of the UI's CDN assets.

## File structure

| Path | Status | Responsibility |
|---|---|---|
| `storage_monitor/storage_monitor` | Modify | Launcher. Phase A: depth, probe overlap, worker default. Phase B: `walk_tree` delegates to the helper, plus walker discovery and the startup check. The Python walker and the dead legacy pipeline are removed. |
| `storage_monitor/tests/perf/measure_scan.py` | Create (A0) | Real-disk phase timer. Writes private output outside the checkout. |
| `storage_monitor/tests/parity/compare_walkers.py` | Create (B2) | Real-disk parity check: the current walker vs the walker at a baseline Git ref. |
| `storage_monitor/tests/test_scan_pipeline.py` | Create (A2/A3) | Depth parity and provider-overlap tests. |
| `storage_monitor/tests/conftest.py` | Create (B1) | Session fixture that builds the helper once with `make` into a temporary directory and exports `STORAGE_MONITOR_WALKER`. |
| `storage_monitor/tests/test_native_walker.py` | Create (B1) | Tests of the helper's command-line and record protocol, run against the binary directly. |
| `storage_monitor/tests/test_walker.py` | Modify (B2) | Existing accounting tests, now exercising the helper through `walk_tree`, plus integration failure cases. |
| `storage_monitor/native/Makefile` | Create (B1) | `all`, `sanitize`, `tsan`, `clean` targets; `BUILD_DIR` override. |
| `storage_monitor/native/src/storage_monitor_walk.c` | Create (B1) | The walker (single file, about 450 lines). |
| `storage_monitor/.gitignore` | Modify (B1) | Ignore `native/build/`. |
| `tools/deployment_files.mjs` | Modify (B3) | Gains the shared helpers extracted from `deploy_colophon.mjs`. |
| `tools/deploy_colophon.mjs` | Modify (B3) | Imports the extracted helpers. Behavior and receipt hash are unchanged. |
| `tools/deploy_storage_monitor.mjs` | Create (B4) | Checks, conditional build, install, receipt, dry run, audit and rollback for the launcher and helper. |
| `tools/tests/deploy_storage_monitor.test.mjs` | Create (B4) | Lifecycle tests with invented data. |
| `tools/tests/storage-monitor-deployment-fixture.mjs` | Create (B5) | Invented receipt and binary for read-only fleet audit fixtures. |
| `tools/check_local_deployments.zsh` | Modify (B5) | Replaces the direct-copy mapping with a native block that calls the installer's `--audit`. |
| `tools/tests/test_check_local_deployments.zsh` | Modify (B5) | Fixture coverage for the new block. |
| `docs/local_deployment_sync.md` | Modify (B5) | Adds a Storage Monitor deployment section and removes the direct-copy line. |
| `storage_monitor/README.md`, `README.md`, `agents.md` | Modify (B6) | Requirements, build and deploy instructions, and the validation matrix. |

---

# Phase A — Python-only improvements

Phase A ships on its own and needs no new toolchain.

### Task A0: Real-disk measurement tool and baseline

**Files:**
- Create: `storage_monitor/tests/perf/measure_scan.py`

**Interfaces:**
- Produces: `measure_scan.py --runtime-home DIR --output FILE --runs N [--launcher PATH]`. It wraps each named launcher function with a timer, runs `create_scan_run` → `collect_scan_report` → `persist_report` → `finalize_scan_run` N times, and writes a JSON array `[{run, total_s, collect_s, summary, phases: {name: {seconds, calls}}}]`.

The tool loads the launcher with `tools.testkit.load_launcher` after setting `STORAGE_MONITOR_HOME` to `--runtime-home`. Wrap these module attributes with `functools.wraps` timers, replacing them on the module with `setattr` so internal calls are timed: `walk_tree`, `resolve_hardlink_ownership`, `rollup_subtree_totals`, `persist_full_walk`, `upsert_node_rows`, `run_parallel_call_map`, `probe_providers`, `discover_cache_candidates`, `collect_installed_bundle_ids`, `collect_orphan_candidates`, `scan_watchlist`, `build_breakdowns_from_db`, `fetch_large_files_from_db`, `persist_report`, `finalize_scan_run`. Nested timings overlap: `persist_full_walk` includes `upsert_node_rows`. State this in the script's docstring. The `summary` field is the "Visible Data volume usage" check's summary string.

- [ ] **Step 1:** Write the script. Refuse to run if `--runtime-home` or `--output` resolves inside the repository (compare `Path.resolve()` against the repository root), and create the output with mode `0600`. The output names no paths except counts, but it is still private.
- [ ] **Step 2:** Record the baseline on the current `main` code with these commands:

```zsh
acceptance=$(mktemp -d "$HOME/.storage_monitor-acceptance.XXXXXX")
storage_monitor/.venv/bin/python storage_monitor/tests/perf/measure_scan.py \
  --runtime-home "$acceptance/home-baseline" --output "$acceptance/baseline.json" --runs 3
```

Expected: three runs with `walk_tree` at about 70% of `total_s`. Keep `$acceptance` for the comparisons in A4 and B2, and never copy it into the repository.
- [ ] **Step 3:** Commit only the script.

### Task A1: Remove the unreferenced legacy scan pipeline

`_legacy_collect_scan_report` (about lines 1976–2420) has no caller. The following helpers are called only from it:

- `list_root_breakdown`
- `scan_directory_index`
- `scan_large_files_in_root`
- `scan_large_files`
- `scan_immediate_child_breakdown` (no callers at all)
- `du_bytes`
- `select_data_prefetch_plan`
- `store_immediate_breakdown`

Together they keep a second, `du`-based walker and three extra `path_depth` callers alive. Removing them first means Phases A and B change only live code.

**Files:**
- Modify: `storage_monitor/storage_monitor`

- [ ] **Step 1:** For each name above, confirm with `rg -n '\b<name>\(' storage_monitor/storage_monitor storage_monitor/tests` that every remaining reference is inside `_legacy_collect_scan_report` or the removed set. If any live caller exists, keep that function and record why in the commit body.
- [ ] **Step 2:** Delete the functions. Delete any constants or imports used only by them, checking each with `rg`.
- [ ] **Step 3:** Run `cd storage_monitor && .venv/bin/python -m pytest -q`. Expected: everything passes with the same test count as before.
- [ ] **Step 4:** Commit with the subject "Remove unreferenced legacy Storage Monitor scan pipeline".

### Task A2: String-based `path_depth`

**Files:**
- Modify: `storage_monitor/storage_monitor` (`path_depth`, currently at line 517)
- Create: `storage_monitor/tests/test_scan_pipeline.py`

**Interfaces:**
- Produces: `path_depth(root: Path, path_str: str) -> int`, with the signature unchanged. It must equal `len(PurePosixPath(path_str).relative_to(root).parts)` and return `0` where `relative_to` raises `ValueError`.

Pathlib's semantics are lexical: it collapses repeated `/`, drops single `.` components and ignores a trailing `/`. Match them exactly:

```python
def path_depth(root: Path, path_str: str) -> int:
    root_str = str(root)
    prefix = root_str if root_str.endswith("/") else root_str + "/"
    if path_str.rstrip("/") == root_str.rstrip("/"):
        return 0
    if not path_str.startswith(prefix):
        return 0
    return sum(1 for part in path_str[len(prefix):].split("/") if part not in ("", "."))
```

- [ ] **Step 1: Write the failing parity test.** In `test_scan_pipeline.py`, load the launcher (follow the `load()` helper in `tests/test_walker.py`) and compare `module.path_depth` with a pathlib reference over a table of cases, plus a performance guard:

```python
CASES = [
    ("/r", "/r"), ("/r", "/r/"), ("/r", "/r/a"), ("/r", "/r/a/b/c"), ("/r", "/r//a///b"),
    ("/r", "/r/./a"), ("/r", "/r/a/"), ("/r", "/rx/a"), ("/r", "/other"), ("/r/", "/r/a"),
    ("/", "/a/b"), ("/r", "relative/a"),
]

def reference(root, path_str):
    try:
        return len(PurePosixPath(path_str).relative_to(PurePosixPath(root)).parts)
    except ValueError:
        return 0

@pytest.mark.parametrize("root,path_str", CASES)
def test_path_depth_matches_pathlib(monkeypatch, tmp_path, root, path_str):
    module = load(monkeypatch, tmp_path)
    assert module.path_depth(Path(root), path_str) == reference(root, path_str)

def test_path_depth_is_fast(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = Path("/synthetic/root")
    paths = [f"/synthetic/root/a{i}/b/c/d" for i in range(300_000)]
    started = time.perf_counter()
    for item in paths:
        module.path_depth(root, item)
    assert time.perf_counter() - started < 1.0
```

- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_scan_pipeline.py`. Expected: the parity cases pass on the old code too (they pin semantics), and `test_path_depth_is_fast` fails (about 7 s).
- [ ] **Step 3:** Replace the body with the code above.
- [ ] **Step 4:** Run the full suite. Expected: everything passes.
- [ ] **Step 5:** Commit with the subject "Compute Storage Monitor path depth without pathlib".

### Task A3: Start provider probes before the walk

`probe_provider(scan_id, slug)` (line 1159) runs one subprocess (`brew cleanup -n`, `docker system df`, `uv cache dir`). Only the uv branch reads the index, and it does so after the subprocess finishes (`indexed_path_bytes`). Split the subprocess from the index-dependent assembly so the subprocesses overlap the walk.

**Files:**
- Modify: `storage_monitor/storage_monitor` (`probe_provider`, `probe_providers`, `collect_scan_report`)
- Modify: `storage_monitor/tests/test_scan_pipeline.py`

**Interfaces:**
- Produces:
  - `run_provider_probe(slug: str) -> Optional[Dict[str, Any]]`: returns `None` when `shutil.which(spec["binary"])` is `None`, otherwise the `run_command(spec["probe"], timeout=spec["probe_timeout"])` result.
  - `build_provider_item(scan_id: int, slug: str, probe_result: Optional[Dict[str, Any]]) -> Dict[str, Any]`: everything `probe_provider` does after the subprocess, unchanged.
  - `probe_provider(scan_id, slug)` becomes `build_provider_item(scan_id, slug, run_provider_probe(slug))`, so its callers (`rebuild_and_publish_report` and the tests) are unchanged.
  - `probe_providers(scan_id, probe_results: Optional[Dict[str, Optional[Dict[str, Any]]]] = None)`: when results are supplied, it builds items without running subprocesses.

In `collect_scan_report`, right after `publish_event("snapshot_found", …)` and before `walk_tree`, submit `run_provider_probe` for every slug in `PROVIDER_SPECS` to a dedicated `ThreadPoolExecutor(max_workers=len(PROVIDER_SPECS))`. Use a `with` block that encloses the rest of the function body up to `intelligence`, so a walk exception still joins the probe threads. In the `intelligence` map, pass `lambda: probe_providers(scan_id, {slug: future.result() for slug, future in probe_futures.items()})`.

- [ ] **Step 1: Write failing tests:**
  - `test_provider_probes_start_before_walk`: monkeypatch `run_command` to record a timestamp, and `walk_tree` to record its start time and then raise a sentinel exception. Assert that every available probe ran (`shutil.which` monkeypatched to succeed) and was submitted before the sentinel was raised. Assert that `collect_scan_report` propagates the sentinel after the probe threads finished: the executor is joined, and no thread named `ThreadPoolExecutor-*` started by the test is still alive.
  - `test_probe_provider_composition_unchanged`: the existing `test_uv_provider_uses_index_and_missing_row_is_valid` must keep passing unchanged. No new code is needed beyond running it.
- [ ] **Step 2:** Run the new tests. Expected: they fail.
- [ ] **Step 3:** Implement the split and the restructuring.
- [ ] **Step 4:** Run the full suite. Expected: everything passes.
- [ ] **Step 5:** Commit with the subject "Overlap Storage Monitor provider probes with the volume walk".

### Task A4: Python walker default of 4 workers, documentation and Phase A acceptance

**Files:**
- Modify: `storage_monitor/storage_monitor:183` (`SCAN_WORKER_COUNT` default `"8"` → `"4"`)
- Modify: `storage_monitor/README.md` (Runtime State: "default: 4"; replace the "roughly 35-second" sentence with "Full-scan time depends on directory count, storage performance, permissions, and concurrent disk activity.")

- [ ] **Step 1:** Make both edits. `SCAN_WORKER_COUNT` also sizes `run_parallel_call_map`. Confirm that `scan_watchlist`'s 20 entries are index lookups: the fallback walk runs only for paths missing from the index.
- [ ] **Step 2:** Run the full suite, the help check (`UV_PYTHON_DOWNLOADS=never ./storage_monitor --help`) and the fleet header guard (`uv run --no-python-downloads --script tools/check_uv_headers.py` from the repository root). Expected: all pass, with exit 0.
- [ ] **Step 3: Acceptance.** Run `measure_scan.py --runs 3` into `"$acceptance/phase-a.json"`. Expected: median `total_s` at most 75% of the baseline median, `walk_tree` no slower than baseline, and `persist_full_walk` under 3 s in this scope. If probes running alongside the walk slow `walk_tree` by more than 1 s, report it with the numbers rather than tuning silently.
- [ ] **Step 4:** Commit with the subject "Default the Storage Monitor walk to four workers".

---

# Phase B — native walker

### Task B1: `storage_monitor_walk` C helper and protocol tests

**Files:**
- Create: `storage_monitor/native/Makefile`
- Create: `storage_monitor/native/src/storage_monitor_walk.c`
- Create: `storage_monitor/tests/conftest.py`
- Create: `storage_monitor/tests/test_native_walker.py`
- Modify: `storage_monitor/.gitignore` (add `native/build/`)

**Interfaces (the protocol; Python in B2 and the installer in B4 depend on it exactly):**

```text
storage_monitor_walk --version
  stdout: "storage_monitor_walk <SMW_VERSION> protocol <SMW_PROTOCOL>\n", exit 0
  The values come from: #define SMW_VERSION "1.0.0" and #define SMW_PROTOCOL 1 in the C source.

storage_monitor_walk walk --root PATH --workers N --large-file-bytes B --progress-every K
                          [--exclude PATH]... [--registered-inodes-stdin] [--stat-mode]
  stdout: a stream of records. Every field is ASCII decimal or raw path bytes, and every field,
          including the last one in each record, is terminated by a single NUL byte.
    D <dir_path> <local_bytes>                                    one per walked directory
    H <dev> <ino> <nlink> <allocated> <parent_path> <name>        hardlink candidate
    L <apparent_bytes> <allocated> <parent_path> <name>           apparent size >= B
    P <directories_completed>                                     every K directories
    S <dirs> <files> <errors> <duration_ms>                       exactly once, last record, on success
  exit 0: success (S written)
  exit 2: usage error (message on stderr)
  exit 3: lstat(root) failed. stderr's first line is "errno=<n>"; nothing is written to stdout.
  exit 1: any other fatal error (allocation, thread creation, write failure)
  --registered-inodes-stdin: read decimal inode numbers, one per line, until EOF, BEFORE writing
          anything to stdout.
  --stat-mode: diagnostic and parity switch that forces readdir + fstatat instead of getattrlistbulk.
```

Required semantics. Each item mirrors today's `walk_tree` in `storage_monitor/storage_monitor:1237-1333`; keep that function open while implementing.

1. **Root handling.** `lstat(root)` gives `root_dev` and the root's own bytes (`st_blocks * 512`). Open the root without `O_NOFOLLOW`, because `os.scandir` follows a symlinked root. Every other directory is opened with `O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`.
2. **Path joining.** `child = parent + "/" + name`, except when `parent` is `/`, where the result is `"/" + name`. This matches `os.path.join`.
3. **Directory entries** (`ATTR_CMN_OBJTYPE == VDIR`, or `S_ISDIR` in stat mode). Skip any entry with `dev != root_dev`. Skip it if the joined path is byte-equal to any `--exclude`. Otherwise queue it. When a non-root directory is opened, `fstat` it. If `st_dev != root_dev`, discard it: no D record, not counted, no error (this is the mount-point rule from Review Focus 2). Otherwise its own bytes are that `fstat`'s `st_blocks * 512`.
4. **Non-directory entries** (regular files, symlinks, devices, FIFOs and sockets): skip any entry with `dev != root_dev`. Allocation is `ATTR_FILE_ALLOCSIZE`, apparent size is `ATTR_FILE_DATALENGTH` and links come from `ATTR_FILE_LINKCOUNT`. If `nlink > 1` or the inode is in the registered set, emit H and do not add the allocation to local bytes. Otherwise add it to the directory's local bytes. Independently, emit L if `apparent >= B`. Count every non-directory entry as a file.
5. **Errors.** Count an error for each entry carrying `ATTR_CMN_ERROR`, for each failed `fstatat` in stat mode, and for each failed directory open or failed `getattrlistbulk` call (which stops that directory's listing). A directory that failed to open or list still emits its D record with its own bytes, plus whatever was summed before the failure. This matches Python's `dir_local[path] = local_bytes` after an `OSError`.
6. **Missing attributes.** If `ATTR_CMN_RETURNED_ATTRS` shows that a needed attribute was not returned for an entry, fall back to `fstatat(dfd, name, &st, AT_SYMLINK_NOFOLLOW)` for that entry. If the first `getattrlistbulk` call on a directory fails with `ENOTSUP` or `EINVAL`, process that whole directory in stat mode.
7. **Threading.** A mutex/condition-variable LIFO work queue with a `pending` counter. The walk ends when `pending` reaches 0. Each worker buffers whole records in a private buffer and flushes with one `fwrite` under a single output mutex when the buffer exceeds 64 KiB and at thread exit. A record must never be split across flushes. P records are emitted under the output mutex when the global completed-directory count is a multiple of K. `main` writes S after joining all workers, then `fflush`. A failed `fwrite` or `fflush` exits with status 1 (`SIGPIPE` keeps its default action).
8. **Buffers.** Each thread gets a 256 KiB `getattrlistbulk` buffer allocated once (do not use `static __thread` arrays larger than the thread stack). Read 8-byte fields with `memcpy`: attributes are only 4-byte aligned.

The subtle part is parsing `getattrlistbulk` records. The attribute order is fixed: `ATTR_CMN_ERROR` comes immediately after `ATTR_CMN_RETURNED_ATTRS`, then the other attributes follow in bit order. This excerpt is verified against 2.6M entries:

```c
struct attrlist al = {.bitmapcount = ATTR_BIT_MAP_COUNT,
    .commonattr = ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_NAME | ATTR_CMN_DEVID | ATTR_CMN_OBJTYPE |
                  ATTR_CMN_FILEID | ATTR_CMN_ERROR,
    .fileattr = ATTR_FILE_LINKCOUNT | ATTR_FILE_ALLOCSIZE | ATTR_FILE_DATALENGTH};
for (;;) {
    int n = getattrlistbulk(dfd, &al, buf, buf_size, 0);
    if (n <= 0) break;                       /* n < 0: count one error and stop this directory */
    char *entry = buf;
    for (int i = 0; i < n; i++) {
        char *p = entry;
        uint32_t reclen; memcpy(&reclen, p, 4); p += 4;
        attribute_set_t ret; memcpy(&ret, p, sizeof ret); p += sizeof ret;
        uint32_t err = 0;
        if (ret.commonattr & ATTR_CMN_ERROR) { memcpy(&err, p, 4); p += 4; }
        attrreference_t nref; memcpy(&nref, p, sizeof nref);
        const char *name = p + nref.attr_dataoffset; p += sizeof nref;
        dev_t dev; memcpy(&dev, p, sizeof dev); p += sizeof dev;
        fsobj_type_t type; memcpy(&type, p, sizeof type); p += sizeof type;
        uint64_t ino; memcpy(&ino, p, 8); p += 8;
        uint32_t nlink = 1; off_t alloc = 0, size = 0;
        if (ret.fileattr & ATTR_FILE_LINKCOUNT) { memcpy(&nlink, p, 4); p += 4; }
        if (ret.fileattr & ATTR_FILE_ALLOCSIZE) { memcpy(&alloc, p, 8); p += 8; }
        if (ret.fileattr & ATTR_FILE_DATALENGTH) { memcpy(&size, p, 8); p += 8; }
        /* err != 0 -> count an error and skip; otherwise apply semantics 3-4 (and 6 for missing bits) */
        entry += reclen;
    }
}
```

Makefile requirements:

- `CC ?= clang`
- `CFLAGS += -std=c17 -O2 -Wall -Wextra -Werror -D_DARWIN_C_SOURCE`, plus `-pthread`
- `BUILD_DIR ?= build`
- `all` produces `$(BUILD_DIR)/storage_monitor_walk`
- `sanitize` produces `$(BUILD_DIR)/sanitize/storage_monitor_walk` with `-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer`
- `tsan` produces `$(BUILD_DIR)/tsan/storage_monitor_walk` with `-O1 -g -fsanitize=thread`
- `clean`
- Honor the variables passed on the command line, because the installer passes them explicitly. Never download anything.

`tests/conftest.py`: a session-scoped fixture `walker_binary` builds with `make -C <native> BUILD_DIR=<tmp_path_factory dir> all` and returns the path. If the `STORAGE_MONITOR_WALKER` environment variable is already set when pytest starts (the sanitizer runs use this), validate and use that binary instead of building. An autouse fixture sets `STORAGE_MONITOR_WALKER` for every test through `monkeypatch.setenv`. A build failure fails the session with make's stderr: no skip.

- [ ] **Step 1: Write the failing protocol tests** in `tests/test_native_walker.py`. Add a helper `run_walk(binary, root, *extra, stdin=None) -> (records, completed_process)`, where `records` is a list of tuples parsed by splitting stdout on `b"\0"` and grouping by the field counts D=2, H=6, L=4, P=1, S=4. Build every tree under `tmp_path` with synthetic names. Tests:
  - `test_version_reports_protocol`: matches the regular expression `^storage_monitor_walk \d+\.\d+\.\d+ protocol 1\n$`.
  - `test_matches_du_on_nested_tree_with_hardlinks_and_symlinks`: the tree from `tests/test_walker.py:22`. Sum the D local bytes plus each hardlink group's allocation once, and compare against `du -xsk` × 1024.
  - `test_names_with_control_characters_round_trip`: files and directories named `"new\nline"`, `"tab\tname"`, `"sp ace"` and `"é"` (NFC and NFD). Every D path and H/L name must equal the corresponding `os.fsencode` of the `os.scandir` value.
  - `test_directory_larger_than_one_bulk_buffer`: 20,000 empty files plus 50 four-KiB files in one directory. The file count equals 20,050, and the local bytes equal the sum of `os.lstat` `st_blocks*512`.
  - `test_mounted_volume_is_skipped`: `hdiutil create -size 8m -fs APFS -volname SMWSynthetic <tmp>/img.dmg`, then `hdiutil attach -nobrowse -mountpoint <tree>/mnt <img>`, then write a 1 MiB file inside it. Assert that no D record starts with `<tree>/mnt` and that the total excludes the 1 MiB. Detach in a `finally` block.
  - `test_excluded_path_and_registered_inodes`: one `--exclude` subtree is absent. An `nlink == 1` file whose inode is supplied on stdin with `--registered-inodes-stdin` becomes an H record.
  - `test_unreadable_directory_counts_error_and_keeps_own_bytes`: `chmod 000` a subdirectory, and restore permissions in a `finally` block. Its D record is present, and `S.errors >= 1`.
  - `test_large_file_threshold_uses_apparent_size`: a sparse file truncated to `B + 1` with `--large-file-bytes B` gives one L record whose apparent size is `B + 1`.
  - `test_progress_records_every_k_directories`: 25 directories with `--progress-every 10` give P records `10, 20`.
  - `test_missing_root_exits_3_with_errno`: exit code 3, stdout empty, and the first stderr line is `errno=2`.
  - `test_stat_mode_matches_bulk_mode`: on one mixed tree, `--stat-mode` and the default give identical D/H/L record multisets.
  - `test_deep_tree`: 300 nested directories, with one D per level and no crash.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_native_walker.py`. Expected: the session build fails because there is no Makefile.
- [ ] **Step 3:** Implement the Makefile and the C source.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q tests/test_native_walker.py`. Expected: everything passes.
- [ ] **Step 5:** Run the sanitizer builds:

```zsh
make -C native BUILD_DIR="$PWD/native/build" sanitize tsan
STORAGE_MONITOR_WALKER="$PWD/native/build/sanitize/storage_monitor_walk" .venv/bin/python -m pytest -q tests/test_native_walker.py
STORAGE_MONITOR_WALKER="$PWD/native/build/tsan/storage_monitor_walk" .venv/bin/python -m pytest -q tests/test_native_walker.py
```

Expected: everything passes with no sanitizer reports on stderr. Add an assertion in `run_walk` that `stderr` contains neither `"Sanitizer"` nor `"runtime error"`.
- [ ] **Step 6:** Commit the native source, Makefile, conftest, tests and `.gitignore`, with the subject "Add native getattrlistbulk walker for Storage Monitor".

### Task B2: Delegate `walk_tree` to the helper

**Files:**
- Modify: `storage_monitor/storage_monitor`
- Modify: `storage_monitor/tests/test_walker.py`
- Create: `storage_monitor/tests/parity/compare_walkers.py`

**Interfaces:**
- Consumes: the B1 protocol.
- Produces:
  - `WALKER_PROTOCOL = 1` (a module constant, alone on its line in exactly this form, because B4's installer reads it with the regular expression `^WALKER_PROTOCOL = (\d+)$`).
  - `walker_path() -> Path`: the first of these that exists:
    1. `STORAGE_MONITOR_WALKER`, if set (if it is set but missing, raise `WalkerUnavailable`)
    2. `Path(__file__).resolve().parent / "storage_monitor_walk"`, the deployed sibling
    3. `Path(__file__).resolve().parent / "native/build/storage_monitor_walk"`, the development build

    Otherwise it raises `WalkerUnavailable`.
  - `class WalkerUnavailable(RuntimeError)`.
  - `check_walker() -> str`: runs `--version` with a 10 s timeout and requires `protocol {WALKER_PROTOCOL}`. On a mismatch or failure it raises `WalkerUnavailable` with this message: `Storage Monitor's native walker is missing or incompatible (<detail>). Deploy with: node tools/deploy_storage_monitor.mjs  — or, in a development checkout: make -C storage_monitor/native`.
  - `walk_tree(...)`: same signature and `WalkResult` as before.

Implementation of `walk_tree`:

- Build the argument vector: `walk --root str(root) --workers str(workers) --large-file-bytes str(LARGE_FILE_THRESHOLD_BYTES) --progress-every 2000`, plus `--exclude` for each excluded path, plus `--registered-inodes-stdin` when `registered_inodes` is non-empty.
- Start `subprocess.Popen(argv, stdin=PIPE if registered else DEVNULL, stdout=PIPE, stderr=<tempfile.TemporaryFile()>)`.
- If inodes are registered, write `"\n".join(map(str, sorted(registered_inodes))).encode()` to stdin and close it before reading stdout. The helper reads all of stdin first, so this cannot deadlock.
- Parse incrementally:

```python
_FIELDS = {b"D": 2, b"H": 6, b"L": 4, b"P": 1, b"S": 4}

def _iter_walker_records(stream):
    pending = b""
    fields: List[bytes] = []
    while True:
        chunk = stream.read(1 << 20)
        if not chunk:
            break
        pending += chunk
        parts = pending.split(b"\0")
        pending = parts.pop()            # bytes after the last NUL stay buffered
        for part in parts:
            fields.append(part)
            kind = fields[0]
            if kind not in _FIELDS:
                raise RuntimeError(f"storage_monitor_walk protocol error: record type {kind!r}")
            if len(fields) == _FIELDS[kind] + 1:
                yield kind, fields[1:]
                fields = []
    if pending or fields:
        raise RuntimeError("storage_monitor_walk protocol error: truncated record stream")
```

- Decode paths with `os.fsdecode` and integers with `int`.
  - D: `dir_local[path] = bytes`.
  - H: `(dev, ino, os.path.join(parent, name), parent, alloc, nlink)`.
  - L: `{"path": os.path.join(parent, name), "parent_path": parent, "name": name, "apparent_bytes": …, "allocated_bytes": …}`.
  - P: `progress_callback(count)` if it is set.
  - S: the counts.
- After `wait()`:
  - exit 3: raise `OSError(errno, os.strerror(errno), str(root))`, preserving today's behavior when `os.lstat(root)` fails.
  - nonzero exit, missing S, or a record after S: raise `RuntimeError` including the first 2,000 characters of stderr.
- `duration_ms` is measured in Python, as today.
- On any exception, kill and wait the process (`try/finally`).

Also:

- Delete the Python `scan_dir` walker body.
- Change `SCAN_WORKER_COUNT`'s default to `"8"`. Bulk walks peak at 6–10 workers; the clamp is unchanged.
- In `main()`, call `check_walker()` immediately after `parse_args()`, so `--help` still works without the helper. On `WalkerUnavailable`, log the message and `raise SystemExit(2)` before any runtime state is created.

- [ ] **Step 1: Write failing tests** in `tests/test_walker.py`. The existing four tests stay as they are; they now run through the helper.
  - `test_startup_rejects_missing_or_mismatched_walker`: (a) `STORAGE_MONITOR_WALKER=<tmp>/absent`; (b) a synthetic shell script that prints `storage_monitor_walk 9.9.9 protocol 99`. In both cases `check_walker()` raises `WalkerUnavailable`, and the message contains `deploy_storage_monitor.mjs`. Also run the launcher's `--help` through `tools.testkit.run_launcher` with the walker missing: exit 0.
  - `test_truncated_stream_raises_and_persists_nothing`: point `STORAGE_MONITOR_WALKER` at a synthetic script that prints one D record without S and exits 0. `walk_tree` raises `RuntimeError`. Then call `run_scan_thread` on a fresh database with `collect_scan_report`'s probes monkeypatched out. Assert that the scan run's status is `failed`, a previously completed `active=1` run stays active, and its `nodes` rows are intact.
  - `test_registered_inodes_reach_helper`: a single-link file whose inode is passed in `registered_inodes` appears in `hardlink_candidates`.
  - `test_walk_tree_missing_root_raises_oserror`: `walk_tree(tmp_path / "absent", workers=1, excluded_paths=[])` raises `FileNotFoundError`.
  - `test_progress_callback_receives_counts`: 4,100 directories give callbacks at 2000 and 4000.
- [ ] **Step 2:** Run the suite. Expected: the new tests fail.
- [ ] **Step 3:** Implement the changes above.
- [ ] **Step 4:** Run the full suite (`.venv/bin/python -m pytest -q`), the sanitizer runs from B1 Step 5 against the whole suite, the help check, and the fleet header guard. Expected: everything passes with no skips.
- [ ] **Step 5: Write the parity tool** `tests/parity/compare_walkers.py --baseline-ref REF --root PATH --output FILE`:
  - It writes `git show REF:storage_monitor/storage_monitor` to a private temporary file and loads both launchers with `load_launcher`.
  - It runs each walker, applies `resolve_hardlink_ownership` (with `full_scan=True`) and `rollup_subtree_totals` exactly as `collect_scan_report` does, then compares.
  - Comparison: the set of directory paths, the per-directory totals at depth ≤ 3, the large-file set and the hardlink-owner set. It writes counts plus mismatching *counts* to `--output` (mode 0600). Paths are printed only with `--show-paths`, to the terminal, never to the file.
  - Like A0, it refuses repository-internal outputs.
- [ ] **Step 6: Real-disk acceptance** (outputs stay in `$acceptance`):

```zsh
storage_monitor/.venv/bin/python storage_monitor/tests/parity/compare_walkers.py \
  --baseline-ref main --root /System/Volumes/Data --output "$acceptance/parity.json"
STORAGE_MONITOR_WALKER="$PWD/storage_monitor/native/build/storage_monitor_walk" \
  storage_monitor/.venv/bin/python storage_monitor/tests/perf/measure_scan.py \
  --runtime-home "$acceptance/home-native" --output "$acceptance/phase-b.json" --runs 3
```

Build first with `make -C storage_monitor/native`. Expected:
  - Parity differences are confined to paths modified during the run. Re-run the parity check once; any persistent mismatch is a defect.
  - The large-file and hardlink-owner sets match.
  - The median `total_s` is at most 50% of the A0 baseline median.

  Report the numbers to the owner, and state whether the shell has Full Disk Access.
- [ ] **Step 7:** Commit with the subject "Delegate Storage Monitor walks to the native helper".

### Task B3: Extract shared deployment helpers (no behavior change)

`tools/deploy_colophon.mjs` holds generic helpers that the new installer also needs. Extract them instead of copying them, so the second native installer reuses rather than duplicates (see "identify the common pieces from working code" in `docs/local_deployment_sync.md`).

**Files:**
- Modify: `tools/deployment_files.mjs`
- Modify: `tools/deploy_colophon.mjs`

**Constraint from the colophon tests (verified at `cc21e50`):** `preCutoverInstaller` in `tools/tests/deploy_colophon.test.mjs` builds an "old" installer by running `replaceAll` over `deploy_colophon.mjs`'s source text. It rewrites `colophon/`, `colophon\/`, `'colophon'], {encoding` and `path.join(scratch, 'colophon')`, then copies `deployment_files.mjs` next to it unmodified. Therefore:

- Every Colophon-specific literal those rewrites target must stay in `deploy_colophon.mjs` with its exact current text. In particular, keep the line `execFileSync('git', ['-C', repo, 'ls-files', '--stage', '--sparse', '-z', '--', 'colophon'], {encoding: 'utf8'})` verbatim, along with `buildInput`, the required-input list and `path.join(scratch, 'colophon')`.
- `deployment_files.mjs` must contain no `colophon` literal and import only Node built-ins.
- Do not edit `deploy_colophon.test.mjs`. If the extraction cannot pass it unchanged, stop and report why instead of adapting the test.

**Interfaces:**
- Produces, in `deployment_files.mjs`:
  - `sha(bytes) -> string`
  - `exists(file) -> boolean` (an `lstat`-based check that rethrows anything except `ENOENT`)
  - `atomicFile(target, bytes, mode, stagePrefix)`, which is `deploy_colophon.mjs`'s `atomicFile` with the staging prefix as a parameter (Colophon passes `'.colophon-stage-'`)
  - `parseIndexSnapshot(file) -> [{mode, name}]`, which is the `snapshot` branch of `sourceInventory` (`Invalid native source inventory`)
  - `parseStagedListing(raw) -> [{mode, oid, name}]`, which parses `git ls-files --stage -z` output (`Native project must have only regular stage-zero tracked files`)
  - `normalizeEntries(entries) -> entries`, which sorts by name and throws `Duplicate native input`
  - `hashInventory(repo, entries, requireStaged) -> {entries, sourceHash}`, which is the path, mode, staged-bytes and hash loop. Its errors are `Invalid native input path`, `Native source mode differs from index` and `Native working bytes differ from Git index; validate and stage first`.

  Error strings and the hash construction (`name\0mode-octal\0sha\0` over the name-sorted entries) must be byte-for-byte unchanged, because tests match them.
- `deploy_colophon.mjs` keeps exporting `buildInput` and `sourceInventory(repo, snapshot, requireStaged)`, because the fleet fixture `tools/tests/native-deployment-fixture.mjs` imports `sourceInventory`. The order of checks stays as it is today: list or parse, filter with `buildInput`, `normalizeEntries`, the required-input check, then `hashInventory`.
- Colophon's private-state names `.colophon-native.json` and `~/.utilities-deploy-backups/colophon-native/` are documented compatibility exceptions. Leave them as they are.

- [ ] **Step 1:** Record the baseline from the repository root:
  - `node -e "import('./tools/deploy_colophon.mjs').then(m=>console.log(m.sourceInventory(process.cwd()).sourceHash))"`. Expected: the hash in Starting state.
  - `node tools/deploy_colophon.mjs --audit`, saving its stdout, stderr and exit status.
  - `zsh tools/check_local_deployments.zsh 2>&1 | grep -E '^(OK|FAIL)'`, saved to a scratch file outside the repository.
- [ ] **Step 2:** Extract the helpers and rewire Colophon.
- [ ] **Step 3:** Re-run the three commands from Step 1. Expected: the same hash, the same Colophon audit result (currently exit 1, `Native build source drift`), and an identical `OK`/`FAIL` line set.
- [ ] **Step 4:** Run `node --test tools/tests/deploy_colophon.test.mjs tools/tests/deploy_ai_model_timeline.test.mjs`, `node --test tools/tests/check_static_deployments.test.mjs` and `zsh tools/tests/test_check_local_deployments.zsh`. Expected: all pass, including `pre-cutover receipt drifts after relocation…` with no test edits. Also run `rg -n colophon tools/deployment_files.mjs`. Expected: no matches.
- [ ] **Step 5:** Commit with the subject "Extract shared native deployment helpers".

### Task B4: `tools/deploy_storage_monitor.mjs`

This installer owns both deployed files, `<scripts>/storage_monitor` (the launcher) and `<scripts>/storage_monitor_walk` (the helper), plus a receipt. It replaces the direct copy.

**Files:**
- Create: `tools/deploy_storage_monitor.mjs`
- Create: `tools/tests/deploy_storage_monitor.test.mjs`

**Interfaces:**
- Consumes: B3's helpers; B1's `--version` output and Makefile; B2's `WALKER_PROTOCOL` line.
- Command line: `node tools/deploy_storage_monitor.mjs [--dry-run | --audit | --rollback BACKUP] [--rebuild] [--repo DIR] [--scripts-dir DIR] [--source-inventory FILE]`. Defaults and overrides are the same as Colophon's: `UTILITIES_SCRIPTS_DIR` or `~/Library/Scripts`, and destinations inside the repository or through directory links are refused.
- Inputs come from `git ls-files --stage --sparse -z -- storage_monitor`, or `--source-inventory` in audit mode, and pass through `parseStagedListing`/`parseIndexSnapshot`, an input filter, `normalizeEntries`, a required-input check and `hashInventory` (all from B3):
  - the launcher: `storage_monitor/storage_monitor`, required, mode 100755
  - native inputs: `storage_monitor/native/Makefile` and `storage_monitor/native/src/**`, with the Makefile and `src/storage_monitor_walk.c` required

  Two hashes: `nativeSourceHash` over the native inputs only, and `launcherHash = sha(launcher bytes)`.
- Receipt at `<scripts>/.storage_monitor.json`, mode 0600:

```json
{"schema": 1, "launcherHash": "<sha256>", "launcherMode": 493, "nativeSourceHash": "<sha256>",
 "walkerHash": "<sha256>", "walkerMode": 493, "walkerVersion": "1.0.0", "protocol": 1}
```

- Backups go to `~/.utilities-deploy-backups/storage_monitor/copy-*/` (directories 0700, files 0600). `state.json` records each prior file's presence, hash and mode, for the launcher, the walker and the receipt.
- Success output lines (tests assert them):
  - `launcher: current|update`
  - `walker: current|rebuild (<reason>)`, where the reason is `source changed`, `binary missing`, `binary drift`, `no receipt`, `receipt invalid` or `forced`
  - then either `Storage Monitor deployed; rollback backup: <dir>` or `Storage Monitor already current; nothing changed`
- Audit output: exactly `OK: storage_monitor deployment` (30 bytes plus a newline; B5 asserts the size).

Decision procedure for the default and `--dry-run` modes. This is what makes deployment "check and build only as needed":

1. Take the inventory with `hashInventory(repo, entries, true)`, so the working bytes and modes of the native inputs and the launcher must equal the Git index. `nativeSourceHash` is `hashInventory` over the native inputs only; `launcherHash` is `sha` of the launcher bytes.
2. **Protocol pre-check.** Read `^WALKER_PROTOCOL = (\d+)$` from the staged launcher and `^#define SMW_PROTOCOL (\d+)$` from the staged C source. If they differ or either is missing, fail before touching anything with `launcher expects walker protocol X but native source declares Y`.
3. Classify the walker. It is `current` only when all of these hold:
   - the receipt parses with schema 1 and mode 0600
   - `receipt.nativeSourceHash` equals the current hash
   - the installed walker is a regular file whose sha and mode match the receipt
   - running the installed walker with `--version` reports `protocol <SMW_PROTOCOL>`

   Otherwise it is `rebuild (<reason>)`. `--rebuild` forces `rebuild (forced)`, which is the documented remedy after an Xcode or SDK upgrade, because the receipt cannot detect compiler changes.
4. Classify the launcher: `current` when the installed bytes and mode equal the staged launcher.
5. **Toolchain check** whenever a rebuild is needed, including in `--dry-run`. `xcrun --find clang` and `make --version` must succeed. Otherwise fail with `Xcode Command Line Tools are required to build storage_monitor_walk: run xcode-select --install`.
6. `--dry-run` prints both classification lines and `Dry run: no files changed`, then exits 0 without building or writing.
7. If both are current, print `already current` and exit 0 without a backup.
8. If a rebuild is needed:
   - Write the native inputs into a fresh `mkdtemp` scratch directory.
   - Run `make -C <scratch>/storage_monitor/native BUILD_DIR=build CC=clang CFLAGS= CPPFLAGS= LDFLAGS= all`, with `MAKEFLAGS`, `MFLAGS`, `CFLAGS`, `CPPFLAGS` and `LDFLAGS` cleared in the environment and a 300 s timeout.
   - Require a Mach-O magic number.
   - Run `--version`, which must equal `storage_monitor_walk <version> protocol <SMW_PROTOCOL>`.
   - Run a functional smoke test: create a synthetic tree in scratch (two directories, one 4 KiB file, one hardlink pair) and run `walk --root <tree> --workers 2 --large-file-bytes 1073741824 --progress-every 2000`. Require exit 0, a final S record with `dirs == 3`, and an H record count of 2.
   - Then re-take the inventory and require an unchanged hash ("inputs changed during build").

   When not rebuilding, reuse the installed walker bytes for the receipt.
9. Back up everything that exists. Install with `atomicFile` in this order: walker (0755), launcher (0755), receipt (0600). Then run the installed walker's `--version`. On any failure, restore the backup and rethrow.

`--audit` (read-only; never builds or executes anything):
- It takes the inventory from `--source-inventory` when given (the fleet audit's validated index snapshot, in Colophon's `mode\tpath\0` format).
- It checks the receipt, `nativeSourceHash`, the walker's sha and mode against the receipt, and the launcher's bytes and mode against the staged source (`launcherHash` in the receipt must also match).
- It prints the OK line, or throws with `source drift`, `walker drift`, `launcher drift` or `receipt invalid`.

`--rollback BACKUP`: validates the whole backup, backs up the current state, then restores all three files, mirroring Colophon's `readBackup` and `restore`.

- [ ] **Step 1: Write failing lifecycle tests.** Model the fixture on `tools/tests/deploy_colophon.test.mjs`: an invented repository under `os.tmpdir()`, `HOME` redirected, and a synthetic `storage_monitor/storage_monitor` launcher containing `WALKER_PROTOCOL = 1` and a trivial body. The native source is a tiny C program that implements only `--version` and a `walk` producing correct records for the smoke tree. Construct its records with `printf` from a fixed table, because the installer's smoke check only reads the S and H records. Tests:
  - `dry-run reports rebuild on first deploy and writes nothing`
  - `first deploy installs launcher, walker and receipt with modes 0755/0755/0600`
  - `second run with no changes reports already current and creates no backup`
  - `launcher-only change does not rebuild`: assert that the walker bytes are unchanged and the line `walker: current` is printed
  - `native change rebuilds`
  - `--rebuild forces a build`
  - `protocol mismatch is refused before backup`: change the launcher to `WALKER_PROTOCOL = 2`
  - `missing toolchain fails before backup`: run with `PATH` limited to a directory containing a `xcrun` stub that exits 1
  - `unstaged working change is refused`
  - `activation failure restores prior deployment`: make the installed `--version` fail, using Colophon's `failInstalled` technique of checking `argv[0]`
  - `audit passes, then fails on walker drift, launcher drift and source drift`
  - `rollback restores the previous files and modes`
  - `existing direct-copy launcher without receipt is backed up and replaced`: this is the migration from today's deployment
- [ ] **Step 2:** Run `node --test tools/tests/deploy_storage_monitor.test.mjs`. Expected: the tests fail because the module is missing.
- [ ] **Step 3:** Implement the installer.
- [ ] **Step 4:** Run `node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_ai_model_timeline.test.mjs`. Expected: all pass.
- [ ] **Step 5:** Commit with the subject "Add Storage Monitor deployment with conditional native build".

### Task B5: Fleet audit integration

**Files:**
- Modify: `tools/check_local_deployments.zsh`
- Create: `tools/tests/storage-monitor-deployment-fixture.mjs`
- Modify: `tools/tests/test_check_local_deployments.zsh`
- Modify: `docs/local_deployment_sync.md`

Changes:

- In `check_local_deployments.zsh`:
  - Remove `'storage_monitor/storage_monitor|storage_monitor'` from `copy_mappings` (line 145).
  - Add `storage_monitor`, `tools/deploy_storage_monitor.mjs` to `audited_scopes` (around line 289).
  - After the Colophon block (lines 611–644), add an equivalent block. It builds `$AUDIT_TMP/storage-monitor-source-inventory` from `index_paths` matching `storage_monitor/*`, requires `storage_monitor/storage_monitor`, `storage_monitor/native/Makefile`, `tools/deploy_storage_monitor.mjs` and `tools/deployment_files.mjs` in the index with valid state, and calls `node tools/deploy_storage_monitor.mjs --audit --repo … --scripts-dir … --source-inventory …`.
  - Accept only an empty stderr and stdout of exactly `OK: storage_monitor deployment` (31 bytes, including the newline). Failure messages are `storage_monitor source inventory unverified`, `storage_monitor child protocol unverified` and `storage_monitor deployment unverified (source, launcher, walker or receipt drift)`.
- In `tools/tests/test_check_local_deployments.zsh`, remove `'storage_monitor/storage_monitor|storage_monitor'` from the fixture's own `COPY_MAPPINGS` list (line 106, consumed at lines 244 and 419). Otherwise the fixture keeps writing a direct copy that the audit no longer expects.
- The fixture `.mjs` writes an invented walker plus a matching receipt, as `native-deployment-fixture.mjs` does for Colophon. It imports B3's helpers from `../deployment_files.mjs`. The fleet fixture setup (around line 236, next to the Colophon synthetic inputs) writes a synthetic `storage_monitor/storage_monitor` launcher containing `WALKER_PROTOCOL = 1`, synthetic `storage_monitor/native/Makefile` and `storage_monitor/native/src/storage_monitor_walk.c` files, copies `tools/deploy_storage_monitor.mjs` into the fixture repository's `tools/` (as it does for `deploy_colophon.mjs`), then invokes the new fixture next to the existing `native-deployment-fixture.mjs` call (line 311).
- The audit's passing line for this project changes from `OK: storage_monitor` (direct copy) to `OK: storage_monitor deployment`. Update any fixture assertion that expects the old line.
- **Expected live transition:** once B5 is committed, the real fleet audit reports `FAIL: storage_monitor deployment unverified …` until B6's authorized live deploy. The deployed direct copy has no walker or receipt. This failure is the expected signal that the deploy is due, not a defect. All other `OK`/`FAIL` lines must match the B3 baseline.
- Add `test_storage_monitor_deployment` covering: a passing baseline, walker drift, launcher drift, native source drift, a missing receipt, and native source removed from the index. Assert the failure message in each case, mirroring `test_native_colophon_deployment` (line 1537).
- In `docs/local_deployment_sync.md`, remove the `storage_monitor` line from the direct-copy list and add a "Storage Monitor deployment" section after "Native Colophon deployment". It covers the commands (`--dry-run`, deploy, `--audit`, fleet audit), the conditional rebuild rules and `--rebuild`, the receipt, backups and rollback, the toolchain requirement, the receipt not tracking compiler versions, and the migration from the direct copy.

- [ ] **Step 1:** Write the failing fixture test.
- [ ] **Step 2:** Run `zsh tools/tests/test_check_local_deployments.zsh`. Expected: the new test fails.
- [ ] **Step 3:** Implement the audit block and the documentation section.
- [ ] **Step 4:** Run all deployment and audit suites from the validation matrix:
  - `node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_ai_model_timeline.test.mjs`
  - `node --test tools/tests/check_static_deployments.test.mjs`
  - `zsh tools/tests/test_check_local_deployments.zsh`

  The validation matrix says changes to the static audit's child runner also require Market Atlas's suites. This task does not touch `check_static_deployments.mjs`, so confirm that with `git diff --stat` and state it in the commit body. Expected: all pass.

  Then run the real read-only `zsh tools/check_local_deployments.zsh 2>&1 | grep -E '^(OK|FAIL)'` and compare it with the B3 baseline. Expected: the only difference is the storage_monitor line, now in its expected pre-deploy `FAIL` state.
- [ ] **Step 5:** Commit with the subject "Audit Storage Monitor's native deployment".

### Task B6: Documentation, dependencies and live deployment

**Files:**
- Modify: `storage_monitor/README.md`
- Modify: `README.md`
- Modify: `agents.md`

`storage_monitor/README.md`:

- **Requirements:**
  - macOS with APFS, `diskutil`, `tmutil`
  - uv
  - **Xcode Command Line Tools** (`xcode-select --install`), which provide Apple clang and `make`, needed to build `storage_monitor_walk`
  - **Node.js**, for `tools/deploy_storage_monitor.mjs`
  - a browser with CDN access (unchanged)

  Note that the running app never compiles anything.
- **Architecture paragraph:** the single-file launcher plus the native walker. State what each owns, and that the launcher refuses to start if the walker is missing or speaks a different protocol.
- **Install/Deploy:** replace the symlink-only quick start with this:
  - Development: `make -C native`, then `UV_PYTHON_DOWNLOADS=never ./storage_monitor`. The launcher finds `native/build/storage_monitor_walk`.
  - Installed use: `node ../tools/deploy_storage_monitor.mjs --dry-run`, then deploy.
  - Symlinking the repository launcher still works after `make -C native`.
- **Runtime State:**
  - `STORAGE_MONITOR_SCAN_WORKERS` defaults to 8 (clamped 1–16)
  - `STORAGE_MONITOR_WALKER` overrides the helper path
  - Remove the "roughly 35-second" claim if A4 did not already.
- **Validation:**
  - `.venv/bin/python -m pytest -q`, which builds the walker into a temporary directory
  - sanitizer runs: `make -C native sanitize tsan`, plus the two `STORAGE_MONITOR_WALKER=…` pytest commands
  - deployment tests
  - the perf and parity tools, with private outputs

`README.md` (root):

- In "Projects At A Glance", extend the `storage_monitor` entry with: "A native `getattrlistbulk` walker (C) indexes the volume; building and deploying it requires Xcode Command Line Tools and Node.js."
- In "Single-File Python Launcher", after "This is the common form for tools like … `storage_monitor` …", add one sentence: `storage_monitor` pairs its launcher with a native helper deployed by `tools/deploy_storage_monitor.mjs`, so its machine prerequisites also include Xcode Command Line Tools.

This bubbles the dependency up to the root, because the root README currently states uv as the only prerequisite of this form.

`agents.md`, Validation Matrix: add a `storage_monitor` entry:
- `.venv/bin/python -m pytest -q` from `storage_monitor/` (unit, native protocol, integration and browser tests; builds the walker; no skips)
- `make -C native sanitize tsan` and both sanitizer pytest runs
- after launcher header edits, the fleet guard
- deployment changes run `node --test tools/tests/deploy_storage_monitor.test.mjs` and `zsh tools/tests/test_check_local_deployments.zsh`
- real-disk perf and parity runs require owner approval; their outputs are private and never committed

Also extend the existing "Static deployment/fleet audit tooling" entry (`agents.md` line 68). Its first command becomes `node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_ai_model_timeline.test.mjs`, so a change to the shared `tools/deployment_files.mjs` runs both native installers' lifecycle tests. In `docs/local_deployment_sync.md`, update the Colophon section's "Installer lifecycle and fleet integration fixtures" command the same way.

- [ ] **Step 1:** Make the documentation edits. Check every command in them by running it, except the live deploy.
- [ ] **Step 2:** Run the complete validation:
  - the storage_monitor suite and sanitizer runs
  - `UV_PYTHON_DOWNLOADS=never ./storage_monitor --help`
  - a smoke start `UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" UV_PYTHON_DOWNLOADS=never ./storage_monitor --no-browser --port <free-port>`: request `/api/state` until `scan_status.phase` is `idle` with no error, then stop it
  - the uv header guard
  - all deployment and audit suites from B5

  Expected: all pass. Report any failure with its output.
- [ ] **Step 3:** Commit with the subject "Document Storage Monitor native walker requirements and deployment".
- [ ] **Step 4: Live deployment (requires separate owner authorization).** Stage the reviewed source, then run:

```zsh
node tools/deploy_storage_monitor.mjs --dry-run     # expect: launcher: update, walker: rebuild (no receipt)
node tools/deploy_storage_monitor.mjs
node tools/deploy_storage_monitor.mjs --audit       # expect: OK: storage_monitor deployment
zsh tools/check_local_deployments.zsh               # expect: OK: storage_monitor deployment; all other lines as in the B3 baseline
~/Library/Scripts/storage_monitor_walk --version    # expect: storage_monitor_walk 1.0.0 protocol 1
```

Then run the installed `storage_monitor` normally, confirm that a full scan completes and the dashboard renders, and compare its "Visible Data volume usage" walk duration with the app's previous scans. Record the result only in the private acceptance directory and report it to the owner.

---

## Self-review notes

- **Coverage:** Phase A covers the depth, probe-overlap and worker items (A2–A4), plus the measurement baseline (A0). Phase B covers the helper (B1), the integration with no fallback (B2), the deployment with checks and conditional build (B3–B5, including the protocol pre-check, toolchain check, `--rebuild` and audit), and the README dependency notes in the project and root READMEs (B6). The dead-code removal (A1) is preparatory and can be dropped without affecting later tasks, except that B2 would then also have to keep `du_bytes` in mind.
- **Consistency:** `WALKER_PROTOCOL` (Python) and `SMW_PROTOCOL` (C) are both 1 and are cross-checked by B2 at runtime and by B4 at deploy time. The record field counts D=2, H=6, L=4, P=1, S=4 are the same in B1's protocol, B1's tests and B2's parser. The audit line `OK: storage_monitor deployment` is 31 bytes including the newline, in both B4 and B5.
- **Known limits:**
  - The receipt cannot detect compiler or SDK changes, so `--rebuild` is the documented remedy.
  - Real-disk numbers depend on Full Disk Access, cache state and concurrent activity.
  - FSEvents incremental scanning is deliberately excluded.
