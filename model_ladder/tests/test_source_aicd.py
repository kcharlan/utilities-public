"""Invented leaderboard rows and the provider's table shape."""
import pytest
from datetime import datetime, timezone
from test_fetch import Opener
from test_source_fc import HtmlResponse

HEADERS = ['#', 'Model', 'Total<br>points (max 900)', 'Avg cost<br>per prompt', 'Avg time<br>per prompt', 'Video', 'Tested with', 'Points per project', 'Penalty Points deducted for INCONSISTENT results across attempts.', 'Laravel Code Quality (max 100)', 'React-TS Code Quality (max 110)', 'Bug Finding Test (max 120)', 'Python Code Quality (max 130)', 'Edge-case Testing (4 projects,<br>max 140)']

def row(rank, name, cost='$1.25', time='1:05', harness='Harness One'):
    return f'<tr><td>{rank}</td><td><a href="/invented">{name}</a></td><td>42.5</td><td>{cost}</td><td>{time}</td><td>video</td><td>{harness} <time datetime="2024-03-02">March 2</time></td><td>11</td><td>12</td><td>13</td><td>14</td><td>15</td><td>−2.5</td></tr>'

def table(rows):
    return ('<p>Last update: <b>March 3rd, 2024</b> (invented)</p><table><thead><tr>'
            + ''.join(f'<th rowspan="2">{h}</th>' for h in HEADERS[:7])
            + '<th colspan="5">' + HEADERS[7] + '</th><th rowspan="2">' + HEADERS[8] + '</th></tr><tr>'
            + ''.join(f'<th>{h}</th>' for h in HEADERS[9:]) + '</tr></thead><tbody>' + rows + '</tbody></table>')

AICD_FIXTURE = table(row(1, 'Example (Tag) (High)') + '<tr><td colspan="13">Advertisement</td></tr>' + row(2, 'Example (Tag) (Low)', 'N/A', '0:30').replace('<td>11</td>', '<td>10</td>') + row(3, 'Example (Tag) (High)', harness='Harness Two') + row(4, 'Other'))
EXPECTED_SCORES = dict(total=42.5, laravel=11, react_ts=12, bug_finding=13, python=14, edge_cases=15)
EXPECTED_MAXIMA = dict(total=900, laravel=100, react_ts=110, bug_finding=120, python=130, edge_cases=140)

def test_aicd_parses_rows(ml):
    result = ml.parse_ai_coding_daily(AICD_FIXTURE)
    rows = ml.classify_ai_coding_daily(result['models'])
    assert len(rows) == 4
    assert rows[0]['scores'] == EXPECTED_SCORES
    assert rows[0]['axes'] == {'cost': 1.25, 'time': 65}
    assert rows[0]['extras'] == {'penalty': -2.5, 'tested': '2024-03-02'}
    assert rows[1]['axes'] == {'cost': None, 'time': 30}
    assert result['index_maxima'] == EXPECTED_MAXIMA

def test_aicd_published(ml):
    assert ml.parse_ai_coding_daily(AICD_FIXTURE)['published'] == {'date': '2024-03-03', 'note': 'invented'}

def test_aicd_two_harnesses_are_two_families(ml):
    rows = ml.classify_ai_coding_daily(ml.parse_ai_coding_daily(AICD_FIXTURE)['models'])
    assert rows[0]['family_key'] != rows[2]['family_key']
    assert rows[0]['slug'] != rows[2]['slug']

def test_aicd_two_groups_keep_effort(ml):
    rows = ml.classify_ai_coding_daily(ml.parse_ai_coding_daily(AICD_FIXTURE)['models'])
    assert (rows[0]['family'], rows[0]['rung'], rows[0]['maker']) == ('Example (Tag)', 'high', 'Harness One')

@pytest.mark.parametrize('where', ['header', 'identity'])
def test_aicd_hidden_text_is_excluded(ml, where):
    if where == 'header':
        html = AICD_FIXTURE.replace('Model</th>', 'Model<script>ignored()</script><style>ignored</style></th>')
    else:
        html = AICD_FIXTURE.replace('Example (Tag) (High)</a>', 'Example (Tag) (High)<script>ignored()</script><style>ignored</style></a>', 1)
        html = html.replace('Harness One <time', 'Harness One<script>ignored()</script><style>ignored</style> <time', 1)
    row = ml.classify_ai_coding_daily(ml.parse_ai_coding_daily(html)['models'])[0]
    assert (row['name'], row['maker'], row['family'], row['rung']) == ('Example (Tag) (High)', 'Harness One', 'Example (Tag)', 'high')
    assert row['slug'] == '/invented|high|Harness One'

@pytest.mark.parametrize('changed', [AICD_FIXTURE.replace('Model</th>', 'Changed</th>'), AICD_FIXTURE.replace('</thead>', '<th>extra</th></thead>'), AICD_FIXTURE.replace('<th rowspan="2">Video</th>', ''), AICD_FIXTURE.replace('max 900', 'max 0')])
def test_aicd_rejects_changed_header(ml, changed):
    with pytest.raises(ml.FetchError, match='changed its leaderboard columns'):
        ml.parse_ai_coding_daily(changed)

@pytest.mark.parametrize('old,new', [('$1.25', '1.25'), ('1:05', 'slow'), ('42.5', 'bad'), ('<td>video</td>', '')])
def test_aicd_rejects_bad_cell(ml, old, new):
    with pytest.raises(ml.FetchError, match='AI Coding Daily row'):
        ml.parse_ai_coding_daily(AICD_FIXTURE.replace(old, new, 1))

@pytest.mark.parametrize('value,expected', [('1:05',65), ('01:05',65), ('1:02:03',3723), ('0:00',None), ('00:00:00',None)])
def test_aicd_time_formats(ml, value, expected):
    result = ml.parse_ai_coding_daily(table(row(1, 'Example', time=value)))
    assert ml.classify_ai_coding_daily(result['models'])[0]['axes']['time'] == expected

@pytest.mark.parametrize('value', ['1:60','1:60:00','1:00:60'])
def test_aicd_invalid_times(ml, value):
    with pytest.raises(ml.FetchError, match='Time'):
        ml.parse_ai_coding_daily(table(row(1, 'Example', time=value)))

def test_aicd_no_rows_is_an_error(ml):
    with pytest.raises(ml.FetchError, match='leaderboard has no rows'):
        ml.parse_ai_coding_daily(table(''))

def test_aicd_notice_counts_missing_costs(ml):
    rows = ml.classify_ai_coding_daily(ml.parse_ai_coding_daily(AICD_FIXTURE)['models'])
    assert '1 configurations have no cost per prompt' in ml.SOURCE_SPECS['aicd']['notice'](rows)

def test_aicd_maxima_survive_offline_build(ml, tmp_path):
    opener = Opener([HtmlResponse(AICD_FIXTURE)])
    result = ml.fetch_ai_coding_daily(opener)
    assert len(opener.requests) == 1 and opener.requests[0].get_header('User-agent') == ml.USER_AGENT
    path = ml.save_snapshot(tmp_path, result, datetime.now(timezone.utc), source='aicd')
    saved = ml.read_snapshot(path, 'aicd')
    payload = ml.build_payload({'aicd': (saved, None)}, ml.DEFAULT_CONFIG)
    assert {index['key']: index['max'] for index in payload['sources']['aicd']['indexes']} == result['index_maxima']
    output = tmp_path / 'offline.html'
    ml.build_page(tmp_path, output)
    assert '"max":140' in output.read_text()
