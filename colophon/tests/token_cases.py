"""Stored upstream reference cases; no upstream checkout or CLI is used here."""
from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
TOKEN_CASES = FIXTURES / 'token_cases'
SCRUBBED = FIXTURES / 'scrubbed'
POINTERS = {
    'a': 'CostUsageScanner.swift:431–855, parseCodexFileCancellable:4177–5264 @ 3bbf6bc48',
    'b': 'CostUsageScanner.swift:1611–2003, resolveForkBaseline, raiseInheritedBaselineIfContinuedCounter @ 3bbf6bc48',
    'c': 'CodexSubagentRolloutShape.swift:1–228; CostUsageScanner.swift:5016–5264; ForkCoverage.swift:43–46 @ 3bbf6bc48',
    's': 'CostUsageScanner.swift:4177–5264; CodexSubagentRolloutShape.swift @ 3bbf6bc48',
}


@dataclass
class Case:
    home: Path
    meta: dict
    expected: dict


def load_case(root: Path, name: str, tmp: Path) -> Case:
    source = root / name
    meta = json.loads((source / 'case.json').read_text())
    home = tmp / 'codex-home'
    shutil.copytree(source / 'codex-home', home)
    for relative, milliseconds in meta['mtimes_ms'].items():
        ns = milliseconds * 1_000_000
        os.utime(home / relative, ns=(ns, ns))
    return Case(home, meta, json.loads((source / 'expected.json').read_text()))


def account_case(colophon, home: Path) -> dict[str, list]:
    records = [colophon.parse_log_file(log.path, size=log.size, mtime_ns=log.mtime_ns,
                                      archived=log.archived)
               for log in colophon.discover_logs(home)]
    results = colophon.account_logs(records)
    return {Path(path).relative_to(colophon.codex_path_key(home)).as_posix(): result.rows
            for path, result in results.items()}


def expected_rows(case: Case) -> dict[str, list[dict]]:
    files = {item['file']: item['rows'] for item in case.expected['files']}
    if case.meta['name'] == 'b10_fork_of_fork_scan_order':
        # A4#7: same counters as b04; only ids, dates and mtimes differ.
        reference = json.loads((TOKEN_CASES / 'b04_fork_of_fork' / 'expected.json').read_text())
        reference_meta = json.loads((TOKEN_CASES / 'b04_fork_of_fork' / 'case.json').read_text())
        delta_days = (date.fromisoformat(case.meta['day_utc'])
                      - date.fromisoformat(reference_meta['day_utc'])).days
        source = next(item for item in reference['files'] if item['file'].endswith('3000.jsonl'))
        target = next(path for path in case.meta['files'] if path.endswith('3000.jsonl'))
        files[target] = [dict(row, day=case.meta['day_utc'],
                              timestampUnixMs=row['timestampUnixMs'] + delta_days * 86400000)
                         for row in source['rows']]
    return files


def assert_case(case: Case, actual: dict[str, list]) -> None:
    expected = expected_rows(case)
    context = f"{case.meta['name']}: {case.meta['description']}\n{POINTERS[case.meta['name'][0]]}"
    assert set(actual) == set(expected), f'{context}\nfiles: actual={set(actual)} expected={set(expected)}'
    fields = [('event_index', 'eventIndex'), ('day_key', 'day'),
              ('timestamp_unix_ms', 'timestampUnixMs'), ('turn_id', 'turnID'),
              ('model', 'model'), ('model_raw', 'rawModel'),
              ('input', 'input'), ('cached', 'cached'), ('output', 'output'),
              ('reasoning', 'reasoning')]
    for path, wanted_rows in expected.items():
        got_rows = actual[path]
        for index in range(max(len(got_rows), len(wanted_rows))):
            got = ({target: getattr(got_rows[index], source) for source, target in fields}
                   if index < len(got_rows) else None)
            wanted = ({target: wanted_rows[index].get(target) for _, target in fields}
                      if index < len(wanted_rows) else None)
            assert got == wanted, f'{context}\n{path} row {index}\nactual: {got}\nexpected: {wanted}'
    grouped = defaultdict(lambda: [0, 0, 0])
    for rows in actual.values():
        for row in rows:
            bucket = grouped[row.day_key, row.model]
            for i, value in enumerate((row.input, row.cached, row.output)):
                bucket[i] += value
    wanted_grouped = {(row['day'], row['model']): [row[key] for key in
                       ('input_tokens', 'cached_tokens', 'output_tokens')]
                      for row in case.expected['day_aggregates']}
    daily = defaultdict(lambda: [0, 0, 0])
    wanted_daily = {row['date']: [row.get(key, 0) for key in
                    ('inputTokens', 'cacheReadTokens', 'outputTokens')]
                   for row in case.expected['report']['daily']}
    if case.meta['name'] == 'b10_fork_of_fork_scan_order':
        extra = next(rows for path, rows in expected.items() if path.endswith('3000.jsonl'))
        for row in extra:
            values = [row[key] for key in ('input', 'cached', 'output')]
            bucket = wanted_grouped.setdefault((row['day'], row['model']), [0, 0, 0])
            day = wanted_daily.setdefault(row['day'], [0, 0, 0])
            for i, value in enumerate(values):
                bucket[i] += value
                day[i] += value
    for key in set(grouped) | set(wanted_grouped):
        assert grouped.get(key, [0, 0, 0]) == wanted_grouped.get(key, [0, 0, 0]), f'{context}\nbucket {key}: {grouped.get(key)} != {wanted_grouped.get(key)}'
    for (day, _), values in grouped.items():
        for i, value in enumerate(values):
            daily[day][i] += value
    for day in set(daily) | set(wanted_daily):
        assert daily.get(day, [0, 0, 0]) == wanted_daily.get(day, [0, 0, 0]), f'{context}\nday {day}: {daily.get(day)} != {wanted_daily.get(day)}'
