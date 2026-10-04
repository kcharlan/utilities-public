"""Byte-based progress is live only on a terminal; clocks are never invented."""
import re

import pytest

from fixturegen import CodexHome
from test_cli_integration import args
from test_payload import NOW


@pytest.mark.parametrize('done,total,elapsed,expected', [
    (1024**2, 4*1024**2, 2, 'parsing 1.0/4.0 MB · ETA 6s'),
    (1024**2, 2*1024**2, 1.2, 'parsing 1.0/2.0 MB · ETA 2s'),
    (512*1024, 1024**2, 3, 'parsing 0.5/1.0 MB · ETA 3s'),
    (1024**2, 1024**2, 4, 'parsing 1.0/1.0 MB · ETA 0s'),
    (0, 1024**2, 3, 'parsing 0.0/1.0 MB · ETA ?s'),
    (0, 0, 3, 'parsing 0.0/0.0 MB · ETA 0s'),
])
def test_format_progress(colophon, done, total, elapsed, expected):
    assert colophon.format_progress(done, total, elapsed) == expected


@pytest.mark.parametrize('tty', [True, False])
def test_cold_run_progress_obeys_explicit_tty(colophon, codex_home, capsys, tty):
    CodexHome(codex_home).log('synthetic-progress').meta().task_started().user_item().task_complete().write()
    assert colophon.run(args(colophon, codex_home, '--rebuild'), now_ms=NOW, stderr_tty=tty) == 0
    output = capsys.readouterr()
    assert '1 parsed, 0 cached' in output.out
    if tty:
        assert re.search(r'\rcolophon: parsing \d+\.\d/\d+\.\d MB · ETA 0s\n', output.err)
    else:
        assert '\r' not in output.err
        assert 'parsing ' not in output.err


@pytest.mark.parametrize('tty', [True, False])
def test_run_uses_stderr_isatty_by_default(colophon, codex_home, capsys, monkeypatch, tty):
    CodexHome(codex_home).log('synthetic-progress').meta().task_started().user_item().task_complete().write()
    monkeypatch.setattr(colophon.sys.stderr, 'isatty', lambda: tty)
    assert colophon.run(args(colophon, codex_home), now_ms=NOW) == 0
    assert ('\rcolophon: parsing ' in capsys.readouterr().err) is tty


def test_warm_cache_and_empty_home_have_no_progress(colophon, codex_home, capsys):
    assert colophon.run(args(colophon, codex_home), now_ms=NOW, stderr_tty=True) == 0
    assert '\r' not in capsys.readouterr().err
    CodexHome(codex_home).log('synthetic-progress').meta().task_started().user_item().task_complete().write()
    assert colophon.run(args(colophon, codex_home), now_ms=NOW, stderr_tty=True) == 0
    capsys.readouterr()
    assert colophon.run(args(colophon, codex_home), now_ms=NOW, stderr_tty=True) == 0
    output = capsys.readouterr()
    assert '0 parsed, 1 cached' in output.out
    assert '\r' not in output.err
