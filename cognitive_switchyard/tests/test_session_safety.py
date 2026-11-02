"""Safety regressions for session worktree admission."""
import hashlib
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from cognitive_switchyard.server import _create_session_worktree, _cleanup_session_worktree


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def tree_hashes(root):
    return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "synthetic-repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Synthetic Tester")
    git(path, "config", "user.email", "synthetic@example.invalid")
    (path / "file").write_text("original")
    git(path, "add", "file")
    git(path, "commit", "-m", "Initial")
    git(path, "branch", "session")
    return path


def test_collision_never_removes_unregistered_directory(repo):
    sibling = repo.parent / "sibling"
    sibling.mkdir()
    (sibling / "file").write_text("synthetic data")
    for target in (repo, sibling):
        before = tree_hashes(target)
        with pytest.raises(HTTPException) as exc:
            _create_session_worktree(str(repo), "session", target)
        assert exc.value.status_code == 409
        assert tree_hashes(target) == before


def test_registered_worktree_can_be_reused(repo):
    target = repo.parent / "session-tree"
    git(repo, "worktree", "add", str(target), "session")
    assert _create_session_worktree(str(repo), "session", target) == target
    assert target.is_dir()


def test_cleanup_preserves_unmerged_branch(repo):
    target = repo.parent / "session-tree"
    git(repo, "worktree", "add", str(target), "session")
    git(repo, "branch", "switchyard-synthetic-1")
    git(repo, "checkout", "switchyard-synthetic-1")
    (repo / "file").write_text("unmerged")
    git(repo, "commit", "-am", "Unmerged")
    git(repo, "checkout", "main")
    _cleanup_session_worktree(str(repo), str(target))
    assert git(repo, "branch", "--list", "switchyard-synthetic-1").stdout.strip()


def test_rejects_untrusted_session_inputs(tmp_path):
    from tests.test_server import TestClient
    from tests.test_server import _build_store, _write_runtime_pack
    from cognitive_switchyard.server import create_app

    store, paths = _build_store(tmp_path)
    _write_runtime_pack(paths)
    app = create_app(store=store, runtime_paths=paths)
    with TestClient(app) as client:
        for config in (
            {"environment": {"COGNITIVE_SWITCHYARD_SOURCE_REPO": str(tmp_path)}},
            {"environment": {"GIT_CONFIG_COUNT": "1"}},
            {"_worktree": {"source_repo": str(tmp_path), "path": str(tmp_path)}},
        ):
            response = client.post('/api/sessions', json={"id": "synthetic", "pack": "claude-code", "config": config})
            assert response.status_code == 400
        assert client.post('/api/sessions', json={"id": "synthetic", "pack": "../../../outside"}).status_code == 400
        assert client.put('/api/settings', json={"terminal_app": "untrusted-command"}).status_code == 400


def test_guard_rejects_foreign_hosts_and_origins(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from tests.test_server import _build_store
    from cognitive_switchyard.server import create_app
    from tools.testkit import assert_local_server_guard

    store, paths = _build_store(tmp_path)
    app = create_app(store=store, runtime_paths=paths)
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(assert_local_server_guard, app, post_path='/api/sessions', ws_path='/ws').result()


def test_task_cleanup_uses_slot_and_preserves_unmerged_branch(repo, tmp_path):
    import json
    from tests.test_server import _build_store, _register_task
    from cognitive_switchyard.server import ConnectionManager, SessionController

    target = repo.parent / 'session-tree'
    git(repo, 'worktree', 'add', str(target), 'session')
    git(repo, 'branch', 'switchyard-synthetic-1')
    git(repo, 'branch', 'switchyard-synthetic-2')
    git(repo, 'checkout', 'switchyard-synthetic-2')
    (repo / 'file').write_text('unmerged')
    git(repo, 'commit', '-am', 'Unmerged')
    git(repo, 'checkout', 'main')
    store, paths = _build_store(tmp_path)
    session = store.create_session(session_id='synthetic', name='Synthetic', pack='synthetic',
        created_at='2026-01-01T00:00:00Z', config_json=json.dumps({'_worktree': {'source_repo': str(repo), 'path': str(target)}}))
    _register_task(store, session.id, task_id='synthetic', title='Synthetic')
    for slot in (1, 2):
        store.project_task(session.id, 'synthetic', status='active', worker_slot=slot)
        store.project_task(session.id, 'synthetic', status='done')
    SessionController(store=store, runtime_paths=paths, connection_manager=ConnectionManager())._cleanup_task_worktree(session.id, 'synthetic')
    assert not git(repo, 'branch', '--list', 'switchyard-synthetic-1').stdout.strip()
    assert git(repo, 'branch', '--list', 'switchyard-synthetic-2').stdout.strip()


def test_serve_backend_rejects_non_loopback_before_side_effects(tmp_path, monkeypatch):
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.server import serve_backend

    paths = build_runtime_paths(home=tmp_path / 'synthetic-runtime')
    def forbidden(_port):
        raise AssertionError('port scan happened before host validation')
    monkeypatch.setattr('cognitive_switchyard.server.find_free_port', forbidden)
    with pytest.raises(ValueError, match='127.0.0.1'):
        serve_backend(runtime_paths=paths, builtin_packs_root=tmp_path, host='0.0.0.0', port=8100)
    assert not paths.home.exists()


def test_get_settings_and_root_do_not_write_state(tmp_path):
    from tests.test_server import TestClient, _build_store
    from cognitive_switchyard.server import create_app

    store, paths = _build_store(tmp_path)
    app = create_app(store=store, runtime_paths=paths)
    before = tree_hashes(paths.home)
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/settings').status_code == 200
    assert tree_hashes(paths.home) == before
    assert not paths.config.exists()


def test_session_collision_routes_preserve_trees(repo, tmp_path):
    from tests.test_server import TestClient, _build_store, _write_runtime_pack
    from cognitive_switchyard.server import create_app

    sibling = repo.parent / 'synthetic-sibling'
    sibling.mkdir()
    (sibling / 'file').write_text('synthetic data')
    store, paths = _build_store(tmp_path)
    _write_runtime_pack(paths)
    with TestClient(create_app(store=store, runtime_paths=paths)) as client:
        for target in (repo, sibling):
            before = tree_hashes(target)
            response = client.post('/api/sessions', json={
                'id': target.name, 'pack': 'claude-code', 'config': {'environment': {
                    'COGNITIVE_SWITCHYARD_REPO_ROOT': str(repo),
                    'COGNITIVE_SWITCHYARD_BRANCH': 'session',
                }},
            })
            assert response.status_code == 409
            assert tree_hashes(target) == before


@pytest.fixture
def isolated_session(repo, tmp_path):
    from tests.test_server import TestClient, _build_store, _write_runtime_pack
    from cognitive_switchyard.server import create_app

    store, paths = _build_store(tmp_path / 'runtime')
    _write_runtime_pack(paths)
    app = create_app(store=store, runtime_paths=paths)
    with TestClient(app) as client:
        response = client.post('/api/sessions', json={
            'id': 'synthetic', 'pack': 'claude-code', 'config': {'environment': {
                'COGNITIVE_SWITCHYARD_REPO_ROOT': str(repo),
                'COGNITIVE_SWITCHYARD_BRANCH': 'session',
            }},
        })
        assert response.status_code == 201
        worktree = Path(response.json()['session']['config']['environment']['COGNITIVE_SWITCHYARD_REPO_ROOT'])
        assert worktree.is_dir()
        yield store, app, client, worktree


@pytest.mark.parametrize('status', ['paused', 'created'])
def test_abort_without_session_thread_removes_worktree(repo, isolated_session, status):
    store, app, client, worktree = isolated_session
    store.update_session_status('synthetic', status=status)
    assert client.post('/api/sessions/synthetic/abort').status_code == 202
    assert not worktree.exists()
    assert f'worktree {worktree}' not in git(repo, 'worktree', 'list', '--porcelain').stdout.splitlines()


def test_abort_with_live_session_thread_leaves_worktree_to_the_thread(isolated_session):
    store, app, client, worktree = isolated_session
    release = threading.Event()
    thread = threading.Thread(target=release.wait)
    thread.start()
    app.state.controller._threads['synthetic'] = thread
    try:
        assert client.post('/api/sessions/synthetic/abort').status_code == 202
        assert worktree.is_dir()
        assert store.get_session('synthetic').status == 'aborted'
    finally:
        release.set()
        thread.join(timeout=10)
    assert not thread.is_alive()


@pytest.mark.parametrize('route', ['end', 'cleanup-worktree'])
def test_end_and_cleanup_routes_remove_worktree(repo, isolated_session, route):
    store, app, client, worktree = isolated_session
    if route == 'end':
        store.update_session_status('synthetic', status='idle')
    else:
        store.update_session_status('synthetic', status='completed')
    response = client.post(f'/api/sessions/synthetic/{route}')
    assert response.status_code == (202 if route == 'end' else 200)
    if route == 'cleanup-worktree':
        assert response.json() == {'ok': True}
    assert not worktree.exists()
    assert f'worktree {worktree}' not in git(repo, 'worktree', 'list', '--porcelain').stdout.splitlines()


@pytest.mark.parametrize('status', ['idle', 'completed', 'aborted'])
def test_session_thread_removes_worktree_only_when_run_ends_aborted(isolated_session, monkeypatch, status):
    from cognitive_switchyard import server

    store, app, client, worktree = isolated_session
    monkeypatch.setattr(server, 'load_pack_manifest', lambda _: object())
    def finish_session(**kwargs):
        store.update_session_status('synthetic', status=status)
        return SimpleNamespace(started=True)
    monkeypatch.setattr(server, 'start_session', finish_session)
    monkeypatch.setattr(app.state.controller, '_publish_snapshot', lambda _: None)
    app.state.controller._run_session('synthetic')
    assert worktree.is_dir() == (status != 'aborted')


def test_serve_backend_binds_loopback(tmp_path, monkeypatch):
    import threading
    import time
    import uvicorn
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.server import serve_backend

    started = threading.Event()
    servers = []
    def run_real_server(app, **kwargs):
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', **kwargs))
        servers.append(server)
        started.set()
        server.run()
    monkeypatch.setattr(uvicorn, 'run', run_real_server)
    worker = threading.Thread(target=serve_backend, kwargs={
        'runtime_paths': build_runtime_paths(home=tmp_path), 'builtin_packs_root': tmp_path,
        'host': '127.0.0.1', 'port': 0,
    })
    worker.start()
    try:
        assert started.wait(10)
        deadline = time.monotonic() + 10
        while not servers[0].started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert servers[0].started
        sockets = [sock for server in servers[0].servers for sock in server.sockets]
        assert sockets and all(sock.getsockname()[0] == '127.0.0.1' for sock in sockets)
    finally:
        if servers:
            servers[0].should_exit = True
        worker.join(timeout=10)
    assert not worker.is_alive()
