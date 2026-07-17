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
from pathlib import Path
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
    """Test 2: npm outdated returns {} — dep is up to date, severity=ok."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("react", "^18.2.0")
        proc = _mock_proc(json.dumps({}), returncode=0)
        with patch("subprocess.run", return_value=proc):
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
        with patch("subprocess.run", return_value=proc):
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
    """Test 9: dep not in npm outdated output (up-to-date) — severity=ok."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = _make_npm_dep("lodash", "^4.17.21")
        # npm outdated returns info about some other package, not lodash
        stdout = _npm_outdated_output(
            {"some-other-pkg": {"current": "1.0.0", "wanted": "2.0.0", "latest": "2.0.0"}}
        )
        proc = _mock_proc(stdout, returncode=1)
        with patch("subprocess.run", return_value=proc):
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
    """Test 14: subprocess raises CalledProcessError — no crash, deps returned unchanged."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
    try:
        dep = {**_make_npm_dep("react"), "severity": "ok", "advisory_id": None}
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "npm")):
            result = gd.check_node_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
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
        assert result[0]["severity"] == "ok"
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
        assert result[0]["severity"] == "ok"
    finally:
        gd.TOOLS["npm"] = None


# ── check_node_deps ────────────────────────────────────────────────────────────


def test_check_node_deps_full_pipeline(tmp_path):
    """Test 17: Full pipeline — outdated + vulnerable dep, correct severities."""
    gd.TOOLS["npm"] = "/usr/bin/npm"
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


def test_check_node_deps_classify_severity_reused(tmp_path):
    """Verify classify_severity from packet 13 is used (check it exists as module function)."""
    # Ensure the function is accessible as a module-level symbol (not duplicated inside node funcs)
    assert callable(gd.classify_severity)
    # And it still works correctly (regression guard)
    assert gd.classify_severity("4.0.0", "5.0.0") == "major"
    assert gd.classify_severity("2.1.0", "2.3.0") == "outdated"
    assert gd.classify_severity("3.0.0", "3.0.0") == "ok"
