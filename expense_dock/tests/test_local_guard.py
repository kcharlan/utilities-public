import asyncio
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import assert_local_server_guard, load_launcher

def load_module(monkeypatch, runtime_home):
    monkeypatch.setenv("EXPENSE_DOCK_HOME", str(runtime_home))
    return load_launcher(Path(__file__).resolve().parents[1] / "expense_dock")


def request(app, method, path, headers):
    async def run():
        messages = []
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                 'query_string': b'', 'headers': headers, 'server': ('127.0.0.1', 8420),
                 'client': ('127.0.0.1', 12345), 'root_path': ''}
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        async def send(message):
            messages.append(message)
        await app(scope, receive, send)
        return messages[0]['status']
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(run())).result()


def test_host_and_origin_guard_real_routes(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    monkeypatch.setattr(module, 'logout', lambda: None)
    app = module.app
    host = (b'host', b'127.0.0.1:8420')
    origin = (b'origin', b'http://127.0.0.1:8420')
    assert request(app, 'GET', '/', [host]) == 200
    assert request(app, 'GET', '/', [(b'host', b'example.test:8420')]) == 403
    assert request(app, 'POST', '/api/auth/logout', [host]) == 403
    assert request(app, 'POST', '/api/auth/logout', [host, (b'origin', b'http://example.test')]) == 403
    assert request(app, 'POST', '/api/auth/logout', [host, origin]) == 200


def test_shared_guard_contract(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(assert_local_server_guard, module.app, get_path='/api/status',
                        post_path='/api/auth/logout', port=8420).result()


def test_gets_do_not_create_runtime_files(monkeypatch, tmp_path):
    home = tmp_path / 'runtime'
    module = load_module(monkeypatch, home)
    host = [(b'host', b'127.0.0.1:8420')]
    assert request(module.app, 'GET', '/api/status', host) == 200
    assert request(module.app, 'GET', '/api/pending', host) == 200
    assert not home.exists()
