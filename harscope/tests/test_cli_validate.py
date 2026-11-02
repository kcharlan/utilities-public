"""CLI validation of exported synthetic captures."""
import json
from pathlib import Path

import pytest

from conftest import ExportEngine, HARManager, SecurityScanner, load_har
from test_redaction_matrix import capture, threaded
from tools.testkit import run_launcher

LAUNCHER = Path(__file__).resolve().parents[1] / 'harscope'
SECRET = 'SyntheticSecret' + '7319'


@pytest.fixture
def exported_files(tmp_path):
    source = {'log': {'version': '1.2', 'creator': {'name': 'synthetic', 'version': '1'}, 'entries': [{
        'request': {'method': 'GET', 'url': 'https://example.test/', 'headers': [], 'cookies': [],
                    'queryString': [], 'postData': {'text': json.dumps({'password': SECRET})}},
        'response': {'status': 200, 'headers': [], 'cookies': [], 'content': {}}, 'time': 1,
    }]}}
    manager = HARManager()
    manager.from_content(json.dumps(source), 'synthetic.har')
    scanner = SecurityScanner()
    scanner.scan(manager)
    har = tmp_path / 'sanitized.har'
    edl = tmp_path / 'synthetic.edl.json'
    sanitized = ExportEngine.sanitized_har(manager, scanner)
    assert json.loads(sanitized['log']['entries'][0]['request']['postData']['text'])['password'] == '[REDACTED]'
    har.write_text(json.dumps(sanitized))
    edl.write_text(ExportEngine.edl_export(manager, scanner))
    return har, edl


def test_validate_accepts_matching_edl(exported_files):
    har, edl = exported_files
    result = run_launcher(LAUNCHER, '--validate', str(har), '--edl', str(edl), '--format', 'json')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['summary']['valid'] is True


def test_validate_rejects_tampered_har(exported_files):
    har, edl = exported_files
    data = json.loads(har.read_text())
    data['log']['entries'][0]['request']['postData']['text'] = json.dumps({'password': SECRET})
    har.write_text(json.dumps(data))
    result = run_launcher(LAUNCHER, '--validate', str(har), '--edl', str(edl), '--format', 'json')
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)['summary']['valid'] is False


def test_validate_requires_edl(exported_files):
    har, _ = exported_files
    result = run_launcher(LAUNCHER, '--validate', str(har))
    assert result.returncode == 1
    assert '--validate requires --edl' in result.stderr + result.stdout


@threaded
async def test_mixed_decisions_validate_and_manual_removal_restores_value(client):
    source = capture('new_password')
    source['log']['entries'][0]['response']['content']['text'] = json.dumps({'label': 'synthetic-label'})
    await load_har(client, source)
    findings = (await client.get('/api/security')).json()['findings']
    target = findings[0]
    assert (await client.post('/api/security/toggle', json={'id': target['id']})).status_code == 200
    location = 'entries[0].response.content.text(parsed).label'
    assert (await client.post('/api/redaction/manual', json={
        'entryIndex': 0, 'location': location, 'value': 'synthetic-label',
    })).status_code == 200
    edl = (await client.post('/api/export/edl')).json()
    assert any(d['action'] == 'keep' for d in edl['decisions'])
    assert any(d['source'] == 'manual' and d['action'] == 'redact' for d in edl['decisions'])
    exported = (await client.post('/api/export/har')).json()
    assert json.loads(exported['log']['entries'][0]['response']['content']['text'])['label'] == '[REDACTED]'
    await load_har(client, exported)
    result = await client.post('/api/validate', files={'file': ('synthetic.edl.json', json.dumps(edl).encode(), 'application/json')})
    assert result.status_code == 200
    assert result.json()['summary']['valid'] is True

    await load_har(client, source)
    assert (await client.post('/api/redaction/manual', json={
        'entryIndex': 0, 'location': location, 'value': 'synthetic-label',
    })).status_code == 200
    assert (await client.post('/api/redaction/remove-manual', json={'entryIndex': 0, 'location': location})).status_code == 200
    exported = (await client.post('/api/export/har')).json()
    assert json.loads(exported['log']['entries'][0]['response']['content']['text'])['label'] == 'synthetic-label'


@threaded
async def test_severity_selection_controls_export_and_sanitized_rescan(client):
    source = capture('new_password')
    warning = 'Ab1' * 16
    source['log']['entries'][0]['response']['content']['text'] = json.dumps({'data': warning})
    await load_har(client, source)
    findings = (await client.get('/api/security')).json()['findings']
    assert {'critical', 'warning'} <= {f['severity'] for f in findings}
    assert (await client.post('/api/security/bulk', json={'action': 'deselect', 'severity': 'warning'})).status_code == 200
    findings = (await client.get('/api/security')).json()['findings']
    assert all(not f['redact'] for f in findings if f['severity'] == 'warning')
    assert all(f['redact'] for f in findings if f['severity'] == 'critical')
    exported = (await client.post('/api/export/har')).json()
    entry = exported['log']['entries'][0]
    assert json.loads(entry['request']['postData']['text'])['new_password'] == '[REDACTED]'
    assert json.loads(entry['response']['content']['text'])['data'] == warning
    assert (await client.post('/api/redaction/reapply-auto')).status_code == 200
    exported = (await client.post('/api/export/har')).json()
    await load_har(client, exported)
    assert (await client.get('/api/security')).json()['findings'] == []


@threaded
async def test_nested_http_and_websocket_values_survive_export_validation(client):
    source = capture('none')
    entry = source['log']['entries'][0]
    entry['request']['postData'] = {'text': json.dumps({'items': [{'password': 'SyntheticRequest7319'}]})}
    entry['response']['content']['text'] = json.dumps({'items': [{'password': 'SyntheticResponse7319'}]})
    entry['_webSocketMessages'] = [{'type': 'receive', 'time': 0, 'opcode': 1,
        'data': json.dumps({'items': [{'password': 'SyntheticWebSocket7319'}]})}]
    await load_har(client, source)
    edl = (await client.post('/api/export/edl')).json()
    exported = (await client.post('/api/export/har')).json()
    entry = exported['log']['entries'][0]
    for text in (entry['request']['postData']['text'], entry['response']['content']['text'],
                 entry['_webSocketMessages'][0]['data']):
        assert json.loads(text)['items'][0]['password'] == '[REDACTED]'
    await load_har(client, exported)
    result = await client.post('/api/validate', files={'file': ('synthetic.edl.json', json.dumps(edl).encode(), 'application/json')})
    assert result.status_code == 200
    assert result.json()['summary']['valid'] is True
