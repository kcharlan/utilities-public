"""Pure acceptance helpers only: synthetic JSON/Swift, no upstream or CLI."""
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


def helper(name):
    path = Path(__file__).parent / 'parity' / f'{name}.py'
    assert path.is_file(), f'missing acceptance helper {name}'
    spec = importlib.util.spec_from_file_location(f'acceptance_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native_observation(value=500):
    return {'sessions': {'synthetic-tie': {'sessionID': 'synthetic-tie', 'inputTokens': value,
        'cachedInputTokens': 20, 'outputTokens': 10, 'reasoningTokens': None,
        'totalTokens': value + 10, 'requestCount': None, 'costUSD': .00125,
        'lastActivityUnixMs': 1000, 'projectPath': '/synthetic/project', 'modelBreakdowns': []}},
        'daily': [], 'projects': [], 'historyCoverageIsEstablished': True,
        'historyScanIsPartial': False, 'nowUnixMs': 123}


def cache_file(identifier, session, mtime, path=None):
    return {'id': identifier, 'session_id': session, 'mtime_ms': mtime,
            'path': path or f'/synthetic/{identifier}.jsonl'}


def native_project():
    day = {'date': '2024-01-07', 'inputTokens': 500, 'cacheReadTokens': 20,
           'outputTokens': 10, 'totalTokens': 510, 'costUSD': .00125}
    model = {'modelName': 'gpt-synthetic', 'totalTokens': 510, 'costUSD': .00125,
             'standardCostUSD': .001, 'priorityCostUSD': .00025}
    return {'path': '/synthetic/project', 'totalTokens': 510, 'totalCostUSD': .00125,
            'daily': [day], 'modelBreakdowns': [model], 'sources': [
                {'name': 'Synthetic source', 'path': None, 'totalTokens': None,
                 'totalCostUSD': None, 'daily': [], 'modelBreakdowns': None}]}


def native_nested_scope(scope):
    observation = native_observation()
    project = native_project()
    observation['projects'] = [project]
    project['sources'] = [json.loads(json.dumps({key: value for key, value in project.items() if key != 'sources'}))]
    observation['daily'] = json.loads(json.dumps(project['daily']))
    targets = {'session': observation['sessions']['synthetic-tie'], 'day': observation['daily'][0],
               'project-day': project['daily'][0], 'source-day': project['sources'][0]['daily'][0],
               'project': project, 'source': project['sources'][0]}
    return observation, targets[scope]


@pytest.mark.parametrize('scope', ['session', 'day', 'project-day', 'source-day', 'project', 'source'])
@pytest.mark.parametrize('row', [None, {'modelName': 'gpt-synthetic', 'inputTokens': True},
    {'modelName': 'gpt-synthetic', 'requestCount': 1.5},
    {'modelName': 'gpt-synthetic', 'priorityTokens': 2**63},
    {'modelName': 'gpt-synthetic', 'standardCostUSD': -1},
    {'modelName': 'gpt-synthetic', 'costUSD': 10**400}],
    ids=['null-row', 'bool-count', 'fractional-count', 'int-overflow', 'negative-money', 'double-overflow'])
def test_native_nested_models_fail_closed_in_every_scope(scope, row):
    observation, target = native_nested_scope(scope)
    target['modelBreakdowns'] = [row]
    module = helper('compare_codexbar')
    with pytest.raises(ValueError, match='native'):
        module.validate_native(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False


@pytest.mark.parametrize('field', ['inputTokens', 'cacheReadTokens', 'cacheCreationTokens', 'outputTokens',
    'reasoningTokens', 'totalTokens', 'requestCount', 'unpricedRequestCount', 'pricedRequestCount',
    'unmeteredRequestCount', 'estimatedRequestCount'])
@pytest.mark.parametrize('value', [True, 1.5, -1, 2**63, 10**400],
                         ids=['bool', 'fractional', 'negative', 'int-overflow', 'huge-int'])
def test_native_daily_source_counts_are_bounded_ints(field, value):
    module = helper('compare_codexbar')
    for scope in ('day', 'project-day', 'source-day'):
        observation, target = native_nested_scope(scope)
        target[field] = value
        with pytest.raises(ValueError):
            module.validate_native(observation)


@pytest.mark.parametrize('damage', ['bad-model-list', 'bad-model-name', 'bad-models-used', 'bad-models-used-row'])
def test_native_daily_nested_shapes_are_source_typed(damage):
    module = helper('compare_codexbar')
    for scope in ('day', 'project-day', 'source-day'):
        observation, target = native_nested_scope(scope)
        target.update({'modelBreakdowns': None, 'modelsUsed': None})
        if damage == 'bad-model-list':
            target['modelBreakdowns'] = {}
        elif damage == 'bad-model-name':
            target['modelBreakdowns'] = [{'modelName': None}]
        elif damage == 'bad-models-used':
            target['modelsUsed'] = 'gpt-synthetic'
        else:
            target['modelsUsed'] = ['gpt-synthetic', None]
        with pytest.raises(ValueError, match='native'):
            module.validate_native(observation)


@pytest.mark.parametrize('scope', ['session', 'day', 'project-day', 'source-day', 'project', 'source'])
@pytest.mark.parametrize('value', [True, -1, float('inf'), 10**400],
                         ids=['bool-money', 'negative-money', 'nonfinite-money', 'unrepresentable-money'])
def test_native_source_money_rejects_invalid_values_cleanly(scope, value):
    observation, target = native_nested_scope(scope)
    target['totalCostUSD' if scope in ('project', 'source') else 'costUSD'] = value
    with pytest.raises(ValueError):
        helper('compare_codexbar').validate_native(observation)


def test_native_finite_double_limit_and_optional_day_nil_are_preserved():
    observation, target = native_nested_scope('day')
    target.update(costUSD=1.7976931348623157e308, modelBreakdowns=None, modelsUsed=None,
                  pricedRequestCount=None, estimatedRequestCount=0)
    raw = json.loads(json.dumps(observation))
    module = helper('compare_codexbar')
    assert module.validate_native(observation) == raw
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    assert module.material_equal({'costUSD': 1.0}, {'costUSD': 1.0 + 1e-14}) is True
    assert observation == raw


def test_native_source_optional_omissions_nulls_and_int_limits_remain_exact():
    module = helper('compare_codexbar')
    for scope in ('session', 'day', 'project-day', 'source-day', 'project', 'source'):
        observation, target = native_nested_scope(scope)
        target['modelBreakdowns'] = [{'modelName': 'gpt-synthetic', 'costUSD': None,
                                     'inputTokens': 2**63 - 1, 'priorityCostUSD': .00025}]
        if scope.endswith('day') or scope == 'day':
            target.update(modelsUsed=None, requestCount=None, unpricedRequestCount=2**63 - 1)
        raw = json.loads(json.dumps(observation))
        assert module.validate_native(observation) == raw
        # Optional encoder omissions remain omitted rather than filled as zeros.
        assert 'outputTokens' not in target['modelBreakdowns'][0]
        assert target['modelBreakdowns'][0]['costUSD'] is None
        assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
        assert observation == raw
    observation = native_observation()
    observation['sessions']['synthetic-tie']['inputTokens'] = 2**63
    with pytest.raises(ValueError, match='native'):
        module.validate_native(observation)


@pytest.mark.parametrize('text', [
    '{"sessions":{"synthetic-tie":{"inputTokens":600},"synthetic-tie":{"inputTokens":500}}}',
    '{"sessions":{"synthetic-tie":{"inputTokens":600,"inputTokens":500}}}',
    '[{"daily":[{"inputTokens":600,"inputTokens":500}]}]',
    '{"projects":[{"sources":[{"modelBreakdowns":[{"costUSD":1,"costUSD":2}]}]}]}',
    '{"a":1,"\\u0061":2}',
    '{"inputTokens":500,"inputTokens":500}',
], ids=['session-id', 'session-metric', 'cli-day-metric', 'deep-model-money', 'escaped-key', 'agreeing-values'])
def test_acceptance_json_rejects_repeated_object_keys(text):
    with pytest.raises(ValueError, match='duplicate'):
        helper('compare_codexbar').strict_json(text)


def test_acceptance_json_optional_nulls_and_distinct_keys_are_retained():
    text = '{"synthetic-é":{"costUSD":null},"synthetic-é":{"costUSD":0},"daily":[]}'
    assert helper('compare_codexbar').strict_json(text) == json.loads(text)


@pytest.mark.parametrize('field', ['modelBreakdowns', 'sources'])
def test_native_project_missing_breakdown_evidence_is_incomplete(field):
    observation = native_observation()
    project = native_project()
    project.pop(field)
    observation['projects'] = [project]
    assert helper('compare_codexbar').assess_native_oracle([observation] * 3, ties=[])['complete'] is False


@pytest.mark.parametrize('damage', ['missing_models', 'missing_cost', 'malformed_day', 'bad_sources'])
def test_native_source_schema_is_required_for_stability(damage):
    observation = native_observation()
    project = native_project()
    if damage == 'bad_sources':
        project['sources'] = [None]
    elif damage == 'missing_models':
        project['sources'][0].pop('modelBreakdowns')
    elif damage == 'missing_cost':
        project['sources'][0].pop('totalCostUSD')
    else:
        project['sources'][0]['daily'] = [{'date': 'synthetic', 'inputTokens': True}]
    observation['projects'] = [project]
    assert helper('compare_codexbar').assess_native_oracle([observation] * 3, ties=[])['complete'] is False


@pytest.mark.parametrize('scope', ['project', 'source'])
def test_native_project_and_source_breakdowns_are_retained_and_checked(scope):
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['projects'] = [native_project()]
    encoded = 'NATIVE_ORACLE_JSON:' + json.dumps(observation)
    assert module.parse_native_stdout(encoded) == observation
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    changed = json.loads(json.dumps(observation))
    target = changed['projects'][0]
    if scope == 'source':
        target = target['sources'][0]
        target['totalTokens'] = 1
    else:
        target['modelBreakdowns'][0]['totalTokens'] += 1
    oracle = module.assess_native_oracle([observation, observation, changed], ties=[])
    assert oracle['complete'] is False
    assert oracle['observations'][-1] == changed


@pytest.mark.parametrize('scope', ['project', 'source'])
@pytest.mark.parametrize('field', ['standardCostUSD', 'priorityCostUSD'])
def test_native_model_cost_components_use_declared_tolerance(field, scope):
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['projects'] = [native_project()]
    if scope == 'source':
        observation['projects'][0]['sources'][0]['modelBreakdowns'] = [
            dict(observation['projects'][0]['modelBreakdowns'][0])]
    changed = json.loads(json.dumps(observation))
    target = changed['projects'][0]
    if scope == 'source':
        target = target['sources'][0]
    target['modelBreakdowns'][0][field] += 1e-14
    assert module.assess_native_oracle([observation, observation, changed], ties=[])['complete'] is True
    target['modelBreakdowns'][0][field] += 1e-5
    assert module.assess_native_oracle([observation, observation, changed], ties=[])['complete'] is False
    assert module.material_equal({field: None}, {field: 0}) is False
    assert module.material_equal({'standardTokens': 1}, {'standardTokens': 1 + 1e-14}) is False


def test_native_optional_breakdowns_and_encoded_omissions_remain_distinct():
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['projects'] = [native_project()]
    observation['projects'][0]['modelBreakdowns'] = [{'modelName': 'gpt-synthetic'}]
    original = json.loads(json.dumps(observation))
    assert module.parse_native_stdout('NATIVE_ORACLE_JSON:' + json.dumps(observation)) == original
    changed = json.loads(json.dumps(observation))
    changed['projects'][0]['sources'][0]['modelBreakdowns'] = []
    assert module.assess_native_oracle([observation, observation, changed], ties=[])['complete'] is False
    assert observation == original


@pytest.mark.parametrize('change', [None, 'project_model_tokens', 'project_model_cost',
                                  'source_tokens', 'source_cost', 'source_model_tokens', 'source_model_cost',
                                  'project_daily_model_tokens', 'project_daily_model_cost',
                                  'source_daily_model_tokens', 'source_daily_model_cost', 'day_model_tokens', 'day_model_cost'])
def test_native_crosscheck_includes_cli_project_model_and_source_metrics(change):
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['projects'] = [native_project()]
    project = observation['projects'][0]
    project['daily'][0]['modelBreakdowns'] = project['modelBreakdowns']
    observation['daily'] = json.loads(json.dumps(project['daily']))
    project['sources'] = [json.loads(json.dumps({key: value for key, value in project.items() if key != 'sources'}))]
    def cli_models(rows):
        return None if rows is None else [
            {'modelName': row['modelName'], 'totalTokens': row.get('totalTokens'), 'cost': row.get('costUSD')}
            for row in rows]
    def cli_days(rows):
        return [{**{key: value for key, value in row.items() if key not in ('costUSD', 'modelBreakdowns')},
                 'totalCost': row['costUSD'], 'modelBreakdowns': cli_models(row.get('modelBreakdowns'))}
                for row in rows]
    def cli_part(part):
        return {'path': part['path'], 'totalTokens': part['totalTokens'], 'totalCost': part['totalCostUSD'],
                'daily': cli_days(part['daily']), 'modelBreakdowns': cli_models(part['modelBreakdowns'])}
    cli_project = cli_part(project)
    cli_project['sources'] = [cli_part(part) for part in project['sources']]
    cli = {'daily': cli_days(observation['daily']), 'projects': [cli_project]}
    if change:
        target = cli_project if change.startswith('project_') else cli['daily'][0] if change.startswith('day_') else cli_project['sources'][0]
        if '_daily_' in change:
            target = target['daily'][0]
        if 'model_' in change:
            target = target['modelBreakdowns'][0]
        field = 'cost' if 'model_cost' in change else 'totalCost' if change.endswith('cost') else 'totalTokens'
        target[field] += .01 if change.endswith('cost') else 1
    failures = module.crosscheck_native(observation, cli)
    assert bool(failures) is (change is not None)


def test_native_reference_and_incomplete_presence_use_canonical_ids():
    module = helper('compare_codexbar')
    observation = native_observation()
    session = observation['sessions'].pop('synthetic-tie')
    session['sessionID'] = 'synthetic-e\u0301'
    observation['sessions']['synthetic-e\u0301'] = session
    raw = json.loads(json.dumps(observation))
    reference = module.reference_totals(observation)['session']
    assert set(reference) == {'synthetic-é'}
    full = {'synthetic-é': reference['synthetic-é']}
    assert module.compare_scope('session', full, reference, full, proofs={}, custom_build=False) == ([], [])
    assert module.observed_session_ids([observation] * 3) == {'synthetic-é'}
    assert set(full) ^ module.observed_session_ids([observation] * 3) == set()
    assert (set(full) | {'synthetic-really-missing'}) ^ module.observed_session_ids([observation] * 3) == {'synthetic-really-missing'}
    assert observation == raw
    duplicate = json.loads(json.dumps(observation))
    duplicate['sessions']['synthetic-é'] = {**session, 'sessionID': 'synthetic-é'}
    with pytest.raises(ValueError, match='canonical'):
        module.reference_totals(duplicate)


def test_shared_crosscheck_preserves_nil_omissions_and_cli_zero_metadata_filter():
    module = helper('compare_codexbar')
    observation = native_observation()
    project = native_project()
    project['path'] = None
    project['modelBreakdowns'][0]['incompleteRequestCount'] = 0
    observation['projects'] = [project]
    cli = {'daily': [], 'projects': [{'totalTokens': 510, 'totalCost': .00125,
        'daily': [{**row, 'totalCost': row['costUSD']} for row in project['daily']],
        'modelBreakdowns': [{'modelName': 'gpt-synthetic', 'totalTokens': 510, 'cost': .00125}],
        'sources': [{'name': 'Synthetic source', 'daily': []}]}]}
    assert module.crosscheck_native(observation, cli) == []
    assert project['sources'][0]['totalCostUSD'] is None
    assert 'totalCost' not in cli['projects'][0]['sources'][0]
    assert project['modelBreakdowns'][0]['incompleteRequestCount'] == 0


def test_pinned_default_foundation_scalar_is_not_escaped_metadata_evidence(colophon):
    line = b'{"timestamp":"2024-01-07T00:00:00Z","type":"session_meta","payload":{"id":"synthetic-e\\u0301"}}'
    fast = colophon._codex_fast_line(line)
    assert fast[0] == 'M'
    assert fast[1]['session_id'] is None
    builder = colophon.TokenStreamBuilder()
    builder.feed(0, line, None, terminated=True)
    assert builder.result()['observations'][0] == ['P', fast[1]]


def test_pinned_default_foundation_scalar_does_not_change_escaped_model_context(colophon):
    line = b'{"timestamp":"2024-01-07T00:00:00Z","type":"turn_context","payload":{"model":"gpt\\u002d5.4"}}'
    fast = colophon._codex_fast_line(line)
    assert fast[0] == 'C'
    assert fast[2] is None


def test_escaped_context_replay_retains_prior_model_counts_and_source_price(colophon, tmp_path):
    from fixturegen import CodexHome
    home = CodexHome(tmp_path / 'synthetic-foundation-source')
    builder = home.log('synthetic-foundation-context', day='2024-01-07').meta().task_started(
        'synthetic-foundation-turn').turn_context(model='gpt-5.5')
    builder.raw(b'{"timestamp":"2024-01-07T00:00:00.003Z","ordinal":3,"type":"turn_context",'
                b'"payload":{"model":"gpt\\u002d5.4"}}\n')
    builder.token_count(last={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10},
                        total={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10}).task_complete().write()
    runtime = tmp_path / 'synthetic-runtime'
    colophon.ensure_runtime_home(runtime)
    catalog = synthetic_pricing_catalog()
    catalog['openai']['models']['gpt-5.5']['cost'] = {'input': 4, 'cache_read': 1, 'output': 16}
    colophon.atomic_write_json(runtime / 'pricing-cache.json', {'schema': 1, 'url': 'https://example.invalid/synthetic',
        'catalog': catalog, 'fetched_at_ms': 1704585600000, 'etag': None})
    module = helper('compare_codexbar')
    compiled = module.compile_colophon(colophon, home.root, runtime, tmp_path / 'synthetic.html', snapshot_ms=1704585700000)
    fake = tmp_path / 'synthetic-fake'
    fake.mkdir()
    fallback = module.fallback_totals(colophon, compiled['corpus'], fake, catalog)
    metric = fallback['session']['synthetic-foundation-context']
    assert {field: metric[field] for field in ('input', 'cached', 'output')} == {'input': 100, 'cached': 20, 'output': 10}
    assert {unit.original.model for unit in fallback['units']} == {'gpt-5.5'}
    # Pinned context route keeps gpt-5.5:80*4+20*1+10*16 per million.
    assert metric['cost'] == pytest.approx(.0005, rel=0, abs=1e-15)


def test_structural_ties_are_per_id_at_maximum_mtime_only():
    rows = [cache_file(1, 'synthetic-a', 1), cache_file(2, 'synthetic-a', 1),
            cache_file(3, 'synthetic-a', 2), cache_file(4, 'synthetic-b', 3),
            cache_file(5, 'synthetic-b', 3), cache_file(6, 'synthetic-c', 3)]
    assert helper('compare_codexbar').structural_ties(rows) == ['synthetic-b']


def test_structural_ties_distinct_files_and_filename_fallback():
    row = cache_file(1, None, 4, '/synthetic/one/synthetic-fallback.jsonl')
    assert helper('compare_codexbar').structural_ties([row, row]) == []
    assert helper('compare_codexbar').structural_ties([
        row, cache_file(2, None, 4, '/synthetic/two/synthetic-fallback.jsonl')]) == ['synthetic-fallback']


@pytest.mark.parametrize('field,value', [('mtime_ms', None), ('mtime_ms', True),
    ('mtime_ms', '1'), ('session_id', ''), ('session_id', 1), ('path', None)])
def test_malformed_cache_file_is_unknown_oracle_evidence(field, value):
    row = cache_file(1, 'synthetic', 1)
    row[field] = value
    with pytest.raises(ValueError, match='cache file'):
        helper('compare_codexbar').structural_ties([row])


def test_tied_agreeing_native_observations_still_fail_acceptance():
    module = helper('compare_codexbar')
    ties = module.structural_ties([cache_file(1, 'synthetic-tie', 1), cache_file(2, 'synthetic-tie', 1)])
    assessment = module.assess_native_oracle([native_observation(500) for _ in range(3)], ties=ties)
    assert assessment['complete'] is False
    assert assessment['structural_ties'] == ['synthetic-tie']


def test_matching_suffix_does_not_erase_native_disagreement():
    assessment = helper('compare_codexbar').assess_native_oracle([
        native_observation(value) for value in (500, 600, 500, 500, 500)], ties=[])
    assert assessment['complete'] is False
    assert assessment['disagreements']


def test_native_agreement_preserves_ids_nulls_and_uses_cost_tolerance():
    module = helper('compare_codexbar')
    observations = [native_observation() for _ in range(3)]
    observations[-1]['nowUnixMs'] = 999
    observations[-1]['sessions']['synthetic-tie']['costUSD'] += 1e-14
    assert module.assess_native_oracle(observations, ties=[])['complete'] is True
    observations[-1]['sessions']['synthetic-tie']['requestCount'] = 0
    assert module.assess_native_oracle(observations, ties=[])['complete'] is False
    observations[-1]['sessions'] = {}
    assert module.assess_native_oracle(observations, ties=[])['complete'] is False


def test_isolated_cache_record_reader_has_no_window_filter(tmp_path):
    database = tmp_path / 'synthetic.sqlite'
    db = sqlite3.connect(database)
    db.execute('CREATE TABLE files (id INTEGER, path TEXT, session_id TEXT, mtime_ms INTEGER)')
    db.executemany('INSERT INTO files VALUES (?,?,?,?)', [
        (1, '/synthetic/a.jsonl', 'synthetic-outside-window', 1),
        (2, '/synthetic/b.jsonl', 'synthetic-outside-window', 1)])
    db.commit()
    db.close()
    module = helper('compare_codexbar')
    assert module.structural_ties(module.read_isolated_files(database)) == ['synthetic-outside-window']


@pytest.mark.parametrize('rows', [
    [cache_file(1, 'synthetic', 1), cache_file(2, 'synthetic', 1, '/synthetic/1.jsonl')],
    [cache_file(1, 'synthetic', 1), cache_file(1, 'synthetic', 1, '/synthetic/other.jsonl')],
])
def test_cache_conflicting_unique_file_identity_is_unknown(rows):
    with pytest.raises(ValueError, match='cache file'):
        helper('compare_codexbar').structural_ties(rows)


def test_ties_use_source_canonical_string_identity():
    assert helper('compare_codexbar').structural_ties([
        cache_file(1, 'synthetic-e\u0301', 1), cache_file(2, 'synthetic-é', 1)]) == ['synthetic-é']


@pytest.mark.parametrize('damage', ['missing_input', 'boolean_input', 'negative_input',
    'missing_coverage', 'wrong_session_id', 'invalid_cost'])
def test_agreeing_malformed_native_observations_are_not_evidence(damage):
    observation = native_observation()
    session = observation['sessions']['synthetic-tie']
    if damage == 'missing_input':
        session.pop('inputTokens')
    elif damage == 'boolean_input':
        session['inputTokens'] = True
    elif damage == 'negative_input':
        session['inputTokens'] = -1
    elif damage == 'missing_coverage':
        observation.pop('historyScanIsPartial')
    elif damage == 'wrong_session_id':
        session['sessionID'] = 'synthetic-other'
    else:
        session['costUSD'] = float('nan')
    assert helper('compare_codexbar').assess_native_oracle([observation] * 3, ties=[])['complete'] is False


def test_native_partial_scan_does_not_establish_oracle():
    observation = native_observation()
    observation['historyScanIsPartial'] = True
    assert helper('compare_codexbar').assess_native_oracle([observation] * 3, ties=[])['complete'] is False


def test_native_daily_project_crosscheck_is_required_and_keeps_unknowns():
    module = helper('compare_codexbar')
    observation = native_observation()
    day = {'date': '2030-01-07', 'inputTokens': 500, 'cacheReadTokens': 20,
           'outputTokens': 10, 'totalTokens': 510, 'costUSD': None}
    observation['daily'] = [day]
    observation['projects'] = [{'path': '/synthetic/project', 'totalTokens': 510,
                               'totalCostUSD': None, 'daily': [day], 'modelBreakdowns': None, 'sources': []}]
    cli_day = {**day, 'totalCost': None}
    cli_day.pop('costUSD')
    cli = {'daily': [cli_day], 'projects': [{'path': '/synthetic/project',
        'totalTokens': 510, 'totalCost': None, 'daily': [cli_day], 'sources': []}]}
    assert module.crosscheck_native(observation, cli) == []
    cli_day['totalCost'] = 0
    assert module.crosscheck_native(observation, cli)


def test_report_names_all_structural_ties_and_incomplete_oracle():
    report = {'build': {'kind': 'pinned', 'sha256': 'synthetic'}, 'coverage': 'partial',
              'runs': 3, 'historyCoverageIsEstablished': True, 'bucket_tz': 'UTC',
              'differences': [], 'missing_sessions': [], 'unresolved_forks': [],
              'oracle': {'complete': False, 'structural_ties': ['synthetic-tie-outside-window'],
                         'disagreements': [], 'observations': [native_observation()] * 3},
              'failures': ['structural ties make the session oracle incomplete']}
    markdown = helper('compare_codexbar').format_report(report)
    assert 'synthetic-tie-outside-window' in markdown
    assert 'incomplete' in markdown
    assert 'observations: 3' in markdown


def test_scope_comparison_does_not_explain_unproved_gap():
    module = helper('compare_codexbar')
    full = {'synthetic': {'input': 2, 'cached': 0, 'output': 1, 'cost': .01}}
    fallback = {'synthetic': {'input': 1, 'cached': 0, 'output': 1, 'cost': .01}}
    reference = {'synthetic': {'input': 1, 'cached': 0, 'output': 1, 'cost': .01},
                 'synthetic-missing': {'input': 1, 'cached': 0, 'output': 1, 'cost': .01}}
    differences, missing = module.compare_scope('session', full, reference, fallback,
                                               proofs={}, custom_build=False)
    assert any(item['class'] == 'b' and item['key'] == 'synthetic' for item in differences)
    assert missing == [{'id': 'synthetic-missing', 'side': 'CodexBar', 'class': 'b', 'reason': None}]
    differences, _ = module.compare_scope('session', full, reference, fallback,
        proofs={'synthetic': {'tokens': 'confirmed primary record contribution'}}, custom_build=False)
    assert differences[0]['class'] == 'a'
    differences, _ = module.compare_scope('session', full, reference, fallback,
        proofs={'synthetic': {'tokens': 'confirmed primary record contribution'}}, custom_build=True)
    assert differences[0]['class'] == 'd'


def test_fallback_comparison_failure_cannot_be_explained_by_full_path():
    module = helper('compare_codexbar')
    full = {'synthetic': {'input': 1, 'cached': 0, 'output': 1, 'cost': .01}}
    fallback = {'synthetic': {'input': 9, 'cached': 0, 'output': 1, 'cost': .03}}
    differences, _ = module.compare_scope('session', full, full, fallback,
        proofs={'synthetic': {'tokens': 'primary path', 'cost': 'dated history'}}, custom_build=False)
    assert {item['class'] for item in differences} == {'b', 'c'}


def test_duplicate_file_union_is_not_an_approved_parent_lookup_difference():
    module = helper('compare_codexbar')
    union = {'synthetic': {'input': 700, 'cached': 140, 'output': 70, 'cost': .00175}}
    latest = {'synthetic': {'input': 400, 'cached': 80, 'output': 40, 'cost': .001}}
    differences, _ = module.compare_scope('session', union, latest, union, proofs={}, custom_build=False)
    assert {item['class'] for item in differences} == {'b', 'c'}


def test_aggregate_units_keeps_unknown_time_out_of_day_but_in_session():
    module = helper('compare_codexbar')
    units = [SimpleNamespace(session='synthetic', input=10, cached=2, output=1,
                             cost_usd=.01, at_ms=None, source='record')]
    aggregate = module.aggregate_units(units, projects={'synthetic': '/synthetic/project'}, day_key=lambda at: 'synthetic-day')
    assert aggregate['day'] == {}
    assert aggregate['session']['synthetic'] == {'input': 10, 'cached': 2, 'output': 1, 'cost': .01}
    assert aggregate['project']['/synthetic/project']['input'] == 10
    assert aggregate['unknown_time_sessions'] == ['synthetic']


def test_aggregate_units_never_turns_unknown_cost_into_zero():
    units = [SimpleNamespace(session='synthetic', input=10, cached=2, output=1,
                             cost_usd=None, at_ms=1, source='token_count')]
    result = helper('compare_codexbar').aggregate_units(units, projects={}, day_key=lambda at: 'synthetic-day')
    assert result['day']['synthetic-day']['cost'] is None


def test_native_marker_requires_one_valid_json_object():
    parse = helper('compare_codexbar').parse_native_stdout
    value = native_observation()
    text = 'Synthetic XCTest output\nNATIVE_ORACLE_JSON:' + json.dumps(value) + '\n'
    assert parse(text) == value
    for damaged in ('no marker', text + text, 'NATIVE_ORACLE_JSON:[]', 'NATIVE_ORACLE_JSON:{"sessions":{}}'):
        with pytest.raises(ValueError):
            parse(damaged)


def test_inprocess_compile_and_cold_fallback_preserve_source_and_runtime(colophon, tmp_path):
    from fixturegen import CodexHome
    module = helper('compare_codexbar')
    codex, runtime, fake = tmp_path / 'synthetic-source', tmp_path / 'synthetic-runtime', tmp_path / 'synthetic-fake'
    home = CodexHome(codex)
    home.log('synthetic-acceptance', day='2024-01-07').meta().task_started('synthetic-turn').turn_context(
        model='gpt-5.4').token_count(last={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10},
        total={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10}).usage_record(
        usage={'input_tokens': 150, 'cached_input_tokens': 30, 'output_tokens': 15}).task_complete().write()
    colophon.ensure_runtime_home(runtime)
    catalog = synthetic_pricing_catalog()
    colophon.atomic_write_json(runtime / 'pricing-cache.json', {'schema': 1, 'url': 'https://example.invalid/synthetic',
        'catalog': catalog, 'fetched_at_ms': 1704585600000, 'etag': None})
    original = {path: path.read_bytes() for path in codex.rglob('*') if path.is_file()}
    result = module.compile_colophon(colophon, codex, runtime, tmp_path / 'synthetic.html', snapshot_ms=1704585700000)
    assert (tmp_path / 'synthetic.html').is_file()
    assert result['payload']['sessions'][0]['own_usage']['input'] == 150
    fake.mkdir()
    fallback = module.fallback_totals(colophon, result['corpus'], fake, catalog)
    assert fallback['session']['synthetic-acceptance']['input'] == 100
    assert fallback['session']['synthetic-acceptance']['cached'] == 20
    assert {path: path.read_bytes() for path in original} == original


def test_native_provenance_manifest_rejects_wrong_commit_or_hash(tmp_path):
    module = helper('compare_codexbar')
    manifest = {'schema': 1, 'source_commit': 'synthetic-wrong-commit', 'harness_sha256': 'synthetic',
                'bundle_sha256': 'synthetic', 'build_command': ['swift', 'build', '--build-tests']}
    with pytest.raises(ValueError, match='provenance'):
        module.validate_provenance(manifest, harness_hash='synthetic', bundle_hash='synthetic')
    manifest['source_commit'] = module.PINNED_COMMIT
    assert module.validate_provenance(manifest, harness_hash='synthetic', bundle_hash='synthetic') == manifest
    with pytest.raises(ValueError, match='provenance'):
        module.validate_provenance(manifest, harness_hash='changed', bundle_hash='synthetic')


def test_native_fallback_cost_keeps_known_subtotal_and_unknown_volume():
    units = [SimpleNamespace(session='synthetic', input=10, cached=2, output=1,
                             cost_usd=None, at_ms=1, source='token_count'),
             SimpleNamespace(session='synthetic', input=20, cached=4, output=2,
                             cost_usd=.01, at_ms=1, source='token_count')]
    module = helper('compare_codexbar')
    native = module.aggregate_units(units, projects={}, day_key=lambda at: 'synthetic-day', native_costs=True)
    assert native['day']['synthetic-day']['cost'] == .01
    assert native['unpriced_tokens'] == 11
    assert module.aggregate_units(units[:1], projects={}, day_key=lambda at: 'synthetic-day',
                                  native_costs=True)['day']['synthetic-day']['cost'] is None


def test_native_reference_preserves_unknown_and_zero_cached_tokens():
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['sessions']['synthetic-tie']['cachedInputTokens'] = None
    reference = module.reference_totals(observation)
    assert reference['session']['synthetic-tie']['cached'] is None
    observation['sessions']['synthetic-tie']['cachedInputTokens'] = 0
    assert module.reference_totals(observation)['session']['synthetic-tie']['cached'] == 0


def test_complete_native_still_retains_null_without_explicit_zero_evidence():
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['sessions']['synthetic-tie']['cachedInputTokens'] = None
    comparison = module.reference_totals(observation, complete=True)
    assert comparison['session']['synthetic-tie']['cached'] is None
    assert observation['sessions']['synthetic-tie']['cachedInputTokens'] is None
    assert comparison['zero_cached_representation'] == []
    observation['sessions']['synthetic-tie']['inputTokens'] = None
    assert module.reference_totals(observation, complete=True)['session']['synthetic-tie']['cached'] is None
    observation['sessions']['synthetic-tie']['inputTokens'] = 500
    assert module.reference_totals(observation, complete=False)['session']['synthetic-tie']['cached'] is None


@pytest.mark.parametrize('field', ['inputTokens', 'cachedInputTokens', 'outputTokens', 'costUSD'])
def test_required_unknown_native_metric_is_incomplete_not_discrepancy(field):
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['sessions']['synthetic-tie'][field] = None
    oracle = module.assess_native_oracle([observation] * 3, ties=[])
    assert oracle['complete'] is False
    assert f'session synthetic-tie.{field}' in oracle['unknown_metrics']


def test_native_unknown_day_cache_is_incomplete_even_when_cli_agrees():
    module = helper('compare_codexbar')
    observation = native_observation()
    observation['daily'] = [{'date': '2030-01-07', 'inputTokens': 500, 'cacheReadTokens': None,
        'outputTokens': 10, 'totalTokens': 510, 'costUSD': .00125}]
    oracle = module.assess_native_oracle([observation] * 3, ties=[])
    assert oracle['complete'] is False
    assert 'day 2030-01-07.cacheReadTokens' in oracle['unknown_metrics']


def test_private_report_preserves_unknown_and_known_project_identities():
    module = helper('compare_codexbar')
    metrics = {'input': 1, 'cached': 0, 'output': 1, 'cost': .001}
    report = {'reference': {'project': {None: metrics, '/synthetic/project': metrics}}}
    result = json.loads(module.serialize_report(report))
    assert result['reference']['project'] == [
        {'path': None, 'metrics': metrics}, {'path': '/synthetic/project', 'metrics': metrics}]
    assert set(report['reference']['project']) == {None, '/synthetic/project'}


def test_source_inputs_ignore_auth_config_and_sqlite_side_files(tmp_path):
    module = helper('compare_codexbar')
    sessions = tmp_path / 'sessions'
    archive = tmp_path / 'archived_sessions'
    sessions.mkdir()
    archive.mkdir()
    for path in (sessions / 'synthetic-a.jsonl', archive / 'synthetic-b.jsonl',
                 tmp_path / 'auth.json', tmp_path / 'config.toml', tmp_path / 'logs_2.sqlite-wal'):
        path.write_text('synthetic')
    assert module.source_inputs(tmp_path) == sorted([
        sessions / 'synthetic-a.jsonl', archive / 'synthetic-b.jsonl'])


def test_source_inputs_refuse_symlink_jsonl_without_following_it(tmp_path):
    source = tmp_path / 'sessions'
    source.mkdir()
    target = tmp_path / 'synthetic-other.jsonl'
    target.write_text('synthetic')
    (source / 'synthetic-link.jsonl').symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        helper('compare_codexbar').source_inputs(tmp_path)


@pytest.mark.parametrize('filename', ['logs_2.sqlite', 'price-history.json', 'pricing-cache.json', 'priority-turns.json'])
def test_runtime_and_trace_inputs_refuse_nested_symlink_files(tmp_path, filename):
    source = tmp_path / 'synthetic-source'
    source.mkdir()
    target = tmp_path / 'synthetic-other'
    target.write_text('synthetic')
    (source / filename).symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        helper('compare_codexbar').selected_runtime_inputs(source, source)


@pytest.mark.parametrize('damage', [[None], [{'path': None, 'daily': None}], [{'daily': []}]])
def test_malformed_native_projects_fail_closed(damage):
    observation = native_observation()
    observation['projects'] = damage
    assert helper('compare_codexbar').assess_native_oracle([observation] * 3, ties=[])['complete'] is False


def test_pricing_indexes_priority_identity_once_per_pass(colophon):
    class Turns(dict):
        scans = 0
        def items(self):
            self.scans += 1
            assert self.scans == 1, 'whole priority map rescanned per row'
            return super().items()
    turns = Turns({'synthetic-e\u0301': {'model': 'gpt-5.5'}})
    other_turns = Turns({})
    pricing = helper('compare_codexbar').CodexBarPricing(colophon, synthetic_pricing_catalog())
    row = SimpleNamespace(model='gpt-5.4', turn_id='synthetic-é', timestamp_unix_ms=None,
                          input=100, cached=20, output=10)
    for _ in range(4):
        assert pricing.cost(row, turns) == pytest.approx(.000625, rel=0, abs=1e-15)
        assert pricing.cost(row, other_turns) == pytest.approx(.00025, rel=0, abs=1e-15)
    assert turns.scans == 1
    assert other_turns.scans == 1


def test_priority_deviation_requires_positive_sticky_or_new_row_evidence(colophon):
    module = helper('compare_codexbar')
    tier = {'thread_id': 'synthetic-session', 'model': 'gpt-5.4',
            'timestamp': '2030-01-07', 'first_seen_ms': 1}
    assert module.priority_evidence(colophon, {'synthetic-turn': tier}, {}, {}, set()) == {}
    evidence = module.priority_evidence(colophon, {'synthetic-turn': tier}, {},
                                        {'synthetic-turn': tier}, set())
    assert 'sticky' in evidence['synthetic-turn']
    evidence = module.priority_evidence(colophon, {'synthetic-turn': tier}, {}, {}, {'synthetic-turn'})
    assert 'newer' in evidence['synthetic-turn']


def test_dated_cost_proof_checks_actual_reported_period_not_just_presence(colophon):
    module = helper('compare_codexbar')
    period = {'effective_from_ms': None, 'source': 'editable', 'per_million': {
        'input': 1, 'cached_input': .1, 'cache_write': 0, 'output': 2}, 'long_context': None, 'priority': None}
    unit = SimpleNamespace(period=('gpt-synthetic', 0), priority_period=None, priority=None,
                           input=100, cached=20, output=10, cost_usd=.000102)
    models = {'gpt-synthetic': {'periods': [period]}}
    assert module.validated_period_cost(colophon, unit, models) is True
    unit.cost_usd = .001
    assert module.validated_period_cost(colophon, unit, models) is False
    assert module.validated_period_cost(colophon, unit, {}) is False


def test_fork_exception_needs_native_unresolved_and_concrete_two_level_chain():
    module = helper('compare_codexbar')
    parents = {'synthetic-grandchild': 'synthetic-parent', 'synthetic-parent': 'synthetic-root'}
    assert module.fork_chain_evidence(parents, {'synthetic-grandchild'}) == {
        'synthetic-grandchild': ['synthetic-grandchild', 'synthetic-parent', 'synthetic-root']}
    assert module.fork_chain_evidence(parents, set()) == {}
    assert module.fork_chain_evidence({'synthetic-parent': 'synthetic-root'}, {'synthetic-parent'}) == {}
    assert module.fork_chain_evidence({'synthetic-a': 'synthetic-b', 'synthetic-b': 'synthetic-a'},
                                     {'synthetic-a'}) == {}


@pytest.mark.parametrize('damage', [None, 'unproven', 'billed', 'duplicate', 'mixed'])
def test_deliberate_unmetered_day_requires_exact_native_contributor_proof(damage):
    observation = native_observation()
    observation['daily'] = [{'date': '2030-01-07', 'inputTokens': None, 'cacheReadTokens': None,
        'outputTokens': None, 'totalTokens': None, 'costUSD': None, 'unmeteredRequestCount': 1,
        'modelsUsed': None, 'modelBreakdowns': None}]
    observation['fileFacts'] = [{'path': '/synthetic/grandchild.jsonl', 'sessionID': 'synthetic-grandchild',
        'parentID': 'synthetic-parent', 'unresolvedMissingParent': True, 'hasBilledTokens': False,
        'unmeteredDays': {'2030-01-07': 1}}]
    if damage == 'unproven':
        observation['fileFacts'] = []
    elif damage == 'billed':
        observation['fileFacts'][0]['hasBilledTokens'] = True
    elif damage == 'duplicate':
        observation['fileFacts'].append({**observation['fileFacts'][0], 'path': '/synthetic/duplicate.jsonl'})
    elif damage == 'mixed':
        observation['daily'][0]['inputTokens'] = 1
    module = helper('compare_codexbar')
    oracle = module.assess_native_oracle([observation] * 3, ties=[])
    assert oracle['complete'] is (damage is None)
    assert oracle['unmetered_exclusions'] == ({'2030-01-07': ['synthetic-grandchild']} if damage is None else {})


def test_native_marker_rejects_nonfinite_nested_json():
    observation = native_observation()
    observation['sessions']['synthetic-tie']['modelBreakdowns'] = [{'costUSD': float('nan')}]
    with pytest.raises(ValueError, match='nonfinite'):
        helper('compare_codexbar').parse_native_stdout('NATIVE_ORACLE_JSON:' + json.dumps(observation))


def test_source_proven_unmetered_fork_chain_can_explain_missing_scope():
    module = helper('compare_codexbar')
    full = {'synthetic-grandchild': {'input': 1, 'cached': 0, 'output': 1, 'cost': .01}}
    differences, missing = module.compare_scope('session', full, {}, full,
        proofs={'synthetic-grandchild': {'unmetered': 'A4.7 native unresolved no-billed grandchild/parent/root chain',
            'missing': 'A4.7 native unresolved no-billed grandchild/parent/root chain'}}, custom_build=False)
    assert missing[0]['class'] == 'a'
    assert {item['class'] for item in differences} == {'a'}
    differences, _ = module.compare_scope('session', full, {}, full,
        proofs={'synthetic-grandchild': {'unmetered': 'A4.7 native unresolved no-billed grandchild/parent/root chain'}},
        custom_build=True)
    assert {item['class'] for item in differences} == {'d'}


def test_meta_less_session_uses_native_filename_identity_without_selecting_files(colophon, tmp_path):
    from fixturegen import CodexHome
    module = helper('compare_codexbar')
    home = CodexHome(tmp_path / 'synthetic-codex')
    stem = 'synthetic-rollout-00000000-0000-0000-0000-000000000001'
    home.log('synthetic-unused', day='2024-01-07', name=stem + '.jsonl').meta(id=None, session_id=None).task_started(
        'synthetic-turn').turn_context(model='gpt-5.4').token_count(
        last={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10},
        total={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10}).task_complete().write()
    runtime = tmp_path / 'synthetic-runtime'
    colophon.ensure_runtime_home(runtime)
    catalog = synthetic_pricing_catalog()
    colophon.atomic_write_json(runtime / 'pricing-cache.json', {'schema': 1, 'url': 'https://example.invalid/synthetic',
        'catalog': catalog, 'fetched_at_ms': 1704585600000, 'etag': None})
    result = module.compile_colophon(colophon, home.root, runtime, tmp_path / 'synthetic.html', snapshot_ms=1704585700000)
    full = module.full_totals(colophon, result)
    fake = tmp_path / 'synthetic-fake'
    fake.mkdir()
    fallback = module.fallback_totals(colophon, result['corpus'], fake, catalog)
    assert set(full['session']) == set(fallback['session']) == {stem}
    module.confirmed_proofs(colophon, result, full, fallback, catalog)


def test_native_filename_alias_collision_keeps_both_owners_as_unknown(colophon):
    sessions = {}
    for index in (1, 2):
        record = {'key': {'path': f'/synthetic/{index}/synthetic-same.jsonl'},
                  'token_stream': {'observations': [['P', {'session_id': None}]]}}
        sessions[f'file:synthetic-{index}'] = SimpleNamespace(id=f'synthetic-owner-{index}', records=[record],
            meta=None, db_info={}, units=[])
    with pytest.raises(ValueError, match='ambiguous.*synthetic-same') as error:
        helper('compare_codexbar').full_totals(colophon, {'corpus': SimpleNamespace(sessions=sessions)})
    assert 'synthetic-owner-1' in str(error.value) and 'synthetic-owner-2' in str(error.value)


@pytest.mark.parametrize('extra_unexplained', [False, True])
def test_fork_scope_proof_requires_other_contributors_to_match(colophon, extra_unexplained):
    module = helper('compare_codexbar')
    sessions = {}
    for identifier, parent in [('synthetic-root', None), ('synthetic-parent', 'synthetic-root'),
                               ('synthetic-grandchild', 'synthetic-parent'), ('synthetic-other', None)]:
        record = {'key': {'path': f'/synthetic/{identifier}.jsonl'},
            'token_stream': {'observations': [['P', {'session_id': identifier}]]}}
        sessions[identifier] = SimpleNamespace(id=identifier, records=[record], meta={'cwd': '/synthetic/project'},
            db_info={}, forked_from=parent, flags=set())
    units = [SimpleNamespace(session=identifier, owner=sessions[identifier], input=count, cached=1,
        output=1, cost_usd=.01 * count, at_ms=1704585600000) for identifier, count in
        [('synthetic-root', 1), ('synthetic-grandchild', 2)] + ([('synthetic-other', 3)] if extra_unexplained else [])]
    aggregate = module.aggregate_units(units, projects={key: '/synthetic/project' for key in sessions},
        day_key=lambda at: colophon._codex_local_day_key(at / 1000))
    full = {**aggregate, 'units': units}
    known = {'input': 1, 'cached': 1, 'output': 1, 'cost': .01}
    day = colophon._codex_local_day_key(1704585600)
    reference = {'session': {'synthetic-root': known}, 'project': {'/synthetic/project': known}, 'day': {day: known}}
    native = {'fileFacts': [{'path': '/synthetic/synthetic-grandchild.jsonl', 'sessionID': 'synthetic-grandchild',
        'parentID': 'synthetic-parent', 'unresolvedMissingParent': True, 'hasBilledTokens': False, 'unmeteredDays': {day: 1}}], 'daily': []}
    proofs = {'day': {}, 'project': {}, 'session': {}}
    chains = module.attach_fork_evidence(colophon, {'corpus': SimpleNamespace(sessions=sessions)},
        full, full, reference, native, proofs)
    assert chains == {'synthetic-grandchild': ['synthetic-grandchild', 'synthetic-parent', 'synthetic-root']}
    assert 'unmetered' in proofs['session']['synthetic-grandchild']
    assert ('full_tokens' in proofs['day'].get(day, {})) is (not extra_unexplained)
    assert ('fallback-only_cost' in proofs['project'].get('/synthetic/project', {})) is (not extra_unexplained)


@pytest.mark.parametrize('case', ['complete', 'tied', 'native-day-mismatch', 'cache-mutation', 'unknown-missing',
                                  'canonical-complete', 'canonical-incomplete', 'bad-model-null', 'bad-model-count',
                                  'bad-model-money', 'bad-day-request', 'bad-day-model', 'duplicate-native-id',
                                  'duplicate-native-metric', 'duplicate-cli-metric'])
def test_comparison_runtime_wiring_is_isolated_and_ties_fail_closed(colophon, tmp_path, monkeypatch, case):
    from fixturegen import CodexHome
    module = helper('compare_codexbar')
    codex, runtime = tmp_path / 'synthetic-codex', tmp_path / 'synthetic-runtime'
    home = CodexHome(codex)
    identifier = 'synthetic-é' if case.startswith('canonical-') else 'synthetic-tie'
    builder = home.log(identifier, day='2024-01-07')
    if case.startswith('canonical-'):
        metadata = {'type': 'session_meta', 'payload': {'id': identifier, 'cwd': '/synthetic/project'}}
        builder.raw((json.dumps(metadata, ensure_ascii=False) + '\n').encode('utf-8'))
    else:
        builder.meta(cwd='/synthetic/project')
    builder.task_started('synthetic-turn').turn_context(
        model='gpt-5.4').token_count(last={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10},
        total={'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10}).task_complete().write(mtime=1704585600)
    colophon.ensure_runtime_home(runtime)
    colophon.atomic_write_json(runtime / 'pricing-cache.json', {'schema': 1, 'url': 'https://example.invalid/synthetic',
        'catalog': synthetic_pricing_catalog(), 'fetched_at_ms': 1704585600000, 'etag': None})
    cli_path = tmp_path / 'synthetic-cli'
    cli_path.write_text('synthetic')
    (tmp_path / 'PROVENANCE.md').write_text('synthetic-sha')
    monkeypatch.setattr(module, 'prepared_native', lambda *args: {'synthetic': True})
    monkeypatch.setattr(colophon, 'now_ms', lambda: 1704585700000)
    native = native_observation(100)
    native['sessions']['synthetic-tie']['costUSD'] = .00025
    if case.startswith('canonical-'):
        session = native['sessions'].pop('synthetic-tie')
        session['sessionID'] = 'synthetic-e\u0301'
        native['sessions'][session['sessionID']] = session
        if case == 'canonical-incomplete':
            session['cachedInputTokens'] = None
    day = {'date': '2024-01-07', 'inputTokens': 100, 'cacheReadTokens': 20,
           'outputTokens': 10, 'totalTokens': 110, 'costUSD': .00025}
    native['daily'] = [day]
    native['projects'] = [{'path': '/synthetic/project', 'totalTokens': 110, 'totalCostUSD': .00025,
                           'daily': [day], 'modelBreakdowns': None, 'sources': []}]
    cli_day = {**day, 'totalCost': .00025}
    cli_day.pop('costUSD')
    cli = {'historyCoverageIsEstablished': True, 'daily': [cli_day], 'projects': [
        {'path': '/synthetic/project', 'totalTokens': 110, 'totalCost': .00025, 'daily': [cli_day], 'sources': []}]}
    if case == 'native-day-mismatch':
        day['costUSD'] = .02
    if case == 'unknown-missing':
        session = native['sessions'].pop('synthetic-tie')
        session.update(sessionID='synthetic-other', cachedInputTokens=None)
        native['sessions']['synthetic-other'] = session
    if case.startswith('bad-model-'):
        row = {'modelName': 'gpt-synthetic'}
        if case == 'bad-model-count':
            row['inputTokens'] = True
        elif case == 'bad-model-money':
            row['standardCostUSD'] = -1
        native['sessions']['synthetic-tie']['modelBreakdowns'] = [None if case == 'bad-model-null' else row]
    if case == 'bad-day-request':
        native['daily'][0]['requestCount'] = True
    if case == 'bad-day-model':
        native['daily'][0]['modelBreakdowns'] = [{'modelName': 'gpt-synthetic', 'requestCount': True}]
        cli_day['modelBreakdowns'] = [{'modelName': 'gpt-synthetic'}]
    native_text, cli_text = json.dumps(native), json.dumps([cli])
    if case == 'duplicate-native-id':
        item = json.dumps(native['sessions']['synthetic-tie'])
        contradiction = item.replace('"inputTokens": 100', '"inputTokens": 600')
        native_text = native_text.replace('"sessions": {', '"sessions": {"synthetic-tie":' + contradiction + ',', 1)
    if case == 'duplicate-native-metric':
        native_text = native_text.replace('"inputTokens": 100', '"inputTokens":600,"inputTokens": 100', 1)
    if case == 'duplicate-cli-metric':
        cli_text = cli_text.replace('"inputTokens": 100', '"inputTokens":600,"inputTokens": 100', 1)
    events = []
    def seed(fake, catalog):
        assert catalog == synthetic_pricing_catalog()
        pricing = fake / 'Library/Caches/CodexBar/model-pricing'
        pricing.mkdir(parents=True)
        (pricing / 'models-dev-v1.json').write_text(json.dumps(catalog))
        (fake / '.codex').mkdir()
        database = fake / 'Library/Caches/CodexBar/cost-usage/cost-usage.sqlite'
        database.parent.mkdir()
        db = sqlite3.connect(database)
        db.execute('CREATE TABLE files (id INTEGER,path TEXT,session_id TEXT,mtime_ms INTEGER)')
        db.execute('INSERT INTO files VALUES (1,?,?,1)', ('/synthetic/one.jsonl', identifier))
        if case == 'tied':
            db.execute('INSERT INTO files VALUES (2,?,?,1)', ('/synthetic/two.jsonl', 'synthetic-tie'))
        db.execute('CREATE TABLE scan_metadata (payload TEXT)')
        db.execute('INSERT INTO scan_metadata VALUES (?)', (json.dumps({
            'timeZoneIdentifier': 'UTC', 'catchUpPending': False, 'completedFiles': 1, 'totalFiles': 1}),))
        db.commit()
        db.close()
    def guarded_run(executable, profile, fake, source, commands, snapshot, **kwargs):
        assert source == codex
        assert profile.read_text() == 'synthetic denied network/home/cache'
        assert kwargs['stable_runs'] == 3
        events.append((executable, commands))
        if executable == Path('/bin/sh') and case == 'cache-mutation':
            db = sqlite3.connect(fake / 'Library/Caches/CodexBar/cost-usage/cost-usage.sqlite')
            db.execute('UPDATE files SET mtime_ms=2')
            db.commit()
            db.close()
        for _ in range(3):
            snapshot([cli_text] * 3 if executable == cli_path else ['NATIVE_ORACLE_JSON:' + native_text])
    guard = SimpleNamespace(PINNED_CLI_SHA256='synthetic-sha', COST_COMMAND=['cost', '--period', 'all'],
        require_symlink_free=lambda path: None, sha256_file=lambda path: 'synthetic-sha', app_running=lambda: False,
        real_state_fingerprint=lambda: 'synthetic-fingerprint', seed_fake_home=seed,
        profile_text=lambda **kwargs: 'synthetic denied network/home/cache',
        self_test_guard=lambda *args, **kwargs: events.append('self-test'),
        guarded_env=lambda fake, source: {'HOME': str(fake), 'CFFIXED_USER_HOME': str(fake), 'CODEX_HOME': str(source)},
        canonical=lambda value: value, run_until_stable=guarded_run)
    args = SimpleNamespace(output_dir=tmp_path / 'private-report', work_parent=tmp_path,
        real_data_approved=False, codex_home=codex, colophon_home=runtime, native_clone=tmp_path / 'synthetic-clone',
        native_bundle=tmp_path / 'synthetic-bundle', native_provenance=tmp_path / 'synthetic-provenance',
        cli=cli_path, custom_build=False, offline_catalog=True, max_runs=3, native_runs=3)
    report, status = module.run_comparison(args, module=colophon, guard=guard)
    assert report['fingerprint_unchanged'] is True
    accepted = case in ('complete', 'canonical-complete')
    assert report['accepted'] is accepted
    assert status == int(not accepted)
    assert report['oracle']['complete'] is accepted
    assert report['oracle']['structural_ties'] == (['synthetic-tie'] if case == 'tied' else [])
    if case == 'unknown-missing':
        assert {item['id'] for item in report['missing_sessions']} == {'synthetic-tie', 'synthetic-other'}
        assert all('incomplete native oracle' in item['reason'] for item in report['missing_sessions'])
        assert report['differences'] == []
    if case.startswith('canonical-'):
        assert report['missing_sessions'] == []
        assert report['oracle']['observations'][0]['sessions'].keys() == {'synthetic-e\u0301'}
        assert report['colophon']['session'].keys() == {'synthetic-é'}
    if case.startswith(('bad-', 'duplicate-')):
        assert report['failures'] or report['oracle']['disagreements']
        if case != 'duplicate-cli-metric':
            assert (args.output_dir / 'native-attempt-1.stdout').read_text() == 'NATIVE_ORACLE_JSON:' + native_text
        else:
            assert (args.output_dir / 'cli-default.json').read_text() == cli_text
            assert report['runs'] == 1
    assert events[0] == 'self-test'
    assert events[1][1] == [['cost', '--period', 'all'], ['cost', '--period', 'all', '--group-by', 'session'],
                             ['cost', '--period', 'all', '--group-by', 'project']]
    if case != 'duplicate-cli-metric':
        assert events[2][0] == Path('/bin/sh')
    assert (args.output_dir / 'report.json').is_file()


def test_immutable_native_inputs_detect_cache_or_catalog_changes(tmp_path):
    module = helper('compare_codexbar')
    database = tmp_path / 'synthetic.sqlite'
    db = sqlite3.connect(database)
    db.execute('CREATE TABLE synthetic (id INTEGER PRIMARY KEY, value INTEGER)')
    db.execute('INSERT INTO synthetic VALUES (1,1)')
    db.commit()
    catalog = tmp_path / 'synthetic-catalog.json'
    catalog.write_text('{"synthetic":1}')
    before = module.input_fingerprint(database, [catalog])
    assert module.input_fingerprint(database, [catalog]) == before
    db.execute('UPDATE synthetic SET value=2')
    db.commit()
    assert module.input_fingerprint(database, [catalog]) != before
    db.close()
    before = module.input_fingerprint(database, [catalog])
    catalog.write_text('{"synthetic":2}')
    assert module.input_fingerprint(database, [catalog]) != before


@pytest.mark.parametrize(('stable', 'established', 'unmetered', 'expected'), [
    (False, True, 0, 'partial'), (True, False, 0, 'partial'),
    (True, False, 2, 'complete with unresolved forks'), (True, True, 0, 'complete'),
    (True, True, 2, 'complete'), (True, None, 2, 'partial'),
    (True, False, True, 'partial'), (True, False, -1, 'partial'),
])
def test_coverage_requires_known_evidence(stable, established, unmetered, expected):
    module = helper('compare_codexbar')
    assert module.classify_coverage({'historyCoverageIsEstablished': established,
                                    'coverage': {'unmetered': unmetered}}, stable=stable) == expected


def test_difference_classification_requires_confirmed_explanation():
    classify = helper('compare_codexbar').classify_difference
    assert classify(kind='tokens', explained_by=None) == 'b'
    assert classify(kind='cost', explained_by=None) == 'c'
    assert classify(kind='cost', explained_by='primary path') == 'a'
    assert classify(kind='tokens', explained_by='') == 'b'
    assert classify(kind='cost', explained_by='dated history', custom_build=True) == 'd'
    with pytest.raises(ValueError, match='difference kind'):
        classify(kind='unrecognized', explained_by=None)


def test_private_markdown_report_lists_missing_sessions_and_unresolved_forks():
    report = {'build': {'sha256': 'synthetic-sha', 'kind': 'pinned'}, 'runs': 4,
              'coverage': 'complete with unresolved forks', 'bucket_tz': 'UTC',
              'differences': [{'scope': 'day', 'key': '2030-01-07', 'class': 'b',
                               'detail': 'Synthetic input mismatch'}],
              'missing_sessions': [{'id': 'synthetic|session', 'side': 'Colophon',
                                    'class': 'b', 'reason': None}],
              'unresolved_forks': ['synthetic-fork'], 'historyCoverageIsEstablished': False}
    rendered = helper('compare_codexbar').format_report(report)
    for literal in ('synthetic-sha', 'runs: 4', 'UTC', 'complete with unresolved forks',
                    'Missing sessions', 'synthetic\\|session', 'synthetic-fork',
                    'Synthetic input mismatch', 'unexplained token'):
        assert literal in rendered


SWIFT = '''
enum SyntheticPricing {
  private static let codexPriorityInputTokenLimit = 123_000
  private static func gpt56Pricing(
    standard: (input: Double, cached: Double, write: Double, output: Double),
    longContext: (input: Double, cached: Double, write: Double, output: Double)) -> CodexPricing {
    CodexPricing(inputCostPerToken: standard.input, outputCostPerToken: standard.output,
      cacheReadInputCostPerToken: standard.cached, cacheWriteInputCostPerToken: standard.write,
      thresholdTokens: 123_000, inputCostPerTokenAboveThreshold: longContext.input,
      outputCostPerTokenAboveThreshold: longContext.output,
      cacheReadInputCostPerTokenAboveThreshold: longContext.cached,
      cacheWriteInputCostPerTokenAboveThreshold: longContext.write)
  }
  private static let codex: [String: CodexPricing] = [
    // Delimiters inside comments are not structure: ] ) }
    "gpt-synthetic-a": CodexPricing(inputCostPerToken: 1.8e-6,
      outputCostPerToken: 8e-6, cacheReadInputCostPerToken: nil,
      displayLabel: "Synthetic ) ] label"),
    "gpt-synthetic-b": Self.gpt56Pricing(standard: (2e-6, 3e-7, 4e-6, 5e-6),
      longContext: (6e-6, 7e-7, 8e-6, 9e-6)),
  ]
  private static let syntheticCutoff = Date(timeIntervalSince1970: 1_000)
  private static let codexHistoricalPricing: [String: (cutoff: Date, pricing: CodexPricing)] = [
    "gpt-synthetic-b": (Self.syntheticCutoff, Self.gpt56Pricing(
      standard: (1e-6, 2e-7, 3e-6, 4e-6), longContext: (5e-6, 6e-7, 7e-6, 8e-6))),
  ]
  static func codexAPIFastMultiplier(model: String) -> Double? {
    switch self.normalizeCodexModel(model) {
    case "gpt-synthetic-a", "gpt-synthetic-b": 2
    default: nil
    }
  }
  private static func codexAPIFastAllowsLongContext(model: String) -> Bool {
    self.normalizeCodexModel(model) == "gpt-synthetic-b"
  }
}
'''


def test_swift_tables_parse_tuple_order_nil_comments_labels_and_priority():
    tables = helper('check_upstream_tables').parse_pricing_tables(SWIFT)
    assert tables['bundled']['gpt-synthetic-a'] == {
        'inputCostPerToken': 1.8e-6, 'outputCostPerToken': 8e-6,
        'displayLabel': 'Synthetic ) ] label'}
    assert tables['bundled']['gpt-synthetic-b']['cacheWriteInputCostPerToken'] == 4e-6
    assert tables['bundled']['gpt-synthetic-b']['outputCostPerTokenAboveThreshold'] == 9e-6
    assert tables['historical']['gpt-synthetic-b']['cutoff_ms'] == 1_000_000
    assert tables['historical']['gpt-synthetic-b']['pricing']['cacheReadInputCostPerToken'] == 2e-7
    assert tables['priority'] == {
        'gpt-synthetic-a': {'multiplier': 2, 'max_input_tokens': 123000},
        'gpt-synthetic-b': {'multiplier': 2, 'max_input_tokens': None}}


@pytest.mark.parametrize('damaged', [
    SWIFT.replace('1.8e-6', 'someComputation()'),
    SWIFT.replace('standard.input', 'standard.unknown'),
    SWIFT.replace('case "gpt-synthetic-a", "gpt-synthetic-b": 2',
                  'case "gpt-synthetic-a", "gpt-synthetic-b": unknown'),
    SWIFT.replace('"gpt-synthetic-a": CodexPricing', '"gpt-synthetic-b": CodexPricing'),
])
def test_unrecognized_swift_is_not_successful_table_evidence(damaged):
    with pytest.raises(ValueError):
        helper('check_upstream_tables').parse_pricing_tables(damaged)


def test_table_comparison_exact_decimal_history_and_priority():
    module = helper('check_upstream_tables')
    tables = module.parse_pricing_tables(SWIFT)
    history = {'schema': 1, 'entries': [
        {'model': 'gpt-synthetic-a', 'effective_from': None,
         'per_million': {'input': 1.8, 'cached_input': 1.8, 'cache_write': 1.8, 'output': 8},
         'priority': {'multiplier': 2, 'max_input_tokens': 123000}},
        {'model': 'gpt-synthetic-b', 'effective_from': None,
         'per_million': {'input': 1, 'cached_input': .2, 'cache_write': 3, 'output': 4},
         'long_context': {'threshold': 123000, 'input': 5, 'cached_input': .6,
                          'cache_write': 7, 'output': 8},
         'priority': {'multiplier': 2, 'max_input_tokens': None}},
    ]}
    assert module.compare_tables(tables, tables['bundled'], history,
                                 {'gpt-synthetic-b': 1000000}) == []
    history['entries'][1]['per_million']['cached_input'] = .25
    failures = module.compare_tables(tables, tables['bundled'], history,
                                      {'gpt-synthetic-b': 1000000})
    assert any('gpt-synthetic-b' in error and 'historical' in error for error in failures)
    history['entries'][0]['priority']['multiplier'] = 3
    assert any('priority' in error for error in module.compare_tables(
        tables, {}, history, {'gpt-synthetic-b': 0}))


def test_drift_extracts_overloads_nested_functions_and_ignores_comment_delimiters():
    source = '''enum Synthetic {
      func scan(input: Int) -> Int {
        // } is not a brace
        let message = "Synthetic } string"
        func nested() -> Int { 1 }
        return nested()
      }
      func scan(input: String) -> Int { 2 }
    }'''
    module = helper('check_upstream_drift')
    functions = module.extract_declarations(source)
    assert len(functions['scan']) == 2
    assert 'return nested()' in functions['scan'][0]
    assert functions['nested'] == ['func nested() -> Int { 1 }']
    diff = module.compare_declarations(source, source.replace('{ 2 }', '{ 3 }'), ['scan'])
    assert '-func scan(input: String) -> Int { 2 }' in diff
    assert '+func scan(input: String) -> Int { 3 }' in diff
    assert module.compare_declarations(source, source, ['scan', 'nested']) == ''
    with pytest.raises(ValueError, match='missing'):
        module.compare_declarations(source, source, ['absent'])


def test_drift_rule_rows_cover_multiple_table_formats_and_new_files():
    document = '''
| Rule | Upstream file | Function | Commit | Decision | Notes |
| --- | --- | --- | --- | --- | --- |
| Synthetic rate | CostUsagePricing.swift | rate, helper | 3bbf6bc48 | Port | context |
| Addition | Colophon spec | local | — | Addition | context |
| Python function | Upstream file and function | Treatment |
| --- | --- | --- |
| synthetic_parse | `CostUsageScanner.swift`, `scan` | Port |
'''
    module = helper('check_upstream_drift')
    rows = module.rule_rows(document)
    assert [row['rule'] for row in rows] == ['Synthetic rate', 'Addition', 'synthetic_parse']
    assert rows[0]['citation'] == 'CostUsagePricing.swift rate, helper'
    assert module.new_source_files(['Sources/CostUsageOld.swift'], [
        'Sources/CostUsageOld.swift', 'Sources/CodexNew.swift', 'Sources/CostUsageNew.swift',
        'Sources/Unrelated.swift', 'Sources/CodexNew.txt']) == [
            'Sources/CodexNew.swift', 'Sources/CostUsageNew.swift']


@pytest.mark.parametrize('source', [
    'let rates: [String: (cutoff: Int, value: Double)] = ["synthetic": (1, 2e-6)]',
    'let rates: [String: Double] =\n  ["synthetic": 2e-6]',
    'let rates: (String) -> Double = { value in\n  2e-6\n}',
])
def test_drift_typed_initializers_include_changed_values(source):
    module = helper('check_upstream_drift')
    declarations = module.extract_declarations(source)
    assert '2e-6' in declarations['rates'][0]
    assert '3e-6' in module.compare_declarations(source, source.replace('2e-6', '3e-6'), ['rates'])


def test_drift_scanner_does_not_copy_unbounded_suffixes():
    class Source(str):
        def __getitem__(self, key):
            assert not (isinstance(key, slice) and key.stop is None), 'unbounded suffix copy'
            return super().__getitem__(key)

    module = helper('check_upstream_drift')
    source = Source(' ' * 100000 + 'func synthetic() { "Synthetic }" }')
    mask = module._mask(source)
    assert len(mask) == len(source)
    assert 'Synthetic' not in mask


def test_drift_raw_multiline_strings_and_nested_comments_hide_false_declarations():
    source = '''func synthetic() {
      /* outer /* func fake() { } */ } */
      let value = #"""Synthetic } func fake() { } """#
      return value
    }'''
    declarations = helper('check_upstream_drift').extract_declarations(source)
    assert 'fake' not in declarations
    assert 'return value' in declarations['synthetic'][0]


def test_drift_file_name_does_not_cite_same_named_enclosing_type():
    module = helper('check_upstream_drift')
    source = 'enum CostUsageScanner { func cited() { 1 } func uncited() { 2 } }'
    old = module.extract_declarations(source)
    after = source.replace('uncited() { 2 }', 'uncited() { 3 }')
    new = module.extract_declarations(after)
    names = module.cited_declaration_names('CostUsageScanner.swift cited', old, new)
    assert names == ['cited']
    assert module.compare_declarations(source, after, names) == ''
    assert module.compare_declarations(source, source.replace('cited() { 1 }', 'cited() { 4 }'), names)
    assert 'CostUsageScanner' in module.cited_declaration_names(
        'CostUsageScanner.swift CostUsageScanner, cited', old, new)


def synthetic_pricing_catalog():
    return {'openai': {'models': {model: {'id': model,
            'cost': {'input': 2, 'cache_read': .5, 'output': 8}}
            for model in ('gpt-5.4', 'gpt-5.5', 'gpt-5.6-terra')}}}


@pytest.mark.parametrize(('timestamp', 'expected'), [
    (1785369599999, .000355),  # historical Terra:80*2.5+20*.25+10*15 per million
    (1785369600000, .00025),  # cutoff: current synthetic2/.5/8
    (None, .00025),          # no pricing clock: current, never borrow at_ms
])
def test_cold_fallback_pricing_uses_nullable_upstream_timestamp(colophon, timestamp, expected):
    pricing = helper('compare_codexbar').CodexBarPricing(colophon, synthetic_pricing_catalog())
    row = SimpleNamespace(model='gpt-5.6-terra', turn_id='synthetic-turn',
                          timestamp_unix_ms=timestamp, at_ms=0, input=100, cached=20, output=10)
    assert pricing.cost(row, {}) == pytest.approx(expected, rel=0, abs=1e-15)


@pytest.mark.parametrize(('trace_model', 'expected'), [('gpt-5.5', .000625),
                                                      ('synthetic-unsupported', .0005), (None, .0005)])
def test_cold_fallback_priority_override_and_unsupported_model(colophon, trace_model, expected):
    pricing = helper('compare_codexbar').CodexBarPricing(colophon, synthetic_pricing_catalog())
    row = SimpleNamespace(model='gpt-5.4', turn_id='synthetic-turn',
                          timestamp_unix_ms=None, at_ms=0, input=100, cached=20, output=10)
    assert pricing.cost(row, {'synthetic-turn': {'model': trace_model}}) == pytest.approx(expected, rel=0, abs=1e-15)
    assert pricing.cost(row, {}) == pytest.approx(.00025, rel=0, abs=1e-15)


def test_cold_fallback_priority_above_cap_uses_base_cost(colophon):
    pricing = helper('compare_codexbar').CodexBarPricing(colophon, synthetic_pricing_catalog())
    row = SimpleNamespace(model='gpt-5.4', turn_id='synthetic-turn', timestamp_unix_ms=None,
                          at_ms=0, input=272001, cached=0, output=0)
    # No synthetic catalog long block: source fills bundled5-per-million long input.
    assert pricing.cost(row, {'synthetic-turn': {'model': 'gpt-5.4'}}) == pytest.approx(1.360005, rel=0, abs=1e-15)


def test_cold_fallback_unpriced_model_remains_unknown(colophon):
    pricing = helper('compare_codexbar').CodexBarPricing(colophon, {})
    row = SimpleNamespace(model='gpt-synthetic-unknown', turn_id=None, timestamp_unix_ms=None,
                          at_ms=0, input=100, cached=20, output=10)
    assert pricing.cost(row, {}) is None
