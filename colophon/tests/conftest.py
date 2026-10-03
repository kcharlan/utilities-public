"""Isolated launcher fixtures; tests may connect only to loopback hosts."""

from __future__ import annotations

import ipaddress
import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from tools.testkit import load_launcher, run_launcher


@pytest.fixture(scope="session")
def colophon():
    return load_launcher(PROJECT_ROOT / "colophon")


@pytest.fixture
def home(tmp_path):
    return tmp_path / "colophon-home"


@pytest.fixture
def codex_home(tmp_path):
    path = tmp_path / "synthetic-codex-home"
    (path / "sessions").mkdir(parents=True)
    return path


@pytest.fixture
def run_cli():
    def invoke(*args, home, codex_home, env=None):
        overrides = {
            "COLOPHON_HOME": str(home),
            "COLOPHON_PRICING_URL": "http://127.0.0.1:9/catalog.json",
        }
        if env:
            overrides.update(env)
        return run_launcher(
            PROJECT_ROOT / "colophon",
            *args,
            "--codex-home",
            str(codex_home),
            cwd=PROJECT_ROOT,
            env_overrides=overrides,
        )

    return invoke


@pytest.fixture(autouse=True)
def isolate_user_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "synthetic-user-home"))
    monkeypatch.setenv("COLOPHON_HOME", str(tmp_path / "colophon-home"))
    monkeypatch.setenv("COLOPHON_PRICING_URL", "http://127.0.0.1:9/catalog.json")


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch):
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def check_address(address):
        # Unix-domain sockets never leave this computer.
        if not isinstance(address, tuple):
            return
        host = address[0]
        if host == "localhost":
            return
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            raise AssertionError(f"External network forbidden in tests: {host}")

    def connect(sock, address):
        check_address(address)
        return original_connect(sock, address)

    def create_connection(address, *args, **kwargs):
        check_address(address)
        return original_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)
