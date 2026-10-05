"""Local parity report helpers. Private acceptance output must never be committed."""
from __future__ import annotations

import math
import json
import contextlib
import io
import os
import hashlib
import sys
import subprocess
import shutil
import tempfile
import time
import argparse
from datetime import datetime, timezone
from types import SimpleNamespace
import sqlite3
import unicodedata
from pathlib import Path

COST_REL_TOL = 1e-10
COST_ABS_TOL = 1e-12
PINNED_COMMIT = '3bbf6bc48c20d8e507b30ed93dbdce19ed928bb6'


def source_inputs(codex_home: Path) -> list[Path]:
    """Only scanner JSONL inputs; never authentication/config/SQLite side files."""
    files = []
    for name in ('sessions', 'archived_sessions'):
        root = codex_home / name
        if root.is_symlink():
            raise ValueError('symlink source root refused')
        for path in root.rglob('*.jsonl'):
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
                raise ValueError('symlink source JSONL refused')
            if path.is_file():
                files.append(path)
    return sorted(files)


def selected_runtime_inputs(codex_home: Path, colophon_home: Path) -> list[Path]:
    paths = [codex_home / 'logs_2.sqlite', *[colophon_home / name for name in (
        'price-history.json', 'pricing-cache.json', 'priority-turns.json')]]
    for path in paths:
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError('symlink trace/runtime input refused')
    return [path for path in paths if path.is_file()]


def serialize_report(report: dict) -> str:
    """Project identities are nullable rows, avoiding JSON object-key coercion."""
    def encode(value):
        if isinstance(value, dict):
            return {key: ([{'path': path, 'metrics': encode(metrics)}
                           for path, metrics in sorted(item.items(), key=lambda pair: (pair[0] is not None, str(pair[0])))]
                          if key == 'project' and isinstance(item, dict) else encode(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value
    return json.dumps(encode(report), indent=2, sort_keys=True, allow_nan=False) + '\n'


def input_fingerprint(database: Path, files: list[Path]) -> str:
    """Fingerprint isolated inputs, including WAL-visible logical cache rows."""
    digest = hashlib.sha256()
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)
    try:
        for statement in connection.iterdump():
            digest.update(statement.encode())
            digest.update(b'\n')
    finally:
        connection.close()
    for path in sorted(files):
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def bundle_hash(bundle: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(bundle.rglob('*')):
        if path.is_file():
            digest.update(str(path.relative_to(bundle)).encode())
            digest.update(file_hash(path).encode())
    return digest.hexdigest()


def native_source_identity(clone: Path) -> None:
    commit = subprocess.check_output(['git', '-C', str(clone), 'rev-parse', 'HEAD'], text=True).strip()
    source_status = subprocess.check_output(['git', '-C', str(clone), 'status', '--porcelain', '--', 'Sources'], text=True)
    if commit != PINNED_COMMIT or source_status:
        raise ValueError('native oracle requires exact pinned commit and unmodified Sources')


def prepared_native(clone: Path, bundle: Path, provenance: Path, *, record: bool = False) -> dict:
    native_source_identity(clone)
    source = Path(__file__).parent / 'native_oracle/ColophonNativeOracleTests.swift'
    copied = clone / 'Harness/ColophonNativeOracleTests/ColophonNativeOracleTests.swift'
    if file_hash(copied) != file_hash(source) or not bundle.is_dir() or not bundle.resolve().is_relative_to(clone.resolve()):
        raise ValueError('native oracle prepared harness/bundle mismatch')
    hashes = {'harness_hash': file_hash(source), 'bundle_hash': bundle_hash(bundle)}
    if record:
        manifest = {'schema': 1, 'source_commit': PINNED_COMMIT, 'harness_sha256': hashes['harness_hash'],
            'bundle_sha256': hashes['bundle_hash'], 'build_command': ['swift', 'build', '--build-tests',
                '--disable-keychain', '--force-resolved-versions', '-j', '8']}
        provenance.write_text(json.dumps(manifest, indent=2) + '\n')
    else:
        manifest = json.loads(provenance.read_bytes())
    return validate_provenance(manifest, **hashes)


def validate_provenance(manifest: object, *, harness_hash: str, bundle_hash: str) -> dict:
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1
            or manifest.get('source_commit') != PINNED_COMMIT
            or manifest.get('harness_sha256') != harness_hash
            or manifest.get('bundle_sha256') != bundle_hash
            or not isinstance(manifest.get('build_command'), list) or not manifest['build_command']
            or not all(isinstance(part, str) and part for part in manifest['build_command'])):
        raise ValueError('native oracle provenance mismatch')
    return manifest


def compile_colophon(colophon, codex_home: Path, runtime: Path, output: Path, *, snapshot_ms: int) -> dict:
    """Observe the real in-process offline compiler; restore hooks/environment."""
    previous = os.environ.get('COLOPHON_HOME')
    original_payload, original_priority = colophon.build_payload, colophon.load_priority_turns
    captured = {}

    def payload(corpus, *args, **kwargs):
        result = original_payload(corpus, *args, **kwargs)
        captured.update(corpus=corpus, payload=result)
        return result

    def priority(*args, **kwargs):
        result = original_priority(*args, **kwargs)
        captured['priority'] = result
        return result

    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        os.environ['COLOPHON_HOME'] = str(runtime)
        colophon.build_payload, colophon.load_priority_turns = payload, priority
        args = colophon.build_arg_parser().parse_args([
            '--offline', '--no-open', '--rebuild', '--output', str(output), '--codex-home', str(codex_home)])
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = colophon.run(args, now_ms=snapshot_ms, stderr_tty=False)
        if result:
            raise ValueError(f'in-process Colophon exit {result}: {stdout.getvalue()}\n{stderr.getvalue()}')
    finally:
        colophon.build_payload, colophon.load_priority_turns = original_payload, original_priority
        if previous is None:
            os.environ.pop('COLOPHON_HOME', None)
        else:
            os.environ['COLOPHON_HOME'] = previous
    captured.update(stdout=stdout.getvalue(), stderr=stderr.getvalue())
    return captured


def comparison_session_id(colophon, session) -> str:
    """Align labels with native identity; keep every contributing file/unit."""
    identifiers = set()
    for record in session.records:
        observations = record['token_stream']['observations']
        identifier = observations[0][1].get('session_id') if observations and observations[0][0] == 'P' else None
        if identifier is None:
            identifier = Path(record['key']['path']).stem
        if not isinstance(identifier, str) or not identifier:
            raise ValueError('unknown comparison session identity')
        identifiers.add(colophon._codex_session_identity(identifier))
    if len(identifiers) != 1:
        raise ValueError('ambiguous comparison session identities; no native file winner is reconstructed')
    return identifiers.pop()


def comparison_identities(colophon, corpus) -> tuple[dict, list]:
    aliases, owners, rows = {}, {}, []
    for raw_key, session in corpus.sessions.items():
        identifier = comparison_session_id(colophon, session)
        row = {'colophon_accounting_key': raw_key, 'colophon_display_id': session.id,
               'native_id': identifier, 'paths': [record['key']['path'] for record in session.records]}
        rows.append(row)
        if identifier in owners:
            raise ValueError(f'ambiguous native identity {identifier}: {owners[identifier]} / {row}; no contributor selected')
        owners[identifier] = row
        aliases[raw_key] = identifier
    return aliases, rows


def fallback_totals(colophon, corpus, fake: Path, catalog: dict) -> dict:
    """Colophon's prescribed cold fallback recomputation, never native selection."""
    records = [record for session in corpus.sessions.values() for record in session.records]
    records.extend(corpus.skipped_records)
    results = colophon.account_logs(records)
    cold_home = fake / 'cold-colophon-priority'
    cold_home.mkdir(mode=0o700)
    priority = colophon.load_priority_turns(codex_home=fake / '.codex', home=cold_home)
    pricing = CodexBarPricing(colophon, catalog)
    projects, units = {}, []
    aliases, identities = comparison_identities(colophon, corpus)
    for raw_key, session in corpus.sessions.items():
        identifier = aliases[raw_key]
        projects[identifier] = (session.meta or {}).get('cwd') or session.db_info.get('cwd')
        seen = set()
        for record in session.records:
            result = results[record['key']['path']]
            accepted = set()
            for row in result.rows:
                key = colophon._codex_cross_file_row_key(result.session_id, record['key']['path'], row)
                if key in seen:
                    continue
                accepted.add(key)
                units.append(SimpleNamespace(session=identifier, owner=session, input=row.input, cached=row.cached,
                    output=row.output, cost_usd=pricing.cost(row, priority.turns), at_ms=row.at_ms,
                    day_key=row.day_key, source=row.kind, original=row))
            seen.update(accepted)
    totals = aggregate_units(units, projects=projects, native_costs=True,
                             day_key=lambda at: colophon._codex_local_day_key(at / 1000))
    totals['units'], totals['priority_turns'], totals['trace_messages'] = units, priority.turns, priority.messages
    totals['identity_mapping'] = identities
    return totals


def read_isolated_files(database: Path) -> list[dict]:
    """Read only file identity facts. No window filter or selected-file oracle."""
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)
    try:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute('SELECT id,path,session_id,mtime_ms FROM files')]
    finally:
        connection.close()


def structural_ties(records: list[dict]) -> list[str]:
    by_session = {}
    seen = {}
    paths, identifiers = {}, {}
    for record in records:
        identifier, path = record.get('id'), record.get('path')
        session, mtime = record.get('session_id'), record.get('mtime_ms')
        if (type(identifier) is not int or not isinstance(path, str) or not Path(path).is_absolute()
                or type(mtime) is not int or not -(2**63) <= mtime < 2**63
                or (session is not None and (not isinstance(session, str) or not session))):
            raise ValueError('unknown cache file identity/mtime')
        identity = (identifier, path)
        if identity in seen:
            if seen[identity] != record:
                raise ValueError('conflicting cache file records')
            continue
        seen[identity] = record
        if path in paths or identifier in identifiers:
            raise ValueError('conflicting unique cache file identity')
        paths[path], identifiers[identifier] = identifier, path
        session = session if session is not None else Path(path).stem
        if not session:
            raise ValueError('unknown cache file session identity')
        key = unicodedata.normalize('NFC', session)
        entry = by_session.setdefault(key, {'id': key, 'files': []})
        entry['files'].append((identity, mtime))
    ties = []
    for entry in by_session.values():
        maximum = max(mtime for _, mtime in entry['files'])
        if sum(mtime == maximum for _, mtime in entry['files']) > 1:
            ties.append(entry['id'])
    return sorted(ties)


def material_equal(left, right, *, key: str = '') -> bool:
    if key in ('costUSD', 'totalCostUSD', 'totalCost', 'cost'):
        if left is None or right is None:
            return left is right
        if type(left) not in (int, float) or type(right) not in (int, float):
            return False
        return math.isfinite(left) and math.isfinite(right) and math.isclose(
            left, right, rel_tol=COST_REL_TOL, abs_tol=COST_ABS_TOL)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(material_equal(left[k], right[k], key=k) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(material_equal(a, b) for a, b in zip(left, right))
    return left == right


def native_unmetered_facts(observation: dict) -> dict:
    """Interpret exported native predicates; never select files or infer billing."""
    groups, paths = {}, set()
    facts = observation.get('fileFacts', [])
    if not isinstance(facts, list):
        raise ValueError('malformed native file facts')
    for fact in facts:
        if (not isinstance(fact, dict) or not isinstance(fact.get('path'), str) or fact['path'] in paths
                or 'sessionID' not in fact or fact['sessionID'] is not None and not isinstance(fact['sessionID'], str)
                or 'parentID' not in fact or fact['parentID'] is not None and not isinstance(fact['parentID'], str)
                or type(fact.get('unresolvedMissingParent')) is not bool or type(fact.get('hasBilledTokens')) is not bool
                or not isinstance(fact.get('unmeteredDays'), dict)
                or any(not isinstance(day, str) or type(count) is not int or count <= 0
                       for day, count in fact['unmeteredDays'].items())):
            raise ValueError('malformed native file facts')
        paths.add(fact['path'])
        identifier = fact['sessionID']
        if identifier:
            groups.setdefault(unicodedata.normalize('NFC', identifier), []).append(fact)
    return {identifier: entries[0] for identifier, entries in groups.items()
            if len(entries) == 1 and entries[0]['parentID'] and entries[0]['unresolvedMissingParent']
            and not entries[0]['hasBilledTokens'] and entries[0]['unmeteredDays']}


def deliberate_unmetered_exclusions(observation: dict) -> dict:
    eligible = native_unmetered_facts(observation)
    exclusions = {}
    for row in observation['daily']:
        count = row.get('unmeteredRequestCount')
        contributors = {identifier: fact['unmeteredDays'].get(row['date'], 0) for identifier, fact in eligible.items()
                        if row['date'] in fact['unmeteredDays']}
        if (type(count) is int and count > 0 and sum(contributors.values()) == count
                and all(row.get(field) is None for field in ('inputTokens', 'cacheReadTokens', 'outputTokens', 'totalTokens', 'costUSD'))
                and not row.get('modelsUsed') and not row.get('modelBreakdowns')):
            exclusions[row['date']] = sorted(contributors)
    return exclusions


def assess_native_oracle(observations: list[dict], *, ties: list[str]) -> dict:
    disagreements = []
    unknown_metrics = set()
    exclusions = {}
    if len(observations) < 3:
        disagreements.append('fewer than three native observations')
    reference = None
    for index, observation in enumerate(observations, 1):
        try:
            validate_native(observation)
            observed_exclusions = deliberate_unmetered_exclusions(observation)
            eligible = native_unmetered_facts(observation)
        except ValueError as exc:
            disagreements.append(f'observation {index}: {exc}')
            continue
        if observation['historyScanIsPartial']:
            disagreements.append(f'observation {index}: native scan is partial')
        exclusions.update(observed_exclusions)
        for identifier, session in observation['sessions'].items():
            if (unicodedata.normalize('NFC', identifier) in eligible and not session['modelBreakdowns']
                    and all(session[field] is None for field in ('inputTokens', 'cachedInputTokens', 'outputTokens', 'totalTokens', 'costUSD'))):
                continue
            for field in ('inputTokens', 'cachedInputTokens', 'outputTokens', 'costUSD'):
                if session[field] is None:
                    unknown_metrics.add(f'session {identifier}.{field}')
        for label, rows in [('day', observation['daily']), *[
                (f'project {project.get("path")}', project.get('daily')) for project in observation['projects']]]:
            try:
                days = _day_map(rows, native=True)
                for day, metric in days.items():
                    if label == 'day' and day in observed_exclusions:
                        continue
                    for key, field in (('input', 'inputTokens'), ('cached', 'cacheReadTokens'),
                                       ('output', 'outputTokens'), ('cost', 'costUSD')):
                        if metric[key] is None:
                            unknown_metrics.add(f'{label} {day}.{field}')
            except (ValueError, TypeError, AttributeError) as exc:
                disagreements.append(f'observation {index}: {exc}')
        current = {key: value for key, value in observation.items() if key != 'nowUnixMs'}
        if reference is None:
            reference = current
        elif not material_equal(reference, current):
            disagreements.append(f'observation {index}: native ID set or metrics disagree')
    return {'complete': not ties and not disagreements and not unknown_metrics, 'structural_ties': sorted(ties),
            'disagreements': disagreements, 'unknown_metrics': sorted(unknown_metrics),
            'unmetered_exclusions': exclusions, 'observations': observations}


def validate_native(observation: object) -> dict:
    if (not isinstance(observation, dict) or not isinstance(observation.get('sessions'), dict)
            or type(observation.get('historyCoverageIsEstablished')) is not bool
            or type(observation.get('historyScanIsPartial')) is not bool
            or not isinstance(observation.get('daily'), list) or not isinstance(observation.get('projects'), list)):
        raise ValueError('malformed native schema/coverage')
    _day_map(observation['daily'], native=True)
    paths = set()
    for project in observation['projects']:
        if (not isinstance(project, dict) or 'path' not in project
                or (project['path'] is not None and not isinstance(project['path'], str))
                or project['path'] in paths):
            raise ValueError('malformed native project identity')
        paths.add(project['path'])
        _day_map(project.get('daily'), native=True)
        for field in ('totalTokens', 'totalCostUSD'):
            value = project.get(field)
            if field not in project or value is not None and (
                    type(value) not in (int, float) or not math.isfinite(value) or value < 0
                    or field == 'totalTokens' and type(value) is not int):
                raise ValueError('malformed native project metric')
    identities = set()
    for identifier, session in observation['sessions'].items():
        if (not isinstance(identifier, str) or not identifier or not isinstance(session, dict)
                or session.get('sessionID') != identifier):
            raise ValueError('malformed native session identity')
        canonical = unicodedata.normalize('NFC', identifier)
        if canonical in identities:
            raise ValueError('duplicate canonical native session identity')
        identities.add(canonical)
        for key in ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningTokens',
                    'totalTokens', 'requestCount'):
            if key not in session or (session[key] is not None and (type(session[key]) is not int or session[key] < 0)):
                raise ValueError(f'malformed native session {key}')
        if ('costUSD' not in session or (session['costUSD'] is not None and
                (type(session['costUSD']) not in (int, float) or not math.isfinite(session['costUSD']) or session['costUSD'] < 0))
                or type(session.get('lastActivityUnixMs')) is not int
                or 'projectPath' not in session or (session['projectPath'] is not None and not isinstance(session['projectPath'], str))
                or not isinstance(session.get('modelBreakdowns'), list)):
            raise ValueError('malformed native session metrics')
    return observation


def _day_map(rows: list, *, native: bool) -> dict:
    output = {}
    if not isinstance(rows, list):
        raise ValueError('unknown daily report')
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('date'), str) or row['date'] in output:
            raise ValueError('malformed/duplicate report day')
        metrics = {key: row.get(source) for key, source in (
            ('input', 'inputTokens'), ('cached', 'cacheReadTokens'), ('output', 'outputTokens'),
            ('total', 'totalTokens'), ('cost', 'costUSD' if native else 'totalCost'))}
        for key, value in metrics.items():
            if value is None:
                continue
            if key == 'cost':
                valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
            else:
                valid = type(value) is int and value >= 0
            if not valid:
                raise ValueError('malformed daily metrics')
        output[row['date']] = metrics
    return output


def crosscheck_native(native: dict, cli: dict) -> list[str]:
    """Independent cache-path crosscheck; never a session selection oracle."""
    failures = []
    try:
        validate_native(native)
        if not material_equal(_day_map(native['daily'], native=True), _day_map(cli['daily'], native=False)):
            failures.append('native daily metrics disagree with CLI')
        native_projects, cli_projects = {}, {}
        for source, output, is_native in ((native['projects'], native_projects, True),
                                          (cli['projects'], cli_projects, False)):
            if not isinstance(source, list):
                raise ValueError('unknown project report')
            for project in source:
                if (not isinstance(project, dict) or 'path' not in project
                        or (project['path'] is not None and not isinstance(project['path'], str))
                        or project['path'] in output):
                    raise ValueError('malformed/duplicate project path')
                output[project['path']] = {'total': project.get('totalTokens'),
                    'cost': project.get('totalCostUSD' if is_native else 'totalCost'),
                    'daily': _day_map(project['daily'], native=is_native)}
        if not material_equal(native_projects, cli_projects):
            failures.append('native project metrics disagree with CLI')
    except (ValueError, KeyError, TypeError) as exc:
        failures.append(f'unknown native/CLI crosscheck evidence: {exc}')
    return failures


def parity_cost_equal(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return (type(left) in (int, float) and type(right) in (int, float)
            and math.isfinite(left) and math.isfinite(right)
            and abs(left - right) <= 1e-9 * abs(right) + 1e-9)


def parse_native_stdout(stdout: str) -> dict:
    lines = [line.removeprefix('NATIVE_ORACLE_JSON:') for line in stdout.splitlines()
             if line.startswith('NATIVE_ORACLE_JSON:')]
    if len(lines) != 1:
        raise ValueError('expected exactly one native JSON marker')
    return validate_native(strict_json(lines[0]))


def strict_json(text: str | bytes):
    def invalid(value):
        raise ValueError(f'nonfinite JSON constant: {value}')
    return json.loads(text, parse_constant=invalid)


def aggregate_units(units: list, *, projects: dict, day_key, native_costs: bool = False) -> dict:
    groups = {'day': {}, 'project': {}, 'session': {}, 'unknown_time_sessions': []}
    unknown, seen_cost = set(), set()
    unpriced = 0
    for unit in units:
        if unit.cost_usd is None:
            unpriced += unit.input + unit.output
        keys = [('session', unit.session), ('project', projects.get(unit.session))]
        if unit.at_ms is None:
            unknown.add(unit.session)
        else:
            keys.append(('day', unit.day_key if hasattr(unit, 'day_key') else day_key(unit.at_ms)))
        for scope, key in keys:
            metric = groups[scope].setdefault(key, {'input': 0, 'cached': 0, 'output': 0, 'cost': 0.0})
            for field in ('input', 'cached', 'output'):
                metric[field] += getattr(unit, field)
            if native_costs:
                if unit.cost_usd is not None:
                    metric['cost'] += unit.cost_usd
                    seen_cost.add((scope, key))
            else:
                metric['cost'] = None if metric['cost'] is None or unit.cost_usd is None else metric['cost'] + unit.cost_usd
    if native_costs:
        for scope in ('day', 'project', 'session'):
            for key, metric in groups[scope].items():
                if (scope, key) not in seen_cost or not math.isfinite(metric['cost']):
                    metric['cost'] = None
    groups['unknown_time_sessions'] = sorted(unknown)
    groups['unpriced_tokens'] = unpriced
    return groups


def reference_totals(native: dict, *, complete: bool = False) -> dict:
    validate_native(native)
    reference = {'day': _day_map(native['daily'], native=True), 'project': {}, 'session': {},
                 'zero_cached_representation': []}
    for identifier, session in native['sessions'].items():
        reference['session'][identifier] = {'input': session['inputTokens'], 'cached': session['cachedInputTokens'],
            'output': session['outputTokens'], 'cost': session['costUSD']}
    for project in native['projects']:
        days = _day_map(project['daily'], native=True)
        metrics = {}
        for field in ('input', 'cached', 'output'):
            values = [day[field] for day in days.values()]
            metrics[field] = sum(values) if values and all(value is not None for value in values) else None
        metrics['cost'] = project.get('totalCostUSD')
        reference['project'][project['path']] = metrics
    return reference


def compare_scope(scope: str, full: dict, reference: dict, fallback: dict,
                  *, proofs: dict, custom_build: bool) -> tuple[list[dict], list[dict]]:
    differences, missing = [], []
    for key in sorted(set(full) | set(reference), key=str):
        if scope == 'session' and (key not in full or key not in reference):
            reason = proofs.get(key, {}).get('missing')
            missing.append({'id': key, 'side': 'Colophon' if key in full else 'CodexBar',
                            'class': classify_difference(kind='tokens', explained_by=reason,
                                                         custom_build=custom_build), 'reason': reason})
    for path, candidate in (('full', full), ('fallback-only', fallback)):
        for key in sorted(set(candidate) | set(reference), key=str):
            left, right = candidate.get(key), reference.get(key)
            if left is None or right is None:
                reason = proofs.get(key, {}).get('unmetered')
                differences.append({'scope': scope, 'key': key,
                    'class': classify_difference(kind='tokens', explained_by=reason, custom_build=custom_build),
                    'detail': f'{path}: scope missing on one side' + (f'; {reason}' if reason else '')})
                continue
            for kind, fields in (('tokens', ('input', 'cached', 'output')), ('cost', ('cost',))):
                equal = all(parity_cost_equal(left.get(field), right.get(field)) if kind == 'cost'
                            else left.get(field) == right.get(field) for field in fields)
                if equal:
                    continue
                explanation = proofs.get(key, {}).get(f'{path}_{kind}')
                if explanation is None and proofs.get(key, {}).get('unmetered') and all(right.get(field) is None for field in fields):
                    explanation = proofs[key]['unmetered']
                if path == 'full' and key in fallback:
                    check = fallback[key]
                    verified = all(parity_cost_equal(check.get(field), right.get(field)) if kind == 'cost'
                                   else check.get(field) == right.get(field) for field in fields)
                    if verified:
                        explanation = proofs.get(key, {}).get(kind)
                    elif explanation is None and proofs.get(key, {}).get(f'fallback-only_{kind}') and proofs.get(key, {}).get(kind):
                        explanation = proofs[key][f'fallback-only_{kind}'] + '; ' + proofs[key][kind]
                differences.append({'scope': scope, 'key': key,
                    'class': classify_difference(kind=kind, explained_by=explanation, custom_build=custom_build),
                    'detail': f'{path} {kind}: Colophon { {f:left.get(f) for f in fields} } / '
                              f'CodexBar { {f:right.get(f) for f in fields} }'
                              + (f'; {explanation}' if explanation else '')})
    return differences, missing


class CodexBarPricing:
    """Cold fallback rows priced as pinned PricingRows.swift4–45, without ledger
    observations or sticky/cache state. The caller supplies only copied-trace
    priority turns and the same catalog snapshot seeded into the guarded CLI.
    """

    def __init__(self, colophon, snapshot: dict):
        self.colophon = colophon
        self.index = colophon.ModelsDevIndex.from_catalog(snapshot)
        self.history = colophon.PriceHistory(
            colophon.validate_ledger(colophon.CURATED_PRICE_HISTORY, curated=True).entries, [])
        self._priority_indexes = {}

    def cost(self, row, priority_turns: dict) -> float | None:
        module = self.colophon
        identity = module._codex_session_identity
        context = self._priority_indexes.get(id(priority_turns))
        if context is None:
            index = {}
            for key, value in priority_turns.items():
                index.setdefault(identity(key), value)
            # Strong reference prevents object-ID reuse during this immutable pass.
            context = (priority_turns, index)
            self._priority_indexes[id(priority_turns)] = context
        priority = None
        if row.turn_id is not None:
            priority = context[1].get(identity(row.turn_id))
        priced_model = row.model
        if priority is not None:
            raw = priority.get('model')
            if isinstance(raw, str) and module.codex_api_fast_multiplier(raw) is not None:
                priced_model = raw
        normalized = module.normalize_codex_model(priced_model)
        timestamp = row.timestamp_unix_ms
        cutoff = module.HISTORICAL_CUTOFFS.get(normalized)
        if timestamp is not None and cutoff is not None and timestamp < cutoff:
            picked = self.history.pick(normalized, timestamp)
            rates = picked.entry if picked is not None else None
        else:
            rates = module.resolve_rates(priced_model, self.index)
        if rates is None:
            return None
        counts = {'input': row.input, 'cached': row.cached, 'output': row.output}
        base = module.cost_usd(rates, **counts)
        if priority is None:
            return base
        multiplier = module.codex_api_fast_multiplier(priced_model)
        policy = None if multiplier is None else {
            'multiplier': multiplier,
            'max_input_tokens': None if normalized == 'gpt-6-astra' else 272000}
        fast = module.priority_cost_usd(rates, policy, **counts)
        return base if fast is None else max(base, fast)


def classify_coverage(report: object, *, stable: bool) -> str:
    """Missing or malformed coverage cannot establish complete history."""
    if not stable or not isinstance(report, dict):
        return 'partial'
    established = report.get('historyCoverageIsEstablished')
    if established is True:
        return 'complete'
    coverage = report.get('coverage')
    unmetered = coverage.get('unmetered') if isinstance(coverage, dict) else None
    if established is False and type(unmetered) is int and unmetered > 0:
        return 'complete with unresolved forks'
    return 'partial'


def classify_difference(*, kind: str, explained_by: str | None,
                        custom_build: bool = False) -> str:
    if kind not in ('tokens', 'cost'):
        raise ValueError('unknown difference kind')
    if custom_build:
        return 'd'
    if isinstance(explained_by, str) and explained_by.strip():
        return 'a'
    return 'b' if kind == 'tokens' else 'c'


def _markdown(value: object) -> str:
    return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('\n', '<br>')


def format_report(report: dict) -> str:
    labels = {'a': 'explained difference', 'b': 'unexplained token difference',
              'c': 'unexplained cost difference', 'd': 'custom-build difference'}
    build = report['build']
    lines = ['# Colophon / CodexBar parity', '',
             f"Build: {_markdown(build['kind'])}; SHA-256: {_markdown(build['sha256'])}",
             f"Coverage: {_markdown(report['coverage'])}; runs: {report['runs']}",
             f"historyCoverageIsEstablished: {report['historyCoverageIsEstablished']}",
             f"Bucket zone: {_markdown(report['bucket_tz'])}", '',
             'Costs: API-equivalent estimate (not billed).', '', '## Differences', '',
             '| Scope | Key | Classification | Detail |', '| --- | --- | --- | --- |']
    for item in report['differences']:
        lines.append('| ' + ' | '.join(_markdown(value) for value in (
            item['scope'], item['key'], labels[item['class']], item['detail'])) + ' |')
    lines += ['', '## Missing sessions', '', '| Session | Present in | Classification | Reason |',
              '| --- | --- | --- | --- |']
    for item in report['missing_sessions']:
        lines.append('| ' + ' | '.join(_markdown(value) for value in (
            item['id'], item['side'], labels[item['class']], item['reason'] or 'unexplained gap')) + ' |')
    lines += ['', '## Unresolved forks', '']
    lines.extend(f'- {_markdown(identifier)}' for identifier in report['unresolved_forks'])
    oracle = report.get('oracle')
    if oracle is not None:
        lines += ['', '## Native session oracle', '',
                  f"Oracle: {'complete' if oracle['complete'] else 'incomplete'}; observations: {len(oracle['observations'])}",
                  '', 'Structurally tied session IDs (all isolated cache files):']
        lines.extend(f'- {_markdown(identifier)}' for identifier in oracle['structural_ties'])
        if not oracle['structural_ties']:
            lines.append('- none')
        lines.extend(f'- {_markdown(message)}' for message in oracle['disagreements'])
        lines += ['', 'Required metrics without native evidence:']
        lines.extend(f'- {_markdown(metric)}' for metric in oracle.get('unknown_metrics', []))
        lines += ['', 'Source-proven deliberate unmetered-only days (raw metrics remain null):']
        lines.extend(f'- {_markdown(day)}: {_markdown(identifiers)}'
                     for day, identifiers in oracle.get('unmetered_exclusions', {}).items())
        lines += ['', 'Retained native observations:', '', '```json',
                  json.dumps(oracle['observations'], indent=2, sort_keys=True, allow_nan=False), '```']
    lines += ['', '## Evidence failures', '']
    lines.extend(f'- {_markdown(message)}' for message in report.get('failures', []))
    return '\n'.join(lines) + '\n'


def full_totals(colophon, compiled: dict) -> dict:
    corpus = compiled['corpus']
    projects, units = {}, []
    aliases, identities = comparison_identities(colophon, corpus)
    for raw_key, session in corpus.sessions.items():
        identifier = aliases[raw_key]
        projects[identifier] = (session.meta or {}).get('cwd') or session.db_info.get('cwd')
        units.extend(SimpleNamespace(session=identifier, owner=session, input=unit.input, cached=unit.cached,
            output=unit.output, cost_usd=unit.cost_usd, at_ms=unit.at_ms, source=unit.source,
            original=unit) for unit in session.units)
    totals = aggregate_units(units, projects=projects,
                             day_key=lambda at: colophon._codex_local_day_key(at / 1000))
    totals['units'] = units
    totals['identity_mapping'] = identities
    return totals


def priority_evidence(colophon, observed: dict, cold: dict, initial: dict, newer: set[str]) -> dict:
    identity = colophon._codex_session_identity
    cold_keys = {identity(key) for key in cold}
    stored = {identity(key): value for key, value in initial.items()}
    evidence = {}
    for spelling, value in observed.items():
        key = identity(spelling)
        if key not in cold_keys and stored.get(key) == value:
            evidence[key] = f'A4.3 sticky priority memory: turn {spelling} matches the initial copied memory and is absent from the cold trace'
        elif key in newer:
            evidence[key] = f'trace-database timing: turn {spelling} has matching parsed trace evidence newer than the copied rowid'
    return evidence


def fork_chain_evidence(parents: dict[str, str], native_unresolved: set[str]) -> dict:
    """Name concrete chains; the caller must prove native per-ID unresolved facts."""
    evidence = {}
    for identifier in sorted(native_unresolved):
        parent = parents.get(identifier)
        grandparent = parents.get(parent)
        if isinstance(parent, str) and isinstance(grandparent, str) and len({identifier, parent, grandparent}) == 3:
            evidence[identifier] = [identifier, parent, grandparent]
    return evidence


def attach_fork_evidence(colophon, compiled: dict, full: dict, fallback: dict, reference: dict,
                         native: dict, proofs: dict) -> dict:
    """Only native-qualified chains; prove other contributors still match exactly."""
    eligible = native_unmetered_facts(native)
    aliases, _ = comparison_identities(colophon, compiled['corpus'])
    sessions = {aliases[key]: session for key, session in compiled['corpus'].sessions.items()}
    parents = {identifier: colophon._codex_session_identity(session.forked_from)
               for identifier, session in sessions.items() if isinstance(session.forked_from, str)}
    qualifying = {identifier for identifier, fact in eligible.items()
                  if fact['parentID'] is not None and parents.get(identifier) == colophon._codex_session_identity(fact['parentID'])}
    chains = {identifier: chain for identifier, chain in fork_chain_evidence(parents, qualifying).items()
              if all(member in sessions and 'fork_baseline_unavailable' not in sessions[member].flags for member in chain)}
    if not chains:
        return {}
    reason = 'A4.7: native missing-parent/no-billed contributor in source-confirmed fork-of-fork chain ' + json.dumps(chains, sort_keys=True)
    projects = {unit.session: (unit.owner.meta or {}).get('cwd') or unit.owner.db_info.get('cwd') for unit in full['units']}
    for path, totals in (('full', full), ('fallback-only', fallback)):
        stripped = aggregate_units([unit for unit in totals['units'] if unit.session not in chains], projects=projects,
            native_costs=path == 'fallback-only', day_key=lambda at: colophon._codex_local_day_key(at / 1000))
        for scope in ('day', 'project', 'session'):
            for key, metric in totals[scope].items():
                if stripped[scope].get(key) == metric:
                    continue
                proof = proofs[scope].setdefault(key, {})
                other, expected = stripped[scope].get(key), reference[scope].get(key)
                if other is None and (expected is None or all(expected.get(field) is None for field in ('input', 'cached', 'output', 'cost'))):
                    if scope == 'day' and key not in deliberate_unmetered_exclusions(native):
                        continue
                    proof['unmetered'] = reason + '; no numerical reference is asserted for this unmetered-only scope'
                    if scope == 'session':
                        proof['missing'] = reason
                    continue
                if other is None or expected is None:
                    continue
                for kind, fields in (('tokens', ('input', 'cached', 'output')), ('cost', ('cost',))):
                    known = all(other.get(field) is not None and expected.get(field) is not None for field in fields)
                    equal = known and all(parity_cost_equal(other[field], expected[field]) if kind == 'cost'
                                          else other[field] == expected[field] for field in fields)
                    if equal:
                        proof[f'{path}_{kind}'] = reason + '; remaining contributors match the independent native reference'
    return chains


def newer_trace_turns(colophon, database: Path, last_rowid: int | None, *, observed: dict, cold: dict) -> set[str]:
    if not database.is_file():
        return set()
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)
    turns = set()
    identity = colophon._codex_session_identity
    observed = {identity(key): value for key, value in observed.items()}
    cold = {identity(key): value for key, value in cold.items()}
    try:
        connection.text_factory = bytes
        for _, timestamp, raw in connection.execute('SELECT rowid,ts,feedback_log_body FROM logs WHERE rowid>? AND ts>=0 ORDER BY rowid',
                                                    (last_rowid or 0,)):
            body = colophon._codex_sqlite_text(raw)
            if body is None:
                continue
            priority = colophon._parse_codex_priority_trace(colophon._codex_sqlite_text(timestamp), body)
            completed = colophon._parse_codex_completed_trace(body)
            if priority is not None:
                key, entry = identity(priority[0]), priority[1]
                if key in observed and all(observed[key].get(field) == entry.get(field) for field in ('thread_id', 'timestamp')):
                    turns.add(key)
            if completed is not None:
                key, model = identity(completed[0]), completed[1]
                if key in observed and key in cold and observed[key].get('model') == model and cold[key].get('model') != model:
                    turns.add(key)
    finally:
        connection.close()
    return turns


def validated_period_cost(colophon, unit, models: dict) -> bool:
    try:
        key, index = unit.period
        entry = models[key]['periods'][index]
        counts = {'input': unit.input, 'cached': unit.cached, 'output': unit.output}
        cost = colophon.cost_usd(entry, **counts)
        if unit.priority is not None and unit.priority_period is not None:
            key, index = unit.priority_period
            priority = models[key]['periods'][index]['priority']
            fast = colophon.priority_cost_usd(entry, priority, **counts)
            if fast is not None:
                cost = max(cost, fast)
        return parity_cost_equal(unit.cost_usd, cost)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return False


def confirmed_proofs(colophon, compiled: dict, full: dict, fallback: dict, catalog: dict,
                     *, priority_proofs: dict | None = None) -> dict:
    """Only declared deviations with actual contributing-unit evidence."""
    proofs = {scope: {} for scope in ('day', 'project', 'session')}
    pricing = CodexBarPricing(colophon, catalog)
    cold = fallback['priority_turns']
    for view in full['units']:
        unit = view.original
        session = view.owner
        keys = [('session', view.session), ('project', (session.meta or {}).get('cwd') or session.db_info.get('cwd'))]
        if view.at_ms is not None:
            keys.append(('day', colophon._codex_local_day_key(view.at_ms / 1000)))
        reasons = []
        valid_price = validated_period_cost(colophon, unit, compiled['payload'].get('models', {}))
        if unit.source == 'record':
            reasons.append('A4.1: this scope has contributing primary token_usage_record units; cold fallback is checked independently')
        source_cost = pricing.cost(unit, cold)
        cost_reasons = list(reasons) if valid_price else []
        if valid_price and not parity_cost_equal(unit.cost_usd, source_cost):
            current_with_same_priority = pricing.cost(unit, compiled['priority'].turns)
            if not parity_cost_equal(unit.cost_usd, current_with_same_priority):
                cost_reasons.append(f'A4.2: unit {view.session}:{unit.file}:{unit.line} cost matches reported periods '
                    f'{unit.period}/{unit.priority_period} and differs from source rates with the same observed priority evidence')
            if unit.priority is not None and unit.turn_id is not None:
                evidence = (priority_proofs or {}).get(colophon._codex_session_identity(unit.turn_id))
                if evidence:
                    cost_reasons.append(evidence)
        for scope, key in keys:
            proof = proofs[scope].setdefault(key, {})
            if unit.source == 'record':
                proof['tokens'] = reasons[0]
            if cost_reasons:
                proof['cost'] = '; '.join(dict.fromkeys([proof.get('cost', ''), *cost_reasons])).strip('; ')
    return proofs


def _isolated_runtime(module, source: Path, destination: Path, *, offline_catalog: bool) -> dict:
    module.ensure_runtime_home(destination)
    for name in ('price-history.json', 'pricing-cache.json', 'priority-turns.json'):
        path = source / name
        if path.is_file():
            shutil.copy2(path, destination / name)
    catalog = module.fetch_catalog(os.environ.get('COLOPHON_PRICING_URL', module.DEFAULT_PRICING_URL),
        destination / 'pricing-cache.json', offline=offline_catalog, refresh=False, now_ms=module.now_ms())
    if catalog.catalog is None:
        raise ValueError('no shared catalog snapshot available in temporary Colophon pricing cache')
    return json.loads((destination / 'pricing-cache.json').read_bytes())['catalog']


def _trace_backup(source: Path, destination: Path) -> int | None:
    if not source.is_file():
        return None
    source_db = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)
    target = sqlite3.connect(destination)
    try:
        source_db.backup(target)
        return target.execute('SELECT max(rowid) FROM logs').fetchone()[0]
    finally:
        source_db.close()
        target.close()


def _read_scan_metadata(database: Path) -> dict:
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)
    try:
        rows = connection.execute('SELECT payload FROM scan_metadata').fetchall()
        if len(rows) != 1:
            raise ValueError('unknown scan metadata')
        metadata = json.loads(rows[0][0])
        if not isinstance(metadata.get('timeZoneIdentifier'), str):
            raise ValueError('unknown bucket time zone')
        return metadata
    finally:
        connection.close()


def _json_report(stdout: str) -> dict:
    report = strict_json(stdout)
    if not isinstance(report, list) or len(report) != 1 or not isinstance(report[0], dict):
        raise ValueError('unexpected CLI JSON shape')
    return report[0]


def run_comparison(args, *, module, guard) -> tuple[dict, int]:
    """Maintainer runtime. All CodexBar execution stays in the imported guard."""
    project = Path(__file__).resolve().parents[2]
    repository = project.parent
    for path in (args.output_dir, args.work_parent):
        if path.resolve().is_relative_to(repository):
            raise ValueError('private output/work must be outside repository')
    real_home = Path.home().resolve()
    if not args.real_data_approved and any(path.resolve().is_relative_to(real_home)
            for path in (args.codex_home, args.colophon_home, args.output_dir)):
        raise ValueError('real-data/home access requires separate explicit approval')
    if not args.codex_home.is_dir():
        raise ValueError('Codex source home missing')
    guard.require_symlink_free(args.codex_home)
    source_files = source_inputs(args.codex_home)
    for path in source_files:
        guard.require_symlink_free(path)
    for path in selected_runtime_inputs(args.codex_home, args.colophon_home):
        guard.require_symlink_free(path)
    guard.require_symlink_free(args.work_parent)
    native = prepared_native(args.native_clone, args.native_bundle, args.native_provenance)
    cli_hash = guard.sha256_file(args.cli)
    custom = cli_hash != guard.PINNED_CLI_SHA256
    if custom and not args.custom_build:
        raise ValueError('pinned CLI hash mismatch; a custom build must be explicitly selected')
    provenance = args.cli.parent / 'PROVENANCE.md'
    if not custom and guard.PINNED_CLI_SHA256 not in provenance.read_text():
        raise ValueError('pinned CLI provenance mismatch')
    if guard.app_running():
        raise ValueError('REFUSED: CodexBar app is running')
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'build': {'kind': 'custom' if custom else 'pinned', 'sha256': cli_hash,
                       'source_commit': None if custom else PINNED_COMMIT},
        'native_provenance': native, 'coverage': 'partial', 'runs': 0,
        'historyCoverageIsEstablished': None, 'bucket_tz': None, 'differences': [],
        'missing_sessions': [], 'unresolved_forks': [], 'failures': [],
        'oracle': {'complete': False, 'structural_ties': [], 'disagreements': [], 'observations': []},
        'cost_tolerance': {'parity': 'abs(delta) <= 1e-9*abs(reference)+1e-9 USD',
                           'native_relative': COST_REL_TOL, 'native_absolute': COST_ABS_TOL}}
    previous_tz = os.environ.get('TZ')
    before = guard.real_state_fingerprint()
    (args.output_dir / 'before-fingerprint.txt').write_text(before)
    try:
        with tempfile.TemporaryDirectory(prefix='colophon-parity-', dir=args.work_parent) as temporary:
            work = Path(temporary)
            guard.require_symlink_free(work)
            fake, runtime = work / 'fake-home', work / 'colophon-home'
            catalog = _isolated_runtime(module, args.colophon_home, runtime, offline_catalog=args.offline_catalog)
            (args.output_dir / 'shared-catalog.json').write_text(json.dumps(catalog, sort_keys=True, allow_nan=False) + '\n')
            report['catalog_sha256'] = file_hash(args.output_dir / 'shared-catalog.json')
            initial_messages = []
            initial_priority = module._stored_priority_turns(runtime / 'priority-turns.json', initial_messages)
            report['failures'].extend(initial_messages)
            guard.seed_fake_home(fake, catalog)
            report['trace_copy_last_rowid'] = _trace_backup(args.codex_home / 'logs_2.sqlite', fake / '.codex/logs_2.sqlite')
            profile = work / 'guard.sb'
            profile.write_text(guard.profile_text(allow_real_codex_read=args.real_data_approved))
            guard.self_test_guard(profile, expect_real_codex_read_denied=not args.real_data_approved)
            commands = [list(guard.COST_COMMAND), [*guard.COST_COMMAND, '--group-by', 'session'],
                        [*guard.COST_COMMAND, '--group-by', 'project']]
            report['commands'], report['environment'] = commands, guard.guarded_env(fake, args.codex_home)
            cli_reports = []

            def cli_snapshot(stdouts):
                nonlocal cli_reports
                cli_reports = [_json_report(stdout) for stdout in stdouts]
                report['runs'] += 1
                for label, stdout in zip(('default', 'session', 'project'), stdouts):
                    (args.output_dir / f'cli-{label}.json').write_text(stdout)
                normalized = [{key: value for key, value in item.items() if key != 'updatedAt'} for item in cli_reports]
                report['cli_reports'] = cli_reports
                return guard.canonical(normalized)

            cli_stable = False
            try:
                guard.run_until_stable(args.cli, profile, fake, args.codex_home, commands, cli_snapshot,
                                       max_runs=args.max_runs, stable_runs=3)
                cli_stable = True
            except RuntimeError as exc:
                report['failures'].append(str(exc))
                if not str(exc).startswith('no stable result after'):
                    raise
            if not cli_reports:
                raise ValueError('no CLI report evidence')
            cli = cli_reports[0]
            if any(not material_equal({key: value for key, value in cli.items() if key != 'updatedAt'},
                    {key: value for key, value in other.items() if key != 'updatedAt'}) for other in cli_reports[1:]):
                report['failures'].append('CLI grouped JSON reports disagree')
            report['coverage'] = classify_coverage(cli, stable=cli_stable)
            report['cli_coverage'] = report['coverage']
            report['historyCoverageIsEstablished'] = cli.get('historyCoverageIsEstablished')
            database = fake / 'Library/Caches/CodexBar/cost-usage/cost-usage.sqlite'
            metadata = _read_scan_metadata(database)
            report['scan_metadata'], report['bucket_tz'] = metadata, metadata['timeZoneIdentifier']
            if metadata.get('catchUpPending') is not False or metadata.get('completedFiles') != metadata.get('totalFiles'):
                report['coverage'] = 'partial'
                report['failures'].append('CLI scan is not complete')
            os.environ['TZ'] = report['bucket_tz']
            time.tzset()
            snapshot_ms = module.now_ms()
            compiled = compile_colophon(module, args.codex_home, runtime, args.output_dir / 'colophon.html',
                                        snapshot_ms=snapshot_ms)
            (args.output_dir / 'colophon.stdout').write_text(compiled['stdout'])
            (args.output_dir / 'colophon.stderr').write_text(compiled['stderr'])
            native_input = fake / 'native-input.json'
            native_input.write_text(json.dumps({'nowUnixMs': snapshot_ms, 'bucket_tz': report['bucket_tz']}))
            immutable = [native_input, fake / 'Library/Caches/CodexBar/model-pricing/models-dev-v1.json']
            if (fake / '.codex/logs_2.sqlite').exists():
                immutable.append(fake / '.codex/logs_2.sqlite')
            immutable.extend(source_files)
            input_before = input_fingerprint(database, immutable)
            report['input_fingerprint_before'] = input_before
            ties = structural_ties(read_isolated_files(database))
            observations = []
            stable_native = None
            native_command = [str(project / 'tests/parity/native_oracle/run_native.sh'), str(args.native_bundle)]
            report['native_command'] = ['/bin/sh', *native_command]

            def native_snapshot(stdouts):
                nonlocal stable_native
                index = len(observations) + 1
                (args.output_dir / f'native-attempt-{index}.stdout').write_text(stdouts[0])
                observation = parse_native_stdout(stdouts[0])
                observations.append(observation)
                if input_fingerprint(database, immutable) != input_before:
                    raise ValueError('native cache/catalog/trace/window/source inputs changed during observations')
                # Keep every full observation. A later identical suffix cannot
                # erase any disagreement in assess_native_oracle.
                current = {key: value for key, value in observation.items() if key != 'nowUnixMs'}
                if stable_native is None or not material_equal(stable_native, current):
                    stable_native = current
                return stable_native

            if report['coverage'] != 'partial':
                try:
                    guard.run_until_stable(Path('/bin/sh'), profile, fake, args.codex_home, [native_command],
                        native_snapshot, max_runs=args.native_runs, stable_runs=3)
                except (RuntimeError, ValueError) as exc:
                    report['failures'].append(str(exc))
            report['oracle'] = assess_native_oracle(observations, ties=ties)
            if ties:
                report['failures'].append('structural ties make the native session oracle incomplete')
            report['input_fingerprint_after'] = input_fingerprint(database, immutable)
            if report['input_fingerprint_after'] != input_before:
                report['oracle']['complete'] = False
                report['failures'].append('native inputs changed')
            for observation in observations:
                crosscheck_failures = crosscheck_native(observation, cli)
                report['failures'].extend(crosscheck_failures)
                if crosscheck_failures:
                    report['oracle']['complete'] = False
            for name in ('native-run.stdout', 'native-run.stderr'):
                if (fake / name).is_file():
                    shutil.copy2(fake / name, args.output_dir / name)
            full = full_totals(module, compiled)
            fallback = fallback_totals(module, compiled['corpus'], fake, catalog)
            newer = newer_trace_turns(module, args.codex_home / 'logs_2.sqlite', report['trace_copy_last_rowid'],
                observed=compiled['priority'].turns, cold=fallback['priority_turns'])
            report['trace_newer_turns'] = sorted(newer)
            report['unresolved_forks'] = compiled['payload']['diagnostics']['fork_baseline_unavailable']
            report['trace_messages'] = fallback['trace_messages']
            if fallback['trace_messages']:
                report['failures'].append('cold trace recomputation has unknown evidence')
            if observations:
                reference = reference_totals(observations[-1], complete=report['coverage'] == 'complete')
                priority_proofs = priority_evidence(module, compiled['priority'].turns, fallback['priority_turns'], initial_priority, newer)
                report['priority_evidence'] = priority_proofs
                proofs = confirmed_proofs(module, compiled, full, fallback, catalog, priority_proofs=priority_proofs)
                report['fork_chain_evidence'] = attach_fork_evidence(module, compiled, full, fallback, reference,
                                                                    observations[-1], proofs)
                report['difference_evidence'] = proofs
                for scope in ('day', 'project', 'session') if report['oracle']['complete'] else ():
                    differences, missing = compare_scope(scope, full[scope], reference[scope], fallback[scope],
                        proofs=proofs[scope], custom_build=custom)
                    report['differences'].extend(differences)
                    report['missing_sessions'].extend(missing)
                report['reference'] = reference
                if not report['oracle']['complete']:
                    observed_ids = set().union(*(set(item['sessions']) for item in observations))
                    for identifier in sorted(set(full['session']) ^ observed_ids):
                        report['missing_sessions'].append({'id': identifier,
                            'side': 'Colophon' if identifier in full['session'] else 'CodexBar',
                            'class': 'd' if custom else 'b',
                            'reason': 'incomplete native oracle: observed ID presence gap; absence is not proved'})
            report['colophon'] = {scope: full[scope] for scope in ('day', 'project', 'session', 'unknown_time_sessions', 'identity_mapping')}
            report['fallback'] = {scope: fallback[scope] for scope in ('day', 'project', 'session', 'unknown_time_sessions', 'unpriced_tokens')}
    except (ValueError, RuntimeError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        report['failures'].append(f'{type(exc).__name__}: {exc}')
    finally:
        if previous_tz is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = previous_tz
        time.tzset()
        after = guard.real_state_fingerprint()
        report['fingerprint_unchanged'] = before == after
        (args.output_dir / 'after-fingerprint.txt').write_text(after)
        if before != after:
            report['failures'].append('real CodexBar cache/preferences fingerprint changed')
        failed = bool(report['failures'] or report['coverage'] == 'partial' or not report['oracle']['complete'] or any(
            item['class'] in ('b', 'c', 'd') for item in report['differences'] + report['missing_sessions']))
        report['accepted'] = not failed
        report['failures'] = list(dict.fromkeys(report['failures']))
        (args.output_dir / 'report.json').write_text(serialize_report(report))
        (args.output_dir / 'report.md').write_text(format_report(report))
    return report, 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Private Colophon/CodexBar parity. Native oracle must be prepared externally.')
    parser.add_argument('--codex-home', type=Path, default=Path.home() / '.codex')
    parser.add_argument('--colophon-home', type=Path, default=Path(os.environ.get('COLOPHON_HOME', str(Path.home() / '.colophon'))))
    parser.add_argument('--cli', type=Path, default=Path.home() / 'Downloads/colophon-prebuilt/codexbar-cli-3bbf6bc48/CodexBarCLI')
    parser.add_argument('--custom-build', action='store_true')
    parser.add_argument('--native-clone', type=Path, required=True)
    parser.add_argument('--native-bundle', type=Path, required=True)
    parser.add_argument('--native-provenance', type=Path, required=True)
    parser.add_argument('--record-native-provenance', action='store_true')
    parser.add_argument('--approved', action='store_true', help='explicitly authorized guarded execution; not permission for real data')
    parser.add_argument('--real-data-approved', action='store_true', help='separate human approval for selected real homes/data')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--work-parent', type=Path, default=Path('/private/var/tmp'))
    parser.add_argument('--offline-catalog', action='store_true')
    parser.add_argument('--max-runs', type=int, default=30)
    parser.add_argument('--native-runs', type=int, default=10)
    args = parser.parse_args(argv)
    if args.record_native_provenance:
        if args.native_provenance.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
            parser.error('provenance must remain outside the repository')
        prepared_native(args.native_clone, args.native_bundle, args.native_provenance, record=True)
        print(f'Native provenance: {args.native_provenance}')
        return 0
    if not args.approved:
        parser.error('guarded execution needs explicit human approval (--approved)')
    if args.max_runs < 3 or args.native_runs < 3:
        parser.error('at least three runs are required')
    if args.output_dir is None:
        args.output_dir = args.colophon_home / 'parity' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    sys.dont_write_bytecode = True
    project = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(project.parent), str(project / 'tests/tools')]
    from tools.testkit import load_launcher
    import codexbar_expected as guard
    module = load_launcher(project / 'colophon')
    try:
        report, status = run_comparison(args, module=module, guard=guard)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'parity: {exc}', file=sys.stderr)
        return 1
    print(f"parity: {'accepted' if report['accepted'] else 'FAILED'}; {args.output_dir / 'report.md'}")
    return status


if __name__ == '__main__':
    raise SystemExit(main())
