def test_guard_rejects_foreign_host_and_origin(test_app):
    client, _ = test_app
    assert client.get('/api/status', headers={'host': 'foreign.invalid:8300'}).status_code == 403
    assert client.post('/api/fleet/scan', headers={'origin': 'http://foreign.invalid'}).status_code == 403
