"""Tests for Packet 13: Python Dep Health (Outdated + Vuln).

Tests cover:
  - classify_severity()
  - check_python_outdated()
  - check_python_vulns()
  - check_python_deps()
"""

import json
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import git_dashboard as gd


# ── classify_severity ─────────────────────────────────────────────────────────


def test_classify_severity_same_version():
    assert gd.classify_severity("2.3.0", "2.3.0") == "ok"


def test_classify_severity_minor_update():
    assert gd.classify_severity("2.1.0", "2.3.0") == "outdated"


def test_classify_severity_major_update():
    assert gd.classify_severity("2.3.0", "3.0.0") == "major"


def test_classify_severity_patch_update():
    assert gd.classify_severity("2.3.0", "2.3.1") == "outdated"


def test_classify_severity_prerelease_latest():
    # Major version differs even if latest is a pre-release
    assert gd.classify_severity("2.3.0", "3.0.0rc1") == "major"


def test_classify_severity_current_newer_than_latest():
    # current >= latest → "ok" (e.g. pre-release installed)
    assert gd.classify_severity("3.0.0", "2.9.9") == "ok"


# ── check_python_outdated ─────────────────────────────────────────────────────


def _make_pypi_response(version: str) -> MagicMock:
    """Return a mock urllib response object for a given latest version."""
    body = json.dumps({"info": {"version": version}}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_check_python_outdated_up_to_date():
    dep = {"name": "flask", "version": "3.0.0", "manager": "pip"}
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("3.0.0")):
        result = gd.check_python_outdated([dep])
    assert len(result) == 1
    r = result[0]
    assert r["latest_version"] == "3.0.0"
    assert r["severity"] == "ok"


def test_check_python_outdated_outdated_minor():
    dep = {"name": "requests", "version": "2.28.0", "manager": "pip"}
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("2.31.0")):
        result = gd.check_python_outdated([dep])
    r = result[0]
    assert r["latest_version"] == "2.31.0"
    assert r["severity"] == "outdated"


def test_check_python_outdated_major_update():
    dep = {"name": "django", "version": "3.2.0", "manager": "pip"}
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("5.0.0")):
        result = gd.check_python_outdated([dep])
    r = result[0]
    assert r["latest_version"] == "5.0.0"
    assert r["severity"] == "major"


def test_check_python_outdated_no_pinned_version():
    dep = {"name": "flask", "version": None, "manager": "pip"}
    with patch("urllib.request.urlopen") as mock_url:
        result = gd.check_python_outdated([dep])
    mock_url.assert_not_called()
    r = result[0]
    assert r.get("latest_version") is None
    assert r.get("severity", "ok") == "ok"


def test_check_python_outdated_network_error():
    from urllib.error import URLError
    dep = {"name": "flask", "version": "2.0.0", "manager": "pip"}
    with patch("urllib.request.urlopen", side_effect=URLError("timeout")):
        result = gd.check_python_outdated([dep])
    r = result[0]
    assert r.get("latest_version") is None
    assert r.get("severity", "ok") == "ok"


def test_check_python_outdated_invalid_json():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"not valid json{"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    dep = {"name": "flask", "version": "2.0.0", "manager": "pip"}
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = gd.check_python_outdated([dep])
    r = result[0]
    assert r.get("latest_version") is None
    assert r.get("severity", "ok") == "ok"


def test_check_python_outdated_multiple_deps_mixed():
    deps = [
        {"name": "flask", "version": "3.0.0", "manager": "pip"},    # ok
        {"name": "requests", "version": "2.28.0", "manager": "pip"}, # outdated
        {"name": "django", "version": "3.2.0", "manager": "pip"},    # major
    ]
    responses = [
        _make_pypi_response("3.0.0"),
        _make_pypi_response("2.31.0"),
        _make_pypi_response("5.0.0"),
    ]
    with patch("urllib.request.urlopen", side_effect=responses):
        result = gd.check_python_outdated(deps)
    assert result[0]["severity"] == "ok"
    assert result[1]["severity"] == "outdated"
    assert result[2]["severity"] == "major"


# ── check_python_vulns ────────────────────────────────────────────────────────


def test_check_python_vulns_no_pip_audit(tmp_path):
    original = gd.TOOLS.get("pip_audit")
    gd.TOOLS["pip_audit"] = None
    try:
        dep = {"name": "flask", "version": "2.0.0", "manager": "pip", "severity": "ok"}
        result = gd.check_python_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
        assert result[0].get("advisory_id") is None
    finally:
        gd.TOOLS["pip_audit"] = original


def _pip_audit_output(vulns_by_name: dict) -> str:
    """Build a pip-audit JSON output string.

    vulns_by_name: {pkg_name: [vuln_id, ...]}
    """
    deps_list = []
    for name, vuln_ids in vulns_by_name.items():
        vulns = [{"id": vid, "fix_versions": []} for vid in vuln_ids]
        deps_list.append({"name": name, "version": "1.0", "vulns": vulns})
    return json.dumps({"dependencies": deps_list})


def test_check_python_vulns_finds_vulnerability(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.0.0\n")

    audit_output = _pip_audit_output({"flask": ["CVE-2023-1234"]})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 0

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    try:
        dep = {"name": "flask", "version": "2.0.0", "manager": "pip", "severity": "ok", "advisory_id": None}
        with patch("subprocess.run", return_value=mock_result):
            result = gd.check_python_vulns(tmp_path, [dep])
        r = result[0]
        assert r["severity"] == "vulnerable"
        assert r["advisory_id"] == "CVE-2023-1234"
    finally:
        gd.TOOLS["pip_audit"] = None


def test_check_python_vulns_no_vulns(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==3.0.0\n")

    audit_output = _pip_audit_output({})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 0

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    try:
        dep = {"name": "flask", "version": "3.0.0", "manager": "pip", "severity": "ok", "advisory_id": None}
        with patch("subprocess.run", return_value=mock_result):
            result = gd.check_python_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
        assert result[0].get("advisory_id") is None
    finally:
        gd.TOOLS["pip_audit"] = None


def test_check_python_vulns_subprocess_fails(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.0.0\n")

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    try:
        dep = {"name": "flask", "version": "2.0.0", "manager": "pip", "severity": "ok"}
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "pip-audit")):
            result = gd.check_python_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
    finally:
        gd.TOOLS["pip_audit"] = None


def test_check_python_vulns_unexpected_json(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.0.0\n")

    mock_result = MagicMock()
    mock_result.stdout = json.dumps({"unexpected_key": []})
    mock_result.returncode = 0

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    try:
        dep = {"name": "flask", "version": "2.0.0", "manager": "pip", "severity": "ok"}
        with patch("subprocess.run", return_value=mock_result):
            result = gd.check_python_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "ok"
    finally:
        gd.TOOLS["pip_audit"] = None


def test_check_python_vulns_overrides_major_severity(tmp_path):
    """Vuln overrides even 'major' severity (vuln > major > outdated > ok)."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("django==3.2.0\n")

    audit_output = _pip_audit_output({"django": ["CVE-2024-9999"]})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 0

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    try:
        dep = {
            "name": "django", "version": "3.2.0", "manager": "pip",
            "severity": "major", "advisory_id": None,
        }
        with patch("subprocess.run", return_value=mock_result):
            result = gd.check_python_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "vulnerable"
        assert result[0]["advisory_id"] == "CVE-2024-9999"
    finally:
        gd.TOOLS["pip_audit"] = None


def test_check_python_vulns_overrides_outdated_severity(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("requests==2.28.0\n")

    audit_output = _pip_audit_output({"requests": ["CVE-2024-5678"]})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 0

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    try:
        dep = {
            "name": "requests", "version": "2.28.0", "manager": "pip",
            "severity": "outdated", "advisory_id": None,
        }
        with patch("subprocess.run", return_value=mock_result):
            result = gd.check_python_vulns(tmp_path, [dep])
        assert result[0]["severity"] == "vulnerable"
        assert result[0]["advisory_id"] == "CVE-2024-5678"
    finally:
        gd.TOOLS["pip_audit"] = None


# ── check_python_deps orchestrator ────────────────────────────────────────────


def test_check_python_deps_full_pipeline(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("requests==2.28.0\nflask==3.0.0\n")

    pypi_responses = [
        _make_pypi_response("2.31.0"),  # requests: outdated
        _make_pypi_response("3.0.0"),   # flask: ok
    ]
    audit_output = _pip_audit_output({"requests": ["CVE-2024-0001"]})
    mock_proc = MagicMock()
    mock_proc.stdout = audit_output
    mock_proc.returncode = 0

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    deps = [
        {"name": "requests", "version": "2.28.0", "manager": "pip"},
        {"name": "flask", "version": "3.0.0", "manager": "pip"},
    ]
    try:
        with patch("urllib.request.urlopen", side_effect=pypi_responses), \
             patch("subprocess.run", return_value=mock_proc):
            result = gd.check_python_deps(tmp_path, deps)
        requests_dep = next(d for d in result if d["name"] == "requests")
        flask_dep = next(d for d in result if d["name"] == "flask")
        assert requests_dep["severity"] == "vulnerable"
        assert requests_dep["advisory_id"] == "CVE-2024-0001"
        assert flask_dep["severity"] == "ok"
    finally:
        gd.TOOLS["pip_audit"] = None


def test_check_python_deps_no_pip_audit(tmp_path):
    """Outdated check still works when pip-audit is not available."""
    gd.TOOLS["pip_audit"] = None
    deps = [{"name": "flask", "version": "2.0.0", "manager": "pip"}]
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("3.0.0")):
        result = gd.check_python_deps(tmp_path, deps)
    assert result[0]["severity"] == "major"
    assert result[0]["latest_version"] == "3.0.0"


def test_check_python_deps_empty_list(tmp_path):
    result = gd.check_python_deps(tmp_path, [])
    assert result == []


def test_check_python_deps_all_fields_present(tmp_path):
    """All enriched dep dicts must contain the required fields."""
    gd.TOOLS["pip_audit"] = None
    dep = {"name": "requests", "version": "2.28.0", "manager": "pip"}
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("2.31.0")):
        result = gd.check_python_deps(tmp_path, [dep])
    r = result[0]
    required_fields = {"name", "version", "manager", "current_version", "wanted_version",
                       "latest_version", "severity", "advisory_id", "checked_at"}
    assert required_fields.issubset(set(r.keys())), f"Missing fields: {required_fields - set(r.keys())}"


def test_check_python_deps_non_pip_deps_unchanged(tmp_path):
    """Non-pip deps (e.g. npm) are returned unchanged by check_python_deps."""
    gd.TOOLS["pip_audit"] = None
    npm_dep = {"name": "lodash", "version": "4.0.0", "manager": "npm"}
    pip_dep = {"name": "flask", "version": "3.0.0", "manager": "pip"}
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("3.0.0")):
        result = gd.check_python_deps(tmp_path, [npm_dep, pip_dep])
    npm_result = next(d for d in result if d["name"] == "lodash")
    # npm dep must not have any health-check fields added
    assert "severity" not in npm_result
    assert "current_version" not in npm_result
    assert "latest_version" not in npm_result
    assert "checked_at" not in npm_result


def test_check_python_deps_range_version_skipped(tmp_path):
    """Deps with range versions (>=) are skipped in outdated check."""
    gd.TOOLS["pip_audit"] = None
    dep = {"name": "flask", "version": ">=2.0.0", "manager": "pip"}
    with patch("urllib.request.urlopen") as mock_url:
        result = gd.check_python_deps(tmp_path, [dep])
    mock_url.assert_not_called()
