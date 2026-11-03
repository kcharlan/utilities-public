from concurrent.futures import ThreadPoolExecutor

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import assert_local_server_guard, load_launcher, probe_http

def load_module(monkeypatch, runtime_home):
    monkeypatch.setenv("EXPENSE_DOCK_HOME", str(runtime_home))
    return load_launcher(Path(__file__).resolve().parents[1] / "expense_dock")


def test_shared_guard_contract(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(assert_local_server_guard, module.app, get_path='/api/status',
                        post_path='/api/auth/logout', port=8420).result()


def test_gets_do_not_create_runtime_files(monkeypatch, tmp_path):
    home = tmp_path / 'runtime'
    module = load_module(monkeypatch, home)
    host = '127.0.0.1:8420'
    with ThreadPoolExecutor(max_workers=1) as executor:
        for route in ('/api/status', '/api/pending'):
            assert executor.submit(probe_http, module.app, 'GET', route, host=host, port=8420).result() == 200
    assert not home.exists()
