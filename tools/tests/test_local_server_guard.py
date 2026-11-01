import asyncio
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('guard', Path(__file__).parents[1] / 'local_server_guard.py')


@pytest.mark.parametrize('kind,method,hosts,origins,server,allowed', [
    ('http', 'GET', ['127.0.0.1:8200'], [], ('127.0.0.1', 8200), True),
    ('http', 'GET', ['localhost:8200'], [], ('127.0.0.1', 8200), True),
    *[('http', 'GET', [host], [], ('127.0.0.1', 8200), False) for host in ('evil.example', 'evil.example:8200', '127.0.0.1:9999', '127.0.0.1:None')],
    ('http', 'GET', [], [], ('127.0.0.1', 8200), False),
    ('http', 'GET', ['localhost:8200'] * 2, [], ('127.0.0.1', 8200), False),
    ('http', 'GET', ['127.0.0.1:None'], [], ('127.0.0.1', None), False),
    ('http', 'GET', ['127.0.0.1:0'], [], ('127.0.0.1', 0), False),
    ('http', 'HEAD', ['localhost:8200'], [], ('127.0.0.1', 8200), True),
    *[('http', method, ['127.0.0.1:8200'], [], ('127.0.0.1', 8200), False) for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')],
    ('http', 'POST', ['127.0.0.1:8200'], ['http://127.0.0.1:8200'], ('127.0.0.1', 8200), True),
    ('http', 'POST', ['localhost:8200'], ['http://localhost:8200'], ('127.0.0.1', 8200), True),
    *[('http', 'POST', ['127.0.0.1:8200'], [origin], ('127.0.0.1', 8200), False) for origin in ('http://localhost:8200', 'http://evil.example', 'null')],
    ('http', 'POST', ['127.0.0.1:8200'], ['http://127.0.0.1:8200'] * 2, ('127.0.0.1', 8200), False),
    ('websocket', None, ['127.0.0.1:8200'], ['http://127.0.0.1:8200'], ('127.0.0.1', 8200), True),
    *[('websocket', None, ['127.0.0.1:8200'], origins, ('127.0.0.1', 8200), False) for origins in ([], ['http://evil.example'], ['http://localhost:8200'])],
    ('lifespan', None, [], [], None, True),
])
def test_guard(kind, method, hosts, origins, server, allowed):
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls, sent = [], []
    async def app(scope, receive, send):
        calls.append(scope)
    async def receive():
        return {'type': 'websocket.connect'}
    async def send(message):
        sent.append(message)
    scope = {'type': kind, 'method': method, 'server': server,
             'headers': [(b'HoSt', h.encode()) for h in hosts] + [(b'OrIgIn', o.encode()) for o in origins]}
    asyncio.run(module.LocalOriginGuard(app)(scope, receive, send))
    assert bool(calls) is allowed
    if not allowed:
        assert sent[0] == ({'type': 'websocket.close', 'code': 1008} if kind == 'websocket' else
                           {'type': 'http.response.start', 'status': 403, 'headers': [(b'content-type', b'text/plain')]})
