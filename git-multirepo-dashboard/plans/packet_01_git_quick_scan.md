# Packet 01: Git Quick Scan

## Why This Packet Exists

The fleet overview depends on being able to quickly scan each repo's working state (uncommitted changes, current branch, last commit). This packet implements the core git subprocess operations that feed the fleet view. It's pure git + parsing — no API, no UI.

## Scope

- Async helper function `run_git(repo_path, *args)` that wraps `asyncio.create_subprocess_exec` with `git -C {repo_path}` and returns decoded stdout/stderr
- `quick_scan_repo(repo_path)` function that runs 4 git commands and returns a structured dict
- `is_valid_repo(repo_path)` function using `git rev-parse --is-inside-work-tree`
- `parse_porcelain_status(output)` function that parses `git status --porcelain=v1` into modified_count, untracked_count, staged_count, has_uncommitted
- `parse_last_commit(output)` function that parses `git log -1 --format='%H%x00%aI%x00%s'` into hash, date, message
- `get_current_branch(repo_path)` function using `git rev-parse --abbrev-ref HEAD`
- `upsert_working_state(db, repo_id, data)` function that writes results to the `working_state` table

## Non-Goals

- No full history scan (packet 06)
- No branch listing (packet 07)
- No API endpoints (packet 03)
- No parallel orchestration across multiple repos (packet 03)
- No dependency detection (packet 12)
- No error recovery or path-not-found handling (packet 22)

## Relevant Design Doc Sections

- Section 3: Git Data Collection (intro + cross-platform subprocess notes)
- Section 3.1: Quick Scan (all of it)
- Section 9: Edge Cases — "Repo has zero commits", "Non-UTF8 commit messages", "Shallow clone"

## Allowed Files

- `git-multirepo-dashboard/git_dashboard.py` (modify — add functions after the bootstrap/schema code)
- `git-multirepo-dashboard/tests/test_git_quick_scan.py` (create)

## Tests to Write First

1. **Test: `run_git` executes git command and returns output**
   - Create a temp git repo (`git init`, `git commit --allow-empty`).
   - Call `run_git(temp_repo, "rev-parse", "--is-inside-work-tree")`.
   - Expect stdout to contain `"true"`.

2. **Test: `is_valid_repo` returns True for a git repo**
   - Create a temp git repo. Call `is_valid_repo(temp_path)`. Expect `True`.
   - Call `is_valid_repo("/tmp/nonexistent")`. Expect `False`.

3. **Test: `parse_porcelain_status` with clean repo**
   - Input: `""` (empty string).
   - Expect: `{"modified_count": 0, "untracked_count": 0, "staged_count": 0, "has_uncommitted": False}`.

4. **Test: `parse_porcelain_status` with dirty repo**
   - Input:
     ```
      M file1.py
     M  file2.py
     A  file3.py
     ?? newfile.txt
     ?? another.txt
     ```
   - Expect: `modified_count=1` (worktree modifications: ` M`), `staged_count=2` (index changes: `M ` and `A `), `untracked_count=2`, `has_uncommitted=True`.

5. **Test: `parse_porcelain_status` distinguishes index vs worktree changes**
   - `MM file.py` → both staged AND modified (staged_count=1, modified_count=1).
   - `A  file.py` → staged only (staged_count=1, modified_count=0).
   - ` M file.py` → modified only (staged_count=0, modified_count=1).

6. **Test: `parse_last_commit` with valid output**
   - Input: `"abc123def456\x002026-03-09T14:23:00-06:00\x00fix: handle empty response"`.
   - Expect: `{"hash": "abc123def456", "date": "2026-03-09T14:23:00-06:00", "message": "fix: handle empty response"}`. <!-- pragma: allowlist secret -->

7. **Test: `parse_last_commit` with empty repo (no commits)**
   - Input: `""`.
   - Expect: `{"hash": None, "date": None, "message": None}`.

8. **Test: `quick_scan_repo` integration test**
   - Create a temp git repo with one commit and one uncommitted file.
   - Call `quick_scan_repo(temp_path)`.
   - Verify: `has_uncommitted=True`, `current_branch` is set, `last_commit_hash` is set, `last_commit_date` is an ISO datetime string.

9. **Test: `upsert_working_state` writes and updates**
   - Create in-memory DB with schema. Upsert working state for a repo_id.
   - Verify row exists with correct values.
   - Upsert again with different values. Verify row is updated (not duplicated).

## Implementation Notes

### `run_git` helper

```python
async def run_git(repo_path: str | Path, *args: str) -> tuple[str, str, int]:
    """Run a git command and return (stdout, stderr, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_path), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
        proc.returncode,
    )
```

Key: always use `errors='replace'` for non-UTF8 commit messages. Always pass args as a list, never `shell=True`.

### Porcelain v1 format

Each line is exactly: `XY filename` where X = index status, Y = worktree status.

- `X != ' ' and X != '?'` → staged change (staged_count += 1)
- `Y == 'M'` → worktree modification (modified_count += 1)
- `X == '?' and Y == '?'` → untracked (untracked_count += 1)
- Any non-empty output → has_uncommitted = True

Note: `MM` means both index AND worktree modified — count in both staged and modified.

### Quick scan command sequence

Per spec section 3.1, run these 4 commands for each repo:

1. `git rev-parse --is-inside-work-tree` → confirm valid
2. `git status --porcelain=v1` → parse working tree state
3. `git log -1 --format='%H%x00%aI%x00%s'` → last commit info
4. `git rev-parse --abbrev-ref HEAD` → current branch

Run them sequentially per repo (they're fast, <100ms total). Parallelism across repos comes in packet 03.

### `upsert_working_state`

Use `INSERT OR REPLACE INTO working_state (...)` with all columns. Set `checked_at` to `datetime.now(timezone.utc).isoformat()`.

### Edge case: empty repo (no commits)

`git log -1` returns empty output with returncode 128. Handle gracefully: set hash/date/message to None. `git rev-parse --abbrev-ref HEAD` may return "HEAD" (detached). `git status --porcelain` still works on empty repos.

## Acceptance Criteria

1. `run_git()` successfully executes git commands against real repos and returns decoded output.
2. `is_valid_repo()` returns True for git repos, False for non-repos and nonexistent paths.
3. `parse_porcelain_status()` correctly classifies all status line patterns (staged, modified, untracked).
4. `parse_last_commit()` correctly parses the NUL-delimited format and handles empty repos.
5. `quick_scan_repo()` returns a complete dict with all working_state fields for a real git repo.
6. `upsert_working_state()` creates and updates rows in the working_state table correctly.
7. All tests pass.
8. Non-UTF8 commit messages are handled without crashing (`errors='replace'`).

## Validation Focus Areas

- Porcelain status parsing: this is the most error-prone part. Verify all XY combinations are handled correctly. Pay special attention to `MM`, `AM`, `AD`, `R `, `D `, `DD`, `UU` (merge conflicts).
- Empty repo handling: verify all 4 commands handle repos with zero commits.
- Subprocess execution: verify `asyncio.create_subprocess_exec` is used (not `shell=True`), and paths with spaces work.
