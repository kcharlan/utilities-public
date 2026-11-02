import sys
import socket
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import assert_local_server_guard, load_launcher


def test_guard_rejects_foreign_requests():
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    assert_local_server_guard(module.app, get_path='/api/status', post_path='/api/query')


def test_port_selection_skips_occupied_port():
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        selected = module.find_free_port(port)
        assert port < selected <= port + 19


def test_port_zero_resolves_once_for_browser_and_server(monkeypatch, tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    selected = module.find_free_port(0)
    assert 1 <= selected <= 65535
    calls = []
    monkeypatch.setattr(module, 'parse_args', lambda: SimpleNamespace(db_path=str(tmp_path / 'synthetic.sqlite'), port=0))
    monkeypatch.setattr(module, 'find_free_port', lambda port: calls.append(('select', port)) or selected)
    monkeypatch.setattr(module, 'testing_mode_enabled', lambda: False)
    class Thread:
        def __init__(self, *, target, args, daemon):
            calls.append(('browser', args[0]))
        def start(self):
            pass
    monkeypatch.setattr(module.threading, 'Thread', Thread)
    monkeypatch.setattr(module.uvicorn, 'run', lambda app, **kwargs: calls.append(('server', kwargs['port'])))
    module.main()
    assert calls == [('select', 0), ('browser', selected), ('server', selected)]
