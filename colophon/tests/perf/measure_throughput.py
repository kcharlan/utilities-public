"""Local cold-throughput acceptance; invoke with the Colophon project venv.

Defaults read real Codex logs and the runtime baseline: real-data acceptance
requires the user's authorization. Tests always pass a synthetic --codex-home
and COLOPHON_HOME. The measured compiler uses a fresh temporary runtime home,
offline and without opening a browser. No private page or cache is retained.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.testkit import load_launcher

colophon = load_launcher(Path(__file__).resolve().parents[2] / 'colophon')


def measure(codex_home: Path) -> dict:
    """Time a fresh cold CLI pipeline, counting actual ScanResult bytes."""
    previous_home = os.environ.get('COLOPHON_HOME')
    original_scan = colophon.scan_logs
    scans = []

    def scan(*args, **kwargs):
        result = original_scan(*args, **kwargs)
        scans.append(result)
        return result

    try:
        with tempfile.TemporaryDirectory(prefix='colophon-throughput-') as temporary:
            os.environ['COLOPHON_HOME'] = str(Path(temporary) / 'runtime')
            colophon.scan_logs = scan
            args = colophon.build_arg_parser().parse_args([
                '--rebuild', '--offline', '--no-open', '--codex-home', str(codex_home)])
            start = time.perf_counter()
            compiler_stderr = io.StringIO()
            with contextlib.redirect_stderr(compiler_stderr):
                exit_code = colophon.run(args, stderr_tty=False)
            elapsed = time.perf_counter() - start
            messages = compiler_stderr.getvalue()
            print(messages, file=sys.stderr, end='')
            if exit_code == 0 and 'colophon: diagnostics:' not in messages:
                print('throughput: diagnostics: none', file=sys.stderr)
            if exit_code:
                raise ValueError(f'cold compiler failed with exit {exit_code}')
            result = scans[0]
            if result.bytes_parsed <= 0:
                raise ValueError('no parsed log bytes; no throughput baseline recorded')
            if elapsed <= 0:
                raise ValueError('nonpositive measurement duration')
            return {'mb_per_s': result.bytes_parsed / (1024 * 1024) / elapsed,
                    'measured_at': colophon.format_rfc3339(colophon.now_ms()),
                    'logs': result.parsed, 'bytes': result.bytes_parsed}
    finally:
        colophon.scan_logs = original_scan
        if previous_home is None:
            os.environ.pop('COLOPHON_HOME', None)
        else:
            os.environ['COLOPHON_HOME'] = previous_home


def validate_baseline(value: object) -> dict:
    """Malformed measurements cannot establish a comparison baseline."""
    valid = isinstance(value, dict) and set(value) == {'mb_per_s', 'measured_at', 'logs', 'bytes'}
    if valid:
        rate = value['mb_per_s']
        try:
            valid = (type(rate) in (int, float) and math.isfinite(rate) and rate > 0
                     and isinstance(value['measured_at'], str)
                     and colophon.parse_rfc3339_ms(value['measured_at']) is not None
                     and type(value['logs']) is int and value['logs'] > 0
                     and type(value['bytes']) is int and value['bytes'] > 0)
        except OverflowError:
            valid = False
    if not valid:
        raise ValueError('invalid throughput baseline; preserve it and review before replacing it')
    return value


def is_regression(measured: float, baseline: float) -> bool:
    return measured < baseline / 1.5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path('~/.codex'))
    args = parser.parse_args(argv)
    try:
        baseline_path = colophon.runtime_home() / 'perf-baseline.json'
        baseline = None
        if baseline_path.exists():
            try:
                baseline = validate_baseline(json.loads(baseline_path.read_bytes(),
                    parse_constant=colophon._reject_json_constant))
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ValueError(f'invalid throughput baseline: {exc}') from exc
        measurement = measure(args.codex_home.expanduser())
        print(f"throughput: {measurement['mb_per_s']:.3f} MB/s · "
              f"{measurement['logs']} logs · {measurement['bytes']} parsed bytes")
        if baseline is None:
            colophon.ensure_runtime_home(baseline_path.parent)
            colophon.atomic_write_json(baseline_path, measurement)
            print(f'throughput: baseline recorded at {baseline_path}')
            return 0
        regression = is_regression(measurement['mb_per_s'], baseline['mb_per_s'])
        print(f"throughput: {'REGRESSION' if regression else 'within baseline'} · "
              f"baseline {baseline['mb_per_s']:.3f} MB/s · "
              f"minimum {baseline['mb_per_s'] / 1.5:.3f} MB/s")
        return 1 if regression else 0
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        print(f'throughput: {exc or "interrupted"}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
