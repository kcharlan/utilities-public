from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import asyncio

from httpx import ASGITransport, AsyncClient

from conftest import app, harscope_mod, load_har
from tools.testkit import assert_local_server_guard


def test_local_guard_rejects_foreign_requests():
    with ThreadPoolExecutor() as executor:
        executor.submit(assert_local_server_guard, app, post_path='/api/redaction/reset').result()


def test_get_routes_do_not_change_application_state():
    async def probe():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1:8000',
                               headers={'Origin': 'http://127.0.0.1:8000'}) as client:
            await load_har(client)
            objects = (harscope_mod.har_manager, harscope_mod.security_scanner, harscope_mod.sequence_builder)
            before = deepcopy([obj.__dict__ for obj in objects])
            for path in ('/', '/api/status', '/api/entries', '/api/entry/0', '/api/waterfall',
                         '/api/domains', '/api/stats', '/api/security', '/api/redaction/decisions',
                         '/api/sequence', '/api/sequence/flows'):
                response = await client.get(path)
                assert response.status_code == 200, path
            assert [obj.__dict__ for obj in objects] == before

    with ThreadPoolExecutor() as executor:
        executor.submit(asyncio.run, probe()).result()
