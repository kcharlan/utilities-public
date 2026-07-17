# Packet 14: Node Dep Health (Outdated + Vuln)

## Why This Packet Exists

With Python dep health in packet 13, this packet adds the second ecosystem: Node.js. Unlike Python (which uses a per-package HTTP API for outdated checks), Node relies entirely on CLI tools — `npm outdated --json` for outdated detection and `npm audit --json` for vulnerability scanning. Both require `npm` to be installed and run in the repo's directory. This packet reuses the `classify_severity()` helper introduced in packet 13.

## Scope

- `check_node_outdated(repo_path: Path, deps: list[dict]) -> list[dict]` — if `npm` is available (via `TOOLS["npm"]`), run `npm outdated --json` in the repo directory, parse the JSON output, and enrich each dep with `current_version`, `wanted_version`, `latest_version`, and `severity`.
- `check_node_vulns(repo_path: Path, deps: list[dict]) -> list[dict]` — if `npm` is available, run `npm audit --json` in the repo directory, parse the JSON output, and merge vulnerability info (advisory IDs, severity escalation to `"vulnerable"`) into the dep dicts.
- `check_node_deps(repo_path: Path, deps: list[dict]) -> list[dict]` — orchestrator that runs outdated check, then vuln check, merges results, and returns final dep list with all health fields populated.

## Non-Goals

- Writing results to the `dependencies` table — packet 16
- API endpoints for deps — packet 17
- UI for deps — packet 17
- Python health checks — packet 13 (already planned)
- Go/Rust/Ruby/PHP health checks — packet 15
- Installing `node_modules` or running `npm install` for the user
- Parsing `package-lock.json` (only `package.json` from packet 12)
- Integration with the full scan orchestration loop — packet 16

## Relevant Design Doc Sections

- §3.5 Dependency Health Check — per-ecosystem tooling table, severity classification (lines 297–308), Node details (lines 328–344), fallback behavior (lines 409–418)
- §3.5 Cross-Platform Notes — `shutil.which("npm")`, Windows `npm.cmd` (lines 400–407)
- §2.1 Startup Preflight Checks — npm tool detection (line 38)

## Allowed Files

- `git_dashboard.py`
- `tests/test_node_dep_health.py`

## Tests to Write First

### check_node_outdated Tests

1. **check_node_outdated — npm not available**: `TOOLS["npm"]` is `None`. Assert deps returned unchanged (no health data added).

2. **check_node_outdated — single dep, up-to-date** (mock subprocess): Mock `npm outdated --json` returns `{}` (empty = all up to date). Dep `{"name": "react", "version": "^18.2.0", "manager": "npm"}`. Assert `severity="ok"`.

3. **check_node_outdated — single dep, outdated minor** (mock subprocess): Mock `npm outdated --json` returns `{"react": {"current": "18.2.0", "wanted": "18.3.1", "latest": "18.3.1"}}`. Assert `current_version="18.2.0"`, `wanted_version="18.3.1"`, `latest_version="18.3.1"`, `severity="outdated"`.

4. **check_node_outdated — single dep, major update** (mock subprocess): Mock returns `{"express": {"current": "4.18.0", "wanted": "4.21.0", "latest": "5.0.0"}}`. Assert `latest_version="5.0.0"`, `severity="major"`.

5. **check_node_outdated — multiple deps, mixed results** (mock): 3 deps: one up-to-date (not in npm outdated output), one outdated, one major. Assert each gets correct severity.

6. **check_node_outdated — npm subprocess fails** (mock): Mock `subprocess.run` raising `CalledProcessError`. Assert no crash, deps returned unchanged.

7. **check_node_outdated — npm returns invalid JSON** (mock): Mock stdout with non-JSON. Assert no crash, deps returned unchanged.

8. **check_node_outdated — npm outdated exit code 1** (mock): `npm outdated` exits with code 1 when outdated deps exist (this is normal npm behavior). Assert the output is still parsed correctly despite non-zero exit code.

9. **check_node_outdated — dep not in npm outdated output**: Dep exists in parsed list but not in npm outdated output (meaning it's up to date). Assert `severity="ok"`, `latest_version` set to current if available.

### check_node_vulns Tests

10. **check_node_vulns — npm not available**: `TOOLS["npm"]` is `None`. Assert deps returned unchanged.

11. **check_node_vulns — no vulnerabilities** (mock subprocess): Mock `npm audit --json` returns `{"vulnerabilities": {}}`. Assert deps unchanged.

12. **check_node_vulns — one vulnerable dep** (mock subprocess): Mock `npm audit --json` returns `{"vulnerabilities": {"lodash": {"severity": "high", "via": [{"source": 1234, "name": "lodash", "title": "Prototype Pollution"}], "fixAvailable": true}}}`. Assert `severity="vulnerable"`, `advisory_id` set.

13. **check_node_vulns — vuln overrides outdated**: Dep already has `severity="outdated"` from outdated check. npm audit reports a vuln for that dep. Assert final `severity="vulnerable"`.

14. **check_node_vulns — npm audit subprocess fails** (mock): Mock raises `CalledProcessError`. Assert no crash, deps returned unchanged.

15. **check_node_vulns — npm audit returns unexpected JSON** (mock): Mock output missing `vulnerabilities` key. Assert no crash, deps returned unchanged.

16. **check_node_vulns — npm audit no lockfile** (mock): `npm audit` fails because no `package-lock.json` exists. Assert graceful fallback, deps returned unchanged.

### check_node_deps Orchestrator Tests

17. **check_node_deps — full pipeline** (mock subprocess for both): 2 deps, one outdated and one vulnerable. Assert final list has correct severities and advisory IDs.

18. **check_node_deps — npm not available, all checks skipped**: `TOOLS["npm"]` is `None`. Assert deps returned with no health data, no crash.

19. **check_node_deps — empty dep list**: Pass `[]`. Assert returns `[]`.

20. **check_node_deps — enriched output shape**: Assert all returned dicts contain fields: `name`, `version`, `manager`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`, `checked_at`.

## Implementation Notes

### check_node_outdated(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("npm")`. If `None`, return deps unchanged (each dep gets default health fields: `severity="ok"`, `latest_version=None`, etc.).
2. Run: `subprocess.run([npm_path, "outdated", "--json"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
3. **Important**: `npm outdated` exits with code 1 when outdated packages exist. This is NOT an error. Check `stdout` regardless of return code. Only treat it as a failure if `stdout` is empty or unparseable.
4. Parse JSON output. Shape: `{"pkg_name": {"current": "1.0.0", "wanted": "1.0.5", "latest": "2.0.0", "dependent": "myapp"}, ...}`.
5. Build a lookup dict from the output keyed by package name.
6. For each dep in the input list:
   - If the dep's `name` appears in the outdated output: set `current_version` from `current`, `wanted_version` from `wanted`, `latest_version` from `latest`. Call `classify_severity(current, latest)` to set severity.
   - If the dep's `name` is NOT in the outdated output: it's up to date. Set `severity="ok"`. Leave `current_version` as the declared version from `package.json` if available.
7. Set `checked_at` to current ISO timestamp for all processed deps.

**Error handling**: Wrap the subprocess call in try/except. On timeout, `CalledProcessError` with empty stdout, or JSON parse failure, log a warning and return deps with default health fields.

### check_node_vulns(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("npm")`. If `None`, return deps unchanged.
2. Run: `subprocess.run([npm_path, "audit", "--json"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
3. **Important**: `npm audit` also exits with non-zero codes when vulnerabilities exist. Parse `stdout` regardless of exit code.
4. Parse JSON output. Shape: `{"vulnerabilities": {"pkg_name": {"severity": "high"|"moderate"|"low"|"critical", "via": [...], "fixAvailable": bool}, ...}}`.
5. Build a vuln lookup: `{name: severity_string}` for each entry in `vulnerabilities`.
6. For each dep in the input list: if the dep's name appears in the vuln lookup, set `severity = "vulnerable"` and `advisory_id = f"npm:{name}"` (npm audit doesn't provide CVE IDs directly in the top-level structure; use the npm advisory reference). Vulnerability overrides any prior severity.

**Fallback**: If `npm audit` fails (common when no `package-lock.json` exists — npm audit requires a lockfile), catch the error and skip vuln scanning. The outdated check (which doesn't need a lockfile) still provides value.

### check_node_deps(repo_path: Path, deps: list[dict]) -> list[dict]

Orchestrator:
1. Filter `deps` to only those with `manager == "npm"`.
2. Run `check_node_outdated(repo_path, npm_deps)`.
3. Run `check_node_vulns(repo_path, npm_deps)`.
4. Return the updated list. Non-npm deps are returned unchanged.

### Data Flow

Input (from packet 12 parsers):
```python
{"name": "react", "version": "^18.2.0", "manager": "npm"}
```

Output (after this packet):
```python
{
    "name": "react",
    "version": "^18.2.0",       # original declared version from package.json
    "manager": "npm",
    "current_version": "18.2.0", # from npm outdated (actual installed)
    "wanted_version": "18.3.1",  # highest satisfying declared range
    "latest_version": "18.3.1",  # latest on registry
    "severity": "outdated",      # classified by current vs latest
    "advisory_id": None,         # or "npm:lodash" if vulnerable
    "checked_at": "2026-03-10T..."
}
```

### Key Difference from Python (Packet 13)

- Python's outdated check queries PyPI per-package (HTTP). Node's outdated check runs `npm outdated --json` once for the entire repo (subprocess).
- Python's `wanted_version == current_version` (pip doesn't have a "wanted" concept). Node's `wanted_version` comes directly from npm's semver resolution.
- Node requires `npm` CLI to be installed for ALL checks. Python's outdated check uses only stdlib HTTP.
- `npm outdated` and `npm audit` both use non-zero exit codes for "there are issues" — this is normal behavior, not an error.

### npm Exit Code Handling

Both `npm outdated` and `npm audit` exit with code 1 when they find issues (outdated packages or vulnerabilities, respectively). The implementation MUST NOT treat exit code 1 as a fatal error. Instead:
- Run with `subprocess.run(...)` (not `check=True`).
- Check if `stdout` contains valid JSON.
- Only treat as error if stdout is empty/unparseable AND the return code is non-zero.

## Acceptance Criteria

1. `check_node_outdated()` skips gracefully when npm is not available (returns deps unchanged).
2. `check_node_outdated()` correctly parses `npm outdated --json` output and sets `current_version`, `wanted_version`, `latest_version`.
3. `check_node_outdated()` uses `classify_severity()` to set severity from current vs latest version.
4. `check_node_outdated()` handles `npm outdated` exit code 1 correctly (parses output, doesn't crash).
5. `check_node_outdated()` handles subprocess failures gracefully (no crash).
6. `check_node_outdated()` handles invalid JSON output gracefully (no crash).
7. `check_node_vulns()` skips gracefully when npm is not available.
8. `check_node_vulns()` parses `npm audit --json` output and sets `severity="vulnerable"` + `advisory_id`.
9. `check_node_vulns()` handles npm audit failures gracefully (e.g., no lockfile).
10. Vulnerability severity overrides outdated/major severity.
11. `check_node_deps()` orchestrates both checks and returns enriched dep dicts.
12. `check_node_deps()` returns `[]` for empty input.
13. All enriched dep dicts contain the fields: `name`, `version`, `manager`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`, `checked_at`.
14. `classify_severity()` from packet 13 is reused (not reimplemented).
15. All existing tests (235+ from prior packets, plus packet 13 tests) still pass (no regressions).

## Validation Focus Areas

- **Subprocess mocking**: All tests must mock `subprocess.run` — never run real `npm` during tests. Use `unittest.mock.patch`.
- **Exit code handling**: Verify that non-zero exit codes from `npm outdated` and `npm audit` are handled correctly (output is still parsed).
- **Severity escalation**: Verify that `vulnerable > major > outdated > ok` ordering is respected when both outdated and vuln checks produce results for the same dep.
- **classify_severity reuse**: Verify the function from packet 13 is imported/called, not duplicated.
- **npm audit lockfile fallback**: Verify behavior when `npm audit` fails due to missing `package-lock.json` — should degrade gracefully, outdated check still works.
- **No DB writes**: This packet only produces enriched dicts. Verify no database operations are introduced.
- **TOOLS dict access**: Verify that `TOOLS["npm"]` is checked (not hardcoded path).
- **Regression**: All prior tests pass without modification.
