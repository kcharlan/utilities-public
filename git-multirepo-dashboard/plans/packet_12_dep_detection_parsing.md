# Packet 12: Dependency Detection & Parsing

## Why This Packet Exists

Dependency health is a core feature of Git Fleet (§3.4–3.5). Before we can check whether packages are outdated or vulnerable (packets 13–15), we need to detect which manifest files exist in each repo and parse them to extract dependency names and versions. This packet is pure logic — no API endpoints, no UI, no network calls.

## Scope

- `detect_dep_files(repo_path)` — scan a repo directory for known manifest files, return a list of `{file, manager, runtime}` dicts ordered by detection priority
- `parse_requirements_txt(file_path)` — parse `pkg==version` lines, handle comments, blank lines, `-e` editable installs (skip), and `-r includes` (follow one level, skip circular)
- `parse_pyproject_toml(file_path)` — parse `[project].dependencies` and/or `[tool.poetry.dependencies]`
- `parse_package_json(file_path)` — parse `dependencies` and `devDependencies` objects
- `parse_go_mod(file_path)` — parse `require (...)` block, extract `module vX.Y.Z` lines
- `parse_cargo_toml(file_path)` — parse `[dependencies]` section, handle both `name = "version"` and `name = { version = "..." }` forms
- `parse_gemfile(file_path)` — parse `gem 'name', '~> version'` lines with basic regex
- `parse_composer_json(file_path)` — parse `require` and `require-dev` objects
- `parse_deps_for_repo(repo_path)` — orchestrator that calls `detect_dep_files` then the appropriate parsers, returns a merged list of `{name, version, manager}` dicts
- Each parser returns a list of `{name: str, version: str | None, manager: str}` dicts

## Non-Goals

- Health checks (outdated/vulnerability) — packets 13–15
- Writing parsed deps to the `dependencies` table — packet 16
- API endpoints for deps — packet 17
- UI for deps — packet 17
- Network calls to package registries (PyPI, npm, etc.)
- Parsing lockfiles (package-lock.json, Pipfile.lock, Cargo.lock, etc.)
- Resolving transitive dependencies
- Modifying `detect_runtime()` — it already handles runtime classification; this packet adds dep-file detection alongside it

## Relevant Design Doc Sections

- §3.4 Dependency Detection — file detection priority table, runtime classification, mixed-ecosystem handling, cross-platform notes
- §3.5 Dependency Health Check — per-ecosystem tooling overview (context only; health checks are NOT in this packet)
- §9 Edge Cases — `requirements.txt` with `-r` includes, mixed-ecosystem repos

## Allowed Files

- `git_dashboard.py`
- `tests/test_dep_detection_parsing.py`

## Tests to Write First

### Detection Tests

1. **detect_dep_files — single Python (requirements.txt)**: Create a temp dir with `requirements.txt`; assert returns `[{file: "requirements.txt", manager: "pip", runtime: "python"}]`.

2. **detect_dep_files — single Python (pyproject.toml)**: Create a temp dir with `pyproject.toml`; assert returns `[{file: "pyproject.toml", manager: "pip", runtime: "python"}]`.

3. **detect_dep_files — single Node**: Create a temp dir with `package.json`; assert returns `[{file: "package.json", manager: "npm", runtime: "node"}]`.

4. **detect_dep_files — single Go**: Temp dir with `go.mod`; assert manager `gomod`, runtime `go`.

5. **detect_dep_files — single Rust**: Temp dir with `Cargo.toml`; assert manager `cargo`, runtime `rust`.

6. **detect_dep_files — single Ruby**: Temp dir with `Gemfile`; assert manager `bundler`, runtime `ruby`.

7. **detect_dep_files — single PHP**: Temp dir with `composer.json`; assert manager `composer`, runtime `php`.

8. **detect_dep_files — mixed ecosystem**: Temp dir with both `pyproject.toml` and `package.json`; assert returns both entries (pip and npm).

9. **detect_dep_files — no manifest files**: Empty temp dir; assert returns `[]`.

10. **detect_dep_files — priority order**: Temp dir with both `pyproject.toml` and `requirements.txt`; assert `pyproject.toml` appears first (higher priority).

### Parser Tests — requirements.txt

11. **parse_requirements_txt — basic**: File with `flask==2.3.0\nrequests==2.31.0`; assert returns 2 deps with correct names and versions.

12. **parse_requirements_txt — comments and blanks**: File with `# comment\n\nflask==2.3.0\n  # indented comment`; assert returns 1 dep.

13. **parse_requirements_txt — unpinned**: File with `flask\nrequests>=2.0`; assert returns deps with version `None` for unpinned, version string for constrained.

14. **parse_requirements_txt — editable installs skipped**: File with `-e ./local_pkg\nflask==2.3.0`; assert returns 1 dep (flask only).

15. **parse_requirements_txt — -r include (one level)**: Main file has `-r other.txt\nflask==2.3.0`; `other.txt` has `requests==2.31.0`; assert returns both deps.

16. **parse_requirements_txt — -r circular include**: Main file has `-r other.txt`; `other.txt` has `-r requirements.txt`; assert no infinite loop, returns deps from both without error.

### Parser Tests — pyproject.toml

17. **parse_pyproject_toml — [project].dependencies**: Standard PEP 621 format; assert extracts package names and versions.

18. **parse_pyproject_toml — [tool.poetry.dependencies]**: Poetry format; assert extracts package names and versions.

19. **parse_pyproject_toml — no dependencies section**: Valid TOML with no dependency keys; assert returns `[]`.

### Parser Tests — package.json

20. **parse_package_json — deps and devDeps**: File with both sections; assert all deps returned with correct manager `npm`.

21. **parse_package_json — no dependencies key**: File with only `name` and `version`; assert returns `[]`.

22. **parse_package_json — version ranges**: Versions like `^1.2.3`, `~2.0.0`, `>=3.0.0`; assert version strings preserved as-is.

### Parser Tests — go.mod

23. **parse_go_mod — require block**: Standard `require (...)` block with multiple entries; assert extracts module paths and versions.

24. **parse_go_mod — single require**: `require github.com/pkg/errors v0.9.1` (no parens); assert parsed correctly.

25. **parse_go_mod — indirect deps**: Lines with `// indirect` comment; assert still parsed (they're still deps).

### Parser Tests — Cargo.toml

26. **parse_cargo_toml — string versions**: `serde = "1.0"` format; assert returns correct name/version.

27. **parse_cargo_toml — table versions**: `serde = { version = "1.0", features = ["derive"] }` format; assert returns correct name/version.

28. **parse_cargo_toml — no dependencies section**: Valid TOML with no `[dependencies]`; assert returns `[]`.

### Parser Tests — Gemfile

29. **parse_gemfile — basic gems**: `gem 'rails', '~> 7.0'\ngem 'puma', '>= 5.0'`; assert returns 2 deps.

30. **parse_gemfile — no version constraint**: `gem 'rake'`; assert returns dep with version `None`.

### Parser Tests — composer.json

31. **parse_composer_json — require and require-dev**: Both sections present; assert all deps returned.

32. **parse_composer_json — no require key**: Assert returns `[]`.

### Orchestrator Test

33. **parse_deps_for_repo — Python repo**: Temp dir with `requirements.txt` containing deps; assert `parse_deps_for_repo` returns merged list with manager `pip`.

34. **parse_deps_for_repo — mixed repo**: Temp dir with `requirements.txt` and `package.json`; assert returns deps from both with correct managers.

35. **parse_deps_for_repo — empty repo**: No manifest files; assert returns `[]`.

## Implementation Notes

### detect_dep_files(repo_path) → list[dict]

Scan the repo root for manifest files in priority order (§3.4):

| Priority | File | Manager | Runtime |
|---|---|---|---|
| 1 | `pyproject.toml` | `pip` | `python` |
| 2 | `requirements.txt` | `pip` | `python` |
| 3 | `package.json` | `npm` | `node` |
| 4 | `go.mod` | `gomod` | `go` |
| 5 | `Cargo.toml` | `cargo` | `rust` |
| 6 | `Gemfile` | `bundler` | `ruby` |
| 7 | `composer.json` | `composer` | `php` |

Use `pathlib.Path` for file existence checks. Use `path.name.lower()` for case-insensitive matching on Windows.

Return all detected files (not just the first match) — a repo can have multiple ecosystems. If both `pyproject.toml` and `requirements.txt` exist, return only `pyproject.toml` (higher priority for the same ecosystem). But if `pyproject.toml` and `package.json` both exist, return both (different ecosystems).

**De-duplication rule**: Within the same runtime, only the highest-priority file is returned. Across different runtimes, all are returned.

### TOML Parsing

For `pyproject.toml` and `Cargo.toml`, use Python's `tomllib` (stdlib in 3.11+). Add a conditional import:

```python
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None
```

If `tomllib` is unavailable, the TOML parsers should return `[]` and log a warning. Do NOT add `tomli` to the bootstrap dependencies — `tomllib` is available in 3.11+ and that's the expected runtime.

### Parser Return Shape

All parsers return `list[dict]` where each dict has:
```python
{"name": "package-name", "version": "1.2.3" or None, "manager": "pip"|"npm"|"gomod"|"cargo"|"bundler"|"composer"}
```

- `version` is the declared/pinned version string as-is from the manifest (e.g., `"2.31.0"`, `"^1.2.3"`, `"~> 7.0"`). It is `None` if no version is specified.
- Version resolution/normalization happens later in health check packets.
- `manager` is set by the parser itself (each parser knows its own manager).

### requirements.txt Parsing Details

- Lines starting with `#` are comments → skip.
- Blank/whitespace-only lines → skip.
- Lines starting with `-e` or `--editable` → skip (editable installs).
- Lines starting with `-r` or `--requirement` → follow the include path relative to the file's directory. Track visited files to prevent circular includes. Follow at most one level (as spec says).
- Lines starting with other flags (`-i`, `--index-url`, `-f`, etc.) → skip.
- Package lines: match `name==version`, `name>=version`, `name~=version`, `name<=version`, `name!=version`, `name[extras]==version`. For `==` pins, extract the exact version. For other constraints or unpinned, set `version = None` (exact version unknown without resolution).

### pyproject.toml Parsing Details

- **PEP 621** (`[project].dependencies`): List of strings like `"flask>=2.0"`, `"requests==2.31.0"`. Parse each string to extract name and version constraint. Use regex: `^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)` for the package name, then look for `==X.Y.Z` for exact version.
- **Poetry** (`[tool.poetry.dependencies]`): Dict of `name: "^version"` or `name: {version: "^X.Y"}`. Extract name and version string.
- If both sections exist, prefer `[project].dependencies` (PEP 621 is the standard).

### go.mod Parsing Details

- Find `require (` block and parse lines until `)`.
- Also handle single-line `require module/path vX.Y.Z`.
- Each entry: module path and version. Strip `// indirect` comments.
- Exclude the module's own path (first `module` line in go.mod).

### Cargo.toml Parsing Details

- Parse `[dependencies]` and `[dev-dependencies]` sections via `tomllib`.
- Values can be: string (`"1.0"`) or table (`{version = "1.0", features = [...]}`).
- If value is a string, that's the version. If a table, extract the `version` key.

### Gemfile Parsing Details

- Match lines like: `gem 'name'`, `gem "name"`, `gem 'name', '~> 7.0'`, `gem 'name', '>= 5.0', '< 6.0'`.
- Use regex: `gem\s+['"]([^'"]+)['"]\s*(?:,\s*['"]([^'"]+)['"])?`.
- First capture = name, second capture (optional) = version constraint.

### composer.json Parsing Details

- JSON file. Parse `require` and `require-dev` objects.
- Keys are package names (e.g., `"laravel/framework"`), values are version constraints (e.g., `"^10.0"`).
- Skip `php` and `ext-*` entries (these are platform requirements, not packages).

## Acceptance Criteria

1. `detect_dep_files()` correctly identifies all 7 manifest file types.
2. `detect_dep_files()` returns only the highest-priority file per runtime (e.g., `pyproject.toml` over `requirements.txt` when both exist).
3. `detect_dep_files()` returns files for all detected runtimes in a mixed-ecosystem repo.
4. `detect_dep_files()` returns `[]` for repos with no manifest files.
5. `parse_requirements_txt()` extracts package names and pinned versions (`==` format).
6. `parse_requirements_txt()` skips comments, blanks, `-e` lines, and flag lines.
7. `parse_requirements_txt()` follows `-r` includes one level without circular loops.
8. `parse_pyproject_toml()` extracts deps from `[project].dependencies` (PEP 621).
9. `parse_pyproject_toml()` extracts deps from `[tool.poetry.dependencies]` (Poetry).
10. `parse_package_json()` extracts deps from both `dependencies` and `devDependencies`.
11. `parse_go_mod()` extracts module paths and versions from `require` blocks.
12. `parse_cargo_toml()` handles both string and table version formats.
13. `parse_gemfile()` extracts gem names and version constraints.
14. `parse_composer_json()` extracts deps from `require` and `require-dev`, skipping `php` and `ext-*`.
15. All parsers return the standard shape: `{name, version, manager}`.
16. `parse_deps_for_repo()` orchestrates detection and parsing, returning a merged list.
17. `parse_deps_for_repo()` returns `[]` for repos with no manifest files.
18. No TOML parsing failures crash the application — graceful degradation if `tomllib` unavailable.
19. All existing tests (178+ from prior packets) still pass (no regressions).

## Validation Focus Areas

- **requirements.txt edge cases**: Verify `-r` includes with relative paths, files that don't exist (should not crash), and circular references.
- **TOML availability**: Test behavior when `tomllib` is not available (should return `[]`, not crash). On Python 3.11+ this is unlikely but the fallback path should be exercised.
- **Version extraction accuracy**: For `==` pins the exact version should be extracted. For range constraints (`>=`, `~=`, `^`, `~>`), the raw constraint string should be preserved (not interpreted).
- **Mixed-ecosystem detection**: A repo with both `pyproject.toml` and `package.json` must return deps from both ecosystems.
- **Same-ecosystem de-duplication**: A repo with both `pyproject.toml` and `requirements.txt` must only parse `pyproject.toml` (higher priority).
- **No side effects**: These are pure parsing functions. They must not write to the DB, make network calls, or modify any files.
- **Regression**: All prior 178 tests pass without modification.
