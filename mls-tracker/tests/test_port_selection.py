import argparse
import logging
import socket

import pytest

import mls_tracker


@pytest.fixture
def occupied_port():
    while True:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        if listener.getsockname()[1] <= 65516:
            break
        listener.close()
    with listener:
        yield listener.getsockname()[1]


def test_requested_free_port_is_selected():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert mls_tracker.find_free_port(port) == port


def test_occupied_port_selects_a_later_port(occupied_port):
    selected = mls_tracker.find_free_port(occupied_port)
    assert occupied_port < selected <= occupied_port + 19


def test_exhausted_port_scan_raises(occupied_port):
    with pytest.raises(RuntimeError, match="No free port found"):
        mls_tracker.find_free_port(occupied_port, max_attempts=1)


def test_main_uses_and_warns_about_alternate_port(monkeypatch, caplog, occupied_port):
    port = occupied_port
    calls = []
    monkeypatch.setattr(mls_tracker, "parse_args", lambda: argparse.Namespace(port=port, no_browser=True))
    monkeypatch.setattr(mls_tracker.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    with caplog.at_level(logging.WARNING, logger="mls_tracker"):
        mls_tracker.main()
    assert calls[0]["host"] == "127.0.0.1"
    selected = calls[0]["port"]
    assert port < selected <= port + 19
    assert any(str(port) in record.message and str(selected) in record.message for record in caplog.records)
