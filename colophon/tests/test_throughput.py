"""Local acceptance tool tests use explicit, temporary synthetic homes."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from fixturegen import CodexHome
from tools.testkit import load_launcher

SCRIPT = Path(__file__).parent / 'perf' / 'measure_throughput.py'
VALID_BASELINE = {'mb_per_s': 10, 'measured_at': '2030-01-01T00:00:00Z', 'logs': 1, 'bytes': 10}


@pytest.fixture
def throughput():
    return load_launcher(SCRIPT)


def test_throughput_cold_measurement_uses_scan_bytes(throughput, tmp_path, monkeypatch, capsys):
    source = tmp_path / 'synthetic-source'
    CodexHome(source).scaling_corpus(1)
    baseline_home = tmp_path / 'synthetic-baseline'
    monkeypatch.setenv('COLOPHON_HOME', str(baseline_home))
    clock = iter([10, 12])
    monkeypatch.setattr(throughput.time, 'perf_counter', lambda: next(clock))
    measurement = throughput.measure(source)
    assert measurement['bytes'] == sum(p.stat().st_size for p in source.rglob('*.jsonl'))
    assert measurement['logs'] == 2
    assert measurement['mb_per_s'] == measurement['bytes'] / (1024 * 1024) / 2
    assert throughput.colophon.parse_rfc3339_ms(measurement['measured_at']) is not None
    assert not baseline_home.exists()
    assert os.environ['COLOPHON_HOME'] == str(baseline_home)
    output = capsys.readouterr()
    assert '2 logs (2 parsed, 0 cached)' in output.out
    assert 'page ' in output.out
    assert 'diagnostics:' in output.err


def test_throughput_cli_creates_then_preserves_baseline(tmp_path, codex_home, home):
    CodexHome(codex_home).scaling_corpus(1)
    command = [sys.executable, str(SCRIPT), '--codex-home', str(codex_home)]
    environment = {**os.environ, 'COLOPHON_HOME': str(home)}
    result = subprocess.run(command, capture_output=True, text=True, env=environment)
    assert result.returncode == 0, result.stdout + result.stderr
    baseline = home / 'perf-baseline.json'
    data = json.loads(baseline.read_bytes())
    assert set(data) == {'mb_per_s', 'measured_at', 'logs', 'bytes'}
    assert data['logs'] == 2
    assert 'baseline recorded' in result.stdout
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE(baseline.stat().st_mode) == 0o600
    assert list(home.iterdir()) == [baseline]
    # An unmistakable regression must retain the original baseline verbatim.
    data['mb_per_s'] = 1e30
    baseline.write_text(json.dumps(data))
    before = baseline.read_bytes()
    result = subprocess.run(command, capture_output=True, text=True, env=environment)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'REGRESSION' in result.stdout
    assert baseline.read_bytes() == before


@pytest.mark.parametrize('ratio,regression', [(1, False), (1.5, False), (1.5001, True)])
def test_throughput_regression_threshold(throughput, ratio, regression):
    assert throughput.is_regression(10 / ratio, 10) is regression


@pytest.mark.parametrize('field,value', [
    ('mb_per_s', True), ('mb_per_s', 0), ('mb_per_s', -1),
    ('mb_per_s', '10'), ('mb_per_s', float('inf')), ('mb_per_s', float('nan')),
    ('mb_per_s', 10**1000), ('measured_at', None), ('measured_at', 'Synthetic invalid date'),
    ('logs', True), ('logs', 0), ('logs', -1), ('bytes', True), ('bytes', 0), ('bytes', -1),
])
def test_invalid_baseline_is_not_measurement_evidence(throughput, field, value):
    with pytest.raises(ValueError, match='invalid throughput baseline'):
        throughput.validate_baseline({**VALID_BASELINE, field: value})


@pytest.mark.parametrize('baseline', [None, [], {}, {'mb_per_s': 10}, {**VALID_BASELINE, 'extra': 1}])
def test_invalid_baseline_schema(throughput, baseline):
    with pytest.raises(ValueError, match='invalid throughput baseline'):
        throughput.validate_baseline(baseline)


def test_valid_baseline_is_preserved(throughput):
    assert throughput.validate_baseline(VALID_BASELINE) is VALID_BASELINE


def test_failed_cold_run_restores_instrumentation_and_home(throughput, tmp_path, monkeypatch, capsys):
    runtime = tmp_path / 'synthetic-runtime'
    monkeypatch.setenv('COLOPHON_HOME', str(runtime))
    original = throughput.colophon.scan_logs
    with pytest.raises(ValueError, match='cold compiler failed with exit 1'):
        throughput.measure(tmp_path / 'synthetic-missing-source')
    assert throughput.colophon.scan_logs is original
    assert os.environ['COLOPHON_HOME'] == str(runtime)
    assert not runtime.exists()
    assert 'Codex home is missing or unreadable' in capsys.readouterr().err


def test_empty_source_does_not_create_baseline(throughput, codex_home, home, capsys):
    assert throughput.main(['--codex-home', str(codex_home)]) == 1
    assert 'no parsed log bytes' in capsys.readouterr().err
    assert not (home / 'perf-baseline.json').exists()


def test_bad_baseline_is_preserved_and_reported(throughput, codex_home, home, capsys):
    home.mkdir()
    baseline = home / 'perf-baseline.json'
    baseline.write_bytes(b'{Synthetic damaged baseline')
    CodexHome(codex_home).scaling_corpus(1)
    assert throughput.main(['--codex-home', str(codex_home)]) == 1
    assert 'invalid throughput baseline' in capsys.readouterr().err
    assert baseline.read_bytes() == b'{Synthetic damaged baseline'
