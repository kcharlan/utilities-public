# Packet 13: Python Dep Health (Outdated + Vuln)

## Why This Packet Exists

Packet 12 established dependency detection and parsing for all ecosystems. This packet adds the first health-check capability: determining whether Python packages are outdated (via the PyPI JSON API) and vulnerable (via `pip-audit`). Python is the highest-priority ecosystem to implement first because no external CLI tools are required for the outdated check — only an HTTP call to PyPI per package.

## Scope

- `check_python_outdated(deps: list[dict]) -> list[dict]` — for each parsed Python dep with a pinned `==` version, query the PyPI JSON API (`https://pypi.org/pypi/{name}/json`) to get the latest version. Compare using `packaging.version.parse()`. Return an updated copy of each dep dict with `latest_version`, `wanted_version`, and `severity` fields populated.
- `check_python_vulns(repo_path: Path, deps: list[dict]) -> list[dict]` — if `pip-audit` is available (via `TOOLS["pip_audit"]`), run `pip-audit --requirement <manifest> --format json` and parse the output. Merge vulnerability info (advisory IDs, severity escalation) into the dep dicts.
- `classify_severity(current: str, latest: str) -> str` — shared helper that compares two version strings and returns `"major"` (different major version), `"outdated"` (any other version difference), or `"ok"` (same version). Uses `packaging.version.parse()`.
- `check_python_deps(repo_path: Path, deps: list[dict]) -> list[dict]` — orchestrator that runs outdated check, then vuln check, merges results, and returns final dep list with all health fields populated.

## Non-Goals

- Writing results to the `dependencies` table — packet 16 (Dep Scan Orchestration)
- API endpoints for deps — packet 17
- UI for deps — packet 17
- Node/Go/Rust/Ruby/PHP health checks — packets 14–15
- Checking transitive dependencies (only declared deps from manifests)
- Caching PyPI responses across runs (future enhancement)
- Integration with the full scan orchestration loop — packet 16

## Relevant Design Doc Sections

- §3.5 Dependency Health Check — per-ecosystem tooling table, severity classification, Python details (lines 310–326), fallback behavior (lines 409–418)
- §3.5 Cross-Platform Notes — `shutil.which("pip-audit")` detection (lines 400–407)
- §2.1 Startup Preflight Checks — pip-audit tool detection (line 39)

## Allowed Files

- `git_dashboard.py`
- `tests/test_python_dep_health.py`

## Tests to Write First

### classify_severity Tests

1. **classify_severity — same version**: `classify_severity("2.3.0", "2.3.0")` → `"ok"`.

2. **classify_severity — minor update**: `classify_severity("2.1.0", "2.3.0")` → `"outdated"`.

3. **classify_severity — major update**: `classify_severity("2.3.0", "3.0.0")` → `"major"`.

4. **classify_severity — patch update**: `classify_severity("2.3.0", "2.3.1")` → `"outdated"`.

5. **classify_severity — pre-release latest**: `classify_severity("2.3.0", "3.0.0rc1")` → still `"major"` (major version differs).

### check_python_outdated Tests

6. **check_python_outdated — single dep, up-to-date** (mock PyPI): Dep `{"name": "flask", "version": "3.0.0", "manager": "pip"}`. Mock PyPI response `info.version = "3.0.0"`. Assert result has `latest_version="3.0.0"`, `severity="ok"`.

7. **check_python_outdated — single dep, outdated minor** (mock PyPI): Dep `{"name": "requests", "version": "2.28.0", "manager": "pip"}`. Mock PyPI `info.version = "2.31.0"`. Assert `latest_version="2.31.0"`, `severity="outdated"`.

8. **check_python_outdated — single dep, major update** (mock PyPI): Dep `{"name": "django", "version": "3.2.0", "manager": "pip"}`. Mock PyPI `info.version = "5.0.0"`. Assert `latest_version="5.0.0"`, `severity="major"`.

9. **check_python_outdated — dep with no pinned version**: Dep `{"name": "flask", "version": None, "manager": "pip"}`. Assert skipped — `latest_version` remains `None`, `severity` stays `"ok"`.

10. **check_python_outdated — PyPI network error** (mock raises): Mock `urllib.request.urlopen` to raise `URLError`. Assert dep gets `severity="ok"`, no crash, `latest_version=None`.

11. **check_python_outdated — PyPI returns invalid JSON** (mock): Mock response with non-JSON body. Assert no crash, dep retains `severity="ok"`.

12. **check_python_outdated — multiple deps, mixed results** (mock): 3 deps: one up-to-date, one outdated, one major. Assert each gets the correct severity independently.

### check_python_vulns Tests

13. **check_python_vulns — pip-audit not available**: `TOOLS["pip_audit"]` is `None`. Assert deps returned unchanged (no vuln data added).

14. **check_python_vulns — pip-audit finds vulnerabilities** (mock subprocess): Mock `pip-audit` JSON output with one vulnerable package. Assert that dep's `severity` is escalated to `"vulnerable"` and `advisory_id` is set.

15. **check_python_vulns — pip-audit finds no vulnerabilities** (mock subprocess): Mock `pip-audit` JSON output with empty vulns list. Assert deps unchanged.

16. **check_python_vulns — pip-audit subprocess fails** (mock): Mock `subprocess.run` raising `subprocess.CalledProcessError`. Assert no crash, deps returned unchanged.

17. **check_python_vulns — pip-audit returns unexpected JSON** (mock): Mock output with unexpected structure. Assert no crash, deps returned unchanged.

18. **check_python_vulns — vuln overrides outdated severity**: Dep already has `severity="outdated"` from outdated check. pip-audit reports a vuln for that dep. Assert final `severity="vulnerable"` (vuln takes priority).

### check_python_deps Orchestrator Tests

19. **check_python_deps — full pipeline** (mock PyPI + mock pip-audit): 2 deps, one outdated and one vulnerable. Assert final list has correct severities and advisory IDs.

20. **check_python_deps — no pip-audit available, outdated check still works** (mock PyPI): Assert outdated severity is computed even when pip-audit is missing.

21. **check_python_deps — empty dep list**: Pass `[]`. Assert returns `[]`.

## Implementation Notes

### classify_severity(current_version: str, latest_version: str) -> str

```python
from packaging.version import parse as parse_version

def classify_severity(current: str, latest: str) -> str:
    cur = parse_version(current)
    lat = parse_version(latest)
    if cur >= lat:
        return "ok"
    if cur.major != lat.major:
        return "major"
    return "outdated"
```

This function is ecosystem-agnostic and will be reused by packets 14–15. Place it near the dep-parsing functions (after `parse_deps_for_repo`).

### check_python_outdated(deps: list[dict]) -> list[dict]

For each dep where `dep["version"]` is not `None` and `dep["manager"] == "pip"`:
1. Attempt to extract an exact version. If `dep["version"]` contains `==`, split on `==` and take the right side. If it's already a bare version string (from parsing), use it directly. If the version string contains range operators (`>=`, `~=`, `<`, `!=`), skip the outdated check for that dep (can't determine current installed version from a range).
2. Query `https://pypi.org/pypi/{name}/json` using `urllib.request.urlopen` (stdlib — no `requests` or `httpx` needed).
3. Parse JSON response: `json.loads(response.read())["info"]["version"]` gives the latest stable version.
4. Call `classify_severity(current, latest)` to set severity.
5. Set `latest_version` and `wanted_version` (for pip, `wanted_version == current_version` since pip doesn't have a "wanted" concept like npm).

**Error handling**: Wrap each PyPI call in try/except. On any failure (network, JSON parse, key error), log a warning and leave that dep as `severity="ok"`, `latest_version=None`. Never let one failed lookup block the others.

**Rate limiting**: PyPI has no strict rate limit for its JSON API, but be respectful. Use sequential requests (no asyncio — these are blocking calls in the scan worker). For repos with many deps, this is acceptable since scans run in the background.

### check_python_vulns(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("pip_audit")`. If `None`, return deps unchanged.
2. Find the manifest file in `repo_path` — look for `requirements.txt` or `pyproject.toml` (in priority order). pip-audit accepts `--requirement` for requirements.txt.
3. Run: `subprocess.run([pip_audit_path, "--requirement", manifest_path, "--format", "json"], capture_output=True, text=True, timeout=120)`.
4. Parse JSON output. Shape: `{"dependencies": [{"name": "pkg", "version": "1.0", "vulns": [{"id": "CVE-...", ...}]}]}`.
5. Build a lookup dict: `{name: first_vuln_id}` for packages that have non-empty `vulns`.
6. For each dep in the input list: if the dep's name appears in the vuln lookup, set `severity = "vulnerable"` and `advisory_id = vuln_id`. This overrides any prior severity (vuln > major > outdated > ok).

**Fallback for pyproject.toml**: pip-audit supports `--requirement` only for requirements.txt-style files. If the project only has `pyproject.toml`, skip the vuln check (pip-audit does not natively support pyproject.toml without installing the project). Log a warning.

**Error handling**: Wrap the entire subprocess call in try/except. On any failure (timeout, non-zero exit, parse error), log a warning and return deps unchanged.

### check_python_deps(repo_path: Path, deps: list[dict]) -> list[dict]

Orchestrator:
1. Filter `deps` to only those with `manager == "pip"`.
2. Run `check_python_outdated(pip_deps)`.
3. Run `check_python_vulns(repo_path, pip_deps)`.
4. Return the updated list. Non-pip deps are returned unchanged.

### Data Flow

Input (from packet 12 parsers):
```python
{"name": "flask", "version": "2.3.0", "manager": "pip"}
```

Output (after this packet):
```python
{
    "name": "flask",
    "version": "2.3.0",        # original declared version
    "manager": "pip",
    "current_version": "2.3.0", # same as version for pip
    "wanted_version": "2.3.0",  # same as current for pip
    "latest_version": "3.0.0",  # from PyPI
    "severity": "major",        # classified by version comparison
    "advisory_id": None,        # or "CVE-..." if vulnerable
    "checked_at": "2026-03-10T..."  # ISO timestamp
}
```

This enriched dict maps directly to the `dependencies` table columns for later upsert in packet 16.

## Acceptance Criteria

1. `classify_severity()` correctly returns `"ok"` for same versions.
2. `classify_severity()` correctly returns `"outdated"` for same-major different-minor/patch.
3. `classify_severity()` correctly returns `"major"` for different major versions.
4. `check_python_outdated()` queries PyPI for each pinned dep and sets `latest_version`.
5. `check_python_outdated()` skips deps with `version=None` (unpinned).
6. `check_python_outdated()` handles PyPI network errors gracefully (no crash, dep stays `"ok"`).
7. `check_python_outdated()` handles invalid PyPI JSON gracefully (no crash).
8. `check_python_vulns()` skips gracefully when pip-audit is not installed.
9. `check_python_vulns()` parses pip-audit JSON output and sets `severity="vulnerable"` + `advisory_id`.
10. `check_python_vulns()` handles pip-audit subprocess failures gracefully (no crash).
11. Vulnerability severity overrides outdated/major severity (vuln is highest priority).
12. `check_python_deps()` orchestrates both checks and returns enriched dep dicts.
13. `check_python_deps()` works correctly when only outdated check is available (no pip-audit).
14. `check_python_deps()` returns `[]` for empty input.
15. All enriched dep dicts contain the fields: `name`, `version`, `manager`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`, `checked_at`.
16. All existing tests (235 from prior packets) still pass (no regressions).

## Validation Focus Areas

- **PyPI API mocking**: All tests must mock HTTP calls — no real network access during tests. Use `unittest.mock.patch` on `urllib.request.urlopen`.
- **pip-audit mocking**: All tests must mock `subprocess.run` — never run real pip-audit during tests.
- **Severity escalation**: Carefully verify that `vulnerable > major > outdated > ok` ordering is respected when both outdated and vuln checks produce results for the same dep.
- **Version parsing edge cases**: Verify `packaging.version.parse()` handles common PyPI version formats (PEP 440): `1.0`, `1.0.0`, `1.0rc1`, `1.0.post1`, `1.0.dev1`.
- **No DB writes**: This packet only produces enriched dicts. Verify no database operations are introduced.
- **Global state**: Verify that `TOOLS` dict is accessed (not hardcoded) for pip-audit path detection.
- **Regression**: All prior 235 tests pass without modification.
