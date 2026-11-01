import sys
import socket
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
