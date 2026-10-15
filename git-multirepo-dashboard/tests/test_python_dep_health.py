"""Tests for Packet 13: Python Dep Health (Outdated + Vuln).

Tests cover:
  - classify_severity()
  - check_python_outdated()
  - check_python_vulns()
  - check_python_deps()
"""

import json
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
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
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("3.0.0")):
        result = gd.check_python_outdated([dep])
    r = result[0]
    assert r["latest_version"] == r['wanted_version'] == '3.0.0'
    assert r['outdated_state'] == 'floating'
    assert r.get('current_version') is None


def test_check_python_outdated_network_error():
    from urllib.error import URLError
    dep = {"name": "flask", "version": "2.0.0", "manager": "pip"}
    with patch("urllib.request.urlopen", side_effect=URLError("timeout")):
        result = gd.check_python_outdated([dep])
    r = result[0]
    assert r.get("latest_version") is None
    assert r["severity"] == gd.derive_severity(r) == "unchecked"


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
    assert r["severity"] == gd.derive_severity(r) == "unchecked"


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
        assert result[0]["severity"] == "unchecked"
        assert result[0]['vuln_state'] == 'unchecked'
        assert 'pip-audit' in result[0]['check_note']
        assert result[0].get("advisory_id") is None
    finally:
        gd.TOOLS["pip_audit"] = original


def _pip_audit_output(vulns_by_name: dict, versions: dict) -> str:
    """Build a pip-audit JSON output string.

    vulns_by_name: {pkg_name: [vuln_id, ...]}
    """
    deps_list = []
    for name, vuln_ids in vulns_by_name.items():
        vulns = [{"id": vid, "fix_versions": []} for vid in vuln_ids]
        deps_list.append({"name": name, "version": versions[name], "vulns": vulns})
    return json.dumps({"dependencies": deps_list})


def test_check_python_vulns_finds_vulnerability(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.0.0\n")

    audit_output = _pip_audit_output({"flask": ["CVE-2023-1234"]}, {'flask': '2.0.0'})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 1
    mock_result.stderr = ''

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

    audit_output = _pip_audit_output({'flask': []}, {'flask': '3.0.0'})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 0
    mock_result.stderr = ''

    gd.TOOLS["pip_audit"] = "/usr/bin/pip-audit"
    try:
        dep = {"name": "flask", "version": "3.0.0", "manager": "pip", "severity": "ok", "advisory_id": None,
               "outdated_state": "checked"}
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
        assert result[0]["severity"] == gd.derive_severity(result[0]) == "unchecked"
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
        assert result[0]["severity"] == gd.derive_severity(result[0]) == "unchecked"
    finally:
        gd.TOOLS["pip_audit"] = None


def test_check_python_vulns_overrides_major_severity(tmp_path):
    """Vuln overrides even 'major' severity (vuln > major > outdated > ok)."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("django==3.2.0\n")

    audit_output = _pip_audit_output({"django": ["CVE-2024-9999"]}, {'django': '3.2.0'})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 1
    mock_result.stderr = ''

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

    audit_output = _pip_audit_output({"requests": ["CVE-2024-5678"]}, {'requests': '2.28.0'})
    mock_result = MagicMock()
    mock_result.stdout = audit_output
    mock_result.returncode = 1
    mock_result.stderr = ''

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
    audit_output = _pip_audit_output({"requests": ["CVE-2024-0001"]}, {'requests': '2.28.0'})
    mock_proc = MagicMock()
    mock_proc.stdout = audit_output
    mock_proc.returncode = 1
    mock_proc.stderr = ''

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
        assert flask_dep["severity"] == gd.derive_severity(flask_dep) == "unchecked"
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


def test_check_python_deps_range_version_floats(tmp_path):
    """Supported standalone range declarations select a registry version."""
    gd.TOOLS["pip_audit"] = None
    dep = {"name": "flask", "version": ">=2.0.0", "manager": "pip"}
    with patch("urllib.request.urlopen", return_value=_make_pypi_response("3.0.0")):
        result = gd.check_python_deps(tmp_path, [dep])
    assert result[0]['current_version'] is None
    assert result[0]['wanted_version'] == '3.0.0'
    assert result[0]['outdated_state'] == 'floating'


def test_derive_severity_coverage_precedence():
    for outdated in ('checked', 'floating', 'unchecked'):
        for vuln in ('checked', 'unchecked'):
            row = dict(outdated_state=outdated, vuln_state=vuln, severity='major')
            assert gd.derive_severity(dict(row, advisory_id='SYNTHETIC-1')) == 'vulnerable'
            assert gd.derive_severity(row) == ('major' if outdated != 'unchecked' else 'unchecked')
            row['severity'] = 'ok'
            assert gd.derive_severity(row) == ('unchecked' if 'unchecked' in (outdated, vuln) else 'ok')


def test_finalize_health_is_idempotent():
    rows = [dict(name='synthetic', manager='pip', version='1.0'),
            dict(name='floating', manager='pip', version=None, current_version='direct reference',
                 outdated_state='floating', vuln_state='checked')]
    first = gd.finalize_dep_health(rows)
    assert gd.finalize_dep_health(first) == first
    assert first[0]['current_version'] == '1.0'
    assert first[0]['check_note']
    assert first[1]['current_version'] == 'direct reference'
    assert first[1]['outdated_state'] == 'floating'


def test_finalize_does_not_treat_poetry_constraint_as_current():
    row = gd.finalize_dep_health([dict(name='synthetic', manager='pip', version='^1.0')])[0]
    assert row['current_version'] is None
    assert row['wanted_version'] is None
    assert row['declared_spec'] == '^1.0'
    assert row['severity'] == 'unchecked'


def test_lookup_failure_has_unchecked_reason():
    with patch('urllib.request.urlopen', side_effect=OSError('synthetic lookup failed')):
        row = gd.check_python_deps(__import__('pathlib').Path('/synthetic'),
                                   [dict(name='synthetic', manager='pip', version='1.0')])[0]
    assert row['outdated_state'] == 'unchecked'
    assert 'synthetic lookup failed' in row['check_note']
    assert row['severity'] == 'unchecked'


def test_check_note_accumulates_distinct_bounded_failures():
    note = gd.tool_failure_note('synthetic-tool', ValueError('ignored first line\n\n' + 'x' * 400))
    assert 'ignored first line' not in note
    assert len(note) <= len('synthetic-tool: ') + 240
    row = {}
    for reason in ('synthetic; detail', 'another reason', 'synthetic; detail'):
        gd.add_check_note(row, reason)
    assert row['check_note'] == 'synthetic; detail; another reason'


def test_direct_reference_makes_no_registry_or_audit_calls(tmp_path, monkeypatch):
    (tmp_path / 'requirements.txt').write_text('git+https://git.example.invalid/acme/widget.git\n')
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': 'synthetic-pip-audit'})
    with patch('urllib.request.urlopen') as registry, patch('subprocess.run') as audit:
        [row] = gd.check_python_deps(tmp_path, gd.parse_deps_for_repo(tmp_path))
    registry.assert_not_called()
    audit.assert_not_called()
    assert row['current_version'] == 'git:default branch'
    assert row['severity'] == 'unchecked'
    assert row['outdated_state'] == row['vuln_state'] == 'unchecked'
    assert row['check_note'] == 'direct VCS/URL reference; not compared with PyPI or audited'


def _registry_payload(latest='3.0', versions=('1.0', '1.9', '3.0')):
    return {'info': {'version': latest},
            'releases': {v: [{'yanked': False}] for v in versions}}


def _payload_response(payload):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(payload).encode()
    return response


def _registry_row(name='synthetic-alpha', version=None, **extra):
    return dict(name=name, manager='pip', version=version, **extra)


def test_poetry_constraint_health_does_not_invent_current_version(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text('[tool.poetry.dependencies]\nsynthetic-alpha = "^1.0"\n')
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': 'synthetic-auditor'})
    with patch('urllib.request.urlopen') as registry, patch('subprocess.run') as audit:
        [row] = gd.check_python_deps(tmp_path, gd.parse_deps_for_repo(tmp_path))
    assert row['current_version'] is row['wanted_version'] is None
    assert row['outdated_state'] == row['vuln_state'] == 'unchecked'
    assert 'unsupported' in row['check_note']
    registry.assert_not_called()
    audit.assert_not_called()


def test_floating_selection_and_capped_comparison(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': None})
    rows = [gd.parse_python_requirement(text) for text in (
        'synthetic-alpha', 'synthetic-alpha[extra]>=1,<2; python_version < "0"',
        'synthetic-alpha==1.*', 'synthetic-alpha==1.0')]
    with patch('urllib.request.urlopen', return_value=_payload_response(_registry_payload())):
        result = gd.check_python_deps(tmp_path, rows)
    assert [(r['current_version'], r['wanted_version'], r['latest_version'],
             r['outdated_state'], r['severity']) for r in result] == [
        (None, '3.0', '3.0', 'floating', 'unchecked'),
        (None, '1.9', '3.0', 'floating', 'major'),
        (None, '1.9', '3.0', 'floating', 'major'),
        ('1.0', '1.0', '3.0', 'checked', 'major')]
    assert all('pip-audit' in r['check_note'] for r in result)


def test_floating_resolution_omits_yanked_releases():
    payload = _registry_payload()
    payload['releases'].update({'4.0': [{'yanked': True}], '5.0': [],
                                'invalid': [{'yanked': False}], '6.0': [None],
                                '7.0': [{'yanked': True}, {'yanked': False}]})
    assert gd.resolve_floating_version(payload, '') == '7.0'
    assert gd.resolve_floating_version(payload, '<7') == '3.0'
    assert gd.resolve_floating_version(payload, '>9') is None


def test_floating_resolution_respects_explicit_prereleases():
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
    versions = ['1.0', '2.0rc1']
    payload = _registry_payload(latest='1.0', versions=versions)
    for constraint in ('', '>=1.0rc1'):
        expected = max(SpecifierSet(constraint).filter(map(Version, versions)))
        assert gd.resolve_floating_version(payload, constraint) == str(expected)


def test_registry_fallback_without_releases():
    assert gd.resolve_floating_version({'info': {'version': '2.0'}}, '<3') == '2.0'
    assert gd.resolve_floating_version({'info': {'version': '2.0'}}, '<2') is None
    assert gd.resolve_floating_version({'info': {'version': 'invalid'}}, '') is None
    assert gd.resolve_floating_version({'info': {'version': '2.0'}, 'releases': {}}, '') is None


@pytest.mark.parametrize('version', [123, [], {}, True])
def test_registry_fallback_rejects_non_version_values(version):
    assert gd.resolve_floating_version({'info': {'version': version}}, '') is None


def test_non_string_poetry_constraint_remains_unchecked(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text('[tool.poetry.dependencies]\nsynthetic-alpha = {version = 123}\n')
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': 'synthetic-auditor'})
    with patch('urllib.request.urlopen') as registry, patch('subprocess.run') as audit:
        [row] = gd.check_python_deps(tmp_path, gd.parse_deps_for_repo(tmp_path))
    assert row['current_version'] is row['wanted_version'] is None
    assert row['outdated_state'] == row['vuln_state'] == 'unchecked'
    assert 'unsupported' in row['check_note']
    registry.assert_not_called()
    audit.assert_not_called()


@pytest.mark.parametrize('failure', [False, True])
def test_registry_cache_across_manifests(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': None})
    rows = [_registry_row(name, '1.0', source_path=source) for name, source in (
        ('Synthetic_Alpha', 'requirements.txt'), ('synthetic.alpha', 'nested/pyproject.toml'))]
    with patch('urllib.request.urlopen', side_effect=URLError('synthetic offline') if failure else None,
               return_value=_payload_response(_registry_payload())) as lookup:
        first = gd.check_python_deps(tmp_path, rows)
        assert lookup.call_count == 1
        second = gd.check_python_deps(tmp_path, rows)
        assert lookup.call_count == 2  # a new scan must retry cached failures too
    assert [r['source_path'] for r in first] == ['requirements.txt', 'nested/pyproject.toml']
    assert [r['outdated_state'] for r in first] == ['unchecked' if failure else 'checked'] * 2
    assert [r['outdated_state'] for r in second] == [r['outdated_state'] for r in first]


@pytest.mark.parametrize('error', [TimeoutError('synthetic timeout'), URLError('synthetic connection')])
def test_connection_breaker_bounds_requests(monkeypatch, error):
    monkeypatch.setattr(gd, '_PYPI_MAX_CONSECUTIVE_FAILURES', 2)
    rows = [_registry_row(f'synthetic-{i}', '1.0') for i in range(5)]
    with patch('urllib.request.urlopen', side_effect=error) as lookup:
        result = gd.check_python_outdated(rows)
    assert lookup.call_count == 2
    assert all(r['outdated_state'] == 'unchecked' and r['check_note'] for r in result)
    assert 'connection' in result[-1]['check_note']


def test_connection_breaker_resets_on_success(monkeypatch):
    monkeypatch.setattr(gd, '_PYPI_MAX_CONSECUTIVE_FAILURES', 2)
    outcomes = [URLError('synthetic offline'), _payload_response(_registry_payload()),
                URLError('synthetic offline'), _payload_response(_registry_payload())]
    with patch('urllib.request.urlopen', side_effect=outcomes) as lookup:
        result = gd.check_python_outdated([_registry_row(f'synthetic-{i}', '1.0') for i in range(4)])
    assert lookup.call_count == 4
    assert [r['outdated_state'] for r in result] == ['unchecked', 'checked', 'unchecked', 'checked']


@pytest.mark.parametrize('failure', ['http', 'json'])
def test_http_error_does_not_open_breaker(monkeypatch, failure):
    monkeypatch.setattr(gd, '_PYPI_MAX_CONSECUTIVE_FAILURES', 1)
    bad = HTTPError('https://pypi.org/synthetic', 404, 'synthetic missing', {}, None)
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'invalid synthetic JSON'
    with patch('urllib.request.urlopen', side_effect=[bad if failure == 'http' else response,
                _payload_response(_registry_payload())]) as lookup:
        result = gd.check_python_outdated([_registry_row('synthetic-alpha', '1.0'),
                                          _registry_row('synthetic-beta', '1.0')])
    assert lookup.call_count == 2
    assert result[0]['outdated_state'] == 'unchecked'
    assert result[1]['outdated_state'] == 'checked'


def test_audit_batches_preserve_pin_set_without_name_collisions():
    pins = [('Synthetic_Alpha', '1.0'), ('synthetic-alpha', '1.0'),
            ('synthetic.alpha', '2.0'), ('synthetic-beta', '3.0')]
    batches = gd._pip_audit_batches(pins)
    assert {pin for batch in batches for pin in batch} == {
        ('synthetic-alpha', '1.0'), ('synthetic-alpha', '2.0'), ('synthetic-beta', '3.0')}
    assert sum(map(len, batches)) == 3
    assert all(len({name for name, version in batch}) == len(batch) for batch in batches)


def test_audit_files_are_outside_repository(monkeypatch):
    paths = []
    def audit(command, **kwargs):
        path = Path(command[command.index('--requirement') + 1])
        paths.append(path)
        assert not path.resolve().is_relative_to(Path(gd.__file__).resolve().parents[1])
        assert path.read_text() == 'synthetic-alpha==1.0\n'
        assert command[3:] == ['--no-deps', '--disable-pip', '--format', 'json', '--progress-spinner', 'off']
        assert kwargs == dict(capture_output=True, text=True, timeout=300)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({'dependencies': [
            {'name': 'synthetic-alpha', 'version': '1.0', 'vulns': []}]}), stderr='')
    monkeypatch.setattr(subprocess, 'run', audit)
    result = gd._audit_python_pins('synthetic-auditor', [('synthetic-alpha', '1.0')])
    assert result[('synthetic-alpha', '1.0')]['vuln_state'] == 'checked'
    assert paths and not paths[0].exists()


def test_audit_results_map_to_requested_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': 'synthetic-auditor'})
    (tmp_path / 'requirements.txt').write_text('synthetic-alpha==1.0\n')
    (tmp_path / 'pyproject.toml').write_text('[project]\ndependencies = ["synthetic-alpha==2.0"]\n')
    (tmp_path / 'tool.py').write_text('# /// script\n# dependencies = ["synthetic-alpha>=2"]\n# ///\n')
    def audit(command, **kwargs):
        pins = Path(command[command.index('--requirement') + 1]).read_text().splitlines()
        entries = []
        for pin in pins:
            name, version = pin.split('==')
            entries.append({'name': name.upper().replace('-', '_'), 'version': version,
                            'vulns': [{'id': 'SYNTHETIC-ADVISORY'}] if version == '1.0' else []})
        return subprocess.CompletedProcess(command, int(any(e['vulns'] for e in entries)),
                                           stdout=json.dumps({'dependencies': entries}), stderr='')
    monkeypatch.setattr(subprocess, 'run', audit)
    with patch('urllib.request.urlopen', return_value=_payload_response(_registry_payload())):
        rows = gd.check_python_deps(tmp_path, gd.parse_deps_for_repo(tmp_path))
    by_source = {r['source_path']: r for r in rows}
    assert by_source['requirements.txt']['advisory_id'] == 'SYNTHETIC-ADVISORY'
    assert by_source['pyproject.toml']['advisory_id'] is None
    assert by_source['tool.py']['wanted_version'] == '3.0'
    assert by_source['tool.py']['current_version'] is None
    assert by_source['tool.py']['severity'] == 'ok'
    assert all(r['vuln_state'] == 'checked' for r in rows)


def test_audit_reuses_pins_and_prefers_current_version(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': 'synthetic-auditor'})
    seen = []
    def audit(command, **kwargs):
        seen.append(Path(command[command.index('--requirement') + 1]).read_text())
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({'dependencies': [
            {'name': 'synthetic-alpha', 'version': '1.0', 'vulns': []}]}), stderr='')
    monkeypatch.setattr(subprocess, 'run', audit)
    rows = gd.check_python_vulns(tmp_path, [
        _registry_row(current_version='1.0', wanted_version='2.0', source_path='requirements.txt'),
        _registry_row('Synthetic_Alpha', '1.0', source_path='nested/requirements.txt')])
    assert seen == ['synthetic-alpha==1.0\n']
    assert [r['vuln_state'] for r in rows] == ['checked', 'checked']
    assert [r['source_path'] for r in rows] == ['requirements.txt', 'nested/requirements.txt']


def test_unsatisfied_range_cannot_be_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': 'synthetic-auditor'})
    with patch('urllib.request.urlopen', return_value=_payload_response(_registry_payload())), \
            patch('subprocess.run') as audit:
        [row] = gd.check_python_deps(tmp_path, [gd.parse_python_requirement('synthetic-alpha>9')])
    assert row['current_version'] is row['wanted_version'] is None
    assert row['outdated_state'] == row['vuln_state'] == 'unchecked'
    assert 'no usable release' in row['check_note']
    assert 'no concrete Python version' in row['check_note']
    audit.assert_not_called()


def test_audit_failure_is_limited_to_its_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, 'TOOLS', {'pip_audit': 'synthetic-auditor'})
    def audit(command, **kwargs):
        text = Path(command[command.index('--requirement') + 1]).read_text()
        if '==1.0' in text:
            raise subprocess.TimeoutExpired(command, 300)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({'dependencies': [
            {'name': 'synthetic-alpha', 'version': '2.0', 'vulns': []}]}), stderr='')
    monkeypatch.setattr(subprocess, 'run', audit)
    rows = gd.check_python_vulns(tmp_path, [_registry_row(version='1.0'), _registry_row(version='2.0')])
    assert [r['vuln_state'] for r in rows] == ['unchecked', 'checked']
    assert rows[0]['check_note']


def test_audit_skip_and_missing_entry_are_unchecked(monkeypatch):
    payload = {'dependencies': [{'name': 'synthetic-alpha', 'skip_reason': 'synthetic unsupported'}]}
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout=json.dumps(payload), stderr=''))
    result = gd._audit_python_pins('synthetic-auditor', [('synthetic-alpha', '1.0'), ('synthetic-beta', '2.0')])
    assert result[('synthetic-alpha', '1.0')] == {
        'vuln_state': 'unchecked', 'note': 'pip-audit skipped: synthetic unsupported'}
    assert result[('synthetic-beta', '2.0')] == {
        'vuln_state': 'unchecked', 'note': 'not in pip-audit output'}


@pytest.mark.parametrize('returncode,entry', [
    (2, {'name': 'alpha-lib', 'vulns': []}),
    (0, {'name': 'alpha-lib'}),
    (0, {'name': 'alpha-lib', 'vulns': None}),
    (0, {'name': 'alpha-lib', 'vulns': [{'unexpected': 'synthetic'}]}),
    (1, {'name': 'alpha-lib', 'vulns': []}),
    (0, {'name': 'alpha-lib', 'vulns': [{'id': ''}]}),
    (0, {'name': 'alpha-lib', 'vulns': ['synthetic']}),
    (0, {'name': 'alpha-lib', 'vulns': [], 'version': '2.0'}),
    (0, {'name': 'alpha-lib', 'vulns': [{'id': 'SYNTHETIC-ADVISORY'}]}),
    (0, {'name': None, 'vulns': []}),
    (0, 'synthetic'),
])
def test_audit_rejects_failed_or_incomplete_results(monkeypatch, returncode, entry):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], returncode, stdout=json.dumps({'dependencies': [entry]}), stderr=''))
    result = gd._audit_python_pins('synthetic-auditor', [('alpha-lib', '1.0')])
    assert result[('alpha-lib', '1.0')]['vuln_state'] == 'unchecked'
    assert result[('alpha-lib', '1.0')]['note']


@pytest.mark.parametrize('payload', [[], {}, {'dependencies': None}, {'dependencies': [
    {'name': 'synthetic_alpha', 'vulns': []}, {'name': 'synthetic-alpha', 'vulns': []}]}])
def test_audit_rejects_invalid_output_shape(monkeypatch, payload):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout=json.dumps(payload), stderr=''))
    result = gd._audit_python_pins('synthetic-auditor', [('synthetic-alpha', '1.0')])
    assert result[('synthetic-alpha', '1.0')]['vuln_state'] == 'unchecked'
    assert result[('synthetic-alpha', '1.0')]['note']
