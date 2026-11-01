import asyncio
import sqlite3
import subprocess

import git_dashboard as dashboard


def test_branch_option_is_rejected(test_app, tmp_path):
    client, db = test_app
    victim = tmp_path / 'victim'
    victim.write_text('untouched')
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)',
                     ('synthetic', 'synthetic', str(tmp_path), '2026-01-01'))
    response = client.get('/api/repos/synthetic/commits', params={'branch': '--output=' + str(victim)})
    assert response.status_code == 400
    assert victim.read_text() == 'untouched'


def test_known_branch_is_passed_as_a_ref(test_app, tmp_path, monkeypatch):
    client, db = test_app
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)',
                     ('synthetic', 'synthetic', str(tmp_path), '2026-01-01'))
        conn.execute('INSERT INTO branches (repo_id,name) VALUES (?,?)', ('synthetic', 'main'))
    calls = []
    async def fake_git(path, *args, **kwargs):
        calls.append(args)
        return ('0', '', 0)
    monkeypatch.setattr(dashboard, 'run_git', fake_git)
    assert client.get('/api/repos/synthetic/commits', params={'branch': 'main'}).status_code == 200
    assert calls == [('rev-list', '--count', '--end-of-options', 'main')]


def test_trust_flag_defaults_off():
    assert not dashboard.parse_args([]).trust_repo_tools
    assert dashboard.parse_args(['--trust-repo-tools']).trust_repo_tools


def test_untrusted_repo_tools_are_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard.subprocess, 'run', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('executed')))
    for manager, check in [('cargo', dashboard.check_rust_deps), ('bundler', dashboard.check_ruby_deps)]:
        result = check(tmp_path, [dict(manager=manager, name='synthetic', version='1')])
        assert result[0]['outdated_state'] == 'unchecked'
        assert 'trust-repo-tools' in result[0]['check_note']


def test_git_disables_repo_hooks_and_fsmonitor(tmp_path):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    marker = tmp_path / 'marker'
    hook = tmp_path / '.git/hooks/post-index-change'
    hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
    hook.chmod(0o755)
    subprocess.run(['git', '-C', str(tmp_path), 'config', 'core.fsmonitor', 'touch ' + str(marker)], check=True)
    asyncio.run(dashboard.run_git(tmp_path, 'status', '--porcelain=v1'))
    assert not marker.exists()


def test_requirements_include_cannot_escape_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (tmp_path / 'outside.txt').write_text('synthetic-outside==1\n')
    (repo / 'requirements.txt').write_text('-r ../outside.txt\n')
    assert dashboard.parse_deps_for_repo(repo) == []


def test_includes_reject_external_symlink_and_oversized_file(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('synthetic-outside==1\n')
    (repo / 'link.txt').symlink_to(outside)
    (repo / 'large.txt').write_text('synthetic-large==1\n' * 10)
    (repo / 'requirements.txt').write_text('-r link.txt\n-r large.txt\n')
    monkeypatch.setattr(dashboard, 'MAX_DEP_FILE_SIZE', 64)
    assert dashboard.parse_deps_for_repo(repo) == []


def test_npm_option_name_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard.subprocess, 'run', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('executed')))
    try:
        dashboard._npm_latest_version('npm', tmp_path, '--help')
    except ValueError:
        return
    assert False, 'option-shaped name accepted'


def test_npm_json_option_precedes_end_of_options(tmp_path, monkeypatch):
    def run(args, **kwargs):
        assert args == ['npm', 'view', '--json', '--', 'synthetic-package', 'version']
        return subprocess.CompletedProcess(args, 0, stdout='"1.0.0"', stderr='')
    monkeypatch.setattr(dashboard.subprocess, 'run', run)
    assert dashboard._npm_latest_version('npm', tmp_path, 'synthetic-package') == '1.0.0'
