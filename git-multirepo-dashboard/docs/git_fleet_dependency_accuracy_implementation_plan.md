# Git Fleet Dependency Accuracy Implementation Plan

## Authority and execution

This document plans changes to Git Fleet; implementation requires separate authorization.

Read the repository [README](../../README.md), [agent instructions](../../agents.md),
[lessons](../../docs/lessons_learned.md), project [README](../README.md), and
[design reference](git_dashboard_final_spec.md). Related remediation context:
[Git Fleet report accuracy](../../docs/dependency_report_remediation_implementation_plan.md#git-fleet-report-accuracy).
The runtime and test references below are symbols in [git_dashboard.py](../git_dashboard.py)
and [tests](../tests); use their definitions at execution time.

Follow the repository instructions for environment setup, branching, commits,
sensitive data, lessons, and validation. Resolve PKM context from the working
directory before searching. Consult [deployment discovery](../../tools/check_local_deployments.zsh)
and confirm the actual launch location with Kevin before making a release claim.

Each task owns its contract, regression tests, and behavior documentation. Other
sections refer to that contract rather than redefining it. Follow the project's
README Development section for full-suite commands, and its design reference
Testing contracts for invocation boundaries. Record observed results without
requiring a fixed test-count increment. Run focused regression tests before and
after the corresponding implementation, then the documented full suite for the
affected project. Keep network and tool execution mocked in unit tests.

The task-owned contracts specify proposed behavior absent from current source;
a reference alone would not define those changes. The snippets provide subtle
implementation or regression behavior. Add imports in their
destination modules as needed. Proposed test symbols are acceptance obligations,
not claims that those tests already exist.

## Task: Declaration identity and migration

**Edit:** `git_dashboard.py` symbols `VERSION`, `_SCHEMA_SQL`, `run_migrations`,
`parse_deps_for_repo`, `run_dep_scan_for_repo`, `_fetch_repo_deps`,
`get_analytics_dep_overlap`, and `DepOverlap`.
**Tests:** new `tests/test_dep_schema_v2.py`; extend
`tests/test_packet_00.py`, `tests/test_dep_detection_parsing.py`,
`tests/test_dep_scan_orchestration.py`, and `tests/test_analytics_dep_overlap.py`.
**Documentation:** README Dependency discovery and Analytics; design reference
Runtime state, dependencies, Dependency model, and the overlap API contract.

- [ ] Implement the declaration identity contract.

Use `_DEPENDENCIES_TABLE_SQL` below as the database identity contract. Within a manifest,
keep the first occurrence of a repeated identity. Keep declarations in different
manifests separate. Distinguish package names from fallback reference identifiers
through `reference_identity`, produced by the Direct references task.

```python
def normalize_dep_name(manager: str, name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if manager == "pip" else name


def dependency_identity_name(dep: dict) -> str:
    if dep.get("reference_identity"):
        return dep["name"]
    return normalize_dep_name(dep["manager"], dep["name"])


def _version_sort_key(value: str) -> tuple:
    from packaging.version import InvalidVersion, Version
    try:
        return (0, Version(value), value)
    except InvalidVersion:
        return (1, None, value)
```

Assign `dep["name"] = dependency_identity_name(dep)` before deduplication.
Use the declaration key for upserts, stale-row selection, and deletion.
`_fetch_repo_deps` must expose the fields defined by `_DEPENDENCIES_TABLE_SQL`
that consumers need, including the declared text and check coverage.

```sql
CREATE TABLE IF NOT EXISTS dependencies (
  repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  manager TEXT NOT NULL,
  source_path TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  declared_spec TEXT,
  current_version TEXT,
  wanted_version TEXT,
  latest_version TEXT,
  severity TEXT DEFAULT 'unchecked',
  advisory_id TEXT,
  outdated_state TEXT DEFAULT 'unchecked',
  vuln_state TEXT DEFAULT 'unchecked',
  check_note TEXT,
  checked_at TEXT,
  PRIMARY KEY (repo_id, manager, source_path, name)
);
```

Store this DDL in `_DEPENDENCIES_TABLE_SQL` and use it from schema initialization
and `_migrate_dependencies_v2(conn: sqlite3.Connection) -> None`. Set the release
`VERSION` to `"0.2.0"` with the schema change.

`run_migrations` must perform the additive migrations and then call the rebuild
helper on its connection. For a legacy key, read rows ordered by `rowid`, normalize
package names, coalesce a missing or NULL source to an empty string, and retain
the first row on a normalized-name collision. Rebuild within a transaction;
roll back on failure. Preserve recorded versions and timestamp; move the former
advisory and severity into the migration note, clear the active advisory field,
and invalidate coverage through the Check coverage contract. Include a rescan
instruction in that note. A database with the target key
must return without changing its rows.

`get_analytics_dep_overlap` must group declarations by manager and identity name,
retain groups with repeated uses, and expose `count`, `repo_count`, and
`repos[].source_path`. Sort distinct non-null versions using `_version_sort_key`.
`DepOverlap` must use a React key formed from repository ID and source path and
display manifest attribution alongside the version.

- [ ] Write migration regressions in `tests/test_dep_schema_v2.py`.

Build legacy schemas from the historical DDL in `_SCHEMA_SQL` and
`_MIGRATION_SQL` at commit `1559dcb`, rather than calling the future initializer.
Define `_legacy_db(tmp_path, *, source_path="proj/manifest", include_source=True,
extra_ws_column=True)` to insert the supplied source value without coercion.
Use conspicuously synthetic rows in that fixture.

```python
def test_migration_coalesces_sql_null_source(tmp_path):
    db = _legacy_db(tmp_path, source_path=None)
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM dependencies WHERE source_path IS NULL"
        ).fetchone()[0] > 0
    git_dashboard.run_migrations(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM dependencies WHERE source_path IS NULL"
        ).fetchone()[0] == 0
        assert {r[0] for r in conn.execute(
            "SELECT source_path FROM dependencies"
        )} == {""}
```

Also write `test_fresh_schema_has_declaration_key`,
`test_migration_preserves_data_and_invalidates_coverage`,
`test_migration_keeps_first_normalized_collision`,
`test_migration_handles_absent_source_column`,
`test_migration_handles_existing_missing_tools_column`,
`test_migration_is_idempotent`, and `test_migration_rolls_back_failed_copy`.

- [ ] Write `test_parse_deps_for_repo_keeps_manifest_identities`,
`test_dependency_identity_normalizes_package_names_only`,
`test_scan_removes_only_stale_declarations`,
`test_dep_overlap_counts_manifest_uses_and_repositories`,
`test_dep_overlap_orders_versions`, and `test_overlap_component_keys_include_source`
in the corresponding test files named above.

Update `test_schema_dependencies_columns` to derive the expected schema from
the declaration contract. Keep fixture/API expectations aligned with this intended
schema change; document a contract-based reason for changed assertions.

## Task: Check coverage and asynchronous orchestration

**Edit:** `git_dashboard.py` health helpers, `check_*` functions,
`run_dep_scan_for_repo`, `working_state` DDL, `_MIGRATION_SQL`,
`get_repo_detail`, and `get_fleet`.
**Tests:** `tests/test_python_dep_health.py`, `tests/test_node_dep_health.py`,
`tests/test_remaining_dep_health.py`, `tests/test_dep_scan_orchestration.py`,
`tests/test_deps_subtab_ui.py`, and `tests/test_packet_00.py`.
**Documentation:** design reference Dependency model and working_state;
README Repository detail.

- [ ] Implement the check coverage contract.

`outdated_state` accepts `checked`, `floating`, or `unchecked`.
`vuln_state` accepts `checked` or `unchecked`.
`check_note` accumulates distinct reasons for incomplete coverage.
A successful tool invocation alone is insufficient: validate its exit status,
result structure, and evidence that the row was evaluated. Manager-specific
success rules belong to the Python health and Manifest-directory checks tasks.

```python
def derive_severity(dep: dict) -> str:
    if dep.get("advisory_id"):
        return "vulnerable"
    if (dep.get("outdated_state") in ("checked", "floating")
            and dep.get("severity") in ("major", "outdated")):
        return dep["severity"]
    if "unchecked" in (
        dep.get("outdated_state", "unchecked"),
        dep.get("vuln_state", "unchecked"),
    ):
        return "unchecked"
    return "ok"


def _exact_pip_version(value: str | None) -> str | None:
    from packaging.version import InvalidVersion, Version
    if not value:
        return None
    try:
        Version(value)
    except InvalidVersion:
        return None
    return value
```

Implement `add_check_note`, `mark_unchecked`, and `tool_failure_note`.
Bound tool-error details to their last non-empty line, with a length limit, and
retain logging through the application's logging pattern.

`finalize_dep_health(deps)` must be idempotent. Default `declared_spec` from the
parser's declaration; default `current_version` for pip only through
`_exact_pip_version`, and for gomod from its parser value. Other managers must
obtain concrete versions from their checkers. Set missing `wanted_version` from
a concrete current version; set missing coverage to unchecked and derive severity
with `derive_severity`. Missing evidence must have a reason. Default `checked_at`
only when absent.
Do not replace a checker's floating selection or direct-reference display value.

Move the manager/tool mapping from `run_dep_scan_for_repo` into module-level
`DEP_TOOL_REQUIREMENTS`. Extract parsing and health checks into
`analyze_repo_deps(repo_path: Path) -> DepAnalysis`, whose fields are
`enriched`, `any_error`, `missing_tools`, and `manifests`.
Persist missing tools as objects with `tool` and `description`.
Catch failures per manager, invalidate that manager's coverage with a reason,
and finalize the merged results.

Call the analyzer with `await asyncio.to_thread(analyze_repo_deps, repo_path)`.
Add JSON-text `missing_dep_tools` and `dep_manifests` columns to `working_state`
and its additive migration. Persist analysis metadata on the empty-result path
as well as the populated path, in the dependency scan transaction.
Serve parsed values from `get_repo_detail`; expose missing tools in the fleet
response. Quick scans must preserve dependency metadata.

- [ ] Write `test_derive_severity_coverage_precedence`,
`test_finalize_health_is_idempotent`,
`test_finalize_does_not_treat_poetry_constraint_as_current`,
`test_lookup_failure_has_unchecked_reason`,
`test_missing_tool_marks_served_state_unchecked`,
`test_crashed_checker_invalidates_its_manager_only`,
`test_scan_persists_missing_tools`,
`test_scan_persists_metadata_without_rows`,
`test_dep_scan_allows_event_loop_progress`,
`test_detail_returns_coverage_metadata`, and
`test_quick_scan_preserves_coverage_metadata`.

Use parametrization over manager contracts rather than a copied manager list.
Use `tests/conftest.py::test_app` for API-backed regression work.
Update tests asserting the old failure status to assert `derive_severity`'s
contract. Update schema tests for the intended `working_state` additions.
Checker mocks in orchestration tests must explicitly provide coverage evidence.

## Task: Direct references and Python declaration parsing

**Edit:** `git_dashboard.py::parse_requirements_txt`,
`parse_pyproject_toml`, `parse_deps_for_repo`, and Python checker entry points.
**Tests:** `tests/test_dep_detection_parsing.py`,
`tests/test_python_dep_health.py`, and `tests/test_dep_scan_orchestration.py`.
**Documentation:** design reference Python parsing contract.

- [ ] Implement `parse_python_requirement(text: str) -> dict | None` using
`packaging.requirements.Requirement`. Preserve the declaration text and markers;
extract exact pins without accepting wildcard pins as concrete versions.
Use `_direct_reference` for named references and bare VCS/URL requirements.
Behave as [pip VCS Support](https://pip.pypa.io/en/stable/topics/vcs-support/)
does for separating URL user information from the revision. The implementation
below defines the report identity and display behavior.

```python
_VCS_SCHEMES = ("git+", "hg+", "svn+", "bzr+")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
NOTE_DIRECT_REF = "direct VCS/URL reference; not compared with PyPI or audited"


def _direct_reference(name: str | None, url: str, declared: str) -> dict:
    vcs = next((scheme[:-1] for scheme in _VCS_SCHEMES
                if url.startswith(scheme)), None)
    target = url[len(vcs) + 1:] if vcs else url
    parts = urllib.parse.urlsplit(target)
    path = parts.path
    revision = None
    if vcs and "@" in path:
        path, _, revision = path.rpartition("@")
    egg = urllib.parse.parse_qs(parts.fragment).get("egg", [None])[0]
    if name is None and egg:
        from packaging.requirements import Requirement
        name = Requirement(egg).name
    current = None
    if name is None and not vcs and path.endswith(".whl"):
        from packaging.utils import parse_wheel_filename
        wheel_name, wheel_version, _, _ = parse_wheel_filename(path.rsplit("/", 1)[-1])
        name, current = str(wheel_name), str(wheel_version)
    reference_identity = name is None
    if reference_identity:
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        name = host + path.removesuffix(".git").rstrip("/")
    else:
        name = normalize_dep_name("pip", name)
    if vcs:
        current = f"{vcs}:{revision}" if revision else f"{vcs}:default branch"
    return {
        "name": name, "manager": "pip", "declared_spec": declared,
        "version": None, "current_version": current, "direct_ref": True,
        "reference_identity": reference_identity,
    }
```

`parse_requirements_txt` must join continuations, strip inline comments and
per-requirement options, and pass requirement text to the shared parser.
Preserve include/cycle behavior through the Manifest discovery contract.
Make PEP 621 declarations use the shared parser. Retain the Poetry parser's
supported value forms, but add textual `declared_spec`. Apply the
[Check coverage contract](#task-check-coverage-and-asynchronous-orchestration).

Direct references must bypass registry comparisons and vulnerability audits,
with coverage marked using `NOTE_DIRECT_REF`. Resolving VCS commits or retrieving
remote package metadata for these rows is outside this plan.

- [ ] Add the following parser-to-scan regression, using the actual scanner
and patching external health work through the test module's orchestration helpers.

```python
@pytest.mark.parametrize("transport", ["https", "ssh"])
def test_direct_reference_identity_survives_repo_pipeline(tmp_path, transport):
    authority = "git@git.example.invalid" if transport == "ssh" else "git.example.invalid"
    url = f"git+{transport}://{authority}/acme/widget-kit.git@feature/fix"
    (tmp_path / "requirements.txt").write_text(url + "\n")
    [row] = git_dashboard.parse_deps_for_repo(tmp_path)
    assert row["name"] == "git.example.invalid/acme/widget-kit"
    assert row["current_version"] == "git:feature/fix"
    assert git_dashboard.dependency_identity_name(row) == row["name"]
```

Also write `test_direct_reference_persists_identity_and_coverage`,
`test_named_and_egg_references_normalize_distribution_name`,
`test_wheel_reference_uses_wheel_metadata`,
`test_direct_reference_makes_no_registry_or_audit_calls`,
`test_pep508_extras_markers_wildcards_and_continuations`, and
`test_poetry_declaration_text_is_not_a_mapping`.
Update parser-shape assertions only where the new contract requires fields.

## Task: Manifest discovery and provenance inventory

**Edit:** `git_dashboard.py::_DEP_FILE_PRIORITY`, `detect_dep_files`,
`parse_requirements_txt`, `parse_pyproject_toml`, `parse_deps_for_repo`, and
`analyze_repo_deps`.
**Tests:** `tests/test_dep_detection_parsing.py` and
`tests/test_dep_scan_orchestration.py`.
**Documentation:** README Dependency discovery; design reference Dependency model.

- [ ] Implement detection using `_DEP_WALK_SKIP` and `_DEP_WALK_MAX_DEPTH`
as the traversal policy. Keep the non-Python manifest choices from
`_DEP_FILE_PRIORITY`. Python detection must return `pyproject.toml`,
requirements files matched by `_REQUIREMENTS_RE`, and eligible script candidates
without suppressing a manifest because another kind exists in its directory.

```python
_REQUIREMENTS_RE = re.compile(
    r"^requirements(?:[-_.][A-Za-z0-9_.-]+)?\.(?:txt|lock)$", re.IGNORECASE
)


def _source_path(repo_path: Path, file_path: Path) -> str:
    resolved = file_path.resolve()
    try:
        return resolved.relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        return str(resolved)
```

`detect_dep_files` returns `file`, `kind`, `manager`, `runtime`, and `dir`.
Dispatch parsers by `kind`. A script candidate has a Python suffix or is a
suffixless shebang file.

- [ ] Implement the manifest inventory contract.

Extend `parse_requirements_txt(file_path, _visited=None, *, manifests_out=None)`
with a mutable inventory keyed by resolved `Path`. Pass that object through
recursive includes. Register the manifest when opening is attempted, before
parsing rows; record `kind`, own `dependencies` count, and an optional `error`.
Attribute each row with its resolved `source_file`. Count declarations physically
in that file, not rows imported from another file. Record empty included files,
arbitrary include filenames, external includes, and read/parse failures.
Use `_visited` to prevent repeated reads and cycles.

`parse_deps_for_repo(repo_path, manifests_out=None)` creates a shared inventory
for discovery and recursive parsing, then emits records shaped as
`{"path", "kind", "dependencies", "error"}` using `_source_path`.
Deduplicate rows through the Declaration identity contract. Inventory entries
must survive even when their file produces no rows. Feed inventory errors into
`DepAnalysis.any_error`, and preserve the inventory through the Check coverage
persistence path. Dependency groups may omit empty files; `dep_manifests` is the
coverage source for files.

- [ ] Implement `_find_pep723_block` and `parse_pep723_script`.

Select the script's leading comment/blank-line prelude, stopping before code,
and parse metadata there. For block grammar, closing-line precedence, and
duplicate-block validation, behave as the
[PEP 723 Specification and Reference Implementation](https://peps.python.org/pep-0723/#specification)
do; the prelude selection is the deliberate additional restriction.
Read the complete prelude without a fixed byte cutoff. Ignore unclosed blocks
as specified by the PEP; report malformed TOML or duplicate metadata as an
inventory error. Validate the dependencies value before passing its strings to
`parse_python_requirement`.

Write `test_pep723_suffix_and_shebang_discovery`,
`test_pep723_lookalike_after_code_is_ignored`,
`test_pep723_empty_dependencies_remain_in_inventory`,
`test_pep723_duplicate_script_blocks_report_error`,
`test_pep723_embedded_terminator_obeys_pep_grammar`,
`test_pep723_long_leading_prelude_is_read`, and
`test_pep723_invalid_metadata_reports_error`. Derive grammar fixture text from
the linked PEP examples in test code, keeping the page reference with the test.

- [ ] Extend `parse_pyproject_toml` with PEP 621 optional dependencies and
string declarations in `dependency-groups`. Do not expand `include-group`
tables or add Poetry dependency-group support.

Implement `_load_uv_lock_versions(lock_path)` to use adjacent `uv.lock` as a
version source for pyproject rows, not as an additional declaration manifest.
For a normalized name with a unique locked registry version, use that version
and record its provenance. For ambiguous locked versions, block floating
resolution and record an unchecked reason. For a name absent from the lock,
retain the ordinary declaration resolution path. Keep direct references on
their own coverage path. Treat `requirements.lock` through the requirements
parser, including its transitive declarations.

Write `test_python_manifest_kinds_coexist`,
`test_recursive_includes_keep_declaring_source`,
`test_includes_are_deduplicated_across_discovery`,
`test_lock_manifest_is_independent`,
`test_pyproject_optional_dependencies_and_groups`,
`test_uv_lock_unique_ambiguous_and_absent_names`, and
`test_scan_persists_empty_and_failed_manifests`.
Replace `test_detect_dep_files_priority_order_python` with
`test_detect_dep_files_returns_pyproject_and_requirements` because the manifest
selection contract changes.

```python
def test_inventory_includes_empty_arbitrary_and_external_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("")
    (repo / "empty-extra.txt").write_text("")
    (repo / "requirements.txt").write_text(
        "-r empty-extra.txt\n-r ../outside.txt\nalpha-lib==1.0\n"
    )
    manifests = []
    rows = git_dashboard.parse_deps_for_repo(repo, manifests_out=manifests)
    by_path = {m["path"]: m for m in manifests}
    assert by_path["empty-extra.txt"]["dependencies"] == 0
    assert by_path[str(outside.resolve())]["dependencies"] == 0
    assert by_path["requirements.txt"]["dependencies"] == len(rows)
    assert {r["source_path"] for r in rows} == {"requirements.txt"}
```

## Task: Python health and audit validation

**Edit:** `git_dashboard.py::check_python_outdated`, `check_python_vulns`,
`check_python_deps` and their new helpers.
**Tests:** `tests/test_python_dep_health.py`.
**Documentation:** README dependency-health scope; design reference Python health.

- [ ] Implement `_floating_specifier` and `resolve_floating_version`.

Use `packaging.requirements.Requirement` and `packaging.specifiers.SpecifierSet`
for supported declaration syntax. Use `SpecifierSet.filter` for prerelease
selection as defined by the
[packaging API](https://packaging.pypa.io/en/stable/specifiers.html#packaging.specifiers.SpecifierSet.filter).
Select the highest allowed non-yanked release with usable release files.
If a response lacks a releases mapping, permit its valid `info.version` as
a fallback. Unsupported constraints must remain unchecked with a reason.

The evaluated version is the exact declared/locked version when available;
otherwise it is a floating selection stored in `wanted_version`. Compare that
selection to the registry's latest version with `classify_severity` and set the
appropriate outdated state. Apply the
[Check coverage contract](#task-check-coverage-and-asynchronous-orchestration).
This is a declaration evaluation, not an installed-environment or
full dependency resolution: do not evaluate markers, `requires-python`, or
inter-package compatibility, or audit undeclared transitive Python dependencies.
Expose these limits through the report Scope contract.

Cache lookup successes and failures by normalized package name for the scan.
Introduce `_PYPI_MAX_CONSECUTIVE_FAILURES` and a connection-failure breaker.
Count timeout/connection errors toward it, reset on success, and leave HTTP
and JSON errors outside its counter. Once open, mark uncached lookups unchecked
without attempting them. Skip rows whose coverage is constrained by another
task's contract.

- [ ] Implement `_pip_audit_batches(pins)` and `_audit_python_pins`.

Deduplicate pins and partition so a batch contains at most a single version of a
normalized name. Generate exact-pin requirements in a temporary directory outside
the repository. Use `pip-audit` with `--no-deps`, `--disable-pip`, JSON output,
and the subprocess timeout defined in the helper below.

For exit-status and JSON semantics, use the
[pip-audit documentation](https://pypi.org/project/pip-audit/).
The helper body below specifies the additional validation policy for this report.

```python
def _audit_python_pins(pip_audit: str, batch: list[tuple[str, str]]) -> dict:
    def failed(note):
        return {pin: {"vuln_state": "unchecked", "note": note} for pin in batch}

    proc = None
    try:
        with tempfile.TemporaryDirectory(prefix="git-fleet-audit-") as tmp:
            path = Path(tmp) / "pins.txt"
            path.write_text("".join(f"{name}=={version}\n"
                                    for name, version in batch), encoding="utf-8")
            proc = subprocess.run(
                [pip_audit, "--requirement", str(path), "--no-deps", "--disable-pip",
                 "--format", "json", "--progress-spinner", "off"],
                capture_output=True, text=True, timeout=300,
            )
        if proc.returncode not in (0, 1):
            return failed(tool_failure_note(
                "pip-audit", proc.stderr or f"exit status {proc.returncode}"
            ))
        raw = json.loads(proc.stdout)
        if not isinstance(raw, dict) or not isinstance(raw.get("dependencies"), list):
            raise ValueError("missing dependencies result")
        entries = {}
        for entry in raw["dependencies"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise ValueError("invalid dependency result")
            name = normalize_dep_name("pip", entry["name"])
            if name in entries:
                raise ValueError("duplicate dependency result")
            entries[name] = entry
        results = {}
        for pin in batch:
            name, version = pin
            entry = entries.get(name)
            if entry is None:
                results[pin] = {"vuln_state": "unchecked", "note": "not in pip-audit output"}
                continue
            if entry.get("skip_reason"):
                results[pin] = {"vuln_state": "unchecked",
                                "note": f"pip-audit skipped: {entry['skip_reason']}"}
                continue
            vulns = entry.get("vulns")
            if (not isinstance(vulns, list)
                    or any(not isinstance(v, dict) or not isinstance(v.get("id"), str)
                           or not v["id"] for v in vulns)):
                raise ValueError("missing or invalid vulnerability result")
            if entry.get("version") is not None and entry["version"] != version:
                raise ValueError("audit version differs from requested pin")
            if proc.returncode == 0 and vulns:
                raise ValueError("audit exit status contradicts advisories")
            results[pin] = {"vuln_state": "checked",
                            "advisory_id": vulns[0]["id"] if vulns else None}
        if proc.returncode == 1 and not any(
            result.get("advisory_id") for result in results.values()
        ):
            raise ValueError("advisory exit status without a requested advisory")
        return results
    except Exception as exc:
        detail = proc.stderr if proc is not None and proc.stderr else str(exc)
        return failed(tool_failure_note("pip-audit", detail))
```

Audit only concrete PEP 440 versions obtained from the evaluated row. Prefer a
validated current version, then the validated floating selection. No concrete
version, unavailable tool, missing output entry, skipped dependency, malformed
result, or failed process must produce unchecked coverage with its reason.
Apply results by normalized name and audited version to the matching declaration
rows. Finish through the Check coverage contract.

- [ ] Write `test_poetry_constraint_health_does_not_invent_current_version`,
`test_floating_selection_and_capped_comparison`,
`test_floating_resolution_omits_yanked_releases`,
`test_registry_fallback_without_releases`,
`test_registry_cache_across_manifests`,
`test_connection_breaker_bounds_requests`,
`test_http_error_does_not_open_breaker`,
`test_audit_batches_preserve_pin_set_without_name_collisions`,
`test_audit_files_are_outside_repository`,
`test_audit_results_map_to_requested_versions`,
`test_audit_failure_is_limited_to_its_batch`, and
`test_audit_skip_and_missing_entry_are_unchecked`.

```python
def test_floating_resolution_respects_explicit_prereleases():
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
    versions = ["1.0", "2.0rc1"]
    payload = {"info": {"version": "1.0"},
               "releases": {v: [{"yanked": False}] for v in versions}}
    for constraint in ("", ">=1.0rc1"):
        expected = max(SpecifierSet(constraint).filter(map(Version, versions)))
        assert git_dashboard.resolve_floating_version(payload, constraint) == str(expected)


@pytest.mark.parametrize("returncode,entry", [
    (2, {"name": "alpha-lib", "vulns": []}),
    (0, {"name": "alpha-lib"}),
    (0, {"name": "alpha-lib", "vulns": None}),
    (0, {"name": "alpha-lib", "vulns": [{"unexpected": "synthetic"}]}),
    (1, {"name": "alpha-lib", "vulns": []}),
])
def test_audit_rejects_failed_or_incomplete_results(monkeypatch, returncode, entry):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], returncode, stdout=json.dumps({"dependencies": [entry]}), stderr=""
    ))
    result = git_dashboard._audit_python_pins("synthetic-auditor", [("alpha-lib", "1.0")])
    assert result[("alpha-lib", "1.0")]["vuln_state"] == "unchecked"
    assert result[("alpha-lib", "1.0")]["note"]
```

Update `_pip_audit_output` and its callers to model the documented tool shape.
Replace old unpinned/range skip expectations with the floating-resolution
contract; do not alter unrelated assertions.

## Task: Manifest-directory checks

**Edit:** `git_dashboard.py::check_node_outdated`, `check_node_vulns`,
and non-Python `check_*_deps` orchestrators.
**Tests:** `tests/test_node_dep_health.py` and `tests/test_remaining_dep_health.py`.
**Documentation:** README Dependency discovery; design reference ecosystem health.

- [ ] Implement `_group_by_manifest_dir(repo_path, deps)` from each row's
source path, using `repo_path` only for legacy empty sources. Pass each group
to the manager's inner checkers using the group's directory as their working
directory. Preserve the existing checker signatures.

- [ ] Implement the npm version-evidence contract.

Use `_npm_lock_versions(manifest_dir)` for direct dependency versions from
supported package-lock layouts. Read installed package metadata without running
package lifecycle code when a version is absent from the tool response.
Apply the [Check coverage contract](#task-check-coverage-and-asynchronous-orchestration).

A listed `npm outdated` row needs a concrete current/locked version and a
latest version before classification. An absent row can be checked only if
its concrete version has a registry/tool comparison. If empty output does not
provide that comparison, perform a bounded registry lookup for that declaration
or leave it unchecked with a reason. A lockfile supplies version evidence,
not registry comparison evidence. A successful empty response therefore does
not override missing evidence.

Validate subprocess exit statuses and result structures using the
[npm outdated contract](https://docs.npmjs.com/cli/v11/commands/npm-outdated/).
For `npm audit`, reject a top-level error or a missing/invalid vulnerabilities
mapping. Give `ENOLOCK` its lockfile-specific reason; use the coverage failure
path for other errors. Audit prerequisites do not imply that an audit succeeded.

For the remaining managers, validate their documented result keys and required
per-row fields before marking coverage checked. An absent `go list` row remains
unchecked; for outdated tools that return only findings, absence can count as
checked only when the successful report establishes that it evaluated the
declaration. Preserve independent outdated and vulnerability coverage.

- [ ] Write `test_nonpython_checks_use_manifest_directories`,
`test_node_current_version_from_lock`,
`test_node_current_version_from_installed_metadata`,
`test_node_missing_version_is_unchecked`,
`test_node_empty_output_without_version_is_unchecked`,
`test_node_absent_row_without_comparison_is_unchecked`,
`test_node_empty_output_with_registry_evidence_is_checked`,
`test_node_audit_lock_error_is_unchecked`,
`test_node_audit_error_object_is_unchecked`, and
`test_nonpython_malformed_tool_result_is_unchecked`.
Parametrize directory and malformed-output coverage over manager/tool contracts.
Adapt existing mocks only for evidence required by the changed checker contract.

## Task: Coverage UI, exports, and fleet acceptance

**Edit:** `git_dashboard.py::_fetch_repo_deps`, `get_fleet`, `KpiRow`, `DepBadge`,
`DepsTab`, `ProjectDetail`, and `FleetDepsTab`.
**Tests:** `tests/test_dep_scan_orchestration.py`,
`tests/test_deps_subtab_ui.py`, and `tests/test_e2e.py`.
**Documentation:** README Fleet overview and Repository detail; design reference
Quick scan, HTTP API, and UI contracts.

- [ ] Implement `summarizeDeps(groups)` as the report summary contract.

Return `declarations`, `manifests`, severity counts, `unchecked`, and
`fullyChecked`. Count unchecked coverage by state, even when the headline
severity reports a finding. Count fully checked coverage through the Check
coverage contract. The fleet queries must calculate these values from the same
row predicates, including `repos[].dep_summary.unchecked` and
`kpis.unchecked_deps`. Outdated KPI counts use outdated/major severities.
Manifest-read coverage comes from the discovery inventory, independently of
nonempty dependency groups.

`DepsTab` must fetch repository metadata and application version on mount and
after Check Now. Implement `currentText` and `statusText` from the stored
version and coverage fields. Display floating selections as evaluated versions,
not installed versions. Surface a partially unchecked row even when its headline
severity is vulnerable, major, or outdated. Provide declared text and coverage
reasons in the table, an incomplete-coverage banner, and a Not Checked section.
Use the summary to control the all-up-to-date banner.

`KpiRow` and `FleetDepsTab` must expose Not Checked coverage. `DepBadge` must
indicate incomplete coverage and missing tools, with explanatory title text.
Remove the obsolete `missingDepTools` prop when the metadata fetch replaces it.

- [ ] Implement the report format contract.

The Markdown export has report/repository identity, generation time, application
version, newest scan timestamp, coverage, missing tools, and Scope metadata.
Its sections are Attention Required, Not Checked, All Dependencies, and
Manifests Scanned. Include the declared specification, version display, check
states, headline status, and reasons; display inventory errors with their files.

JSON export:
```javascript
{
  format: "git-fleet-dependency-report",
  format_version: 2,
  generated_at,
  git_fleet_version,
  repo: {id, name},
  missing_tools,
  summary,
  scope,
  manifests,
  groups
}
```

Generate Scope metadata from the named contracts in this plan: Python health's
resolution limits, Direct references' exclusions, Manifest discovery's traversal
and PEP prelude policy, and its dependency-group boundaries. Read runtime
constants when emitting traversal limits. Keep `/api/repos/{id}/deps` a grouped
list; version only the downloaded report object.

- [ ] Add `test_fleet_coverage_counts_follow_states` and
`test_dependency_response_exposes_coverage`. For browser seeding, extend
`tests/test_e2e.py::server` through a context fixture that also yields the
isolated database path, keeping existing callers compatible.

Define synthetic seeded declarations in a shared fixture and compute expected
summary values from it. Write `test_deps_tab_reports_partial_coverage`,
`test_markdown_export_includes_coverage_and_inventory`,
`test_json_export_obeys_report_contract`,
`test_overlap_lists_manifest_uses_without_duplicate_keys`, and
`test_fleet_kpi_displays_unchecked_coverage`. Use the browser-error hooks from
`tools/testkit.py` and add an explicit duplicate-key console assertion to the
overlap test. Test report coverage against the shared fixture rather than
a copied set of prose examples.

- [ ] Perform fleet acceptance with the isolated runtime procedure below.

Before taking a live snapshot, have Kevin stop Git Fleet cleanly. This procedure
opens an existing source database read-only and runs the candidate against a
private destination. It does not establish where installed copies exist.
Use synthetic database initialization if there is no source database; the
synthetic migration regressions then supply legacy-schema coverage.

Run from the Git Fleet project directory through the repository's Python policy:

```bash
REPO=$(git rev-parse --show-toplevel)
ACC=$(mktemp -d "$HOME/.git-fleet-acceptance.XXXXXX")
SERVER_PID=
cleanup_git_fleet_acceptance() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -r -- "$ACC"
}
trap cleanup_git_fleet_acceptance EXIT

SOURCE_DB="$HOME/.git_dashboard/dashboard.db"
if [ -f "$SOURCE_DB" ]; then
  sqlite3 -readonly "$SOURCE_DB" ".backup '$ACC/dashboard.db'" || exit 1
fi

GIT_DASHBOARD_HOME="$ACC" GIT_DASHBOARD_DB="$ACC/dashboard.db" \
  UV_PYTHON_DOWNLOADS=never ./git_dashboard.py --no-browser --port 8340 \
  > "$ACC/server.log" 2>&1 &
SERVER_PID=$!

PORT=
for _ in $(seq 120); do
  PORT=$(sed -n 's#.*localhost:\([0-9]*\).*#\1#p' "$ACC/server.log" | head -1)
  [ -n "$PORT" ] && curl -fsS "http://localhost:$PORT/api/status" > "$ACC/status.json" && break
  kill -0 "$SERVER_PID" 2>/dev/null || break
  sleep 1
done
[ -n "$PORT" ] && [ -s "$ACC/status.json" ] || { cat "$ACC/server.log"; exit 1; }

jq -n --arg path "$REPO" '{path:$path}' > "$ACC/register.json"
curl -fsS -X POST "http://localhost:$PORT/api/repos" \
  -H 'Content-Type: application/json' --data-binary "@$ACC/register.json" \
  > "$ACC/registered.json" || exit 1
ID=$(jq -er --arg path "$REPO" '.repos[] | select(.path==$path) | .id' "$ACC/registered.json") || exit 1
curl -fsS --max-time 1200 -X POST "http://localhost:$PORT/api/repos/$ID/scan/deps" \
  > "$ACC/deps.json" || exit 1
curl -fsS "http://localhost:$PORT/api/repos/$ID" > "$ACC/detail.json" || exit 1

sqlite3 "$ACC/dashboard.db" "PRAGMA table_info(dependencies)"
jq . "$ACC/status.json"
jq '.working_state | {missing_dep_tools, dep_manifests, dep_check_error}' "$ACC/detail.json"
jq '[.[] .packages[] | {name, source_path, severity, outdated_state, vuln_state, check_note}]' "$ACC/deps.json"
```

Compare results against the task contracts and regression fixtures. Build the
discovery comparison from tracked candidates filtered by the traversal policy;
report excluded paths instead of treating them as discovered. Use inventory
records for empty files and includes, rather than requiring dependency groups
for them. Compare lock provenance using the unique/ambiguous/absent-name
regression. Diagnose tool failures from exit status, stderr, and result shape;
do not attribute failure to batching without evidence. Report unavailable
network/tool coverage as an unmet acceptance gate with reasons, separately from
implementation/test failures.

Inspect the Dependencies tab, fleet coverage, overlap expansion, and downloaded
reports using the report-format browser regressions as the checklist. Retain
only sanitized evidence needed for the handoff outside the public checkout;
let the cleanup function remove this run's disposable runtime after inspection.

Do not start the candidate against the live database. Before a later authorized
live migration, reuse the read-only snapshot procedure to retain a backup in
Kevin's chosen private destination, then verify the release identity at its
actual launch location according to the repository's release instructions.
