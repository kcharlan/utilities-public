"""Token thresholds and WebSocket redactions survive export and validation."""
import json

import pytest

from conftest import load_har
from test_redaction_matrix import capture, threaded


@pytest.mark.parametrize('value,flagged', [
    ('Ab1' * 16, True),
    (('Ab1' * 16)[:47], False),
    ('abcdefghij' * 8, True),
    (('abcdefghij' * 8)[:79], False),
])
@threaded
async def test_tier_boundaries_on_neutral_key(client, value, flagged):
    source = capture('none')
    source['log']['entries'][0]['request']['postData'] = {'text': json.dumps({'data': value})}
    await load_har(client, source)
    response = await client.get('/api/security')
    assert response.status_code == 200
    findings = response.json()['findings']
    assert len(findings) == int(flagged), findings
    if flagged:
        assert findings[0]['category'] == 'Opaque Token'
        assert findings[0]['severity'] == 'warning'
    response = await client.post('/api/export/har')
    assert response.status_code == 200, response.text
    body = json.loads(response.json()['log']['entries'][0]['request']['postData']['text'])
    assert body['data'] == ('[REDACTED]' if flagged else value)


@threaded
async def test_hinted_key_promotes_short_token(client):
    value = ('Ab1' * 16)[:47]
    source = capture('none')
    source['log']['entries'][0]['request']['postData'] = {'text': json.dumps({'csrf': value})}
    await load_har(client, source)
    response = await client.get('/api/security')
    assert response.status_code == 200
    findings = response.json()['findings']
    assert len(findings) == 1, findings
    assert findings[0]['severity'] == 'critical'
    assert findings[0]['category'] == 'Token'


@threaded
async def test_websocket_message_secrets_are_removed(client):
    session = 'synthetic-ws-session-7319'
    persona = 'synthetic-persona'
    bearer = 'SyntheticWsBearer0123456789'
    source = capture('none')
    source['log']['entries'][0]['_webSocketMessages'] = [
        {'type': 'receive', 'time': 0, 'opcode': 1,
         'data': json.dumps({'sessionId': session, 'persona': persona})},
        {'type': 'receive', 'time': 1, 'opcode': 1, 'data': 'Bearer ' + bearer},
    ]
    await load_har(client, source)
    response = await client.post('/api/export/har')
    assert response.status_code == 200, response.text
    assert session not in response.text
    assert bearer not in response.text

    response = await client.post('/api/redaction/manual', json={
        'entryIndex': 0,
        'location': 'entries[0]._webSocketMessages[0].data(parsed).persona',
        'value': persona,
    })
    assert response.status_code == 200, response.text
    edl_response = await client.post('/api/export/edl')
    assert edl_response.status_code == 200, edl_response.text
    edl = edl_response.json()
    response = await client.post('/api/export/har')
    assert response.status_code == 200, response.text
    exported = response.json()
    body = json.loads(exported['log']['entries'][0]['_webSocketMessages'][0]['data'])
    assert body['persona'] == '[REDACTED]'
    assert persona not in response.text
    await load_har(client, exported)
    response = await client.post('/api/validate', files={
        'file': ('synthetic.edl.json', json.dumps(edl).encode(), 'application/json'),
    })
    assert response.status_code == 200, response.text
    assert response.json()['summary']['valid'], response.json()
