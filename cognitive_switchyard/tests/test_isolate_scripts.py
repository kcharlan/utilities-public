from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PACKS = Path(__file__).resolve().parents[1] / 'cognitive_switchyard' / 'builtin_packs'
NAMES = ('claude-code', 'codex', 'codex-hybrid')


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'repo'
    path.mkdir()
    git(path, 'init')
    git(path, 'config', 'user.name', 'Synthetic Test')
    git(path, 'config', 'user.email', 'test@example.invalid')
    (path / 'file').write_text('base\n')
    git(path, 'add', 'file')
    git(path, 'commit', '-m', 'base')
    return path


def hook(pack, name, repo, *args):
    return subprocess.run([str(PACKS / pack / 'scripts' / name), *map(str, args)], env={**os.environ, 'COGNITIVE_SWITCHYARD_REPO_ROOT': str(repo)}, capture_output=True, text=True)


def start(pack, repo, session):
    result = hook(pack, 'isolate_start', repo, 0, 'task', session)
    assert result.returncode == 0, result.stderr
    return Path(result.stdout.strip())


def commit_file(repo, value):
    (repo / 'file').write_text(value)
    git(repo, 'add', 'file')
    git(repo, 'commit', '-m', 'change')


def test_end_copies_identical():
    assert len({(PACKS / pack / 'scripts' / 'isolate_end').read_bytes() for pack in NAMES}) == 1


@pytest.mark.parametrize('pack', NAMES)
def test_retry_reuses_slot_and_merges(pack, repo, tmp_path):
    session = tmp_path / 'session'
    workspace = start(pack, repo, session)
    commit_file(workspace, 'first\n')
    assert hook(pack, 'isolate_end', repo, 0, 'task', workspace, 'blocked').returncode == 0
    workspace = start(pack, repo, session)
    commit_file(workspace, 'retry\n')
    result = hook(pack, 'isolate_end', repo, 0, 'task', workspace, 'done')
    assert result.returncode == 0, result.stderr
    assert (repo / 'file').read_text() == 'retry\n'


@pytest.mark.parametrize('pack', NAMES)
def test_dirty_tree_refused_and_preserved(pack, repo, tmp_path):
    workspace = start(pack, repo, tmp_path / 'session')
    commit_file(workspace, 'worker\n')
    (repo / 'file').write_text('uncommitted\n')
    result = hook(pack, 'isolate_end', repo, 0, 'task', workspace, 'done')
    assert result.returncode != 0
    assert (repo / 'file').read_text() == 'uncommitted\n'
    assert git(repo, 'rev-parse', '--verify', 'switchyard-task-0')


@pytest.mark.parametrize('pack', NAMES)
def test_existing_merge_is_not_aborted(pack, repo, tmp_path):
    workspace = start(pack, repo, tmp_path / 'session')
    commit_file(workspace, 'worker\n')
    merge_head = repo / '.git' / 'MERGE_HEAD'
    merge_head.write_text(git(repo, 'rev-parse', 'HEAD') + '\n')
    result = hook(pack, 'isolate_end', repo, 0, 'task', workspace, 'done')
    assert result.returncode != 0
    assert merge_head.exists()
    assert (workspace / 'file').read_text() == 'worker\n'


@pytest.mark.parametrize('pack', NAMES)
def test_conflict_preserves_branch_and_source(pack, repo, tmp_path):
    workspace = start(pack, repo, tmp_path / 'session')
    commit_file(workspace, 'worker\n')
    commit_file(repo, 'source\n')
    result = hook(pack, 'isolate_end', repo, 0, 'task', workspace, 'done')
    assert result.returncode != 0
    assert (repo / 'file').read_text() == 'source\n'
    assert git(repo, 'status', '--porcelain') == ''
    assert git(repo, 'rev-parse', '--verify', 'switchyard-task-0')


@pytest.mark.parametrize('pack', NAMES)
@pytest.mark.parametrize('remove_workspace', (False, True))
def test_conflict_retry_preserves_branch(pack, repo, tmp_path, remove_workspace):
    session = tmp_path / 'session'
    workspace = start(pack, repo, session)
    commit_file(workspace, 'worker\n')
    saved = git(workspace, 'rev-parse', 'HEAD')
    commit_file(repo, 'source\n')
    assert hook(pack, 'isolate_end', repo, 0, 'task', workspace, 'done').returncode != 0
    if remove_workspace:
        git(repo, 'worktree', 'remove', '--force', str(workspace))
    result = hook(pack, 'isolate_start', repo, 0, 'task', session)
    assert result.returncode != 0
    assert git(repo, 'rev-parse', 'switchyard-task-0') == saved
    if not remove_workspace:
        assert (workspace / 'file').read_text() == 'worker\n'


@pytest.mark.parametrize('pack', NAMES)
def test_outside_workspace_intact(pack, repo, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep').write_text('safe')
    result = hook(pack, 'isolate_end', repo, 0, 'task', outside, 'blocked')
    assert (outside / 'keep').read_text() == 'safe'
    assert result.returncode != 0


@pytest.mark.parametrize('pack', NAMES)
def test_start_failure_does_not_detach(pack, repo, tmp_path):
    # A pre-existing branch checked out elsewhere prevents -B from succeeding.
    workspace = start(pack, repo, tmp_path / 'session')
    result = hook(pack, 'isolate_start', repo, 0, 'task', tmp_path / 'another')
    assert result.returncode != 0
    assert git(workspace, 'branch', '--show-current') == 'switchyard-task-0'
