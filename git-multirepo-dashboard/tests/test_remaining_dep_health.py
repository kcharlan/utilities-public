"""Tests for Packet 15: Go / Rust / Ruby / PHP Dep Health.

Tests cover:
  - check_go_outdated(), check_go_vulns(), check_go_deps()
  - check_rust_outdated(), check_rust_vulns(), check_rust_deps()
  - check_ruby_outdated(), check_ruby_vulns(), check_ruby_deps()
  - check_php_outdated(), check_php_vulns(), check_php_deps()
  - Cross-ecosystem: required fields, severity escalation, classify_severity reuse

Run from project root:
    .venv/bin/python -m pytest tests/test_remaining_dep_health.py -v
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import git_dashboard as gd


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_proc(stdout: str, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    return proc


def _make_dep(name: str, version: str, manager: str) -> dict:
    return {"name": name, "version": version, "manager": manager}


_REQUIRED_FIELDS = {
    "name", "version", "manager",
    "current_version", "wanted_version", "latest_version",
    "severity", "advisory_id", "checked_at",
}

FAKE_TOOL_PATH = "/usr/local/bin/fake-tool"


# ══════════════════════════════════════════════════════════════════════════════
# Go Ecosystem Tests
# ══════════════════════════════════════════════════════════════════════════════


# Test 1
def test_check_go_outdated_go_not_available(tmp_path):
    """When go is None, deps returned unchanged."""
    original = gd.TOOLS.get("go")
    gd.TOOLS["go"] = None
    try:
        dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
        result = gd.check_go_outdated(tmp_path, [dep])
        assert result[0]["name"] == "github.com/gin-gonic/gin"
        assert result[0]["version"] == "v1.9.1"
        # No version enrichment fields added
        assert "current_version" not in result[0]
    finally:
        gd.TOOLS["go"] = original


# Test 2
def test_check_go_outdated_up_to_date(tmp_path):
    """Single dep, up-to-date: no Update field → severity='ok', latest=current."""
    gd.TOOLS["go"] = FAKE_TOOL_PATH
    ndjson_out = json.dumps({
        "Path": "github.com/gin-gonic/gin",
        "Version": "v1.9.1",
        "Main": False,
    })
    with patch("subprocess.run", return_value=_mock_proc(ndjson_out)):
        dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
        result = gd.check_go_outdated(tmp_path, [dep])
    d = result[0]
    assert d["severity"] == "ok"
    assert d["latest_version"] == "v1.9.1"
    assert d["current_version"] == "v1.9.1"


# Test 3
def test_check_go_outdated_outdated(tmp_path):
    """Single dep, minor update: severity='outdated'."""
    gd.TOOLS["go"] = FAKE_TOOL_PATH
    ndjson_out = json.dumps({
        "Path": "github.com/gin-gonic/gin",
        "Version": "v1.9.1",
        "Update": {"Path": "github.com/gin-gonic/gin", "Version": "v1.10.0"},
    })
    with patch("subprocess.run", return_value=_mock_proc(ndjson_out)):
        dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
        result = gd.check_go_outdated(tmp_path, [dep])
    d = result[0]
    assert d["current_version"] == "v1.9.1"
    assert d["latest_version"] == "v1.10.0"
    assert d["severity"] == "outdated"


# Test 4
def test_check_go_outdated_major_update(tmp_path):
    """Major version bump → severity='major'."""
    gd.TOOLS["go"] = FAKE_TOOL_PATH
    ndjson_out = json.dumps({
        "Path": "github.com/gin-gonic/gin",
        "Version": "v1.9.1",
        "Update": {"Path": "github.com/gin-gonic/gin", "Version": "v2.0.0"},
    })
    with patch("subprocess.run", return_value=_mock_proc(ndjson_out)):
        dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
        result = gd.check_go_outdated(tmp_path, [dep])
    assert result[0]["severity"] == "major"


# Test 5
def test_check_go_outdated_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["go"] = FAKE_TOOL_PATH
    dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
    with patch("subprocess.run", side_effect=Exception("timeout")):
        result = gd.check_go_outdated(tmp_path, [dep])
    assert result[0]["name"] == "github.com/gin-gonic/gin"
    assert "severity" not in result[0]


# Test 6
def test_check_go_outdated_invalid_output(tmp_path):
    """Non-JSON stdout → no crash, deps returned unchanged."""
    gd.TOOLS["go"] = FAKE_TOOL_PATH
    dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
    with patch("subprocess.run", return_value=_mock_proc("not json at all")):
        result = gd.check_go_outdated(tmp_path, [dep])
    assert result[0]["name"] == "github.com/gin-gonic/gin"
    assert "severity" not in result[0]


# Test 7
def test_check_go_vulns_govulncheck_not_available(tmp_path):
    """When govulncheck is None, deps returned unchanged."""
    original = gd.TOOLS.get("govulncheck")
    gd.TOOLS["govulncheck"] = None
    try:
        dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
        dep["severity"] = "ok"
        result = gd.check_go_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
        assert "advisory_id" not in result[0]
    finally:
        gd.TOOLS["govulncheck"] = original


# Test 8
def test_check_go_vulns_vulnerability_found(tmp_path):
    """Vuln found → severity='vulnerable', advisory_id=OSV ID."""
    gd.TOOLS["govulncheck"] = FAKE_TOOL_PATH
    vuln_json = json.dumps({
        "Vulns": [
            {
                "OSV": {"id": "GO-2024-1234", "aliases": ["CVE-2024-1234"]},
                "Modules": [{"Path": "github.com/gin-gonic/gin"}],
            }
        ]
    })
    with patch("subprocess.run", return_value=_mock_proc(vuln_json)):
        dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
        dep["severity"] = "ok"
        result = gd.check_go_vulns(tmp_path, [dep])
    d = result[0]
    assert d["severity"] == "vulnerable"
    assert d["advisory_id"] == "GO-2024-1234"


# Test 9
def test_check_go_vulns_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["govulncheck"] = FAKE_TOOL_PATH
    dep = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
    dep["severity"] = "ok"
    with patch("subprocess.run", side_effect=Exception("error")):
        result = gd.check_go_vulns(tmp_path, [dep])
    assert result[0]["severity"] == "ok"


# Test 10
def test_check_go_deps_full_pipeline(tmp_path):
    """2 deps: one outdated, one vulnerable. Correct final severities."""
    gd.TOOLS["go"] = FAKE_TOOL_PATH
    gd.TOOLS["govulncheck"] = FAKE_TOOL_PATH

    dep1 = _make_dep("github.com/gin-gonic/gin", "v1.9.1", "gomod")
    dep2 = _make_dep("github.com/gorilla/mux", "v1.8.0", "gomod")

    outdated_ndjson = (
        json.dumps({
            "Path": "github.com/gin-gonic/gin",
            "Version": "v1.9.1",
            "Update": {"Path": "github.com/gin-gonic/gin", "Version": "v1.10.0"},
        }) + "\n" +
        json.dumps({
            "Path": "github.com/gorilla/mux",
            "Version": "v1.8.0",
        })
    )
    vuln_json = json.dumps({
        "Vulns": [
            {
                "OSV": {"id": "GO-2024-9999"},
                "Modules": [{"Path": "github.com/gorilla/mux"}],
            }
        ]
    })

    side_effects = [_mock_proc(outdated_ndjson), _mock_proc(vuln_json)]
    with patch("subprocess.run", side_effect=side_effects):
        result = gd.check_go_deps(tmp_path, [dep1, dep2])

    by_name = {d["name"]: d for d in result}
    assert by_name["github.com/gin-gonic/gin"]["severity"] == "outdated"
    assert by_name["github.com/gorilla/mux"]["severity"] == "vulnerable"
    assert by_name["github.com/gorilla/mux"]["advisory_id"] == "GO-2024-9999"


# Test 11
def test_check_go_deps_empty_list(tmp_path):
    """Empty dep list → returns []."""
    result = gd.check_go_deps(tmp_path, [])
    assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# Rust Ecosystem Tests
# ══════════════════════════════════════════════════════════════════════════════


# Test 12
def test_check_rust_outdated_not_available(tmp_path):
    """When cargo_outdated is None, deps returned unchanged."""
    original = gd.TOOLS.get("cargo_outdated")
    gd.TOOLS["cargo_outdated"] = None
    try:
        dep = _make_dep("serde", "1.0.190", "cargo")
        result = gd.check_rust_outdated(tmp_path, [dep])
        assert result[0]["name"] == "serde"
        assert "current_version" not in result[0]
    finally:
        gd.TOOLS["cargo_outdated"] = original


# Test 13
def test_check_rust_outdated_single_outdated(tmp_path):
    """Single dep, minor update → severity='outdated'."""
    gd.TOOLS["cargo_outdated"] = FAKE_TOOL_PATH
    cargo_json = json.dumps({
        "dependencies": [
            {"name": "serde", "project": "1.0.190", "compat": "1.0.210",
             "latest": "1.0.210", "kind": "Normal"}
        ]
    })
    with patch("subprocess.run", return_value=_mock_proc(cargo_json)):
        dep = _make_dep("serde", "1.0.190", "cargo")
        result = gd.check_rust_outdated(tmp_path, [dep])
    d = result[0]
    assert d["current_version"] == "1.0.190"
    assert d["latest_version"] == "1.0.210"
    assert d["severity"] == "outdated"


# Test 14
def test_check_rust_outdated_major_update(tmp_path):
    """Major version bump → severity='major'."""
    gd.TOOLS["cargo_outdated"] = FAKE_TOOL_PATH
    cargo_json = json.dumps({
        "dependencies": [
            {"name": "serde", "project": "1.0.190", "compat": "2.0.0",
             "latest": "2.0.0", "kind": "Normal"}
        ]
    })
    with patch("subprocess.run", return_value=_mock_proc(cargo_json)):
        dep = _make_dep("serde", "1.0.190", "cargo")
        result = gd.check_rust_outdated(tmp_path, [dep])
    assert result[0]["severity"] == "major"


# Test 15
def test_check_rust_outdated_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["cargo_outdated"] = FAKE_TOOL_PATH
    dep = _make_dep("serde", "1.0.190", "cargo")
    with patch("subprocess.run", side_effect=Exception("error")):
        result = gd.check_rust_outdated(tmp_path, [dep])
    assert result[0]["name"] == "serde"
    assert "severity" not in result[0]


# Test 16
def test_check_rust_vulns_not_available(tmp_path):
    """When cargo_audit is None, deps returned unchanged."""
    original = gd.TOOLS.get("cargo_audit")
    gd.TOOLS["cargo_audit"] = None
    try:
        dep = _make_dep("serde", "1.0.190", "cargo")
        dep["severity"] = "ok"
        result = gd.check_rust_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
    finally:
        gd.TOOLS["cargo_audit"] = original


# Test 17
def test_check_rust_vulns_vulnerability_found(tmp_path):
    """Vuln found → severity='vulnerable', advisory_id=RUSTSEC ID."""
    gd.TOOLS["cargo_audit"] = FAKE_TOOL_PATH
    audit_json = json.dumps({
        "vulnerabilities": {
            "list": [
                {
                    "advisory": {"id": "RUSTSEC-2024-0001", "title": "Test vuln"},
                    "package": {"name": "serde", "version": "1.0.190"},
                }
            ]
        }
    })
    with patch("subprocess.run", return_value=_mock_proc(audit_json)):
        dep = _make_dep("serde", "1.0.190", "cargo")
        dep["severity"] = "ok"
        result = gd.check_rust_vulns(tmp_path, [dep])
    d = result[0]
    assert d["severity"] == "vulnerable"
    assert d["advisory_id"] == "RUSTSEC-2024-0001"


# Test 18
def test_check_rust_vulns_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["cargo_audit"] = FAKE_TOOL_PATH
    dep = _make_dep("serde", "1.0.190", "cargo")
    dep["severity"] = "ok"
    with patch("subprocess.run", side_effect=Exception("error")):
        result = gd.check_rust_vulns(tmp_path, [dep])
    assert result[0]["severity"] == "ok"


# Test 19
def test_check_rust_deps_full_pipeline(tmp_path):
    """Full pipeline: outdated dep gets overridden to vulnerable."""
    gd.TOOLS["cargo_outdated"] = FAKE_TOOL_PATH
    gd.TOOLS["cargo_audit"] = FAKE_TOOL_PATH

    dep = _make_dep("serde", "1.0.190", "cargo")

    outdated_json = json.dumps({
        "dependencies": [
            {"name": "serde", "project": "1.0.190", "compat": "1.0.210",
             "latest": "1.0.210", "kind": "Normal"}
        ]
    })
    audit_json = json.dumps({
        "vulnerabilities": {
            "list": [
                {
                    "advisory": {"id": "RUSTSEC-2024-9999", "title": "Critical"},
                    "package": {"name": "serde", "version": "1.0.190"},
                }
            ]
        }
    })

    side_effects = [_mock_proc(outdated_json), _mock_proc(audit_json)]
    with patch("subprocess.run", side_effect=side_effects):
        result = gd.check_rust_deps(tmp_path, [dep])

    d = result[0]
    # vuln overrides outdated
    assert d["severity"] == "vulnerable"
    assert d["advisory_id"] == "RUSTSEC-2024-9999"


# Test 20
def test_check_rust_deps_empty_list(tmp_path):
    """Empty dep list → returns []."""
    result = gd.check_rust_deps(tmp_path, [])
    assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# Ruby Ecosystem Tests
# ══════════════════════════════════════════════════════════════════════════════


# Test 21
def test_check_ruby_outdated_not_available(tmp_path):
    """When bundle is None, deps returned unchanged."""
    original = gd.TOOLS.get("bundle")
    gd.TOOLS["bundle"] = None
    try:
        dep = _make_dep("rails", "7.0.8", "bundler")
        result = gd.check_ruby_outdated(tmp_path, [dep])
        assert result[0]["name"] == "rails"
        assert "current_version" not in result[0]
    finally:
        gd.TOOLS["bundle"] = original


# Test 22
def test_check_ruby_outdated_single_outdated(tmp_path):
    """Single dep, minor update → severity='outdated'."""
    gd.TOOLS["bundle"] = FAKE_TOOL_PATH
    parseable = "rails (newest 7.1.3, installed 7.0.8, requested ~> 7.0)\n"
    with patch("subprocess.run", return_value=_mock_proc(parseable)):
        dep = _make_dep("rails", "7.0.8", "bundler")
        result = gd.check_ruby_outdated(tmp_path, [dep])
    d = result[0]
    assert d["current_version"] == "7.0.8"
    assert d["latest_version"] == "7.1.3"
    assert d["severity"] == "outdated"


# Test 23
def test_check_ruby_outdated_major_update(tmp_path):
    """Major version bump → severity='major'."""
    gd.TOOLS["bundle"] = FAKE_TOOL_PATH
    parseable = "rails (newest 8.0.0, installed 7.0.8, requested ~> 7.0)\n"
    with patch("subprocess.run", return_value=_mock_proc(parseable)):
        dep = _make_dep("rails", "7.0.8", "bundler")
        result = gd.check_ruby_outdated(tmp_path, [dep])
    assert result[0]["severity"] == "major"


# Test 24
def test_check_ruby_outdated_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["bundle"] = FAKE_TOOL_PATH
    dep = _make_dep("rails", "7.0.8", "bundler")
    with patch("subprocess.run", side_effect=Exception("error")):
        result = gd.check_ruby_outdated(tmp_path, [dep])
    assert result[0]["name"] == "rails"
    assert "severity" not in result[0]


# Test 25
def test_check_ruby_vulns_not_available(tmp_path):
    """When bundler_audit is None, deps returned unchanged."""
    original = gd.TOOLS.get("bundler_audit")
    gd.TOOLS["bundler_audit"] = None
    try:
        dep = _make_dep("rails", "7.0.8", "bundler")
        dep["severity"] = "ok"
        result = gd.check_ruby_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
    finally:
        gd.TOOLS["bundler_audit"] = original


# Test 26
def test_check_ruby_vulns_vulnerability_found(tmp_path):
    """Vuln found → severity='vulnerable', advisory_id set."""
    gd.TOOLS["bundler_audit"] = FAKE_TOOL_PATH
    audit_json = json.dumps({
        "results": [
            {
                "type": "UnpatchedGem",
                "gem": {"name": "rails", "version": "7.0.8"},
                "advisory": {
                    "id": "CVE-2024-12345",
                    "title": "Rails XSS vulnerability",
                    "patched_versions": ["~> 7.1.0"],
                },
            }
        ]
    })
    with patch("subprocess.run", return_value=_mock_proc(audit_json)):
        dep = _make_dep("rails", "7.0.8", "bundler")
        dep["severity"] = "ok"
        result = gd.check_ruby_vulns(tmp_path, [dep])
    d = result[0]
    assert d["severity"] == "vulnerable"
    assert d["advisory_id"] == "CVE-2024-12345"


# Test 27
def test_check_ruby_vulns_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["bundler_audit"] = FAKE_TOOL_PATH
    dep = _make_dep("rails", "7.0.8", "bundler")
    dep["severity"] = "ok"
    with patch("subprocess.run", side_effect=Exception("error")):
        result = gd.check_ruby_vulns(tmp_path, [dep])
    assert result[0]["severity"] == "ok"


# Test 28
def test_check_ruby_deps_full_pipeline(tmp_path):
    """Full pipeline: outdated then vulns, vuln overrides."""
    gd.TOOLS["bundle"] = FAKE_TOOL_PATH
    gd.TOOLS["bundler_audit"] = FAKE_TOOL_PATH

    dep = _make_dep("rails", "7.0.8", "bundler")

    parseable = "rails (newest 7.1.3, installed 7.0.8, requested ~> 7.0)\n"
    audit_json = json.dumps({
        "results": [
            {
                "type": "UnpatchedGem",
                "gem": {"name": "rails", "version": "7.0.8"},
                "advisory": {
                    "id": "CVE-2024-99999",
                    "title": "Critical vuln",
                    "patched_versions": ["~> 7.1.0"],
                },
            }
        ]
    })

    side_effects = [_mock_proc(parseable), _mock_proc(audit_json)]
    with patch("subprocess.run", side_effect=side_effects):
        result = gd.check_ruby_deps(tmp_path, [dep])

    d = result[0]
    assert d["severity"] == "vulnerable"
    assert d["advisory_id"] == "CVE-2024-99999"


# Test 29
def test_check_ruby_deps_empty_list(tmp_path):
    """Empty dep list → returns []."""
    result = gd.check_ruby_deps(tmp_path, [])
    assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# PHP Ecosystem Tests
# ══════════════════════════════════════════════════════════════════════════════


# Test 30
def test_check_php_outdated_not_available(tmp_path):
    """When composer is None, deps returned unchanged."""
    original = gd.TOOLS.get("composer")
    gd.TOOLS["composer"] = None
    try:
        dep = _make_dep("laravel/framework", "10.0.0", "composer")
        result = gd.check_php_outdated(tmp_path, [dep])
        assert result[0]["name"] == "laravel/framework"
        assert "current_version" not in result[0]
    finally:
        gd.TOOLS["composer"] = original


# Test 31
def test_check_php_outdated_single_outdated(tmp_path):
    """Single dep, semver-safe update → severity='outdated'."""
    gd.TOOLS["composer"] = FAKE_TOOL_PATH
    composer_json = json.dumps({
        "installed": [
            {
                "name": "laravel/framework",
                "version": "10.0.0",
                "latest": "10.48.0",
                "latest-status": "semver-safe-update",
            }
        ]
    })
    with patch("subprocess.run", return_value=_mock_proc(composer_json)):
        dep = _make_dep("laravel/framework", "10.0.0", "composer")
        result = gd.check_php_outdated(tmp_path, [dep])
    d = result[0]
    assert d["current_version"] == "10.0.0"
    assert d["latest_version"] == "10.48.0"
    assert d["severity"] == "outdated"


# Test 32
def test_check_php_outdated_major_update(tmp_path):
    """update-possible with major version bump → severity='major'."""
    gd.TOOLS["composer"] = FAKE_TOOL_PATH
    composer_json = json.dumps({
        "installed": [
            {
                "name": "laravel/framework",
                "version": "10.0.0",
                "latest": "11.0.0",
                "latest-status": "update-possible",
            }
        ]
    })
    with patch("subprocess.run", return_value=_mock_proc(composer_json)):
        dep = _make_dep("laravel/framework", "10.0.0", "composer")
        result = gd.check_php_outdated(tmp_path, [dep])
    assert result[0]["severity"] == "major"


# Test 33
def test_check_php_outdated_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["composer"] = FAKE_TOOL_PATH
    dep = _make_dep("laravel/framework", "10.0.0", "composer")
    with patch("subprocess.run", side_effect=Exception("error")):
        result = gd.check_php_outdated(tmp_path, [dep])
    assert result[0]["name"] == "laravel/framework"
    assert "severity" not in result[0]


# Test 34
def test_check_php_vulns_vulnerability_found(tmp_path):
    """Vuln found → severity='vulnerable', advisory_id set."""
    gd.TOOLS["composer"] = FAKE_TOOL_PATH
    audit_json = json.dumps({
        "advisories": {
            "laravel/framework": [
                {
                    "advisoryId": "CVE-2024-56789",
                    "packageName": "laravel/framework",
                    "title": "Laravel XSS",
                    "cve": "CVE-2024-56789",
                    "link": "https://example.com/advisory",
                    "affectedVersions": ">=10.0.0,<10.48.0",
                }
            ]
        }
    })
    with patch("subprocess.run", return_value=_mock_proc(audit_json)):
        dep = _make_dep("laravel/framework", "10.0.0", "composer")
        dep["severity"] = "ok"
        result = gd.check_php_vulns(tmp_path, [dep])
    d = result[0]
    assert d["severity"] == "vulnerable"
    assert d["advisory_id"] == "CVE-2024-56789"


# Test 35
def test_check_php_vulns_subprocess_failure(tmp_path):
    """Subprocess exception → no crash, deps returned unchanged."""
    gd.TOOLS["composer"] = FAKE_TOOL_PATH
    dep = _make_dep("laravel/framework", "10.0.0", "composer")
    dep["severity"] = "ok"
    with patch("subprocess.run", side_effect=Exception("error")):
        result = gd.check_php_vulns(tmp_path, [dep])
    assert result[0]["severity"] == "ok"


# Test 36
def test_check_php_deps_full_pipeline(tmp_path):
    """Full pipeline: outdated then vulns, vuln overrides."""
    gd.TOOLS["composer"] = FAKE_TOOL_PATH

    dep = _make_dep("laravel/framework", "10.0.0", "composer")

    outdated_json = json.dumps({
        "installed": [
            {
                "name": "laravel/framework",
                "version": "10.0.0",
                "latest": "10.48.0",
                "latest-status": "semver-safe-update",
            }
        ]
    })
    audit_json = json.dumps({
        "advisories": {
            "laravel/framework": [
                {
                    "advisoryId": "CVE-2024-11111",
                    "packageName": "laravel/framework",
                    "title": "Critical",
                    "cve": "CVE-2024-11111",
                    "link": "https://example.com",
                    "affectedVersions": ">=10.0.0,<10.48.0",
                }
            ]
        }
    })

    side_effects = [_mock_proc(outdated_json), _mock_proc(audit_json)]
    with patch("subprocess.run", side_effect=side_effects):
        result = gd.check_php_deps(tmp_path, [dep])

    d = result[0]
    assert d["severity"] == "vulnerable"
    assert d["advisory_id"] == "CVE-2024-11111"


# Test 37
def test_check_php_deps_empty_list(tmp_path):
    """Empty dep list → returns []."""
    result = gd.check_php_deps(tmp_path, [])
    assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# Cross-Ecosystem Tests
# ══════════════════════════════════════════════════════════════════════════════


# Test 38 — required fields
@pytest.mark.parametrize("ecosystem,manager,fn_name,tool_key,tool_val,mock_outdated,mock_vulns", [
    (
        "go",
        "gomod",
        "check_go_deps",
        "go",
        FAKE_TOOL_PATH,
        json.dumps({"Path": "pkg/foo", "Version": "v1.0.0"}),
        json.dumps({"Vulns": []}),
    ),
    (
        "rust",
        "cargo",
        "check_rust_deps",
        "cargo_outdated",
        FAKE_TOOL_PATH,
        json.dumps({"dependencies": []}),
        json.dumps({"vulnerabilities": {"list": []}}),
    ),
    (
        "ruby",
        "bundler",
        "check_ruby_deps",
        "bundle",
        FAKE_TOOL_PATH,
        "",  # empty bundle outdated output = all up-to-date
        json.dumps({"results": []}),
    ),
    (
        "php",
        "composer",
        "check_php_deps",
        "composer",
        FAKE_TOOL_PATH,
        json.dumps({"installed": []}),
        json.dumps({"advisories": {}}),
    ),
])
def test_enriched_dicts_have_required_fields(
    tmp_path, ecosystem, manager, fn_name, tool_key, tool_val,
    mock_outdated, mock_vulns
):
    """All enriched dicts contain required fields for each ecosystem."""
    old_val = gd.TOOLS.get(tool_key)
    gd.TOOLS[tool_key] = tool_val

    # For rust: also need cargo_audit set
    old_audit = gd.TOOLS.get("cargo_audit")
    if ecosystem == "rust":
        gd.TOOLS["cargo_audit"] = FAKE_TOOL_PATH

    # For Go: also need govulncheck
    old_govulncheck = gd.TOOLS.get("govulncheck")
    if ecosystem == "go":
        gd.TOOLS["govulncheck"] = FAKE_TOOL_PATH

    # For Ruby: also need bundler_audit
    old_bundler_audit = gd.TOOLS.get("bundler_audit")
    if ecosystem == "ruby":
        gd.TOOLS["bundler_audit"] = FAKE_TOOL_PATH

    try:
        dep = _make_dep("pkg/foo" if ecosystem == "go" else "pkg", "1.0.0", manager)
        fn = getattr(gd, fn_name)
        with patch("subprocess.run", side_effect=[_mock_proc(mock_outdated), _mock_proc(mock_vulns)]):
            result = fn(tmp_path, [dep])

        assert len(result) == 1
        d = result[0]
        missing = _REQUIRED_FIELDS - set(d.keys())
        assert not missing, f"Missing fields for {ecosystem}: {missing}"
    finally:
        gd.TOOLS[tool_key] = old_val
        if ecosystem == "rust":
            gd.TOOLS["cargo_audit"] = old_audit
        if ecosystem == "go":
            gd.TOOLS["govulncheck"] = old_govulncheck
        if ecosystem == "ruby":
            gd.TOOLS["bundler_audit"] = old_bundler_audit


# Test 39 — vuln overrides outdated for each ecosystem
@pytest.mark.parametrize("ecosystem,manager,outdated_fn,vuln_fn", [
    ("go", "gomod", "check_go_outdated", "check_go_vulns"),
    ("rust", "cargo", "check_rust_outdated", "check_rust_vulns"),
    ("ruby", "bundler", "check_ruby_outdated", "check_ruby_vulns"),
    ("php", "composer", "check_php_outdated", "check_php_vulns"),
])
def test_vuln_overrides_outdated(tmp_path, ecosystem, manager, outdated_fn, vuln_fn):
    """Vulnerable severity overrides outdated for every ecosystem."""
    # Set up: dep is already marked outdated
    dep = _make_dep("test-pkg", "1.0.0", manager)
    dep["severity"] = "outdated"
    dep["current_version"] = "1.0.0"
    dep["latest_version"] = "1.1.0"

    # Set the relevant vuln tool
    tool_map = {
        "go": "govulncheck",
        "rust": "cargo_audit",
        "ruby": "bundler_audit",
        "php": "composer",
    }
    tool_key = tool_map[ecosystem]
    old_val = gd.TOOLS.get(tool_key)
    gd.TOOLS[tool_key] = FAKE_TOOL_PATH

    try:
        fn = getattr(gd, vuln_fn)

        # Build mock vuln outputs per ecosystem
        if ecosystem == "go":
            vuln_out = json.dumps({
                "Vulns": [
                    {"OSV": {"id": "GO-2024-TEST"}, "Modules": [{"Path": "test-pkg"}]}
                ]
            })
        elif ecosystem == "rust":
            vuln_out = json.dumps({
                "vulnerabilities": {
                    "list": [
                        {
                            "advisory": {"id": "RUSTSEC-2024-TEST", "title": "Test"},
                            "package": {"name": "test-pkg", "version": "1.0.0"},
                        }
                    ]
                }
            })
        elif ecosystem == "ruby":
            vuln_out = json.dumps({
                "results": [
                    {
                        "type": "UnpatchedGem",
                        "gem": {"name": "test-pkg", "version": "1.0.0"},
                        "advisory": {
                            "id": "CVE-2024-TEST",
                            "title": "Test",
                            "patched_versions": ["~> 1.1.0"],
                        },
                    }
                ]
            })
        else:  # php
            vuln_out = json.dumps({
                "advisories": {
                    "test-pkg": [
                        {
                            "advisoryId": "CVE-2024-TEST",
                            "packageName": "test-pkg",
                            "title": "Test",
                            "cve": "CVE-2024-TEST",
                            "link": "https://example.com",
                            "affectedVersions": ">=1.0.0,<1.1.0",
                        }
                    ]
                }
            })

        with patch("subprocess.run", return_value=_mock_proc(vuln_out)):
            result = fn(tmp_path, [dep])

        assert result[0]["severity"] == "vulnerable", (
            f"{ecosystem}: expected 'vulnerable', got '{result[0]['severity']}'"
        )
    finally:
        gd.TOOLS[tool_key] = old_val


# Test 40 — classify_severity reuse
def test_classify_severity_reuse():
    """Each ecosystem calls the shared classify_severity, not a duplicate."""
    # Verify the function exists in git_dashboard module and is callable
    assert callable(gd.classify_severity)
    # Verify it produces consistent output (not duplicated with different behavior)
    assert gd.classify_severity("1.0.0", "1.1.0") == "outdated"
    assert gd.classify_severity("1.0.0", "2.0.0") == "major"
    assert gd.classify_severity("1.0.0", "1.0.0") == "ok"
    # verify module has no alternative classify functions
    import inspect
    members = inspect.getmembers(gd, predicate=inspect.isfunction)
    classify_fns = [name for name, _ in members if "classify" in name.lower()]
    assert classify_fns == ["classify_severity"], (
        f"Found unexpected classify functions: {classify_fns}"
    )
