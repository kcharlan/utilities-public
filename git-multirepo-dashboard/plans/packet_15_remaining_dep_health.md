# Packet 15: Go / Rust / Ruby / PHP Dep Health

## Why This Packet Exists

Packets 13 and 14 established health checks for Python (PyPI API + pip-audit) and Node (npm outdated/audit). This packet completes ecosystem coverage by adding health checks for the remaining four ecosystems: Go, Rust, Ruby, and PHP. Each follows the same orchestrator pattern (`check_{lang}_outdated` → `check_{lang}_vulns` → `check_{lang}_deps`) and reuses `classify_severity()` from packet 13.

## Scope

- `check_go_outdated(repo_path: Path, deps: list[dict]) -> list[dict]` — if `go` is available (via `TOOLS["go"]`), run `go list -m -u -json all` in the repo directory, parse the NDJSON output, and enrich each dep with `current_version`, `wanted_version`, `latest_version`, and `severity`.
- `check_go_vulns(repo_path: Path, deps: list[dict]) -> list[dict]` — if `govulncheck` is available (via `TOOLS["govulncheck"]`), run `govulncheck -json ./...` in the repo directory, parse the JSON output, and merge vulnerability info into dep dicts.
- `check_go_deps(repo_path: Path, deps: list[dict]) -> list[dict]` — orchestrator for Go.
- `check_rust_outdated(repo_path: Path, deps: list[dict]) -> list[dict]` — if `cargo-outdated` is available (via `TOOLS["cargo_outdated"]`), run `cargo outdated --format json` and enrich deps.
- `check_rust_vulns(repo_path: Path, deps: list[dict]) -> list[dict]` — if `cargo-audit` is available (via `TOOLS["cargo_audit"]`), run `cargo audit --json` and merge vulnerability info.
- `check_rust_deps(repo_path: Path, deps: list[dict]) -> list[dict]` — orchestrator for Rust.
- `check_ruby_outdated(repo_path: Path, deps: list[dict]) -> list[dict]` — if `bundle` is available (via `TOOLS["bundle"]`), run `bundle outdated --parseable` and parse line-by-line output.
- `check_ruby_vulns(repo_path: Path, deps: list[dict]) -> list[dict]` — if `bundler-audit` is available (via `TOOLS["bundler_audit"]`), run `bundle audit check --format json` and merge vulnerability info.
- `check_ruby_deps(repo_path: Path, deps: list[dict]) -> list[dict]` — orchestrator for Ruby.
- `check_php_outdated(repo_path: Path, deps: list[dict]) -> list[dict]` — if `composer` is available (via `TOOLS["composer"]`), run `composer outdated --format=json` and enrich deps.
- `check_php_vulns(repo_path: Path, deps: list[dict]) -> list[dict]` — if `composer` is available, run `composer audit --format=json` and merge vulnerability info.
- `check_php_deps(repo_path: Path, deps: list[dict]) -> list[dict]` — orchestrator for PHP.

## Non-Goals

- Writing results to the `dependencies` table — packet 16 (Dep Scan Orchestration)
- API endpoints for deps — packet 17
- UI for deps — packet 17
- Python health checks — packet 13 (done)
- Node health checks — packet 14 (done)
- Integration with the full scan orchestration loop — packet 16
- Installing missing tools for the user
- Checking transitive dependencies (only declared deps from manifests)

## Relevant Design Doc Sections

- §3.5 Dependency Health Check — per-ecosystem tooling table (lines 297–308), severity classification (lines 309–326)
- §3.5 Go Ecosystem Details (lines 345–363) — `go list -m -u -json all` NDJSON output, `govulncheck -json` output
- §3.5 Rust Ecosystem Details (lines 365–387) — `cargo outdated --format json`, `cargo audit --json` output
- §3.5 Ruby / PHP Ecosystem Details (lines 389–398) — `bundle outdated --parseable`, `bundler-audit`, `composer outdated --format=json`, `composer audit --format=json`
- §3.5 Fallback Behavior (lines 409–418) — graceful degradation for missing tools
- §3.5 Cross-Platform Notes (lines 400–407) — `shutil.which()` pattern for all tools

## Allowed Files

- `git_dashboard.py`
- `tests/test_remaining_dep_health.py`

## Tests to Write First

### Go Ecosystem Tests

1. **check_go_outdated — go not available**: `TOOLS["go"]` is `None`. Assert deps returned unchanged with default health fields.

2. **check_go_outdated — single dep, up-to-date** (mock subprocess): Mock `go list -m -u -json all` returning NDJSON with no `Update` field. Dep `{"name": "github.com/gin-gonic/gin", "version": "v1.9.1", "manager": "gomod"}`. Assert `severity="ok"`, `latest_version="v1.9.1"`.

3. **check_go_outdated — single dep, outdated** (mock subprocess): Mock NDJSON with `Update.Version = "v1.10.0"` for gin. Assert `current_version="v1.9.1"`, `latest_version="v1.10.0"`, `severity="outdated"`.

4. **check_go_outdated — major update** (mock subprocess): Mock `Version="v1.9.1"`, `Update.Version="v2.0.0"`. Assert `severity="major"`.

5. **check_go_outdated — subprocess failure** (mock): Mock `subprocess.run` raising exception. Assert no crash, deps returned unchanged.

6. **check_go_outdated — invalid output** (mock): Mock stdout with non-JSON. Assert no crash, deps returned unchanged.

7. **check_go_vulns — govulncheck not available**: `TOOLS["govulncheck"]` is `None`. Assert deps returned unchanged.

8. **check_go_vulns — vulnerability found** (mock subprocess): Mock `govulncheck -json ./...` output with one vuln entry. Assert `severity="vulnerable"`, `advisory_id` set to the OSV ID.

9. **check_go_vulns — subprocess failure** (mock): Assert no crash, deps returned unchanged.

10. **check_go_deps — full pipeline** (mock both): 2 deps, one outdated and one vulnerable. Assert final severities and advisory IDs correct.

11. **check_go_deps — empty dep list**: Pass `[]`. Assert returns `[]`.

### Rust Ecosystem Tests

12. **check_rust_outdated — cargo-outdated not available**: `TOOLS["cargo_outdated"]` is `None`. Assert deps returned unchanged.

13. **check_rust_outdated — single dep, outdated** (mock subprocess): Mock `cargo outdated --format json` with `dependencies` array containing `{"name": "serde", "project": "1.0.190", "latest": "1.0.210"}`. Assert `current_version="1.0.190"`, `latest_version="1.0.210"`, `severity="outdated"`.

14. **check_rust_outdated — major update** (mock): Mock `project="1.0.190"`, `latest="2.0.0"`. Assert `severity="major"`.

15. **check_rust_outdated — subprocess failure** (mock): Assert no crash, deps returned unchanged.

16. **check_rust_vulns — cargo-audit not available**: `TOOLS["cargo_audit"]` is `None`. Assert deps returned unchanged.

17. **check_rust_vulns — vulnerability found** (mock subprocess): Mock `cargo audit --json` output with one entry in `vulnerabilities.list`. Assert `severity="vulnerable"`, `advisory_id` set to RUSTSEC ID.

18. **check_rust_vulns — subprocess failure** (mock): Assert no crash, deps returned unchanged.

19. **check_rust_deps — full pipeline** (mock both): Assert correct orchestration of outdated then vulns checks.

20. **check_rust_deps — empty dep list**: Pass `[]`. Assert returns `[]`.

### Ruby Ecosystem Tests

21. **check_ruby_outdated — bundle not available**: `TOOLS["bundle"]` is `None`. Assert deps returned unchanged.

22. **check_ruby_outdated — single dep, outdated** (mock subprocess): Mock `bundle outdated --parseable` output: `rails (newest 7.1.3, installed 7.0.8, requested ~> 7.0)`. Assert `current_version="7.0.8"`, `latest_version="7.1.3"`, `severity="outdated"`.

23. **check_ruby_outdated — major update** (mock): Output `rails (newest 8.0.0, installed 7.0.8, requested ~> 7.0)`. Assert `severity="major"`.

24. **check_ruby_outdated — subprocess failure** (mock): Assert no crash, deps returned unchanged.

25. **check_ruby_vulns — bundler-audit not available**: `TOOLS["bundler_audit"]` is `None`. Assert deps returned unchanged.

26. **check_ruby_vulns — vulnerability found** (mock subprocess): Mock `bundle audit check --format json` output with advisory data. Assert `severity="vulnerable"`, `advisory_id` set.

27. **check_ruby_vulns — subprocess failure** (mock): Assert no crash, deps returned unchanged.

28. **check_ruby_deps — full pipeline** (mock both): Assert correct orchestration.

29. **check_ruby_deps — empty dep list**: Pass `[]`. Assert returns `[]`.

### PHP Ecosystem Tests

30. **check_php_outdated — composer not available**: `TOOLS["composer"]` is `None`. Assert deps returned unchanged.

31. **check_php_outdated — single dep, outdated** (mock subprocess): Mock `composer outdated --format=json` output: `{"installed": [{"name": "laravel/framework", "version": "10.0.0", "latest": "10.48.0", "latest-status": "semver-safe-update"}]}`. Assert `current_version="10.0.0"`, `latest_version="10.48.0"`, `severity="outdated"`.

32. **check_php_outdated — major update** (mock): `version="10.0.0"`, `latest="11.0.0"`, `latest-status="update-possible"`. Assert `severity="major"`.

33. **check_php_outdated — subprocess failure** (mock): Assert no crash, deps returned unchanged.

34. **check_php_vulns — vulnerability found** (mock subprocess): Mock `composer audit --format=json` output with advisory data. Assert `severity="vulnerable"`, `advisory_id` set.

35. **check_php_vulns — subprocess failure** (mock): Assert no crash, deps returned unchanged.

36. **check_php_deps — full pipeline** (mock both): Assert correct orchestration.

37. **check_php_deps — empty dep list**: Pass `[]`. Assert returns `[]`.

### Cross-Ecosystem Tests

38. **All enriched dicts have required fields**: For each ecosystem, verify output dicts contain: `name`, `version`, `manager`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`, `checked_at`.

39. **Vuln overrides outdated severity**: For each ecosystem, dep with `severity="outdated"` from outdated check gets escalated to `severity="vulnerable"` when vuln check finds a match.

40. **classify_severity reuse**: Verify each ecosystem calls the shared `classify_severity()` from packet 13 (not a duplicate).

## Implementation Notes

### Go: check_go_outdated(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("go")`. If `None`, return deps with default health fields.
2. Run: `subprocess.run([go_path, "list", "-m", "-u", "-json", "all"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
3. Parse NDJSON output. `go list -m -u -json all` emits one JSON object per line (not a JSON array). Use a streaming parser: split stdout on `}\n{` or use `json.JSONDecoder().raw_decode()` in a loop.
4. Build a lookup dict: `{module_path: {"version": "v1.9.1", "update": "v1.10.0"}}` for modules that have an `Update` field.
5. For each dep: if module is in the lookup and has an update, set `current_version=version`, `latest_version=update_version`, call `classify_severity()`. Note: Go uses `v`-prefixed versions. Strip the `v` prefix before passing to `classify_severity()` (which uses `packaging.version.parse()`).
6. `wanted_version` = `current_version` for Go (no "wanted" concept like npm).

**NDJSON parsing approach**: The output is a sequence of JSON objects separated by newlines. Use a regex-based split or `json.JSONDecoder` with position tracking:
```python
import json
decoder = json.JSONDecoder()
pos = 0
results = []
text = stdout.strip()
while pos < len(text):
    text_remaining = text[pos:].lstrip()
    if not text_remaining:
        break
    obj, end = decoder.raw_decode(text_remaining)
    results.append(obj)
    pos += (len(text[pos:]) - len(text_remaining)) + end
```

### Go: check_go_vulns(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("govulncheck")`. If `None`, return deps unchanged.
2. Run: `subprocess.run([govulncheck_path, "-json", "./..."], cwd=str(repo_path), capture_output=True, text=True, timeout=300)`.
3. Parse JSON output. The output structure has evolved across govulncheck versions. Look for vulnerability entries that contain OSV IDs. Common patterns:
   - Root-level `"Vulns"` array, each with `"OSV": {"id": "GO-2024-..."}` and `"Modules"` listing affected modules.
   - Or NDJSON with `"finding"` objects containing `"osv"` field.
4. Build a vuln lookup: `{module_path: osv_id}`.
5. For each dep: if module matches, set `severity="vulnerable"`, `advisory_id=osv_id`.

**Timeout**: `govulncheck` can be slow (analyzes call graphs). Use a 300s timeout.

### Rust: check_rust_outdated(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("cargo_outdated")`. If `None`, return deps with default health fields.
2. Run: `subprocess.run([cargo_outdated_path, "--format", "json"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
   - Note: `cargo-outdated` is invoked as `cargo outdated` when installed as a cargo subcommand. However, `shutil.which("cargo-outdated")` returns the binary path. Use `TOOLS["cargo_outdated"]` directly.
   - Alternative invocation: `[TOOLS["cargo"], "outdated", "--format", "json"]` if `cargo_outdated` is not found as a standalone binary but `cargo` is available. Check `TOOLS["cargo_outdated"]` first; if None, try `[TOOLS["cargo"], "outdated", "--format", "json"]`.
3. Parse JSON: `{"dependencies": [{"name": "serde", "project": "1.0.190", "compat": "1.0.210", "latest": "1.0.210", "kind": "Normal"}]}`.
4. Build lookup: `{name: {"project": current, "latest": latest}}`.
5. For each dep: if in lookup, set `current_version`, `latest_version`, call `classify_severity()`.
6. `wanted_version` = `current_version` for Rust.

### Rust: check_rust_vulns(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("cargo_audit")`. If `None`, return deps unchanged.
2. Run: `subprocess.run([cargo_audit_path, "--json"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
   - Similar to cargo-outdated, try `TOOLS["cargo_audit"]` first; if None, try `[TOOLS["cargo"], "audit", "--json"]`.
3. Parse JSON: `{"vulnerabilities": {"list": [{"advisory": {"id": "RUSTSEC-2024-...", "title": "..."}, "package": {"name": "...", "version": "..."}}]}}`.
4. Build vuln lookup: `{package_name: rustsec_id}`.
5. For each dep: if in vuln lookup, set `severity="vulnerable"`, `advisory_id=rustsec_id`.

### Ruby: check_ruby_outdated(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("bundle")`. If `None`, return deps with default health fields.
2. Run: `subprocess.run([bundle_path, "outdated", "--parseable"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
3. Parse line-by-line. Format: `gem-name (newest X.Y.Z, installed A.B.C, requested ~> A.B)`. Use regex: `r'^(\S+)\s+\(newest\s+([^,]+),\s+installed\s+([^,]+)'`.
4. Build lookup: `{gem_name: {"installed": version, "newest": version}}`.
5. For each dep: if in lookup, set `current_version=installed`, `latest_version=newest`, call `classify_severity()`.
6. `wanted_version` = `current_version` for Ruby.

### Ruby: check_ruby_vulns(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("bundler_audit")`. If `None`, return deps unchanged.
2. Run: `subprocess.run([bundler_audit_path, "check", "--format", "json"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
   - Note: The actual command is `bundler-audit check --format json` or `bundle audit check --format json`. Use `TOOLS["bundler_audit"]` which points to the `bundler-audit` executable.
3. Parse JSON output. Look for advisory entries containing gem names and CVE/advisory IDs.
4. Build vuln lookup: `{gem_name: advisory_id}`.
5. For each dep: if in vuln lookup, set `severity="vulnerable"`, `advisory_id`.

### PHP: check_php_outdated(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("composer")`. If `None`, return deps with default health fields.
2. Run: `subprocess.run([composer_path, "outdated", "--format=json"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
3. Parse JSON: `{"installed": [{"name": "laravel/framework", "version": "10.0.0", "latest": "10.48.0", "latest-status": "up-to-date"|"semver-safe-update"|"update-possible"}]}`.
4. Build lookup: `{name: {"version": current, "latest": latest}}`.
5. For each dep: if in lookup and `latest-status != "up-to-date"`, set `current_version`, `latest_version`, call `classify_severity()`.
6. `wanted_version` = `current_version` for PHP.

### PHP: check_php_vulns(repo_path: Path, deps: list[dict]) -> list[dict]

1. Check `TOOLS.get("composer")`. If `None`, return deps unchanged. (Audit is built-in since Composer 2.4, same binary.)
2. Run: `subprocess.run([composer_path, "audit", "--format=json"], cwd=str(repo_path), capture_output=True, text=True, timeout=120)`.
3. Parse JSON output for advisory data.
4. Build vuln lookup: `{package_name: advisory_id}`.
5. For each dep: if in vuln lookup, set `severity="vulnerable"`, `advisory_id`.

### Common Pattern (All Ecosystems)

Each `check_{lang}_deps` orchestrator:
1. Filter deps to those with the ecosystem's `manager` value (`gomod`, `cargo`, `bundler`, `composer`).
2. Run `check_{lang}_outdated(repo_path, filtered_deps)`.
3. Run `check_{lang}_vulns(repo_path, filtered_deps)`.
4. Stamp required fields on all deps: `current_version`, `wanted_version`, `latest_version`, `severity` (default `"ok"`), `advisory_id` (default `None`), `checked_at` (ISO timestamp).
5. Return filtered deps (enriched) + non-matching deps (unchanged).

### Version Prefix Handling

Go modules use `v`-prefixed versions (e.g., `v1.9.1`). `packaging.version.parse()` does not handle the `v` prefix. Strip it before calling `classify_severity()`:
```python
def _strip_v(version: str) -> str:
    return version.lstrip("v") if version else version
```

## Acceptance Criteria

1. `check_go_outdated()` skips gracefully when `go` is not available.
2. `check_go_outdated()` correctly parses `go list -m -u -json all` NDJSON output and sets version fields.
3. `check_go_outdated()` uses `classify_severity()` (from packet 13) with `v`-prefix stripped.
4. `check_go_vulns()` skips gracefully when `govulncheck` is not available.
5. `check_go_vulns()` parses govulncheck JSON and sets `severity="vulnerable"` + `advisory_id`.
6. `check_rust_outdated()` skips gracefully when `cargo-outdated` is not available.
7. `check_rust_outdated()` correctly parses `cargo outdated --format json` output.
8. `check_rust_vulns()` skips gracefully when `cargo-audit` is not available.
9. `check_rust_vulns()` parses `cargo audit --json` and sets `severity="vulnerable"` + `advisory_id`.
10. `check_ruby_outdated()` skips gracefully when `bundle` is not available.
11. `check_ruby_outdated()` correctly parses `bundle outdated --parseable` line-by-line output.
12. `check_ruby_vulns()` skips gracefully when `bundler-audit` is not available.
13. `check_ruby_vulns()` parses bundler-audit JSON and sets `severity="vulnerable"` + `advisory_id`.
14. `check_php_outdated()` skips gracefully when `composer` is not available.
15. `check_php_outdated()` correctly parses `composer outdated --format=json` output.
16. `check_php_vulns()` skips gracefully when `composer` is not available.
17. `check_php_vulns()` parses `composer audit --format=json` and sets `severity="vulnerable"` + `advisory_id`.
18. Each ecosystem's orchestrator (`check_{lang}_deps`) runs outdated then vulns and returns enriched dicts.
19. Vulnerability severity overrides outdated/major severity for all ecosystems.
20. All enriched dep dicts contain required fields: `name`, `version`, `manager`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`, `checked_at`.
21. `classify_severity()` from packet 13 is reused (not reimplemented).
22. All subprocess failures handled gracefully (no crash, deps returned unchanged).
23. No DB writes in this packet — functions produce enriched dicts only.
24. All existing tests (283 from prior packets) still pass (no regressions).

## Validation Focus Areas

- **Subprocess mocking**: All tests must mock `subprocess.run` — never run real `go`, `cargo`, `bundle`, or `composer` during tests. Use `unittest.mock.patch`.
- **NDJSON parsing**: Go's `go list -m -u -json all` emits NDJSON (one JSON object per line), not a JSON array. Verify the parser handles this correctly.
- **Version prefix stripping**: Go uses `v`-prefixed versions. Verify `v` is stripped before `classify_severity()`.
- **Parseable output format**: Ruby's `bundle outdated --parseable` is line-based, not JSON. Verify regex parsing handles edge cases (gems with hyphens/underscores in names, missing "requested" field).
- **Tool availability cascading**: Rust has separate tools for outdated and audit. Verify that each is checked independently — `cargo-audit` missing should not prevent `cargo-outdated` from running (and vice versa).
- **Severity escalation**: Verify `vulnerable > major > outdated > ok` for every ecosystem.
- **No DB writes**: Verify no database operations in any function.
- **TOOLS dict access**: Verify each function reads from `TOOLS` (not hardcoded paths).
- **Regression**: All prior 283 tests pass without modification.
- **Packet size**: If this packet exceeds 600 lines of net new code, the implementer should report to the planner for a potential split into 15A–15D.
