def test_foreign_host_and_origin_rejected(client):
    assert client.get('/api/status', headers={'host': 'foreign.invalid:8000'}).status_code == 403
    assert client.post('/api/undo', headers={'origin': 'http://foreign.invalid'}).status_code == 403


def test_same_origin_mutation_reaches_application(client):
    response = client.post('/api/open-content', json={'content': '{}', 'fileName': 'synthetic.json'})
    assert response.status_code == 200
