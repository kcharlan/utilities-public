from concurrent.futures import ThreadPoolExecutor

from tools.testkit import assert_local_server_guard


def test_shared_guard_contract(client):
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(assert_local_server_guard, client.app, get_path='/api/status',
                        post_path='/api/undo').result()
