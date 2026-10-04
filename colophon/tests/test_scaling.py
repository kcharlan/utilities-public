"""Fixed-shape cold CLI measurements, never counting fixture generation."""
import json
import statistics
import time
from collections import Counter

from fixturegen import CodexHome
from test_payload import extract


# Cold calibration: 100 sessions took 5.762016s (at least 2s).
# Keep the workload fixed after calibration, including all forty turns.
SCALING_SESSIONS = 100
TURNS_PER_SESSION = 40


def test_scaling_corpus_shape(colophon, tmp_path):
    root = tmp_path / 'synthetic-shape'
    CodexHome(root).scaling_corpus(2)
    logs = list(root.rglob('*.jsonl'))
    assert len(logs) == 4
    parsed_records = []
    for path in logs:
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert sum(r['type'] == 'event_msg' and r['payload']['type'] == 'task_started' for r in records) == 40
        assert sum(r['type'] == 'event_msg' and r['payload']['type'] == 'token_count' for r in records) == 40
        assert sum(r['type'] == 'token_usage_record' for r in records) == 20
        info = path.stat()
        parsed = colophon.parse_log_file(path, size=info.st_size, mtime_ns=info.st_mtime_ns, archived=False)
        parsed_records.append(parsed)
        assert len(parsed['turns']) == 40
        assert len(parsed['messages']) == 80
        assert len(parsed['tools']) == 40
    parents = [r for p in logs for r in [json.loads(p.read_text().splitlines()[0])]
               if not r['payload'].get('parent_thread_id')]
    assert len(parents) == 2
    metadata = colophon.load_codex_metadata(root)
    corpus = colophon.build_corpus(parsed_records, metadata, 1894708800000)
    colophon.link_subagents(corpus, metadata, 1894708800000)
    colophon.compose_usage(corpus, colophon.PriorityTurns({}, []))
    for session in corpus.sessions.values():
        assert Counter(unit.source for unit in session.units) == {'record': 20, 'token_count': 20}
        if not session.is_subagent:
            assert len(session.children) == 1


def measure_cold(run_cli, root, runtime):
    assert not runtime.exists()
    start = time.perf_counter()
    result = run_cli('--rebuild', '--offline', '--no-open', home=runtime, codex_home=root)
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, result.stdout + result.stderr
    payload = extract((runtime / 'colophon.html').read_bytes())
    assert payload['meta']['counts']['cached'] == 0
    return elapsed, payload


def test_cold_cli_scales_linearly(run_cli, tmp_path, record_property):
    samples = {}
    for count in (SCALING_SESSIONS, 2 * SCALING_SESSIONS):
        root = tmp_path / f'synthetic-codex-{count}'
        CodexHome(root).scaling_corpus(count)
        times = []
        for repetition in range(3):
            elapsed, payload = measure_cold(run_cli, root, tmp_path / f'runtime-{count}-{repetition}')
            assert payload['meta']['counts']['sessions'] == count
            assert payload['meta']['counts']['subagents'] == count
            assert payload['meta']['counts']['parsed'] == 2 * count
            for session in [*payload['sessions'], *payload['subagents'].values()]:
                assert len(session['turns']) == TURNS_PER_SESSION
                assert session['own_usage']['input'] == 4000
                assert session['own_usage']['output'] == 400
                assert session['tools']['shell'] == 40
            times.append(elapsed)
            print(f'cold size={count} repetition={repetition + 1} seconds={elapsed:.6f}', flush=True)
        samples[count] = times
        record_property(f'seconds_{count}', json.dumps(times))
    small = statistics.median(samples[SCALING_SESSIONS])
    large = statistics.median(samples[2 * SCALING_SESSIONS])
    print(f'cold medians S={small:.6f}s 2S={large:.6f}s ratio={large / small:.6f}', flush=True)
    assert small >= 2, f'Fixed S={SCALING_SESSIONS} must meet the 2s calibration floor: {samples}'
    assert large <= 2.5 * small, f'Cold CLI scaling exceeded 2.5: {samples}'
