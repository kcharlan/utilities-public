"""Machine configuration and missing-tool acceptance contracts."""
import pytest
import git_dashboard as gd


@pytest.mark.parametrize('content,expected', [
    ('schema = 1', []),
    ('schema = 1\n[dependencies]\nignore_missing_tools = ["npm", "npm", "pip-audit"]', ['npm', 'pip-audit']),
])
def test_valid_machine_config(tmp_path, monkeypatch, content, expected):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    path.write_text(content)
    result = gd.load_machine_config()
    assert result['error'] is None
    assert result['ignore_missing_tools'] == expected


@pytest.mark.parametrize('content', ['schema = true', 'schema = 2', 'schema = 1\nunknown = 1',
    'schema = 1\n[dependencies]\nignore_missing_tools = ["unknown"]',
    'schema = 1\n[dependencies]\nignore_missing_tools = [1]',
    'schema = 1\n[dependencies]\nunknown = 1'])
def test_invalid_machine_config_accepts_nothing(tmp_path, monkeypatch, content):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    path.write_text(content)
    result = gd.load_machine_config()
    assert result['error']
    assert result['ignore_missing_tools'] == []


def test_unknown_tool_name_error_names_it_and_lists_valid_names(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    path.write_text('schema = 1\n[dependencies]\nignore_missing_tools = ["npm audit"]')
    error = gd.load_machine_config()['error']
    assert "'npm audit'" in error
    assert 'pip-audit' in error and 'cargo-outdated' in error


def test_readme_lists_every_accepted_tool_name():
    from pathlib import Path
    readme = (Path(gd.__file__).parent / 'README.md').read_text()
    names = {tool for reqs in gd.DEP_TOOL_REQUIREMENTS.values() for _, tool, _, _ in reqs}
    assert all(f'`{name}`' in readme for name in names), sorted(names)


def test_tool_gating_matches_checker_call_sites():
    """Each key's gated dimensions come from the checker functions that read it."""
    import inspect
    import re
    derived = {}
    for fname, func in inspect.getmembers(gd, inspect.isfunction):
        match = re.fullmatch(r'check_\w+_(outdated|vulns)', fname)
        if not match:
            continue
        dimension = 'outdated' if match.group(1) == 'outdated' else 'vulnerability'
        for key in re.findall(r'TOOLS\.get\(["\'](\w+)["\']\)', inspect.getsource(func)):
            derived.setdefault(key, set()).add(dimension)
    declared = {key: set(dims) for reqs in gd.DEP_TOOL_REQUIREMENTS.values() for key, _, _, dims in reqs}
    assert {k: derived.get(k, set()) for k in declared} == declared
    assert set(derived) <= set(declared)


def test_missing_ignored_npm_accepts_unchecked_dimensions(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    path.write_text('schema = 1\n[dependencies]\nignore_missing_tools = ["npm"]')
    (tmp_path / 'package.json').write_text('{"dependencies":{"synthetic-widget":"*"}}')
    monkeypatch.setitem(gd.TOOLS, 'npm', None)
    result = gd.analyze_repo_deps(tmp_path)
    row = result.enriched[0]
    assert (row['outdated_state'], row['vuln_state'], row['severity']) == ('accepted', 'accepted', 'accepted')
    assert result.missing_tools == []
    assert [t['tool'] for t in result.ignored_tools] == ['npm']
    assert not result.any_error


def test_template_creation_is_exclusive_and_private(tmp_path, monkeypatch):
    import concurrent.futures
    path = tmp_path / 'home' / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: gd.create_machine_config(), range(8)))
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert gd.load_machine_config()['ignore_missing_tools'] == []
    path.write_text('invalid existing content')
    gd.create_machine_config()
    assert path.read_text() == 'invalid existing content'
    assert gd.load_machine_config()['error']


def test_missing_config_and_unwritable_template_path(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    assert gd.load_machine_config()['error'] is None
    assert gd.load_machine_config()['ignore_missing_tools'] == []
    blocker = tmp_path / 'file'
    blocker.write_text('synthetic')
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', blocker / 'config.toml')
    with pytest.raises(SystemExit, match='Error creating machine config'):
        gd.create_machine_config()
    assert gd.load_machine_config()['error']


def test_ignored_python_audit_accepts_even_direct_reference(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    path.write_text('schema = 1\n[dependencies]\nignore_missing_tools = ["pip-audit"]')
    (tmp_path / 'requirements.txt').write_text('synthetic-widget @ https://example.invalid/synthetic.whl\n')
    monkeypatch.setitem(gd.TOOLS, 'pip_audit', None)
    result = gd.analyze_repo_deps(tmp_path)
    assert result.enriched[0]['vuln_state'] == 'accepted'
    assert result.enriched[0]['outdated_state'] == 'unchecked'
    assert result.any_error
    assert result.enriched[0]['acceptances'][0]['detail'] == {'tools': ['pip-audit'], 'checks': ['vulnerability']}


def test_trust_skipped_cargo_only_accepts_direct_missing_gates(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    path.write_text('schema = 1\n[dependencies]\nignore_missing_tools = ["cargo", "cargo-outdated"]')
    (tmp_path / 'Cargo.toml').write_text('[dependencies]\nsynthetic_widget = "1"\n')
    monkeypatch.setattr(gd, 'TRUST_REPO_TOOLS', False)
    for key in ('cargo', 'cargo_outdated', 'cargo_audit'):
        monkeypatch.setitem(gd.TOOLS, key, None)
    result = gd.analyze_repo_deps(tmp_path)
    row = result.enriched[0]
    assert (row['outdated_state'], row['vuln_state']) == ('accepted', 'unchecked')
    assert [t['tool'] for t in result.missing_tools] == ['cargo-audit']
    assert row['acceptances'][0]['detail'] == {'tools': ['cargo-outdated'], 'checks': ['outdated']}
    assert result.any_error


def test_config_reload_and_installed_tool_has_no_effect(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    (tmp_path / 'package.json').write_text('{"dependencies":{"synthetic-widget":"*"}}')
    monkeypatch.setitem(gd.TOOLS, 'npm', None)
    assert gd.analyze_repo_deps(tmp_path).missing_tools
    path.write_text('schema = 1\n[dependencies]\nignore_missing_tools = ["npm"]')
    assert not gd.analyze_repo_deps(tmp_path).missing_tools
    monkeypatch.setitem(gd.TOOLS, 'npm', 'synthetic-installed')
    monkeypatch.setattr(gd, 'check_node_deps', lambda repo, rows: rows)
    result = gd.analyze_repo_deps(tmp_path)
    assert not result.ignored_tools
    assert not result.enriched[0]['acceptances']
    assert result.any_error


def test_parent_probe_only_finds_auxiliaries_when_parent_present(monkeypatch):
    found = {'cargo-audit', 'cargo-outdated', 'govulncheck', 'bundler-audit'}
    monkeypatch.setattr(gd.shutil, 'which', lambda name: '/synthetic/' + name if name in found else None)
    tools = gd.build_tools_dict()
    assert all(tools[k] is None for k in ('cargo_audit', 'cargo_outdated', 'govulncheck', 'bundler_audit'))
    found.update(('cargo', 'go', 'bundle'))
    tools = gd.build_tools_dict()
    assert all(tools[k] for k in ('cargo_audit', 'cargo_outdated', 'govulncheck', 'bundler_audit'))


@pytest.mark.parametrize('manager,key,tool,expected', [
    ('pip', 'pip_audit', 'pip-audit', ('unchecked', 'accepted')),
    ('npm', 'npm', 'npm', ('accepted', 'accepted')),
    ('gomod', 'go', 'go', ('accepted', 'unchecked')),
    ('gomod', 'govulncheck', 'govulncheck', ('unchecked', 'accepted')),
    ('cargo', 'cargo', 'cargo', ('unchecked', 'unchecked')),
    ('cargo', 'cargo_outdated', 'cargo-outdated', ('accepted', 'unchecked')),
    ('cargo', 'cargo_audit', 'cargo-audit', ('unchecked', 'accepted')),
    ('bundler', 'bundle', 'bundle', ('accepted', 'unchecked')),
    ('bundler', 'bundler_audit', 'bundler-audit', ('unchecked', 'accepted')),
    ('composer', 'composer', 'composer', ('accepted', 'accepted')),
])
def test_direct_missing_tool_gate(manager, key, tool, expected, monkeypatch):
    monkeypatch.setitem(gd.TOOLS, key, None)
    row = {'manager': manager, 'outdated_state': 'unchecked', 'vuln_state': 'unchecked', 'acceptances': []}
    gd.apply_ignored_tools([row], {tool})
    assert (row['outdated_state'], row['vuln_state']) == expected


def test_status_and_snapshot_report_machine_config(tmp_path, monkeypatch, test_app):
    import asyncio
    import json
    import sqlite3
    import aiosqlite
    client, db_path = test_app
    path = gd.MACHINE_CONFIG_PATH
    path.write_text('schema = 1\n[dependencies]\nignore_missing_tools = ["npm"]')
    assert client.get('/api/status').json()['machine_config']['ignore_missing_tools'] == ['npm']
    assert client.get('/api/status').json()['machine_config']['label'] == 'Current config loaded at view refresh; Check Now applies current config'
    (tmp_path / 'package.json').write_text('{"dependencies":{"synthetic-widget":"*"}}')
    monkeypatch.setitem(gd.TOOLS, 'npm', None)
    with sqlite3.connect(db_path) as db:
        db.execute('INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)', ('synthetic', 'synthetic', str(tmp_path), '2026-01-01'))
    async def scan():
        async with aiosqlite.connect(db_path) as db:
            await gd.run_dep_scan_for_repo(db, 'synthetic', str(tmp_path))
            await db.commit()
    asyncio.run(scan())
    detail = client.get('/api/repos/synthetic').json()['working_state']
    assert [item['tool'] for item in detail['ignored_dep_tools']] == ['npm']
    assert detail['missing_dep_tools'] == []
    with sqlite3.connect(db_path) as db:
        assert json.loads(db.execute('SELECT ignored_dep_tools FROM working_state').fetchone()[0]) == detail['ignored_dep_tools']


def test_invalid_bytes_size_and_dangling_link_are_errors(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    path.write_bytes(b'\xff')
    assert gd.load_machine_config()['error']
    path.write_bytes(b' ' * (gd.MAX_DEP_FILE_SIZE + 1))
    assert gd.load_machine_config()['error']
    path.unlink()
    path.symlink_to(tmp_path / 'absent')
    assert gd.load_machine_config()['error']


def test_template_write_failure_retains_file_and_reports_path(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    original = gd.os.fdopen
    def failing_fdopen(fd, *args, **kwargs):
        stream = original(fd, *args, **kwargs)
        class FailingStream:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                stream.close()
            def write(self, value):
                stream.write('schema =')
                raise OSError('synthetic write failure')
        return FailingStream()
    monkeypatch.setattr(gd.os, 'fdopen', failing_fdopen)
    with pytest.raises(SystemExit, match='synthetic write failure') as exc:
        gd.create_machine_config()
    assert str(path) in str(exc.value)
    assert path.read_text() == 'schema ='
    gd.create_machine_config()
    assert path.read_text() == 'schema ='


@pytest.mark.parametrize('link', [False, True])
def test_fifo_config_is_rejected_without_blocking(tmp_path, monkeypatch, test_app, link):
    import os
    from pathlib import Path
    if not hasattr(os, 'mkfifo'):
        pytest.skip('FIFO unavailable')
    fifo = tmp_path / 'synthetic-fifo'
    os.mkfifo(fifo)
    config = tmp_path / 'config.toml'
    if link:
        config.symlink_to(fifo)
    else:
        fifo.rename(config)
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', config)
    real_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path == config:
            raise AssertionError('attempted blocking open of FIFO config')
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    real_os_open = os.open
    def guarded_os_open(path, flags, *args, **kwargs):
        if path == config:
            raise AssertionError('attempted open of FIFO config')
        return real_os_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(gd.os, 'open', guarded_os_open)
    assert gd.load_machine_config()['error']
    response = test_app[0].get('/api/status').json()['machine_config']
    assert response['error'] and response['ignore_missing_tools'] == []


def test_symlink_to_regular_config_is_valid(tmp_path, monkeypatch):
    target = tmp_path / 'actual.toml'
    target.write_text('schema = 1')
    path = tmp_path / 'config.toml'
    path.symlink_to(target)
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    assert gd.load_machine_config()['error'] is None


def test_preflight_redetects_tools_only_after_restart(tmp_path, monkeypatch):
    available = {'git', 'go'}
    monkeypatch.setattr(gd, 'TOOLS', {})
    monkeypatch.setattr(gd.shutil, 'which', lambda name: '/synthetic/' + name if name in available else None)
    monkeypatch.setattr(gd, 'check_node_deps', lambda repo, rows: rows)
    (tmp_path / 'package.json').write_text('{"dependencies":{"synthetic-widget":"*"}}')
    gd.run_preflight()
    assert [item['tool'] for item in gd.analyze_repo_deps(tmp_path).missing_tools] == ['npm']
    available.add('npm')
    assert [item['tool'] for item in gd.analyze_repo_deps(tmp_path).missing_tools] == ['npm']
    gd.run_preflight()
    assert gd.analyze_repo_deps(tmp_path).missing_tools == []


def test_config_display_survives_unavailable_home(tmp_path, monkeypatch):
    from pathlib import Path
    path = tmp_path / 'config.toml'
    path.write_text('schema = 1')
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    def unavailable(cls):
        raise RuntimeError('synthetic home unavailable')
    monkeypatch.setattr(Path, 'home', classmethod(unavailable))
    config = gd.load_machine_config()
    assert config['path'] == str(path)
    assert config['error'] is None


def test_config_replaced_after_stat_cannot_block(tmp_path, monkeypatch):
    import os
    if not hasattr(os, 'mkfifo') or not hasattr(os, 'O_NONBLOCK'):
        pytest.skip('nonblocking FIFO unavailable')
    config = tmp_path / 'config.toml'
    config.write_text('schema = 1')
    fifo = tmp_path / 'synthetic-fifo'
    os.mkfifo(fifo)
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', config)
    real_open = os.open
    def replace_before_open(path, flags, *args, **kwargs):
        if path == config:
            assert flags & os.O_NONBLOCK, 'config open must not block after a path swap'
            return real_open(fifo, flags, *args, **kwargs)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(gd.os, 'open', replace_before_open)
    assert gd.load_machine_config()['error']


@pytest.mark.parametrize('create', [False, True])
def test_fdopen_failure_closes_owned_descriptor(tmp_path, monkeypatch, create):
    import os
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(gd, 'MACHINE_CONFIG_PATH', path)
    if not create:
        path.write_text('schema = 1\n')
    opened = []
    def fail_fdopen(fd, *args, **kwargs):
        assert kwargs['closefd'] is False
        opened.append(fd)
        raise OSError('synthetic fdopen failure')
    monkeypatch.setattr(gd.os, 'fdopen', fail_fdopen)
    if create:
        with pytest.raises(SystemExit, match='synthetic fdopen failure'):
            gd.create_machine_config()
    else:
        assert 'synthetic fdopen failure' in gd.load_machine_config()['error']
    with pytest.raises(OSError):
        os.fstat(opened[0])
