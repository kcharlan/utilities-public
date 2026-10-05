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
    day['modelBreakdowns'] = [dict(model)]
    project = {'path': '/synthetic/project', 'totalTokens': 510, 'totalCostUSD': .00125,
               'daily': [day], 'modelBreakdowns': [model]}
    project['sources'] = [json.loads(json.dumps(project))]
    return project


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


def project_axis_observation():
    """Invented canonical parent with independently observed raw cwd sources."""
    def part(path, count, cost):
        model = {'modelName': 'gpt-synthetic', 'totalTokens': count + 10, 'costUSD': cost}
        day = {'date': '2024-01-07', 'inputTokens': count, 'cacheReadTokens': 20,
               'outputTokens': 10, 'totalTokens': count + 10, 'costUSD': cost,
               'modelBreakdowns': [dict(model)]}
        return {'path': path, 'totalTokens': count + 10, 'totalCostUSD': cost,
                'daily': [day], 'modelBreakdowns': [model]}
    observation = native_observation()
    parent = part('/synthetic/repository', 300, .003)
    parent['daily'][0].update(cacheReadTokens=40, outputTokens=20, totalTokens=320)
    parent['daily'][0]['modelBreakdowns'][0]['totalTokens'] = 320
    parent['totalTokens'] = parent['modelBreakdowns'][0]['totalTokens'] = 320
    parent['sources'] = [part('/synthetic/repository/nested', 100, .001),
                         part('/synthetic/worktree', 200, .002)]
    observation['projects'] = [parent]
    return observation


def presentation_abort_observation():
    """Valid split diagnostics precede a fatal later report's core-token sum."""
    observation = project_axis_observation()
    parent = observation['projects'][0]
    for part in [parent, *parent['sources']]:
        for row in [part['modelBreakdowns'][0], part['daily'][0]['modelBreakdowns'][0]]:
            row['priorityTokens'] = 25
            if part is parent:
                row.update(standardCostUSD=.001, standardTokens=110)
    later = json.loads(json.dumps(parent['sources'][0]))
    later['path'] = '/synthetic/later-parent'
    later['sources'] = [json.loads(json.dumps(later))]
    later['sources'][0]['totalTokens'] += 1
    observation['projects'].append(later)
    return observation


def assert_aborted_presentation(collection):
    assert collection['complete'] is False and collection['aborted'] is True
    assert 'reconciliation mismatch' in collection['failure']
    assert collection['records'] == [
        {'parent_path': '/synthetic/repository', 'scope': scope, 'day': day,
         'model': 'gpt-synthetic', 'field': field, 'parent_value': value,
         'observed_source_sum': 50 if field == 'priorityTokens' else None,
         'omitted_sources': [] if field == 'priorityTokens' else
             [{'path': path, 'value': None} for path in
              ['/synthetic/repository/nested', '/synthetic/worktree']]}
        for scope, day in [('day', '2024-01-07'), ('aggregate', None)]
        for field, value in [('standardCostUSD', .001), ('standardTokens', 110), ('priorityTokens', 25)]]


def test_project_source_failure_retains_only_validated_presentation_records():
    module = helper('compare_codexbar')
    observation = presentation_abort_observation()
    original = json.loads(json.dumps(observation))
    with pytest.raises(ValueError, match='reconciliation') as raised:
        module.reference_totals(observation)
    assert_aborted_presentation(raised.value.presentation_collection)
    oracle = module.assess_native_oracle([observation] * 3, ties=[])
    assert oracle['complete'] is False
    assert len(oracle['native_presentation_collections']) == 3
    for index, evidence in enumerate(oracle['native_presentation_collections'], 1):
        assert evidence['observation'] == index
        assert_aborted_presentation(evidence['collection'])
    assert all('reconciliation mismatch' in failure for failure in oracle['disagreements'])
    assert observation == original


@pytest.mark.parametrize('paths', [
    ('/synthetic/repository/nested', '/synthetic/worktree'),
    ('/synthetic/repository/subdirectory-one', '/synthetic/repository/subdirectory-two'),
    ('/synthetic/repository', '/synthetic/linked-worktree'),
], ids=['nested-and-external', 'two-subdirectories', 'main-and-linked-worktree'])
def test_project_source_axis_uses_raw_directories_and_retains_canonical_evidence(paths):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    for source, path in zip(observation['projects'][0]['sources'], paths):
        source['path'] = path
    original = json.loads(json.dumps(observation))
    reference = module.reference_totals(observation)
    assert reference['project'] == {
        paths[0]: {'input': 100, 'cached': 20, 'output': 10, 'cost': .001},
        paths[1]: {'input': 200, 'cached': 20, 'output': 10, 'cost': .002}}
    assert reference['canonical_project']['/synthetic/repository']['input'] == 300
    assert reference['cross_parent_sources'] == []
    assert reference['native_presentation_collection'] == {
        'complete': True, 'aborted': False, 'records': []}
    assert reference['project_source_parents'] == [
        {'path': path, 'parents': ['/synthetic/repository']} for path in sorted(paths)]
    assert observation == original
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True


@pytest.mark.parametrize('scope', ['parent', 'source'])
@pytest.mark.parametrize('daily_models', ['absent', 'null', 'empty'])
def test_project_source_axis_aggregate_requires_daily_model_evidence(scope, daily_models):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    # Remove every daily model map so identical supplied aggregate rows cannot
    # authorize acceptance through equal empty parent/source daily maps.
    for part in [observation['projects'][0], *observation['projects'][0]['sources']]:
        for day in part['daily']:
            if daily_models == 'absent':
                day.pop('modelBreakdowns')
            else:
                day['modelBreakdowns'] = None if daily_models == 'null' else []
    target = observation['projects'][0]
    if scope == 'source':
        target = target['sources'][0]
    original = json.loads(json.dumps(observation))
    assert module.validate_native(observation) == original
    with pytest.raises(ValueError, match='model'):
        module._source_part(target, set())
    with pytest.raises(ValueError, match='model'):
        module.reference_totals(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False
    assert observation == original


@pytest.mark.parametrize('daily_models', ['absent', 'null', 'empty'])
def test_project_source_axis_model_free_reports_need_no_daily_model_evidence(daily_models):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    for part in [observation['projects'][0], *observation['projects'][0]['sources']]:
        part['modelBreakdowns'] = None if daily_models == 'null' else []
        for day in part['daily']:
            if daily_models == 'absent':
                day.pop('modelBreakdowns')
            else:
                day['modelBreakdowns'] = None if daily_models == 'null' else []
    original = json.loads(json.dumps(observation))
    assert module.reference_totals(observation)['project']['/synthetic/worktree']['input'] == 200
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    assert observation == original


def test_project_source_axis_sums_every_cross_parent_contribution_and_lists_paths():
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    other = json.loads(json.dumps(observation['projects'][0]['sources'][0]))
    other['path'] = '/synthetic/another-canonical-parent'
    other['sources'] = [json.loads(json.dumps(observation['projects'][0]['sources'][0]))]
    observation['projects'].append(other)
    reference = module.reference_totals(observation)
    assert reference['project']['/synthetic/repository/nested'] == {
        'input': 200, 'cached': 40, 'output': 20, 'cost': .002}
    assert reference['cross_parent_sources'] == [{'path': '/synthetic/repository/nested',
        'parents': ['/synthetic/another-canonical-parent', '/synthetic/repository']}]
    assert len(reference['canonical_project']) == 2


@pytest.mark.parametrize('damage', ['missing-sources', 'duplicate-source', 'unknown-input',
    'missing-total', 'unknown-cost', 'source-total', 'source-cost', 'source-day-input',
    'offset-source-day', 'offset-source-model', 'aggregate-model', 'daily-model',
    'missing-model', 'missing-source-day', 'extra-source-day'])
def test_project_source_axis_rejects_insufficient_or_unconserved_evidence(damage):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    source, other = parent['sources']
    if damage == 'missing-sources':
        parent['sources'] = []
    elif damage == 'duplicate-source':
        parent['sources'].append(json.loads(json.dumps(source)))
    elif damage == 'unknown-input':
        source['daily'][0]['inputTokens'] = None
    elif damage == 'missing-total':
        source.pop('totalTokens')
    elif damage == 'unknown-cost':
        source['daily'][0]['costUSD'] = None
    elif damage == 'source-total':
        source['totalTokens'] += 1
    elif damage == 'source-cost':
        source['totalCostUSD'] += .01
    elif damage == 'source-day-input':
        source['daily'][0]['inputTokens'] += 1
    elif damage == 'offset-source-day':
        # Combined parent tokens are unchanged, but each source summary is wrong.
        source['daily'][0]['totalTokens'] += 1
        other['daily'][0]['totalTokens'] -= 1
    elif damage == 'offset-source-model':
        source['daily'][0]['modelBreakdowns'][0]['totalTokens'] += 1
        other['daily'][0]['modelBreakdowns'][0]['totalTokens'] -= 1
    elif damage == 'aggregate-model':
        source['modelBreakdowns'][0]['totalTokens'] += 1
    elif damage == 'daily-model':
        source['daily'][0]['modelBreakdowns'][0]['costUSD'] += .01
    elif damage == 'missing-model':
        source['daily'][0]['modelBreakdowns'] = None
    elif damage == 'missing-source-day':
        source['daily'] = []
    else:
        source['daily'].append({**source['daily'][0], 'date': '2024-01-08'})
    with pytest.raises(ValueError):
        module.reference_totals(observation)
    assessment = module.assess_native_oracle([observation] * 3, ties=[])
    assert assessment['complete'] is False
    assert assessment['disagreements'] or assessment['unknown_metrics']


@pytest.mark.parametrize('delta,accepted', [(1e-14, True), (1e-5, False)])
def test_project_source_axis_reconciliation_uses_existing_native_cost_tolerance(delta, accepted):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    observation['projects'][0]['sources'][0]['totalCostUSD'] += delta
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is accepted


def test_project_source_axis_preserves_unknown_identity_and_actual_gaps():
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    observation['projects'][0]['sources'][0]['path'] = None
    reference = module.reference_totals(observation)
    assert reference['project'][None]['input'] == 100
    assert reference['project_source_parents'][0] == {'path': None, 'parents': ['/synthetic/repository']}
    fallback = json.loads(json.dumps(reference['project']['/synthetic/worktree']))
    fallback['input'] += 1
    differences, _ = module.compare_scope('project', {'synthetic': fallback},
        {'synthetic': reference['project']['/synthetic/worktree']}, {'synthetic': fallback},
        proofs={}, custom_build=False)
    assert {item['class'] for item in differences} == {'b'}


def test_project_source_axis_report_labels_axes_and_lists_cross_parent_paths():
    module = helper('compare_codexbar')
    report = {'build': {'kind': 'pinned', 'sha256': 'synthetic'}, 'coverage': 'complete',
              'runs': 3, 'historyCoverageIsEstablished': True, 'bucket_tz': 'UTC',
              'differences': [], 'missing_sessions': [], 'unresolved_forks': [],
              'reference': {'native_presentation_collection': {'complete': True, 'aborted': False, 'records': []},
                  'cross_parent_sources': [{'path': '/synthetic/shared-cwd',
                  'parents': ['/synthetic/parent-one', '/synthetic/parent-two']}]}, 'failures': []}
    rendered = module.format_report(report)
    assert 'project-source' in rendered
    assert 'canonical project' in rendered
    assert '/synthetic/shared-cwd' in rendered
    assert '/synthetic/parent-one' in rendered and '/synthetic/parent-two' in rendered


@pytest.mark.parametrize('assessment', ['missing', 'aborted-shared', 'complete-empty'])
def test_shared_path_report_distinguishes_incomplete_assessment_from_known_absence(assessment):
    module = helper('compare_codexbar')
    report = {'build': {'kind': 'pinned', 'sha256': 'synthetic'}, 'coverage': 'complete',
              'runs': 3, 'historyCoverageIsEstablished': True, 'bucket_tz': 'UTC',
              'differences': [], 'missing_sessions': [], 'unresolved_forks': [], 'failures': []}
    if assessment == 'complete-empty':
        report['reference'] = module.reference_totals(project_axis_observation())
    elif assessment == 'aborted-shared':
        observation = presentation_abort_observation()
        source = observation['projects'][0]['sources'][0]
        other = json.loads(json.dumps(source))
        other['path'] = '/synthetic/another-canonical-parent'
        other['sources'] = [json.loads(json.dumps(source))]
        observation['projects'].append(other)
        with pytest.raises(ValueError) as raised:
            module.reference_totals(observation)
        report['native_presentation_collection'] = raised.value.presentation_collection
    section = module.format_report(report).split(
        '## Raw paths contributing through multiple canonical parents', 1)[1].split(
        '## Native presentation discrepancies', 1)[0]
    if assessment == 'complete-empty':
        assert '- none' in section
        assert 'not established' not in section
    else:
        assert 'not established' in section and 'incomplete' in section
        assert '- none' not in section
        if assessment == 'aborted-shared':
            assert 'aborted' in section and 'reconciliation mismatch' in section


def test_project_source_report_discloses_cli_split_field_limit_without_discrepancies():
    module = helper('compare_codexbar')
    report = {'build': {'kind': 'pinned', 'sha256': 'synthetic'}, 'coverage': 'complete',
              'runs': 3, 'historyCoverageIsEstablished': True, 'bucket_tz': 'UTC',
              'differences': [], 'missing_sessions': [], 'unresolved_forks': [],
              'reference': {'native_presentation': []}, 'failures': []}
    rendered = module.format_report(report)
    explanation = rendered.split('## Native presentation discrepancies', 1)[1].split('| Parent |', 1)[0]
    assert 'CLI JSON omits standardCostUSD, priorityCostUSD, standardTokens and priorityTokens' in explanation
    assert 'conservation within each native report' in explanation
    assert 'agreement across native observations' in explanation
    assert 'CLI core checks remain mandatory' in explanation
    assert 'Cross-boundary optional split discrepancies do not fail acceptance' in explanation


def test_project_source_axis_serialization_retains_nullable_canonical_paths():
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    observation['projects'][0]['path'] = None
    other = json.loads(json.dumps(observation['projects'][0]))
    other['path'] = '/synthetic/other-parent'
    observation['projects'].append(other)
    reference = module.reference_totals(observation)
    encoded = json.loads(module.serialize_report({'reference': reference}))['reference']
    assert [row['path'] for row in encoded['canonical_project']] == [None, '/synthetic/other-parent']
    assert encoded['project_axis'] == 'project-source (original working directory)'
    assert encoded['cross_parent_sources'][0]['parents'] == [None, '/synthetic/other-parent']


@pytest.mark.parametrize('field,value', [('standardCostUSD', .001), ('priorityCostUSD', .001),
                                        ('standardTokens', 25), ('priorityTokens', 25)])
def test_project_source_axis_optional_model_components_skip_inactive_sources(field, value):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    source, inactive = parent['sources']
    for part in (parent, source):
        part['modelBreakdowns'][0][field] = value
        part['daily'][0]['modelBreakdowns'][0][field] = value
    assert field not in inactive['modelBreakdowns'][0]
    original = json.loads(json.dumps(observation))
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    assert module.reference_totals(observation)['project']['/synthetic/worktree']['input'] == 200
    assert observation == original
    for part in (source,):
        part['modelBreakdowns'][0][field] += .01 if field.endswith('USD') else 1
        part['daily'][0]['modelBreakdowns'][0][field] = part['modelBreakdowns'][0][field]
    # Omission evidence is observed metadata, not an acceptance gate.
    reference = module.reference_totals(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    assert reference['native_presentation'] == [
        {'parent_path': parent['path'], 'scope': scope, 'day': day, 'model': 'gpt-synthetic',
         'field': field, 'parent_value': value, 'observed_source_sum': source['modelBreakdowns'][0][field],
         'omitted_sources': [{'path': inactive['path'], 'value': None}]}
        for scope, day in [('day', '2024-01-07'), ('aggregate', None)]]


@pytest.mark.parametrize('field,value', [('standardCostUSD', .001), ('priorityCostUSD', .001),
                                        ('standardTokens', 25), ('priorityTokens', 25)])
def test_project_source_axis_offsetting_daily_components_cannot_hide_in_equal_aggregates(field, value):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    for part in [parent, *parent['sources']]:
        part['daily'].append(json.loads(json.dumps(part['daily'][0])))
        part['daily'][1]['date'] = '2024-01-08'
        part['totalTokens'] *= 2
        part['totalCostUSD'] *= 2
        part['modelBreakdowns'][0]['totalTokens'] *= 2
        part['modelBreakdowns'][0]['costUSD'] *= 2
    source = parent['sources'][0]
    for part in (parent, source):
        part['modelBreakdowns'][0][field] = value * 2
        for day in part['daily']:
            day['modelBreakdowns'][0][field] = value
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    delta = .0001 if field.endswith('USD') else 1
    source['daily'][0]['modelBreakdowns'][0][field] += delta
    source['daily'][1]['modelBreakdowns'][0][field] -= delta
    reference = module.reference_totals(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    discrepancies = reference['native_presentation']
    assert len(discrepancies) == 2
    assert [item['day'] for item in discrepancies] == ['2024-01-07', '2024-01-08']
    assert all(item['scope'] == 'day' and item['field'] == field for item in discrepancies)
    assert [item['observed_source_sum'] for item in discrepancies] == [value + delta, value - delta]
    assert all(item['omitted_sources'] == [{'path': parent['sources'][1]['path'], 'value': None}]
               for item in discrepancies)


@pytest.mark.parametrize('omission', ['absent', 'null'])
def test_project_source_mode_split_preserves_unknowns_and_reports_every_discrepancy(omission):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    standard, priority = parent['sources']
    for part, values in [(parent, {'standardTokens': 110, 'standardCostUSD': .001,
                                  'priorityTokens': 210, 'priorityCostUSD': .002}),
                         (priority, {'priorityTokens': 210, 'priorityCostUSD': .002})]:
        for row in [part['modelBreakdowns'][0], part['daily'][0]['modelBreakdowns'][0]]:
            row.update(values)
    if omission == 'null':
        for row in [standard['modelBreakdowns'][0], standard['daily'][0]['modelBreakdowns'][0]]:
            row.update({field: None for field in module.SOURCE_MODEL_COMPONENTS})
    original = json.loads(json.dumps(observation))
    reference = module.reference_totals(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    diagnostics = reference['native_presentation']
    assert len(diagnostics) == 4
    assert {(item['scope'], item['field']) for item in diagnostics} == {
        (scope, field) for scope in ['day', 'aggregate'] for field in ['standardTokens', 'standardCostUSD']}
    assert all(item['observed_source_sum'] is None for item in diagnostics)
    assert all(item['omitted_sources'] == [{'path': source['path'], 'value': None}
                                         for source in [standard, priority]] for item in diagnostics)
    assert observation == original
    encoded = json.loads(module.serialize_report({'reference': reference}))
    assert encoded['reference']['native_presentation'] == diagnostics
    report = {'build': {'kind': 'pinned', 'sha256': 'synthetic'}, 'coverage': 'complete',
              'runs': 3, 'historyCoverageIsEstablished': True, 'bucket_tz': 'UTC',
              'differences': [], 'missing_sessions': [], 'unresolved_forks': [],
              'reference': reference, 'failures': []}
    rendered = module.format_report(report)
    assert 'Native presentation discrepancies' in rendered
    for item in diagnostics:
        assert item['field'] in rendered and item['parent_path'] in rendered
        assert str(item['parent_value']) in rendered
    assert standard['path'] in rendered and priority['path'] in rendered
    assert 'omitted' in rendered.lower()


@pytest.mark.parametrize('field', ['standardCostUSD', 'priorityCostUSD', 'standardTokens', 'priorityTokens'])
@pytest.mark.parametrize('parent_nil', [False, True])
def test_project_source_all_supplied_mode_split_mismatch_is_presentation_evidence(field, parent_nil):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    value = .001 if field.endswith('USD') else 25
    for part in [parent, *parent['sources']]:
        for row in [part['modelBreakdowns'][0], part['daily'][0]['modelBreakdowns'][0]]:
            row[field] = None if part is parent and parent_nil else value
    original = json.loads(json.dumps(observation))
    # Pinned CostUsageModels.swift BreakdownAccumulator marks a split present
    # after any non-nil file contribution; a directory row cannot prove coverage.
    reference = module.reference_totals(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    assert reference['native_presentation'] == [
        {'parent_path': parent['path'], 'scope': scope, 'day': day,
         'model': 'gpt-synthetic', 'field': field,
         'parent_value': None if parent_nil else value, 'observed_source_sum': value * 2,
         'omitted_sources': []}
        for scope, day in [('day', '2024-01-07'), ('aggregate', None)]]
    encoded = json.loads(module.serialize_report({'reference': reference}))
    assert encoded['reference']['native_presentation'] == reference['native_presentation']
    rendered = module.format_report({'build': {'kind': 'pinned', 'sha256': 'synthetic'},
        'coverage': 'complete', 'runs': 3, 'historyCoverageIsEstablished': True, 'bucket_tz': 'UTC',
        'differences': [], 'missing_sessions': [], 'unresolved_forks': [], 'reference': reference, 'failures': []})
    for item in reference['native_presentation']:
        expected_row = '| ' + ' | '.join(str(item[key]) for key in (
            'parent_path', 'scope', 'day', 'model', 'field', 'parent_value',
            'observed_source_sum', 'omitted_sources')) + ' |'
        assert expected_row in rendered
    assert observation == original


@pytest.mark.parametrize('field', ['standardCostUSD', 'priorityCostUSD'])
@pytest.mark.parametrize('delta,discrepant', [(0, False), (1e-13, False), (1e-9, True)])
def test_project_source_all_supplied_split_cost_reporting_uses_existing_native_tolerance(field, delta, discrepant):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    for part in [parent, *parent['sources']]:
        value = .003 + delta if part is parent else (.001 if part is parent['sources'][0] else .002)
        for row in [part['modelBreakdowns'][0], part['daily'][0]['modelBreakdowns'][0]]:
            row[field] = value
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    records = module.reference_totals(observation)['native_presentation']
    assert len(records) == (2 if discrepant else 0)
    assert all(item['field'] == field and item['omitted_sources'] == [] for item in records)


def test_project_source_split_reporting_retains_supplied_values_but_requires_model_identity():
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    for part in [parent, *parent['sources']]:
        for row in [part['modelBreakdowns'][0], part['daily'][0]['modelBreakdowns'][0]]:
            row['priorityTokens'] = 25
            if part is parent:
                row['standardTokens'] = 110
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    records = module.reference_totals(observation)['native_presentation']
    assert len(records) == 4
    assert {item['field'] for item in records} == {'standardTokens', 'priorityTokens'}
    assert all(item['omitted_sources'] == [] for item in records if item['field'] == 'priorityTokens')
    for part in [parent, *parent['sources']]:
        for row in [part['modelBreakdowns'][0], part['daily'][0]['modelBreakdowns'][0]]:
            row.pop('priorityTokens')
    parent['sources'][0]['modelBreakdowns'][0]['modelName'] = 'gpt-synthetic-missing'
    parent['sources'][0]['daily'][0]['modelBreakdowns'][0]['modelName'] = 'gpt-synthetic-missing'
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False


@pytest.mark.parametrize('field', ['standardCostUSD', 'priorityCostUSD', 'standardTokens', 'priorityTokens'])
def test_project_source_presentation_reporting_never_waives_within_report_component_drift(field):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    source = parent['sources'][0]
    value = .001 if field.endswith('USD') else 25
    for part in [parent, source]:
        part['modelBreakdowns'][0][field] = value
        part['daily'][0]['modelBreakdowns'][0][field] = value
    source['modelBreakdowns'][0][field] += .001 if field.endswith('USD') else 1
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False
    with pytest.raises(ValueError, match='reconciliation'):
        module.reference_totals(observation)


@pytest.mark.parametrize('field', ['standardCostUSD', 'priorityCostUSD'])
@pytest.mark.parametrize('delta,discrepant', [(1e-12, False), (1.0001e-12, True)])
def test_project_source_all_supplied_split_cost_reporting_absolute_tolerance_boundary(field, delta, discrepant):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    for part in [parent, *parent['sources']]:
        for row in [part['modelBreakdowns'][0], part['daily'][0]['modelBreakdowns'][0]]:
            row[field] = delta if part is parent else 0
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    records = module.reference_totals(observation)['native_presentation']
    assert len(records) == (2 if discrepant else 0)
    assert all(item['field'] == field and item['parent_value'] == delta and
               item['observed_source_sum'] == 0 and item['omitted_sources'] == [] for item in records)


@pytest.mark.parametrize('field,value', [('priorityTokens', 2**63 - 1), ('priorityCostUSD', 1e308)])
def test_project_source_axis_optional_component_overflow_fails_closed(field, value):
    module = helper('compare_codexbar')
    observation = project_axis_observation()
    parent = observation['projects'][0]
    for part in [parent, *parent['sources']]:
        part['modelBreakdowns'][0][field] = value
        part['daily'][0]['modelBreakdowns'][0][field] = value
    with pytest.raises(ValueError):
        module.reference_totals(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False


def native_unmetered_fact(count=1):
    return {'path': '/synthetic/fact.jsonl', 'sessionID': 'synthetic-other', 'parentID': 'synthetic-parent',
            'unresolvedMissingParent': True, 'hasBilledTokens': False, 'unmeteredDays': {'2024-01-07': count}}


@pytest.mark.parametrize('value', [-(2**63) - 1, 2**63, True, 1.5, None],
                         ids=['below-int64', 'above-int64', 'bool', 'fractional', 'null'])
def test_native_activity_requires_exact_signed_int64(value):
    observation = native_observation()
    observation['sessions']['synthetic-tie']['lastActivityUnixMs'] = value
    module = helper('compare_codexbar')
    with pytest.raises(ValueError, match='native'):
        module.validate_native(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False


@pytest.mark.parametrize('value', [-(2**63), -1, 0, 2**63 - 1])
def test_native_activity_retains_signed_int64_boundary_values(value):
    observation = native_observation()
    observation['sessions']['synthetic-tie']['lastActivityUnixMs'] = value
    raw = json.loads(json.dumps(observation))
    module = helper('compare_codexbar')
    assert module.validate_native(observation) == raw
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    assert observation['sessions']['synthetic-tie']['lastActivityUnixMs'] == value


@pytest.mark.parametrize('value', [2**63, 10**400, True, 1.5, None, 0, -1],
                         ids=['int-overflow', 'huge-int', 'bool', 'fractional', 'null', 'zero', 'negative'])
def test_native_unmetered_fact_count_requires_positive_bounded_int(value):
    observation = native_observation()
    observation['fileFacts'] = [native_unmetered_fact(value)]
    module = helper('compare_codexbar')
    with pytest.raises(ValueError, match='native'):
        module.native_unmetered_facts(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False


@pytest.mark.parametrize('value', [1, 2**63 - 1])
def test_native_unmetered_fact_retains_positive_int_boundaries(value):
    observation = native_observation()
    fact = native_unmetered_fact(value)
    observation['fileFacts'] = [fact]
    raw = json.loads(json.dumps(observation))
    module = helper('compare_codexbar')
    assert module.native_unmetered_facts(observation) == {'synthetic-other': fact}
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is True
    assert observation == raw


@pytest.mark.parametrize('scope', ['session', 'day', 'project-day', 'source-day', 'project', 'source'])
@pytest.mark.parametrize('variant', ['same-conflicting', 'same-agreeing', 'canonical-conflicting', 'canonical-agreeing'])
def test_native_model_identity_duplicates_fail_in_every_scope(scope, variant):
    observation, target = native_nested_scope(scope)
    names = ('gpt-synthetic-e\u0301', 'gpt-synthetic-é') if variant.startswith('canonical-') else ('gpt-synthetic',) * 2
    target['modelBreakdowns'] = [{'modelName': names[0], 'inputTokens': 100, 'costUSD': None},
                               {'modelName': names[1], 'inputTokens': 100 if variant.endswith('agreeing') else 200,
                                'costUSD': None}]
    raw = json.loads(json.dumps(observation))
    module = helper('compare_codexbar')
    with pytest.raises(ValueError, match='duplicate.*model'):
        module.validate_native(observation)
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False
    assert observation == raw


@pytest.mark.parametrize('scope', ['session', 'day', 'project-day', 'source-day', 'project', 'source'])
def test_native_distinct_model_identities_preserve_order_names_and_optional_values(scope):
    observation, target = native_nested_scope(scope)
    names = ['gpt-synthetic', 'GPT-synthetic', ' gpt-synthetic', 'gpt-synthetic-Ｋ', 'gpt-synthetic-K']
    target['modelBreakdowns'] = [{'modelName': name, 'costUSD': None} for name in names]
    raw = json.loads(json.dumps(observation))
    module = helper('compare_codexbar')
    assert module.validate_native(observation) == raw
    # Schema preservation is separate from sufficient source reconciliation.
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is (scope in ('session', 'day'))
    assert [row['modelName'] for row in target['modelBreakdowns']] == names
    assert all('inputTokens' not in row and row['costUSD'] is None for row in target['modelBreakdowns'])
    assert observation == raw
    known = json.loads(json.dumps(observation))
    rows = [{'modelName': name, 'totalTokens': 510 if index == 0 else 0,
             'costUSD': .00125 if index == 0 else 0} for index, name in enumerate(names)]
    for part in [known['projects'][0], *known['projects'][0]['sources']]:
        part['modelBreakdowns'] = json.loads(json.dumps(rows))
        part['daily'][0]['modelBreakdowns'] = json.loads(json.dumps(rows))
    assert module.assess_native_oracle([known] * 3, ties=[])['complete'] is True


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
        assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is (scope in ('session', 'day'))
        assert observation == raw
        known = json.loads(json.dumps(observation))
        model = {**target['modelBreakdowns'][0], 'totalTokens': 510, 'costUSD': .00125}
        for part in [known['projects'][0], *known['projects'][0]['sources']]:
            part['modelBreakdowns'] = [dict(model)]
            part['daily'][0]['modelBreakdowns'] = [dict(model)]
        assert module.assess_native_oracle([known] * 3, ties=[])['complete'] is True
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
    # Deliberately unknown source still characterizes raw CLI/native omissions;
    # it cannot establish complete project-source reconciliation.
    project['sources'] = [{'name': 'Synthetic source', 'path': None, 'totalTokens': None,
                           'totalCostUSD': None, 'daily': [], 'modelBreakdowns': None}]
    observation['projects'] = [project]
    cli = {'daily': [], 'projects': [{'totalTokens': 510, 'totalCost': .00125,
        'daily': [{**{key: value for key, value in row.items() if key not in ('costUSD', 'modelBreakdowns')},
                   'totalCost': row['costUSD'], 'modelBreakdowns': [
                       {'modelName': model['modelName'], 'totalTokens': model['totalTokens'],
                        'cost': model['costUSD']} for model in row['modelBreakdowns']]}
                  for row in project['daily']],
        'modelBreakdowns': [{'modelName': 'gpt-synthetic', 'totalTokens': 510, 'cost': .00125}],
        'sources': [{'name': 'Synthetic source', 'daily': []}]}]}
    assert module.crosscheck_native(observation, cli) == []
    assert project['sources'][0]['totalCostUSD'] is None
    assert 'totalCost' not in cli['projects'][0]['sources'][0]
    assert project['modelBreakdowns'][0]['incompleteRequestCount'] == 0
    assert module.assess_native_oracle([observation] * 3, ties=[])['complete'] is False


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


def test_source_inputs_include_every_jsonl_case_in_live_and_archived_layouts(tmp_path):
    module = helper('compare_codexbar')
    expected = []
    for root in ('sessions', 'archived_sessions'):
        for layout in ('', '2024/01/07', 'synthetic-legacy/nested'):
            directory = tmp_path / root / layout
            directory.mkdir(parents=True, exist_ok=True)
            for index, extension in enumerate(('.jsonl', '.JSONL', '.JsonL')):
                path = directory / f'synthetic-{index}{extension}'
                path.write_text('{"synthetic":true}\n')
                expected.append(path)
            for name in ('synthetic.json', 'synthetic.JSONL.backup', 'synthetic.txt'):
                (directory / name).write_text('synthetic excluded')
            (directory / 'synthetic-directory.JSONL').mkdir()
    assert module.source_inputs(tmp_path) == sorted(expected)


@pytest.mark.parametrize('root', ['sessions', 'archived_sessions'])
def test_source_fingerprint_detects_uppercase_jsonl_mutation(tmp_path, root):
    module = helper('compare_codexbar')
    path = tmp_path / root / 'synthetic-nested/upper.JSONL'
    path.parent.mkdir(parents=True)
    path.write_text('{"synthetic":1}\n')
    database = tmp_path / 'synthetic-cache.sqlite'
    connection = sqlite3.connect(database)
    connection.execute('CREATE TABLE synthetic (value INTEGER)')
    connection.commit()
    connection.close()
    before = module.input_fingerprint(database, module.source_inputs(tmp_path))
    path.write_text('{"synthetic":2}\n')
    assert module.input_fingerprint(database, module.source_inputs(tmp_path)) != before


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


@pytest.mark.parametrize('extension', ['.jsonl', '.JSONL', '.JsonL'])
def test_source_inputs_refuse_symlink_jsonl_without_following_it(tmp_path, extension):
    source = tmp_path / 'sessions'
    source.mkdir()
    target = tmp_path / 'synthetic-other.jsonl'
    target.write_text('synthetic')
    (source / f'synthetic-link{extension}').symlink_to(target)
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
                                  'duplicate-native-metric', 'duplicate-cli-metric', 'negative-activity',
                                  'bad-activity-below', 'bad-activity-above', 'bad-unmetered-count',
                                  'bad-model-duplicate-conflicting', 'bad-model-duplicate-agreeing',
                                  'bad-model-canonical-conflicting', 'bad-model-canonical-agreeing',
                                  'presentation-abort'])
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
    native['projects'][0]['sources'] = [json.loads(json.dumps({
        key: value for key, value in native['projects'][0].items() if key != 'sources'}))]
    cli_day = {**day, 'totalCost': .00025}
    cli_day.pop('costUSD')
    cli = {'historyCoverageIsEstablished': True, 'daily': [cli_day], 'projects': [
        {'path': '/synthetic/project', 'totalTokens': 110, 'totalCost': .00025, 'daily': [cli_day], 'sources': []}]}
    cli['projects'][0]['sources'] = [json.loads(json.dumps({
        key: value for key, value in cli['projects'][0].items() if key != 'sources'}))]
    if case == 'native-day-mismatch':
        day['costUSD'] = .02
    if case == 'unknown-missing':
        session = native['sessions'].pop('synthetic-tie')
        session.update(sessionID='synthetic-other', cachedInputTokens=None)
        native['sessions']['synthetic-other'] = session
    if case == 'negative-activity' or case.startswith('bad-activity-'):
        native['sessions']['synthetic-tie']['lastActivityUnixMs'] = (
            -(2**63) - 1 if case == 'bad-activity-below' else 2**63 if case == 'bad-activity-above' else -1)
    if case == 'bad-unmetered-count':
        native['fileFacts'] = [native_unmetered_fact(2**63)]
    if case.startswith('bad-model-'):
        row = {'modelName': 'gpt-synthetic'}
        if case == 'bad-model-count':
            row['inputTokens'] = True
        elif case == 'bad-model-money':
            row['standardCostUSD'] = -1
        native['sessions']['synthetic-tie']['modelBreakdowns'] = [None if case == 'bad-model-null' else row]
        if 'duplicate' in case or 'canonical' in case:
            names = ('gpt-synthetic-e\u0301', 'gpt-synthetic-é') if 'canonical' in case else ('gpt-synthetic',) * 2
            native['sessions']['synthetic-tie']['modelBreakdowns'] = [
                {'modelName': names[0], 'inputTokens': 100},
                {'modelName': names[1], 'inputTokens': 100 if case.endswith('agreeing') else 200}]
    if case == 'bad-day-request':
        native['daily'][0]['requestCount'] = True
    if case == 'bad-day-model':
        native['daily'][0]['modelBreakdowns'] = [{'modelName': 'gpt-synthetic', 'requestCount': True}]
        cli_day['modelBreakdowns'] = [{'modelName': 'gpt-synthetic'}]
    if case == 'presentation-abort':
        native['projects'] = presentation_abort_observation()['projects']
        shared_source = native['projects'][0]['sources'][0]
        other_parent = json.loads(json.dumps(shared_source))
        other_parent['path'] = '/synthetic/another-canonical-parent'
        other_parent['sources'] = [json.loads(json.dumps(shared_source))]
        native['projects'].append(other_parent)
        def cli_part(part):
            return {'path': part['path'], 'totalTokens': part['totalTokens'], 'totalCost': part['totalCostUSD'],
                'daily': [{**{key: value for key, value in row.items() if key not in ('costUSD', 'modelBreakdowns')},
                    'totalCost': row['costUSD'], 'modelBreakdowns': [
                        {'modelName': model['modelName'], 'totalTokens': model['totalTokens'], 'cost': model['costUSD']}
                        for model in row['modelBreakdowns']]} for row in part['daily']],
                'modelBreakdowns': [{'modelName': model['modelName'], 'totalTokens': model['totalTokens'],
                                    'cost': model['costUSD']} for model in part['modelBreakdowns']]}
        cli['projects'] = [{**cli_part(parent), 'sources': [cli_part(source) for source in parent['sources']]}
                           for parent in native['projects']]
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
            'timeZoneIdentifier': 'UTC', 'catchUpPending': False, 'completedFiles': 1, 'totalFiles': 1,
            'lastScanUnixMs': 1704585700000}),))
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
    accepted = case in ('complete', 'canonical-complete', 'negative-activity')
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
    if case == 'presentation-abort':
        assert report['accepted'] is False and status == 1
        assert report['oracle']['complete'] is False
        assert report['differences'] == []
        assert 'reference' not in report  # Aborted metrics never become reference evidence.
        assert any('reconciliation mismatch' in failure for failure in report['failures'])
        assert_aborted_presentation(report['native_presentation_collection'])
        encoded = json.loads((args.output_dir / 'report.json').read_text())
        assert_aborted_presentation(encoded['native_presentation_collection'])
        rendered = (args.output_dir / 'report.md').read_text()
        section = rendered.split('## Native presentation discrepancies', 1)[1].split('## Differences', 1)[0]
        assert 'Collection: incomplete (aborted)' in section
        assert 'reconciliation mismatch' in section
        assert 'standardCostUSD' in section and 'standardTokens' in section
        assert '| gpt-synthetic | priorityTokens | 25 | 50 | [] |' in section
        assert '/synthetic/repository/nested' in section and '/synthetic/worktree' in section
        assert len(encoded['native_presentation_collection']['records']) == 6
        assert all(item['parent_path'] == '/synthetic/repository'
                   for item in encoded['native_presentation_collection']['records'])
        assert '| aggregate |' in section
        assert section.split('| --- | --- | --- | --- | --- | --- | --- | --- |\n', 1)[1].startswith(
            '| /synthetic/repository | day | 2024-01-07 | gpt-synthetic | standardCostUSD |')
        assert 'Presentation collections by native observation' in rendered
        assert len(encoded['oracle']['native_presentation_collections']) == 3
        shared_section = rendered.split('## Raw paths contributing through multiple canonical parents', 1)[1].split(
            '## Native presentation discrepancies', 1)[0]
        assert 'not established' in shared_section and 'incomplete' in shared_section
        assert 'aborted' in shared_section and 'reconciliation mismatch' in shared_section
        assert '- none' not in shared_section
    assert events[0] == 'self-test'
    assert events[1][1] == [['cost', '--period', 'all'], ['cost', '--period', 'all', '--group-by', 'session'],
                             ['cost', '--period', 'all', '--group-by', 'project']]
    if case != 'duplicate-cli-metric':
        assert events[2][0] == Path('/bin/sh')
    assert (args.output_dir / 'report.json').is_file()


@pytest.mark.parametrize('field', ['sessionCostUSD', 'last30DaysCostUSD', 'meteredCostUSD'])
def test_cli_top_level_money_uses_existing_tolerance(field):
    equal = helper('compare_codexbar').material_equal
    assert equal({field: 1.0}, {field: 1.0 + 5e-11})
    assert not equal({field: 1.0}, {field: 1.0 + 2e-10})
    assert equal({field: None}, {field: None})
    assert not equal({field: None}, {field: 0})
    for invalid in (True, False, -1, float('nan'), float('inf'), '1'):
        assert not equal({field: invalid}, {field: invalid})
    assert not equal({'sessionTokens': 1}, {'sessionTokens': 1.0})
    assert not equal({'last30DaysTokens': 1}, {'last30DaysTokens': True})


@pytest.mark.parametrize('complete_after', [2, None])
def test_cli_stability_requires_three_complete_observations_without_wall_waits(tmp_path, monkeypatch, complete_after):
    module = helper('compare_codexbar')
    path = Path(__file__).parent / 'tools/codexbar_expected.py'
    spec = importlib.util.spec_from_file_location('synthetic_cli_stability_guard', path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    clock = {'now': 100000, 'calls': 0, 'attempts': 0}
    waits = []

    def wait(seconds):
        assert 0 < seconds <= 60
        waits.append(seconds)
        clock['now'] += round(seconds * 1000)

    def run(*args, **kwargs):
        clock['calls'] += 1
        return SimpleNamespace(returncode=0, stdout='synthetic-observation', stderr='')

    monkeypatch.setattr(guard.subprocess, 'run', run)

    def snapshot(stdouts):
        assert stdouts == ['synthetic-observation'] * 3
        clock['attempts'] += 1
        complete = complete_after is not None and clock['attempts'] > complete_after
        reports = [{'historyCoverageIsEstablished': complete, 'daily': []}] * 3
        metadata = {'catchUpPending': not complete, 'completedFiles': 2 if complete else 1,
                    'totalFiles': 2, 'lastScanUnixMs': clock['now']}
        return module._cli_stability_snapshot(reports, metadata, attempt=clock['attempts'],
                                              now_ms=clock['now'], wait=wait)

    arguments = (tmp_path / 'synthetic-cli', tmp_path / 'synthetic.sb', tmp_path / 'synthetic-home',
                 tmp_path / 'synthetic-codex', [['cost'], ['session'], ['project']], snapshot)
    if complete_after is None:
        with pytest.raises(RuntimeError, match='no stable result after 30 runs'):
            guard.run_until_stable(*arguments, max_runs=30, stable_runs=3)
        assert clock['attempts'] == 30
        assert clock['calls'] == 90
        assert len(waits) == 60
        assert sum(waits) == pytest.approx(1800.03)
    else:
        _, attempts = guard.run_until_stable(*arguments, max_runs=30, stable_runs=3)
        assert attempts == complete_after + 3
        assert clock['calls'] == 15
        assert len(waits) == 4
        assert sum(waits) == pytest.approx(120.002)


def test_cli_stability_rejects_unknown_scan_metadata_and_waits_for_every_group():
    module = helper('compare_codexbar')
    complete = {'catchUpPending': False, 'completedFiles': 2, 'totalFiles': 2, 'lastScanUnixMs': 100000}
    reports = [{'historyCoverageIsEstablished': True, 'daily': []}] * 3
    for changes in ({'catchUpPending': None}, {'completedFiles': True}, {'totalFiles': None},
                    {'completedFiles': 3}, {'lastScanUnixMs': None}, {'lastScanUnixMs': 100001}):
        with pytest.raises(ValueError, match='unknown CLI scan metadata'):
            module._cli_stability_snapshot(reports, {**complete, **changes}, attempt=1,
                                           now_ms=100000, wait=lambda seconds: pytest.fail('unknown must not wait'))
    waits = []
    partial_group = [*reports[:2], {'historyCoverageIsEstablished': False, 'daily': []}]
    first = module._cli_stability_snapshot(partial_group, complete, attempt=1, now_ms=100000, wait=waits.append)
    second = module._cli_stability_snapshot(partial_group, complete, attempt=2, now_ms=100000, wait=waits.append)
    assert first != second
    assert waits == pytest.approx([60, .001, 60, .001])
    assert module._cli_stability_snapshot(reports, complete, attempt=3, now_ms=200000,
                                         wait=lambda seconds: pytest.fail('complete must not wait')) == reports


def test_trace_backup_finalizes_wal_snapshot_for_readonly_scanner(tmp_path, monkeypatch):
    module = helper('compare_codexbar')
    source = tmp_path / 'synthetic-live.sqlite'
    destination = tmp_path / 'synthetic-snapshot.sqlite'
    writer = sqlite3.connect(source)
    try:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE logs (id INTEGER PRIMARY KEY, body TEXT)')
        writer.executemany('INSERT INTO logs VALUES (?, ?)', [(1, 'synthetic-first'), (2, 'synthetic-second')])
        writer.commit()
        assert Path(str(source) + '-wal').stat().st_size > 0
        before = {path.name: path.read_bytes() for path in (source, Path(str(source) + '-wal'))}
        connect = sqlite3.connect
        opened = []

        def record_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            opened.append((args, kwargs, connection))
            return connection

        monkeypatch.setattr(module.sqlite3, 'connect', record_connect)
        assert module._trace_backup(source, destination) == 2
        assert opened[0][0] == (source.resolve().as_uri() + '?mode=ro',)
        assert opened[0][1] == {'uri': True, 'timeout': .25}
        for _, _, connection in opened:
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                connection.execute('SELECT 1')
        snapshot = connect(destination.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            assert snapshot.execute('PRAGMA journal_mode').fetchone() == ('delete',)
            assert snapshot.execute('SELECT * FROM logs ORDER BY id').fetchall() == [
                (1, 'synthetic-first'), (2, 'synthetic-second')]
        finally:
            snapshot.close()
        assert not Path(str(destination) + '-wal').exists()
        assert writer.execute('PRAGMA journal_mode').fetchone() == ('wal',)
        assert writer.execute('SELECT * FROM logs ORDER BY id').fetchall() == [
            (1, 'synthetic-first'), (2, 'synthetic-second')]
        assert {path.name: path.read_bytes() for path in (source, Path(str(source) + '-wal'))} == before
    finally:
        writer.close()


@pytest.mark.parametrize('journal_result', [('wal',), None])
def test_trace_backup_refuses_unfinalized_snapshot(tmp_path, monkeypatch, journal_result):
    module = helper('compare_codexbar')
    source = tmp_path / 'synthetic-source.sqlite'
    destination = tmp_path / 'synthetic-snapshot.sqlite'
    source_db = sqlite3.connect(source)
    source_db.execute('CREATE TABLE logs (id INTEGER PRIMARY KEY)')
    source_db.execute('INSERT INTO logs VALUES (1)')
    source_db.commit()
    source_db.close()
    connect = sqlite3.connect
    opened = []

    class UnfinalizedSnapshot(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == 'PRAGMA journal_mode=DELETE':
                return SimpleNamespace(fetchone=lambda: journal_result)
            return super().execute(sql, *args, **kwargs)

    def record_connect(database, **kwargs):
        if database == destination:
            kwargs['factory'] = UnfinalizedSnapshot
        connection = connect(database, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(module.sqlite3, 'connect', record_connect)
    with pytest.raises(ValueError, match='trace snapshot journal mode'):
        module._trace_backup(source, destination)
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')


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
