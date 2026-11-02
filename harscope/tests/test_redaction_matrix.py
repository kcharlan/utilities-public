"""Synthetic secrets must not escape through any downloadable format."""
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

import pytest

from conftest import load_har

def threaded(test):
    """Keep async clients off Playwright's already-running event loop."""
    @wraps(test)
    def run(*args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(test(*args, **kwargs))).result()
    return run

SECRET = 'SyntheticSecret' + '7319'
LONG_SECRET = 'SyntheticOpaque' + 'Q7319' * 5


def capture(shape):
    entry = {
        'request': {'method': 'GET', 'url': 'https://example.test/', 'headers': [], 'cookies': [], 'queryString': []},
        'response': {'status': 200, 'headers': [], 'cookies': [], 'content': {}},
        'time': 1,
    }
    log = {'version': '1.2', 'creator': {'name': 'test', 'version': '1'}, 'entries': [entry]}
    request, response = entry['request'], entry['response']
    if shape == 'cookie': request['cookies'] = [{'name': 'connect.sid', 'value': SECRET}]
    elif shape == 'array': request['postData'] = {'text': json.dumps([{'password': SECRET}])}
    elif shape == 'double': request['postData'] = {'text': json.dumps({'nested': json.dumps({'password': SECRET})})}
    elif shape == 'url': request['url'] += '?password=' + SECRET
    elif shape == 'location': response['headers'] = [{'name': 'Location', 'value': 'https://example.test/?password=' + SECRET}]
    elif shape == 'redirect': response['redirectURL'] = 'https://example.test/?password=' + SECRET
    elif shape == 'path': request['headers'] = [{'name': ':path', 'value': '/?password=' + SECRET}]
    elif shape == 'initiator': entry['_initiator'] = {'url': 'https://example.test/?password=' + SECRET}
    elif shape == 'new_password': request['postData'] = {'text': json.dumps({'new_password': SECRET})}
    elif shape == 'page_title': log['pages'] = [{'id': 'page_1', 'title': 'password=' + SECRET}]
    elif shape in ('fragment_location', 'fragment_redirect', 'refresh_location', 'refresh_redirect', 'client_secret_location', 'client_secret_redirect'):
        param = 'access_token' if shape.startswith('fragment') else 'refresh_token' if shape.startswith('refresh') else 'client_secret'
        url = 'https://example.test/cb' + ('#' if shape.startswith('fragment') else '?') + param + '=' + LONG_SECRET
        if shape.endswith('location'): response['headers'] = [{'name': 'Location', 'value': url}]
        else: response['redirectURL'] = url
    return {'log': log}


@pytest.mark.parametrize('shape', ['cookie', 'array', 'double', 'url', 'location', 'redirect', 'path', 'initiator', 'new_password', 'page_title', 'fragment_location', 'fragment_redirect', 'refresh_location', 'refresh_redirect', 'client_secret_location', 'client_secret_redirect'])
@pytest.mark.parametrize('endpoint,payload', [('/api/export/har', None), ('/api/export/edl', None), ('/api/export/csv', None), ('/api/export/csv-findings', None), ('/api/export/report', {'format': 'md'}), ('/api/export/report', {'format': 'html'})])

@threaded
async def test_exports_do_not_contain_secret(client, shape, endpoint, payload):
    source = capture(shape)
    await load_har(client, source)
    response = await client.post(endpoint, json=payload) if payload else await client.post(endpoint)
    assert response.status_code == 200, response.text
    assert SECRET.encode() not in response.content
    assert LONG_SECRET.encode() not in response.content
    if endpoint == '/api/export/har':
        exported = response.json()
        assert len(exported['log']['entries']) == 1
        assert exported['log']['version'] == '1.2'
        assert exported['log']['entries'][0]['response']['status'] == 200


@pytest.mark.parametrize('name', ['password', 'token', 'secret', 'api_key', 'access_token', 'new_password', 'new_token', 'new_secret', 'new_api_key', 'new_access_token'])
@threaded
async def test_existing_sensitive_parameter_names_are_redacted(client, name):
    source = capture('redirect')
    source['log']['entries'][0]['response']['redirectURL'] = 'https://example.test/?' + name + '=' + SECRET
    await load_har(client, source)
    response = await client.post('/api/export/har')
    assert response.status_code == 200
    assert SECRET.encode() not in response.content


def test_failed_index_build_does_not_mark_manager_loaded():
    from conftest import HARManager
    manager = HARManager()
    manager.from_content(json.dumps(capture('cookie')), 'valid.har')
    assert manager.is_loaded
    bad = capture('cookie')
    bad['log']['entries'][0]['response']['status'] = 'invalid'
    with pytest.raises(TypeError):
        manager.from_content(json.dumps(bad), 'test.har')
    assert not manager.is_loaded



@threaded
async def test_open_caps_file_size(client, tmp_path, monkeypatch):
    from conftest import harscope_mod
    path = tmp_path / 'oversize.har'
    path.write_text(json.dumps(capture('cookie')))
    monkeypatch.setattr(harscope_mod, 'MAX_HAR_BYTES', 10)
    response = await client.post('/api/open', json={'path': str(path)})
    assert response.status_code == 413



@threaded
async def test_unicode_filename_export_is_safe(client):
    await load_har(client, capture('cookie'), filename='測試.har')
    response = await client.post('/api/export/edl')
    assert response.status_code == 200



@threaded
async def test_secret_is_swept_from_base64_duplicate(client):
    import base64
    source = capture('new_password')
    source['log']['entries'][0]['response']['content']['text'] = base64.b64encode(('prefix ' + SECRET).encode()).decode()
    await load_har(client, source)
    response = await client.post('/api/export/har')
    assert response.status_code == 200
    encoded = response.json()['log']['entries'][0]['response']['content']['text']
    assert SECRET not in base64.b64decode(encoded).decode()



@threaded
async def test_edl_validation_fails_when_secret_reappears_elsewhere(client):
    source = capture('new_password')
    await load_har(client, source)
    edl = (await client.post('/api/export/edl')).json()
    exported = (await client.post('/api/export/har')).json()
    exported['log']['entries'][0]['response']['content']['text'] = json.dumps({'password': SECRET})
    await load_har(client, exported)
    response = await client.post('/api/validate', files={'file': ('test.edl.json', json.dumps(edl).encode(), 'application/json')})
    assert response.status_code == 200
    assert not response.json()['summary']['valid']



@threaded
async def test_double_encoded_root_json_is_redacted(client):
    source = capture('array')
    source['log']['entries'][0]['request']['postData']['text'] = json.dumps(json.dumps({'password': SECRET}))
    await load_har(client, source)
    response = await client.post('/api/export/har')
    assert response.status_code == 200
    assert SECRET not in response.text



@threaded
async def test_manual_missing_location_refuses_export(client):
    await load_har(client, capture('array'))
    await client.post('/api/redaction/manual', json={'entryIndex': 0, 'location': 'entries[0].missing', 'value': 'synthetic-missing'})
    response = await client.post('/api/export/har')
    assert response.status_code >= 400



@threaded
async def test_page_only_capture_exports(client):
    source = capture('page_title')
    source['log']['entries'] = []
    await load_har(client, source)
    for endpoint in ('/api/export/har', '/api/export/edl', '/api/export/csv-findings'):
        response = await client.post(endpoint)
        assert response.status_code == 200
        assert SECRET not in response.text



@threaded
async def test_manual_redaction_preserves_har_keys(client):
    source = capture('array')
    source['log']['entries'][0]['request']['postData']['text'] = json.dumps({'status': 'ok'})
    await load_har(client, source)
    await client.post('/api/redaction/manual', json={'entryIndex': 0, 'location': 'entries[0].request.postData.text(parsed).status', 'value': 'ok'})
    for endpoint, payload in [('/api/export/har', None), ('/api/export/edl', None), ('/api/export/csv', None), ('/api/export/csv-findings', None), ('/api/export/report', {'format': 'md'}), ('/api/export/report', {'format': 'html'})]:
        response = await client.post(endpoint, json=payload) if payload else await client.post(endpoint)
        assert response.status_code == 422
        assert 'object key' in response.text
    from conftest import harscope_mod
    assert harscope_mod.har_manager.raw_data == source



@threaded
async def test_manual_selection_sweeps_duplicate_values(client):
    source = capture('array')
    secret = 'manual-' + SECRET
    source['log']['entries'][0]['request']['postData']['text'] = json.dumps({'user': secret})
    source['log']['entries'][0]['response']['content']['text'] = json.dumps({'copy': secret})
    await load_har(client, source)
    await client.post('/api/redaction/manual', json={'entryIndex': 0, 'location': 'entries[0].request.postData.text(parsed).user', 'value': secret})
    response = await client.post('/api/export/har')
    assert response.status_code == 200
    assert secret not in response.text
    assert 'cookies' in response.json()['log']['entries'][0]['request']



@threaded
async def test_automatic_secret_in_key_refuses_export(client):
    source = capture('new_password')
    source['log']['entries'][0]['response']['content'][SECRET] = 'ordinary value'
    await load_har(client, source)
    response = await client.post('/api/export/har')
    assert response.status_code == 422



@threaded
async def test_manual_secret_in_nested_json_key_refuses_export(client):
    source = capture('array')
    secret = 'manual-' + SECRET
    source['log']['entries'][0]['request']['postData']['text'] = json.dumps({'user': secret})
    source['log']['entries'][0]['response']['content']['text'] = json.dumps({secret: 'ordinary'})
    await load_har(client, source)
    await client.post('/api/redaction/manual', json={'entryIndex': 0, 'location': 'entries[0].request.postData.text(parsed).user', 'value': secret})
    response = await client.post('/api/export/har')
    assert response.status_code == 422
    assert 'object key' in response.text



@threaded
async def test_url_encoded_duplicate_is_removed(client):
    source = capture('new_password')
    source['log']['entries'][0]['response']['content']['text'] = 'copy=%53' + SECRET[1:]
    await load_har(client, source)
    response = await client.post('/api/export/har')
    assert response.status_code == 200
    from urllib.parse import unquote
    assert SECRET not in unquote(response.text)



@threaded
async def test_manual_secret_in_base64_json_key_refuses_export(client):
    import base64
    source = capture('array')
    secret = 'manual-' + SECRET
    source['log']['entries'][0]['request']['postData']['text'] = json.dumps({'user': secret})
    source['log']['entries'][0]['response']['content']['text'] = base64.b64encode(json.dumps({secret: 'ordinary'}).encode()).decode()
    await load_har(client, source)
    await client.post('/api/security/bulk', json={'action': 'deselect'})
    await client.post('/api/redaction/manual', json={'entryIndex': 0, 'location': 'entries[0].request.postData.text(parsed).user', 'value': secret})
    response = await client.post('/api/export/har')
    assert response.status_code == 422
    assert 'object key' in response.text


@threaded
async def test_short_base64_copy_is_redacted(client):
    import base64
    secret = 'Zx' + '7319'
    source = capture('new_password')
    source['log']['entries'][0]['request']['postData']['text'] = json.dumps({'new_password': secret})
    source['log']['entries'][0]['response']['content']['text'] = base64.b64encode(secret.encode()).decode()
    await load_har(client, source)
    response = await client.post('/api/export/har')
    assert response.status_code == 200
    encoded = response.json()['log']['entries'][0]['response']['content']['text']
    assert secret not in base64.b64decode(encoded).decode()


@pytest.mark.parametrize('kind,secret', [('csv', 'Synthetic"Secret7319'), ('csv-findings', 'Synthetic"Secret7319'), ('html', 'Synthetic&Secret7319')])
@threaded
async def test_formatted_export_hides_escaped_selected_value(client, kind, secret):
    import csv
    import html
    import io
    source = capture('new_password')
    source['log']['entries'][0]['request']['postData']['text'] = json.dumps({'new_password': secret})
    source['log']['entries'][0]['request']['url'] = 'https://example.test/' + secret
    await load_har(client, source)
    if kind.startswith('csv'):
        response = await client.post('/api/export/' + kind)
        assert response.status_code == 200
        assert all(secret not in cell for row in csv.reader(io.StringIO(response.text)) for cell in row)
    else:
        response = await client.post('/api/export/report', json={'format': 'html'})
        assert response.status_code == 200
        assert secret not in html.unescape(response.text)
