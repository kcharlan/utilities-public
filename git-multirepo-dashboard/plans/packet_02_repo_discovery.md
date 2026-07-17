# Packet 02: Repo Discovery & Registration API

## Why This Packet Exists

Users need a way to tell the dashboard where their git repos live. This packet implements the recursive directory scanner that finds git repos and the API endpoints to register/unregister them. It's the bridge between the filesystem and the database.

## Scope

- `discover_repos(root_path)` function: recursively walks a directory tree, finds git repos (directories containing `.git/`), deduplicates using `git rev-parse --show-toplevel`
- Repo ID generation: `sha256(absolute_path)[:16]`
- Runtime detection: check for ecosystem files (pyproject.toml, package.json, go.mod, etc.) per the priority table in spec section 3.4, return the `runtime` classification
- Default branch detection: `git symbolic-ref --short HEAD`
- `POST /api/repos` endpoint: accepts `{"path": "/some/dir"}`, discovers repos, inserts into `repositories` table, returns list of registered repos
- `DELETE /api/repos/{id}` endpoint: removes a repo from all tables (CASCADE), returns 204
- `GET /api/repos` endpoint: lists all registered repos (simple DB query, no scan)
- Handle the `--scan` CLI flag: if provided, register the directory on startup before launching the server

## Non-Goals

- No quick scan during registration (packet 03 handles that via GET /api/fleet)
- No dependency parsing beyond runtime classification (packet 12)
- No UI (packets 04–05)
- No full scan or history (packet 06)
- No branch enumeration (packet 07)

## Relevant Design Doc Sections

- Section 1: Bootstrap Constants (repo ID generation)
- Section 3.4: Dependency Detection (file detection priority table — for runtime classification only)
- Section 4: API Endpoints — POST /api/repos, DELETE /api/repos/{id}
- Section 9: Edge Cases — "Repo inside repo (submodules)", "Registered path deleted from disk"

## Allowed Files

- `git-multirepo-dashboard/git_dashboard.py` (modify — add discovery functions and API endpoints)
- `git-multirepo-dashboard/tests/test_repo_discovery.py` (create)

## Tests to Write First

1. **Test: `discover_repos` finds git repos recursively**
   - Create a temp directory with 3 subdirectories. `git init` in two of them.
   - Call `discover_repos(temp_root)`. Expect 2 repos found.

2. **Test: `discover_repos` skips non-git directories**
   - Create a temp directory with subdirectories but no `.git/`. Expect 0 repos.

3. **Test: `discover_repos` deduplicates submodules**
   - Create a repo with a subdirectory that is also a git repo (simulating a submodule).
   - `discover_repos` should use `git rev-parse --show-toplevel` to deduplicate.
   - Only the toplevel repo should be returned (unless the submodule is at a separate toplevel).

4. **Test: `discover_repos` skips hidden directories and common excludes**
   - Should skip directories named `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`.
   - Create these directories with `.git` inside them. Verify they're excluded.

5. **Test: Repo ID is deterministic**
   - `generate_repo_id("/Users/example/repos/myapp")` returns the same 16-char hex string every time.
   - Different paths produce different IDs.

6. **Test: Runtime detection — Python**
   - Directory contains `pyproject.toml`. Expect runtime = "python".
   - Directory contains `requirements.txt` but no pyproject.toml. Expect runtime = "python".

7. **Test: Runtime detection — Node**
   - Directory contains `package.json`. Expect runtime = "node".

8. **Test: Runtime detection — Mixed**
   - Directory contains both `pyproject.toml` and `package.json`. Expect runtime = "mixed".

9. **Test: Runtime detection — Unknown**
   - Directory contains none of the known files. Expect runtime = "unknown".

10. **Test: POST /api/repos registers repos**
    - Use FastAPI TestClient. POST `{"path": temp_dir}` where temp_dir has 2 git repos.
    - Expect response with `registered: 2` and a `repos` array with 2 entries.
    - Each entry has `id`, `name`, `path`.

11. **Test: POST /api/repos is idempotent**
    - Register the same directory twice. Second call should not create duplicates.
    - Verify repo count is still 2 (not 4).

12. **Test: DELETE /api/repos/{id} removes a repo**
    - Register repos. DELETE one by ID. Expect 204.
    - GET /api/repos should return one fewer repo.

13. **Test: DELETE cascades to related tables**
    - Register a repo. Insert a dummy row into `working_state` for that repo_id.
    - DELETE the repo. Verify the `working_state` row is also gone (CASCADE).

14. **Test: POST /api/repos with nonexistent path**
    - POST `{"path": "/nonexistent/path"}`. Expect 400 or empty result with `registered: 0`.

## Implementation Notes

### `discover_repos`

```python
async def discover_repos(root_path: Path) -> list[dict]:
    """Walk root_path recursively, find directories containing .git/, return repo info."""
    repos = []
    seen_toplevel = set()
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache"}

    for dirpath, dirnames, filenames in os.walk(str(root_path)):
        # Prune directories we don't want to descend into
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]

        git_dir = Path(dirpath) / ".git"
        if git_dir.exists():
            # Deduplicate via git rev-parse --show-toplevel
            stdout, _, rc = await run_git(dirpath, "rev-parse", "--show-toplevel")
            if rc == 0:
                toplevel = Path(stdout).resolve()
                if str(toplevel) not in seen_toplevel:
                    seen_toplevel.add(str(toplevel))
                    repos.append({
                        "path": str(toplevel),
                        "name": toplevel.name,
                    })
            # Don't descend further into this repo's subdirectories
            dirnames.clear()

    return repos
```

Important: `os.walk` is synchronous. Since directory walking is I/O-bound but not CPU-heavy, and we need `await run_git` for deduplication, use `asyncio.to_thread(os.walk, ...)` or convert to an async-compatible pattern. Simplest approach: collect candidate directories synchronously first (just check for `.git/` existence), then async-deduplicate with `run_git`.

### Repo ID Generation

```python
import hashlib

def generate_repo_id(absolute_path: str) -> str:
    return hashlib.sha256(absolute_path.encode()).hexdigest()[:16]
```

### Runtime Detection

Check files in priority order per spec section 3.4. Key logic:

```python
def detect_runtime(repo_path: Path) -> str:
    checks = [
        (["pyproject.toml"], "python"),
        (["requirements.txt"], "python"),
        (["setup.py", "setup.cfg"], "python"),
        (["package.json"], "node"),
        (["go.mod"], "go"),
        (["Cargo.toml"], "rust"),
        (["Gemfile"], "ruby"),
        (["composer.json"], "php"),
        (["Dockerfile", "docker-compose.yml"], "docker"),
    ]
    found = set()
    for files, runtime in checks:
        # Case-insensitive on Windows
        for f in files:
            if (repo_path / f).exists() or any(
                p.name.lower() == f.lower() for p in repo_path.iterdir() if p.is_file()
            ):
                found.add(runtime)
                break

    if len(found) > 1:
        # Filter out 'docker' from mixed classification — it's a packaging concern, not a runtime
        runtimes = found - {"docker"}
        if len(runtimes) > 1:
            return "mixed"
        elif len(runtimes) == 1:
            return runtimes.pop()
    if len(found) == 1:
        return found.pop()

    # Check for shell-heavy or html
    # ... (simplified for spec; implement per section 3.4 priority 10–12)
    return "unknown"
```

For Windows compatibility: use `path.name.lower()` when matching filenames (spec section 3.4 note).

### Default Branch Detection

```python
async def get_default_branch(repo_path: Path) -> str:
    stdout, _, rc = await run_git(repo_path, "symbolic-ref", "--short", "HEAD")
    if rc == 0 and stdout:
        return stdout
    return "main"  # fallback
```

### Database Insert

```python
async def register_repo(db, repo_info: dict) -> dict:
    repo_id = generate_repo_id(repo_info["path"])
    await db.execute(
        """INSERT OR IGNORE INTO repositories (id, name, path, default_branch, runtime, added_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (repo_id, repo_info["name"], repo_info["path"],
         repo_info["default_branch"], repo_info["runtime"],
         datetime.now(timezone.utc).isoformat())
    )
    await db.commit()
    return {"id": repo_id, "name": repo_info["name"], "path": repo_info["path"]}
```

Use `INSERT OR IGNORE` for idempotency (path has UNIQUE constraint).

### `--scan` CLI flag

In the startup sequence (after schema init, before uvicorn), if `args.scan` is set:
```python
if args.scan:
    repos = await discover_repos(Path(args.scan))
    for repo_info in repos:
        await register_repo(db, repo_info)
    print(f"Registered {len(repos)} repos from {args.scan}")
```

### Path Normalization

Always use `Path(path).resolve()` to normalize paths before storing. This handles:
- Relative paths → absolute
- `~` expansion (use `Path(path).expanduser().resolve()`)
- Symlink resolution
- OS-native separators

On Windows, if `Path.resolve()` fails (symlinks without dev mode), catch `OSError` and use the unresolved path.

## Acceptance Criteria

1. `discover_repos()` correctly finds git repos in a directory tree.
2. `discover_repos()` skips `.git`, `node_modules`, `.venv`, and hidden directories.
3. `discover_repos()` deduplicates submodules using `git rev-parse --show-toplevel`.
4. `detect_runtime()` correctly classifies repos by their ecosystem files, including "mixed".
5. `POST /api/repos` accepts a directory path, discovers repos, and returns the list.
6. `POST /api/repos` is idempotent — registering the same directory twice doesn't create duplicates.
7. `DELETE /api/repos/{id}` removes the repo and cascading data, returns 204.
8. `DELETE /api/repos/{nonexistent_id}` returns 404.
9. The `--scan` CLI flag registers repos from the specified directory on startup.
10. Repo IDs are deterministic (same path → same ID).
11. All tests pass.

## Validation Focus Areas

- **Submodule deduplication**: The spec explicitly calls this out (section 9). Verify that a repo-inside-a-repo only registers the outer one unless the inner one has a different `--show-toplevel`.
- **Runtime detection edge cases**: mixed repos (multiple ecosystem files), case-insensitive matching on Windows.
- **Path normalization**: verify `Path.resolve()` is used everywhere, and both Windows-style and Unix-style paths work in the POST body.
- **Idempotency**: registering the same directory multiple times must not create duplicate rows.
- **CASCADE delete**: verify that deleting a repo removes its `working_state`, `daily_stats`, `branches`, `dependencies`, and `scan_log` references.
