"""Tests for Packet 14: Node Dep Health (Outdated + Vuln).

Tests cover:
  - check_node_outdated()
  - check_node_vulns()
  - check_node_deps()

Run from project root:
    .venv/bin/python -m pytest tests/test_node_dep_health.py -v
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import git_dashboard as gd


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_npm_dep(name: str, version: str = "^1.0.0") -> dict:
    return {"name": name, "version": version, "manager": "npm"}


def _mock_proc(stdout: str, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    return proc


def _write_npm_lock(directory, versions):
    (directory / 'package-lock.json').write_text(json.dumps({
        'lockfileVersion': 3,
        'packages': {f'node_modules/{name}': {'version': version} for name, version in versions.items()},
    }))


def _npm_outdated_output(packages: dict) -> str:
    """Build npm outdated --json output.

    packages: {name: {"current": "x", "wanted": "y", "latest": "z"}}
    """
    out = {}
    for name, info in packages.items():
        out[name] = {
            "current": info["current"],
            "wanted": info["wanted"],
            "latest": info["latest"],
            "dependent": "myapp",
            "location": f"node_modules/{name}",
        }
    return json.dumps(out)


def _npm_audit_output(vulnerabilities: dict) -> str:
    """Build npm audit --json output.

    vulnerabilities: {name: {"severity": "high"|"moderate"|"low"|"critical"}}
    """
    vulns = {}
    for name, info in vulnerabilities.items():
        vulns[name] = {
            "name": name,
            "severity": info["severity"],
            "via": [{"source": 1234, "name": name, "title": "Test Vulnerability"}],
            "nodes": [f"node_modules/{name}"],
            "range": "*",
            "isDirect": True,
            "effects": [],
            "fixAvailable": True,
        }
    return json.dumps({"vulnerabilities": vulns})


# ── check_node_outdated ────────────────────────────────────────────────────────


def test_check_node_outdated_npm_not_available(tmp_path):
    """Test 1: When npm is None, deps returned unchanged."""
    original = gd.TOOLS.get("npm")
    gd.TOOLS["npm"] = None
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        result = gd.check_node_outdated(tmp_path, [dep])
        assert result[0]["name"] == "react"
        assert result[0]["version"] == "^18.2.0"
        # No health data enriched — severity, advisory_id, checked_at not set
        assert "severity" not in result[0]
        assert "advisory_id" not in result[0]
        assert "checked_at" not in result[0]
        assert len(result) == 1
    finally:
        gd.TOOLS["npm"] = original


def test_check_node_outdated_up_to_date(tmp_path):
    """Test 2: absent npm row plus concrete version and registry comparison is clean."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        _write_npm_lock(tmp_path, {'react': '18.2.0'})
        proc = _mock_proc(json.dumps({}), returncode=0)
        with patch("subprocess.run", side_effect=[proc, _mock_proc('"18.2.0"')]):
            result = gd.check_node_outdated(tmp_path, [dep])
        r = result[0]
        assert r["severity"] == "ok"
        assert "checked_at" in r
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_outdated_minor_update(tmp_path):
    """Test 3: Single dep with minor update, severity=outdated."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        stdout = _npm_outdated_output(
            {"react": {"current": "18.2.0", "wanted": "18.3.1", "latest": "18.3.1"}}
        )
        proc = _mock_proc(stdout, returncode=1)  # npm outdated exits 1 when outdated
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_outdated(tmp_path, [dep])
        r = result[0]
        assert r["current_version"] == "18.2.0"
        assert r["wanted_version"] == "18.3.1"
        assert r["latest_version"] == "18.3.1"
        assert r["severity"] == "outdated"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_outdated_major_update(tmp_path):
    """Test 4: Single dep with major version update, severity=major."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("express", "^4.18.0")
        stdout = _npm_outdated_output(
            {"express": {"current": "4.18.0", "wanted": "4.21.0", "latest": "5.0.0"}}
        )
        proc = _mock_proc(stdout, returncode=1)
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_outdated(tmp_path, [dep])
        r = result[0]
        assert r["latest_version"] == "5.0.0"
        assert r["severity"] == "major"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_outdated_multiple_deps_mixed(tmp_path):
    """Test 5: 3 deps: one up-to-date, one outdated, one major."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        deps = [
            _make_npm_dep("lodash", "^4.17.21"),   # up-to-date (not in output)
            _make_npm_dep("axios", "^0.27.0"),      # outdated (same major)
            _make_npm_dep("webpack", "^4.0.0"),     # major update
        ]
        stdout = _npm_outdated_output(
            {
                "axios":   {"current": "0.27.0", "wanted": "0.27.2", "latest": "0.27.2"},
                "webpack": {"current": "4.46.0", "wanted": "4.46.0", "latest": "5.88.0"},
            }
        )
        proc = _mock_proc(stdout, returncode=1)
        _write_npm_lock(tmp_path, {'lodash': '4.17.21'})
        with patch("subprocess.run", side_effect=[proc, _mock_proc('"4.17.21"')]):
            result = gd.check_node_outdated(tmp_path, deps)

        by_name = {r["name"]: r for r in result}
        assert by_name["lodash"]["severity"] == "ok"
        assert by_name["axios"]["severity"] == "outdated"
        assert by_name["webpack"]["severity"] == "major"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_outdated_subprocess_fails(tmp_path):
    """Test 6: subprocess raises CalledProcessError — no crash, deps returned unchanged."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "npm")):
            result = gd.check_node_outdated(tmp_path, [dep])
        # No crash; dep returned (possibly unchanged or with defaults)
        assert len(result) == 1
        assert result[0]["name"] == "react"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_outdated_invalid_json(tmp_path):
    """Test 7: npm returns non-JSON stdout — no crash, deps returned unchanged."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        proc = _mock_proc("not valid json{", returncode=0)
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_outdated(tmp_path, [dep])
        assert len(result) == 1
        assert result[0]["name"] == "react"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_outdated_exit_code_1_parsed(tmp_path):
    """Test 8: npm outdated exits with code 1 (normal for outdated deps) — output still parsed."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        stdout = _npm_outdated_output(
            {"react": {"current": "18.2.0", "wanted": "18.3.0", "latest": "18.3.0"}}
        )
        proc = _mock_proc(stdout, returncode=1)  # non-zero exit = outdated packages found
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_outdated(tmp_path, [dep])
        r = result[0]
        assert r["severity"] == "outdated"
        assert r["current_version"] == "18.2.0"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_outdated_dep_not_in_output(tmp_path):
    """Test 9: an absent row is clean only after its own version comparison."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("lodash", "^4.17.21")
        # npm outdated returns info about some other package, not lodash
        stdout = _npm_outdated_output(
            {"some-other-pkg": {"current": "1.0.0", "wanted": "2.0.0", "latest": "2.0.0"}}
        )
        proc = _mock_proc(stdout, returncode=1)
        _write_npm_lock(tmp_path, {'lodash': '4.17.21'})
        with patch("subprocess.run", side_effect=[proc, _mock_proc('"4.17.21"')]):
            result = gd.check_node_outdated(tmp_path, [dep])
        r = result[0]
        assert r["severity"] == "ok"
    finally:
        gd.TOOLS["npm"] = None


# ── check_node_vulns ──────────────────────────────────────────────────────────


def test_check_node_vulns_npm_not_available(tmp_path):
    """Test 10: TOOLS["npm"] is None — deps returned unchanged."""
    original = gd.TOOLS.get("npm")
    gd.TOOLS["npm"] = None
    try:
        dep = {**_make_npm_dep("lodash"), "severity": "ok", "advisory_id": None}
        result = gd.check_node_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
        assert result[0]["advisory_id"] is None
    finally:
        gd.TOOLS["npm"] = original


def test_check_node_vulns_no_vulnerabilities(tmp_path):
    """Test 11: npm audit returns empty vulnerabilities — deps unchanged."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = {**_make_npm_dep("react"), "severity": "ok", "advisory_id": None}
        _write_npm_lock(tmp_path, {'react': '1.0.0'})
        proc = _mock_proc(_npm_audit_output({}), returncode=0)
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
        assert result[0]["advisory_id"] is None
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_vulns_one_vulnerable_dep(tmp_path):
    """Test 12: npm audit reports one vulnerable dep — severity=vulnerable, advisory_id set."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    _write_npm_lock(tmp_path, {'lodash': '1.0.0'})
    try:
        dep = {**_make_npm_dep("lodash"), "severity": "ok", "advisory_id": None}
        audit_out = _npm_audit_output({"lodash": {"severity": "high"}})
        proc = _mock_proc(audit_out, returncode=1)
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_vulns(tmp_path, [dep])
        r = result[0]
        assert r["severity"] == "vulnerable"
        assert r["advisory_id"] == "npm:lodash"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_vulns_overrides_outdated(tmp_path):
    """Test 13: vuln overrides prior severity=outdated."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    _write_npm_lock(tmp_path, {'lodash': '1.0.0'})
    try:
        dep = {**_make_npm_dep("lodash"), "severity": "outdated", "advisory_id": None}
        audit_out = _npm_audit_output({"lodash": {"severity": "critical"}})
        proc = _mock_proc(audit_out, returncode=1)
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "vulnerable"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_vulns_subprocess_fails(tmp_path):
    """Test 14: subprocess raises CalledProcessError — no crash, coverage marked unchecked."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = {**_make_npm_dep("react"), "severity": "ok", "advisory_id": None}
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "npm")):
            result = gd.check_node_vulns(tmp_path, [dep])
        assert result[0]["severity"] == gd.derive_severity(result[0]) == "unchecked"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_vulns_unexpected_json(tmp_path):
    """Test 15: npm audit returns JSON missing 'vulnerabilities' key — no crash, deps unchanged."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = {**_make_npm_dep("react"), "severity": "ok", "advisory_id": None}
        proc = _mock_proc(json.dumps({"metadata": {}, "auditReportVersion": 2}), returncode=0)
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_vulns(tmp_path, [dep])
        assert result[0]["severity"] == gd.derive_severity(result[0]) == "unchecked"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_vulns_no_lockfile_fallback(tmp_path):
    """Test 16: npm audit fails (e.g. no package-lock.json) — graceful fallback, deps unchanged."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = {**_make_npm_dep("react"), "severity": "ok", "advisory_id": None}
        # Simulate npm audit failing with non-JSON stderr output (no lockfile scenario)
        proc = _mock_proc("", returncode=1)
        with patch("subprocess.run", return_value=proc):
            result = gd.check_node_vulns(tmp_path, [dep])
        assert result[0]["severity"] == gd.derive_severity(result[0]) == "unchecked"
    finally:
        gd.TOOLS["npm"] = None


# ── check_node_deps ────────────────────────────────────────────────────────────


def test_check_node_deps_full_pipeline(tmp_path):
    """Test 17: Full pipeline — outdated + vulnerable dep, correct severities."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    _write_npm_lock(tmp_path, {'axios': '0.27.0', 'lodash': '4.17.0'})
    try:
        deps = [
            _make_npm_dep("axios", "^0.27.0"),
            _make_npm_dep("lodash", "^4.17.0"),
        ]
        outdated_stdout = _npm_outdated_output(
            {"axios": {"current": "0.27.0", "wanted": "0.27.2", "latest": "0.27.2"}}
        )
        audit_stdout = _npm_audit_output({"lodash": {"severity": "high"}})

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "outdated" in cmd:
                return _mock_proc(outdated_stdout, returncode=1)
            elif "audit" in cmd:
                return _mock_proc(audit_stdout, returncode=1)
            return _mock_proc("{}", returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            result = gd.check_node_deps(tmp_path, deps)

        by_name = {r["name"]: r for r in result}
        assert by_name["axios"]["severity"] == "outdated"
        assert by_name["lodash"]["severity"] == "vulnerable"
        assert by_name["lodash"]["advisory_id"] == "npm:lodash"
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_deps_npm_not_available(tmp_path):
    """Test 18: TOOLS["npm"] is None — all checks skipped, no crash."""
    original = gd.TOOLS.get("npm")
    gd.TOOLS["npm"] = None
    try:
        deps = [_make_npm_dep("react"), _make_npm_dep("vue")]
        result = gd.check_node_deps(tmp_path, deps)
        assert len(result) == 2
        assert all(r["name"] in ("react", "vue") for r in result)
    finally:
        gd.TOOLS["npm"] = original


def test_check_node_deps_empty_list(tmp_path):
    """Test 19: Empty dep list — returns []."""
    result = gd.check_node_deps(tmp_path, [])
    assert result == []


def test_check_node_deps_enriched_output_shape(tmp_path):
    """Test 20: All returned dicts contain the required 9 fields."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        proc_outdated = _mock_proc(json.dumps({}), returncode=0)
        proc_audit = _mock_proc(_npm_audit_output({}), returncode=0)

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "outdated" in cmd:
                return proc_outdated
            return proc_audit

        with patch("subprocess.run", side_effect=fake_run):
            result = gd.check_node_deps(tmp_path, [dep])

        assert len(result) == 1
        r = result[0]
        required_fields = {
            "name", "version", "manager",
            "current_version", "wanted_version", "latest_version",
            "severity", "advisory_id", "checked_at",
        }
        assert required_fields.issubset(r.keys()), (
            f"Missing fields: {required_fields - r.keys()}"
        )
    finally:
        gd.TOOLS["npm"] = None


def test_check_node_deps_non_npm_deps_unchanged(tmp_path):
    """Non-npm deps are returned unchanged without being passed to npm commands."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        deps = [
            _make_npm_dep("react", "^18.0.0"),
            {"name": "flask", "version": "3.0.0", "manager": "pip"},
            {"name": "github.com/gin-gonic/gin", "version": "v1.9.1", "manager": "gomod"},
        ]
        proc_outdated = _mock_proc(json.dumps({}), returncode=0)
        proc_audit = _mock_proc(_npm_audit_output({}), returncode=0)

        call_idx = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if "outdated" in cmd:
                return proc_outdated
            return proc_audit

        with patch("subprocess.run", side_effect=fake_run):
            result = gd.check_node_deps(tmp_path, deps)

        # All 3 deps come back
        assert len(result) == 3
        by_name = {r["name"]: r for r in result}
        # Non-npm deps unchanged
        assert by_name["flask"]["manager"] == "pip"
        assert by_name["github.com/gin-gonic/gin"]["manager"] == "gomod"
        # npm dep enriched
        assert "checked_at" in by_name["react"]
    finally:
        gd.TOOLS["npm"] = None


def test_unlisted_npm_declaration_is_not_a_concrete_current(tmp_path):
    with patch.dict(gd.TOOLS, npm='synthetic-tool'), patch('subprocess.run', return_value=_mock_proc('{}')):
        row = gd.check_node_deps(tmp_path, [_make_npm_dep('synthetic', '^1.0')])[0]
    assert row['current_version'] is None
    assert row['outdated_state'] == 'unchecked'


def test_tool_failure_logging_is_bounded(tmp_path, caplog):
    proc = _mock_proc('{}', 97)
    proc.stderr = 'synthetic ignored first line\n' + 'x' * 400
    with patch.dict(gd.TOOLS, npm='synthetic-tool'), patch('subprocess.run', return_value=proc):
        gd.check_node_deps(tmp_path, [_make_npm_dep('synthetic')])
    assert 'synthetic ignored first line' not in caplog.text
    assert 'x' * 241 not in caplog.text


def _node_check(tmp_path, monkeypatch, output, *, code=1):
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    with patch('subprocess.run', return_value=_mock_proc(json.dumps(output), code)):
        return gd.check_node_outdated(tmp_path, [_make_npm_dep('synthetic-widget')])[0]


@pytest.mark.parametrize('layout', [1, 2, 3])
def test_node_current_version_from_lock(tmp_path, monkeypatch, layout):
    lock = {'lockfileVersion': layout}
    if layout == 1:
        lock['dependencies'] = {'synthetic-widget': {'version': '1.0.0'}}
    else:
        lock['packages'] = {'node_modules/synthetic-widget': {'version': '1.0.0'}}
    (tmp_path / 'package-lock.json').write_text(json.dumps(lock))
    row = _node_check(tmp_path, monkeypatch, {'synthetic-widget': {'latest': '2.0.0'}})
    assert row['current_version'] == '1.0.0'
    assert row['outdated_state'] == 'checked'
    assert row['severity'] == 'major'


def test_node_current_version_from_installed_metadata(tmp_path, monkeypatch):
    package = tmp_path / 'node_modules/synthetic-widget/package.json'
    package.parent.mkdir(parents=True)
    package.write_text(json.dumps({'name': 'synthetic-widget', 'version': '1.0.0'}))
    row = _node_check(tmp_path, monkeypatch, {'synthetic-widget': {'latest': '1.2.0'}})
    assert row['current_version'] == '1.0.0'
    assert row['outdated_state'] == 'checked'
    assert row['severity'] == 'outdated'


@pytest.mark.parametrize('current', [None, 'MISSING', '^1.0', '', 1, {}])
def test_node_missing_version_is_unchecked(tmp_path, monkeypatch, current):
    row = _node_check(tmp_path, monkeypatch, {'synthetic-widget': {'current': current, 'latest': '2.0.0'}})
    assert row['outdated_state'] == 'unchecked'
    assert 'version' in row['check_note']


def test_node_empty_output_without_version_is_unchecked(tmp_path, monkeypatch):
    row = _node_check(tmp_path, monkeypatch, {}, code=0)
    assert row['outdated_state'] == 'unchecked'
    assert row['current_version'] is None
    assert row['check_note']


def test_node_absent_row_without_comparison_is_unchecked(tmp_path, monkeypatch):
    (tmp_path / 'package-lock.json').write_text(json.dumps({
        'lockfileVersion': 3, 'packages': {'node_modules/synthetic-widget': {'version': '1.0.0'}}}))
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    with patch('subprocess.run', side_effect=[_mock_proc('{}'), _mock_proc('{}')]):
        row = gd.check_node_outdated(tmp_path, [_make_npm_dep('synthetic-widget')])[0]
    assert row['outdated_state'] == 'unchecked'
    assert row['current_version'] == '1.0.0'
    assert 'comparison' in row['check_note']


def test_node_empty_output_with_registry_evidence_is_checked(tmp_path, monkeypatch):
    (tmp_path / 'package-lock.json').write_text(json.dumps({
        'lockfileVersion': 3, 'packages': {'node_modules/synthetic-widget': {'version': '1.0.0'}}}))
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    with patch('subprocess.run', side_effect=[_mock_proc('{}'), _mock_proc('"1.0.0"')]):
        row = gd.check_node_outdated(tmp_path, [_make_npm_dep('synthetic-widget')])[0]
    assert row['current_version'] == row['latest_version'] == '1.0.0'
    assert row['outdated_state'] == 'checked'
    assert row['severity'] == 'ok'


def test_node_audit_lock_error_is_unchecked(tmp_path, monkeypatch):
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    with patch('subprocess.run', return_value=_mock_proc(json.dumps({'error': {'code': 'ENOLOCK'}}), 1)):
        row = gd.check_node_vulns(tmp_path, [_make_npm_dep('synthetic-widget')])[0]
    assert row['vuln_state'] == 'unchecked'
    assert 'lockfile' in row['check_note']


def test_node_audit_error_object_is_unchecked(tmp_path, monkeypatch):
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    with patch('subprocess.run', return_value=_mock_proc(json.dumps({
            'error': {'code': 'SYNTHETIC_ERROR'}, 'vulnerabilities': {}}), 1)):
        row = gd.check_node_vulns(tmp_path, [_make_npm_dep('synthetic-widget')])[0]
    assert row['vuln_state'] == 'unchecked'
    assert row['check_note']


@pytest.mark.parametrize('vulnerable', [False, True])
@pytest.mark.parametrize('current', ['1.0.0', '2.0.0'])
def test_node_audit_requires_displayed_version_match(tmp_path, monkeypatch, vulnerable, current):
    """Lock-tree results must never certify a different installed current version."""
    (tmp_path / 'package.json').write_text(json.dumps({
        'dependencies': {'synthetic-widget': '^1.0.0'}}))
    _write_npm_lock(tmp_path, {'synthetic-widget': '1.0.0'})
    audit = json.loads(_npm_audit_output({'synthetic-widget': {'severity': 'high'}} if vulnerable else {}))
    if vulnerable:
        audit['vulnerabilities']['synthetic-widget']['nodes'] = ['node_modules/synthetic-widget']
    outdated = _npm_outdated_output({'synthetic-widget': dict(current=current, wanted=current, latest=current)})
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    with patch('subprocess.run', side_effect=[_mock_proc(outdated), _mock_proc(json.dumps(audit), int(vulnerable))]):
        row = gd.check_node_deps(tmp_path, gd.parse_package_json(tmp_path / 'package.json'))[0]
    assert row['current_version'] == current
    assert row['outdated_state'] == 'checked'
    if current == '2.0.0':
        assert row['vuln_state'] == 'unchecked'
        assert 'version' in row['check_note'] and '1.0.0' in row['check_note'] and '2.0.0' in row['check_note']
        assert row['severity'] == 'unchecked'
        assert row['advisory_id'] is None
    else:
        assert row['vuln_state'] == 'checked'
        assert row['severity'] == ('vulnerable' if vulnerable else 'ok')


def test_node_audit_same_name_nested_finding_does_not_taint_direct_node(tmp_path, monkeypatch):
    """npm aggregates same-name nodes; only an affected direct node is our finding."""
    _write_npm_lock(tmp_path, {'synthetic-widget': '2.0.0', 'synthetic-parent': '1.0.0'})
    lock_path = tmp_path / 'package-lock.json'
    lock = json.loads(lock_path.read_text())
    lock['packages']['node_modules/synthetic-parent/node_modules/synthetic-widget'] = {'version': '1.0.0'}
    lock_path.write_text(json.dumps(lock))
    audit = json.loads(_npm_audit_output({'synthetic-widget': {'severity': 'high'}}))
    audit['vulnerabilities']['synthetic-widget']['nodes'] = ['node_modules/synthetic-parent/node_modules/synthetic-widget']
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    dep = dict(_make_npm_dep('synthetic-widget'), current_version='2.0.0', latest_version='2.0.0',
               outdated_state='checked', severity='ok')
    with patch('subprocess.run', return_value=_mock_proc(json.dumps(audit), 1)):
        row = gd.finalize_dep_health(gd.check_node_vulns(tmp_path, [dep]))[0]
    assert row['vuln_state'] == 'checked'
    assert row['severity'] == 'ok'
    assert row['advisory_id'] is None


@pytest.mark.parametrize('nodes', [None, [], 'node_modules/synthetic-widget', [42]])
def test_node_audit_missing_node_evidence_is_unchecked(tmp_path, monkeypatch, nodes):
    _write_npm_lock(tmp_path, {'synthetic-widget': '1.0.0'})
    audit = json.loads(_npm_audit_output({'synthetic-widget': {'severity': 'high'}}))
    audit['vulnerabilities']['synthetic-widget']['nodes'] = nodes
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    with patch('subprocess.run', return_value=_mock_proc(json.dumps(audit), 1)):
        row = gd.check_node_vulns(tmp_path, [dict(_make_npm_dep('synthetic-widget'), current_version='1.0.0')])[0]
    assert row['vuln_state'] == 'unchecked'
    assert not row.get('advisory_id')


@pytest.mark.parametrize('vulnerable', [False, True])
def test_node_audit_requires_concrete_lock_evidence(tmp_path, monkeypatch, vulnerable):
    """Neither absent current nor absent audit version can certify coverage."""
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    audit = _npm_audit_output({'synthetic-widget': {'severity': 'high'}} if vulnerable else {})
    with patch('subprocess.run', return_value=_mock_proc(audit, int(vulnerable))):
        row = gd.finalize_dep_health(gd.check_node_vulns(tmp_path, [_make_npm_dep('synthetic-widget')]))[0]
    assert row['current_version'] is None
    assert row['vuln_state'] == 'unchecked'
    assert 'lock evidence' in row['check_note']
    assert row['advisory_id'] is None
    assert row['severity'] == 'unchecked'


@pytest.mark.parametrize('layout', [1, 2, 3])
def test_node_shrinkwrap_precedes_package_lock_for_current_and_audit(tmp_path, monkeypatch, layout):
    _write_npm_lock(tmp_path, {'synthetic-widget': '1.0.0'})
    shrinkwrap = dict(lockfileVersion=layout)
    if layout == 1:
        shrinkwrap['dependencies'] = {'synthetic-widget': {'version': '2.0.0'}}
    else:
        shrinkwrap['packages'] = {'node_modules/synthetic-widget': {'version': '2.0.0'}}
    (tmp_path / 'npm-shrinkwrap.json').write_text(json.dumps(shrinkwrap))
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    def run(cmd, **kwargs):
        if cmd[1] == 'outdated':
            return _mock_proc('{}')
        if cmd[1] == 'view':
            return _mock_proc('"2.0.0"')
        assert cmd[1] == 'audit'
        return _mock_proc(_npm_audit_output({}))
    with patch('subprocess.run', side_effect=run):
        row = gd.check_node_deps(tmp_path, [_make_npm_dep('synthetic-widget')])[0]
    assert row['current_version'] == '2.0.0'
    assert row['outdated_state'] == row['vuln_state'] == 'checked'
    assert row['severity'] == 'ok'


@pytest.mark.parametrize('shrinkwrap', ['{', '{"lockfileVersion":99}', '{"lockfileVersion":3,"packages":[]}'])
def test_node_invalid_selected_shrinkwrap_never_uses_package_lock(tmp_path, monkeypatch, shrinkwrap):
    _write_npm_lock(tmp_path, {'synthetic-widget': '1.0.0'})
    (tmp_path / 'npm-shrinkwrap.json').write_text(shrinkwrap)
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-npm')
    output = _npm_outdated_output({'synthetic-widget': dict(current='1.0.0', wanted='1.0.0', latest='1.0.0')})
    with patch('subprocess.run', side_effect=[_mock_proc(output), _mock_proc(_npm_audit_output({}))]):
        row = gd.check_node_deps(tmp_path, [_make_npm_dep('synthetic-widget')])[0]
    assert row['current_version'] == '1.0.0'
    assert row['outdated_state'] == 'checked'
    assert row['vuln_state'] == 'unchecked'
    assert 'lock evidence' in row['check_note']
    assert row['severity'] == 'unchecked'
