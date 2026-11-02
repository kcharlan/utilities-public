from concurrent.futures import ThreadPoolExecutor

from tools.testkit import assert_local_server_guard


def test_shared_guard_contract(client):
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(assert_local_server_guard, client.app, get_path='/api/status',
                        post_path='/api/undo').result()


def test_foreign_host_and_origin_rejected(client):
    assert client.get('/api/status', headers={'host': 'foreign.invalid:8000'}).status_code == 403
    assert client.post('/api/undo', headers={'origin': 'http://foreign.invalid'}).status_code == 403


def test_same_origin_mutation_reaches_application(client):
    response = client.post('/api/open-content', json={'content': '{}', 'fileName': 'synthetic.json'})
    assert response.status_code == 200
