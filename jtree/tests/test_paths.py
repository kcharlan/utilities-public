import json
import pytest


def path(parts):
    return {'path': json.dumps(parts)}


def test_special_keys_keep_distinct_identity(client):
    data = {'': 1, 'a.b': 2, '/': 3, 'a': {'b': 4}}
    assert client.post('/api/open-content', json={'content': json.dumps(data), 'fileName': 'synthetic.json'}).status_code == 200
    for index, key in enumerate(('', 'a.b', '/')):
        response = client.put('/api/node', params={'path': json.dumps([key])}, json={'value': index + 10})
        assert response.status_code == 200
    result = json.loads(client.get('/api/download').text)
    assert result == {'': 10, 'a.b': 11, '/': 12, 'a': {'b': 4}}


def test_returned_paths_and_history_preserve_special_keys_and_indices(client):
    original = {'': {'a.b': [10, {'/': 20}]}, 'a': {'b': 99}, '0': 'object key'}
    assert client.post('/api/open-content', json={'content': json.dumps(original), 'fileName': 'synthetic.json'}).status_code == 200
    children = client.get('/api/children', params=path(['', 'a.b'])).json()['children']
    assert [child['path'] for child in children] == [['', 'a.b', 0], ['', 'a.b', 1]]
    assert client.put('/api/node', params=path(['', 'a.b', 1, '/']), json={'value': 21}).status_code == 200
    assert client.post('/api/undo').status_code == 200
    assert client.get('/api/node', params=path(['', 'a.b', 1, '/'])).json()['value'] == 20
    assert client.post('/api/redo').status_code == 200
    assert client.get('/api/node', params=path(['', 'a.b', 1, '/'])).json()['value'] == 21
    assert client.post('/api/rename', params=path(['', 'a.b']), json={'newKey': 'x/y'}).status_code == 200
    assert client.post('/api/undo').status_code == 200
    assert client.post('/api/redo').status_code == 200
    assert client.delete('/api/node', params=path(['', 'x/y', 0])).status_code == 200
    assert client.post('/api/undo').status_code == 200
    assert client.post('/api/redo').status_code == 200
    assert client.get('/api/node', params=path(['', 'x/y'])).json()['childCount'] == 1
    assert client.get('/api/node', params=path(['0'])).json()['value'] == 'object key'


@pytest.mark.parametrize('invalid', ['name', 'null', '{}', '[true]', '[1.5]', '[null]', '["\\ud800"]'])
def test_invalid_path_encoding_rejected(loaded_client, invalid):
    assert loaded_client.get('/api/node', params={'path': invalid}).status_code == 400


def test_path_component_types_are_not_coerced(loaded_client):
    assert loaded_client.get('/api/node', params=path(['tags', '0'])).status_code == 404
    assert loaded_client.get('/api/node', params=path([0])).status_code == 404


def test_search_copy_paste_and_move_use_structured_paths(client):
    source = {'': {'a.b': [{'/': 1}, {'/': 2}]}, 'a': {'b': 'other'}}
    assert client.post('/api/open-content', json={'content': json.dumps(source), 'fileName': 'synthetic.json'}).status_code == 200
    assert client.get('/api/copy', params=path(['', 'a.b', 0, '/'])).json()['key'] == '/'
    results = client.get('/api/search', params={'q': '/', 'type': 'key'}).json()
    assert [result['path'] for result in results] == [['', 'a.b', 0, '/'], ['', 'a.b', 1, '/']]
    assert client.post('/api/move', params=path(['', 'a.b']), json={'fromIndex': 0, 'toIndex': 1}).status_code == 200
    assert client.post('/api/undo').status_code == 200
    assert client.post('/api/redo').status_code == 200
    assert client.post('/api/paste', params=path(['', 'a.b', 0]), json={'key': 'x.y', 'value': 7}).status_code == 200
    assert client.get('/api/node', params=path(['', 'a.b', 0, 'x.y'])).json()['value'] == 7
    assert client.get('/api/node', params=path(['a', 'b'])).json()['value'] == 'other'
