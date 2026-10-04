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


def terminal_lines(stream):
    """Replay CR as cursor movement, without incorrectly erasing old cells."""
    cells, lines = [], []
    cursor = 0
    for character in stream:
        if character == '\r':
            cursor = 0
        elif character == '\n':
            lines.append(''.join(cells))
            cells, cursor = [], 0
        else:
            if cursor < len(cells):
                cells[cursor] = character
            else:
                cells.append(character)
            cursor += 1
    return lines


def test_terminal_replay_preserves_suffix_after_carriage_return():
    assert terminal_lines('ETA 100s\rETA 0s\n') == ['ETA 0s0s']


def test_cold_progress_clears_previous_longer_eta(colophon, codex_home, capsys, monkeypatch):
    builder = CodexHome(codex_home)
    for identity in ('synthetic-a', 'synthetic-b'):
        builder.log(identity).meta().task_started().user_item().task_complete().write()
    sizes = [path.stat().st_size for path in codex_home.rglob('*.jsonl')]
    assert len(sizes) == 2 and sizes[0] == sizes[1] and sum(sizes) < 0.05 * 1024**2
    clocks = iter([0, 100, 101])
    monkeypatch.setattr(colophon.time, 'monotonic', lambda: next(clocks))
    assert colophon.run(args(colophon, codex_home, '--rebuild'), now_ms=NOW, stderr_tty=True) == 0
    output = capsys.readouterr()
    assert '2 logs (2 parsed, 0 cached)' in output.out
    assert output.err.count('\rcolophon: parsing ') == 2
    assert re.findall(r'ETA (\d+)s', output.err) == ['100', '0']
    assert terminal_lines(output.err)[0].rstrip() == 'colophon: parsing 0.0/0.0 MB · ETA 0s'
