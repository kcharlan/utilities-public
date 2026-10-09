"""Publication contracts using only private synthetic runtime directories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re
import ast
import tomllib

import pytest

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent
sys.path.insert(0, str(REPO))
from tools.testkit import assert_launcher_help, load_launcher, run_launcher
from tests.helpers import UNREADABLE_WARNING, unreadable_config_chain, warning_count


@pytest.fixture(autouse=True)
def private_runtime(tmp_path, monkeypatch):
    assert not tmp_path.resolve().is_relative_to(REPO.resolve())
    tmp_path.chmod(0o700)
    monkeypatch.setenv('TAX2_HOME', str(tmp_path / 'runtime'))


def test_help_has_no_side_effects(tmp_path):
    assert_launcher_help(PROJECT / 'tax2', expected_markers=(
        '--output', '--rules-dir', '--no-browser', 'TAX2_HOME', 'config.yaml', 'tax2.html'))
    assert not (tmp_path / 'runtime').exists()


def test_build_relative_output_and_private_modes(tmp_path, monkeypatch):
    launcher = load_launcher(PROJECT / 'tax2')
    monkeypatch.chdir(tmp_path)
    assert launcher.main(['--no-browser', '--output', 'page.html']) == 0
    assert (tmp_path / 'page.html').stat().st_mode & 0o777 == 0o600
    assert (tmp_path / 'runtime').stat().st_mode & 0o777 == 0o700
    assert (tmp_path / 'runtime/config.yaml').stat().st_mode & 0o777 == 0o600


def synthetic_repo(path, protected=True):
    path.mkdir()
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    for name in ('tax2/tax2', 'tools/check_uv_headers.py') if protected else ('synthetic.txt',):
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('synthetic source signature\n')
    subprocess.run(['git', '-C', str(path), 'add', '.'], check=True)
    return path


def test_source_rejection_before_private_state(tmp_path):
    source = synthetic_repo(tmp_path / 'synthetic-source')
    page = source / 'existing.html'
    page.write_bytes(b'synthetic old page')
    before = page.stat().st_mtime_ns
    launcher = load_launcher(PROJECT / 'tax2')
    assert launcher.main(['--output', str(page), '--no-browser']) == 1
    assert page.read_bytes() == b'synthetic old page'
    assert page.stat().st_mtime_ns == before
    assert not (tmp_path / 'runtime').exists()


def test_config_destination_rejected_before_creation(tmp_path):
    launcher = load_launcher(PROJECT / 'tax2')
    assert launcher.main(['--output', str(tmp_path / 'runtime/config.yaml')]) == 1
    assert not (tmp_path / 'runtime').exists()


def existing_config(home):
    home.mkdir(mode=0o700, exist_ok=True)
    config = home / 'config.yaml'
    config.write_bytes(b'default_states: [GA]\n')
    return config


def reject_config_output(output, capsys):
    assert load_launcher(PROJECT / 'tax2').main(['--no-browser', '--output', str(output)]) == 1
    assert capsys.readouterr().err.strip() == 'Tax2: Output destination would replace config.yaml'


@pytest.mark.parametrize('name', ['CONFIG.yaml', 'Config.YAML'])
def test_case_variant_config_output_rejected(tmp_path, capsys, name):
    config = existing_config(tmp_path / 'runtime')
    before = (config.read_bytes(), config.stat().st_mtime_ns)
    reject_config_output(config.with_name(name), capsys)
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before
    assert list(config.parent.iterdir()) == [config]


@pytest.mark.parametrize('home_exists', [False, True])
def test_case_variant_config_output_rejected_on_first_run(tmp_path, capsys, home_exists):
    home = tmp_path / 'runtime'
    if home_exists:
        home.mkdir()
    reject_config_output(home / 'CONFIG.yaml', capsys)
    if home_exists:
        assert list(home.iterdir()) == []
    else:
        assert not home.exists()


def test_case_variant_missing_parent_rejected_early(tmp_path, capsys):
    reject_config_output(tmp_path / 'RUNTIME/config.yaml', capsys)
    assert not (tmp_path / 'runtime').exists()
    assert not (tmp_path / 'RUNTIME').exists()


def test_case_variant_missing_target_parent_rejected(tmp_path, capsys):
    home = tmp_path / 'runtime'
    home.mkdir()
    config = home / 'config.yaml'
    config.symlink_to(tmp_path / 'other/real.yaml')
    reject_config_output(tmp_path / 'OTHER/real.yaml', capsys)
    assert config.is_symlink()
    assert not (tmp_path / 'other').exists()
    assert not (tmp_path / 'OTHER').exists()


def test_prepublish_recheck_rejects_conflict(tmp_path, monkeypatch, capsys):
    """Blind only the early conflict step; the real pre-publish recheck must reject.

    A counting wrapper replaces the ``taxkit.config.config_conflict`` module
    global, which ``ensure_no_config_conflict`` looks up for both the early gate
    and the pre-publish recheck (the launcher never references the name; see
    ``test_config_conflict_raise_has_one_home``). Its first call (the early gate)
    returns False; every later call delegates to the real function. The rest of
    ``validate_output_destination``, including its Git checks, still runs.
    """
    import taxkit.config
    config = existing_config(tmp_path / 'runtime')
    before = (config.read_bytes(), config.stat().st_mtime_ns)
    launcher = load_launcher(PROJECT / 'tax2')
    real = taxkit.config.config_conflict
    calls = []

    def first_call_blind(*args, **kwargs):
        if not calls:
            calls.append(('blinded', False))
            return False
        result = real(*args, **kwargs)
        calls.append(('delegated', result))
        return result

    monkeypatch.setattr(taxkit.config, 'config_conflict', first_call_blind)
    assert launcher.main(['--no-browser', '--output', str(config.with_name('CONFIG.yaml'))]) == 1
    assert calls == [('blinded', False), ('delegated', True)]
    assert capsys.readouterr().err.strip() == 'Tax2: Output destination would replace config.yaml'
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before
    assert list(config.parent.iterdir()) == [config]


def test_dangling_config_symlink_target_rejected(tmp_path, capsys):
    home = tmp_path / 'runtime'
    home.mkdir()
    target = tmp_path / 'missing.yaml'
    config = home / 'config.yaml'
    config.symlink_to(target)
    reject_config_output(target, capsys)
    assert config.is_symlink() and not target.exists()


def test_unresolvable_config_chain_still_builds(tmp_path, caplog):
    home = tmp_path / 'runtime'
    home.mkdir()
    regular = tmp_path / 'regular'
    regular.write_bytes(b'synthetic regular file')
    config = home / 'config.yaml'
    config.symlink_to(regular / 'child')
    assert load_launcher(PROJECT / 'tax2').main(['--no-browser']) == 0
    assert (home / 'tax2.html').read_bytes().startswith(b'<!doctype html>')
    assert UNREADABLE_WARNING in caplog.text
    assert config.is_symlink()


def test_unreadable_config_chain_still_builds(tmp_path, caplog):
    home = tmp_path / 'runtime'
    with unreadable_config_chain(tmp_path, home):
        assert load_launcher(PROJECT / 'tax2').main(['--no-browser']) == 0
        page = home / 'tax2.html'
        assert page.read_bytes().startswith(b'<!doctype html>')
        assert page.stat().st_mode & 0o777 == 0o600
        assert warning_count(caplog) == 1
    assert sorted(path.name for path in home.iterdir()) == ['config.yaml', 'tax2.html']


def test_unreadable_config_chain_unrelated_output_builds(tmp_path, caplog):
    home = tmp_path / 'runtime'
    output = tmp_path / 'elsewhere' / 'out.html'
    with unreadable_config_chain(tmp_path, home):
        assert load_launcher(PROJECT / 'tax2').main(['--no-browser', '--output', str(output)]) == 0
        assert output.read_bytes().startswith(b'<!doctype html>')
        assert output.stat().st_mode & 0o777 == 0o600
        assert warning_count(caplog) == 1
    assert sorted(path.name for path in home.iterdir()) == ['config.yaml']


@pytest.mark.parametrize('member', ['link_a', 'link_b'])
def test_intermediate_config_symlink_rejected(tmp_path, capsys, member):
    config = existing_config(tmp_path / 'runtime')
    target = tmp_path / 'real.yaml'
    config.rename(target)
    (tmp_path / 'link_b').symlink_to(target)
    (tmp_path / 'link_a').symlink_to('link_b')
    config.symlink_to(tmp_path / 'link_a')
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    links = [config, tmp_path / 'link_a', tmp_path / 'link_b']
    original_targets = {path: os.readlink(path) for path in links}
    reject_config_output(tmp_path / member, capsys)
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert all(path.is_symlink() for path in links)
    assert {path: os.readlink(path) for path in links} == original_targets


@pytest.mark.parametrize('home_link', [False, True])
def test_directory_symlink_in_config_path_rejected(tmp_path, monkeypatch, capsys, home_link):
    home = tmp_path / 'runtime'
    config = existing_config(home)
    if home_link:
        output = tmp_path / 'home-link'
        output.symlink_to(home, target_is_directory=True)
        monkeypatch.setenv('TAX2_HOME', str(output))
    else:
        target = tmp_path / 'real-dir'
        target.mkdir()
        config.rename(target / 'real.yaml')
        output = home / 'dirlink'
        output.symlink_to(target, target_is_directory=True)
        config.symlink_to('dirlink/real.yaml')
    original_target = os.readlink(output)
    reject_config_output(output, capsys)
    assert output.is_symlink()
    assert os.readlink(output) == original_target
    assert not (home / 'tax2.html').exists()


def test_config_symlink_loop_still_builds_default_output(tmp_path, caplog, capsys):
    home = tmp_path / 'runtime'
    home.mkdir()
    config = home / 'config.yaml'
    member = home / 'loop.yaml'
    config.symlink_to('loop.yaml')
    member.symlink_to('config.yaml')
    assert load_launcher(PROJECT / 'tax2').main(['--no-browser']) == 0
    assert (home / 'tax2.html').read_bytes().startswith(b'<!doctype html>')
    assert UNREADABLE_WARNING in caplog.text
    capsys.readouterr()
    reject_config_output(member, capsys)
    assert config.is_symlink() and member.is_symlink()


@pytest.mark.parametrize('form', ['direct', 'relative', 'normalized', 'parent-link', 'missing-subdir', 'nested'])
def test_source_path_forms_preserve_state(tmp_path, monkeypatch, form):
    source = synthetic_repo(tmp_path / 'synthetic-source')
    output = source / 'page.html'
    if form == 'relative':
        monkeypatch.chdir(tmp_path)
        output = Path('synthetic-source/page.html')
    elif form == 'normalized':
        output = source / 'unused/../page.html'
    elif form == 'parent-link':
        (tmp_path / 'alias').symlink_to(source, target_is_directory=True)
        output = tmp_path / 'alias/page.html'
    elif form == 'missing-subdir':
        output = source / 'missing/nested/page.html'
    elif form == 'nested':
        output = synthetic_repo(source / 'nested', protected=False) / 'page.html'
    config = tmp_path / 'runtime/config.yaml'
    config.parent.mkdir(mode=0o700)
    config.write_bytes(b'synthetic existing config')
    before = (config.read_bytes(), config.stat().st_mtime_ns)
    assert load_launcher(PROJECT / 'tax2').main(['--output', str(output)]) == 1
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before
    assert not output.exists()
    assert list(config.parent.iterdir()) == [config]


def test_source_worktree_git_indirection(tmp_path):
    source = synthetic_repo(tmp_path / 'synthetic-source')
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Synthetic Test',
        '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm',
        'Create synthetic signature\n\nTrack fake files for source-boundary acceptance.'], check=True)
    worktree = tmp_path / 'synthetic-worktree'
    subprocess.run(['git', '-C', str(source), 'worktree', 'add', '-q', '--detach', str(worktree)], check=True)
    assert (worktree / '.git').is_file()
    assert load_launcher(PROJECT / 'tax2').main(['--output', str(worktree / 'page.html')]) == 1
    assert not (tmp_path / 'runtime').exists()


@pytest.mark.parametrize('kind', ['unrelated', 'sibling', 'deployment'])
def test_safe_destination_classes(tmp_path, kind):
    source = synthetic_repo(tmp_path / 'synthetic-source')
    if kind == 'unrelated':
        destination = synthetic_repo(tmp_path / 'unrelated', protected=False)
    elif kind == 'sibling':
        destination = tmp_path / 'synthetic-source-sibling'
    else:
        destination = tmp_path / 'deployed-copy'
    destination.mkdir(exist_ok=True)
    destination.chmod(0o755)
    output = destination / 'page.html'
    assert load_launcher(PROJECT / 'tax2').main(['--no-browser', '--output', str(output)]) == 0
    assert destination.stat().st_mode & 0o777 == 0o755
    assert output.stat().st_mode & 0o777 == 0o600


def test_output_leaf_symlinks_use_entry_boundary(tmp_path):
    source = synthetic_repo(tmp_path / 'synthetic-source')
    target = source / 'synthetic-target.html'
    target.write_bytes(b'synthetic target')
    before = target.stat().st_mtime_ns
    output = tmp_path / 'outside.html'
    output.symlink_to(target)
    launcher = load_launcher(PROJECT / 'tax2')
    assert launcher.main(['--no-browser', '--output', str(output)]) == 0
    assert not output.is_symlink()
    assert target.read_bytes() == b'synthetic target' and target.stat().st_mtime_ns == before
    inside = source / 'inside.html'
    inside.symlink_to(output)
    before = (output.read_bytes(), output.stat().st_mtime_ns)
    assert launcher.main(['--output', str(inside)]) == 1
    assert inside.is_symlink()
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before


@pytest.mark.parametrize('form', ['direct', 'relative', 'normalized', 'parent-link', 'config-target'])
def test_config_alias_protection(tmp_path, monkeypatch, form):
    home = tmp_path / 'runtime'
    home.mkdir(mode=0o700)
    config = home / 'config.yaml'
    config.write_bytes(b'synthetic untouched config')
    before = config.stat().st_mtime_ns
    output = config
    if form == 'relative':
        monkeypatch.chdir(tmp_path)
        output = Path('runtime/config.yaml')
    elif form == 'normalized':
        output = home / 'missing/../config.yaml'
    elif form == 'parent-link':
        (tmp_path / 'alias').symlink_to(home, target_is_directory=True)
        output = tmp_path / 'alias/config.yaml'
    elif form == 'config-target':
        target = tmp_path / 'actual-config.yaml'
        config.rename(target)
        config.symlink_to(target)
        output = target
    assert load_launcher(PROJECT / 'tax2').main(['--output', str(output)]) == 1
    assert config.read_bytes() == b'synthetic untouched config'
    assert config.stat().st_mtime_ns == before


@pytest.mark.parametrize('failure', ['missing', 'timeout', 'execution', 'nonzero', 'invalid-root'])
def test_git_failures_are_closed_before_private_state(tmp_path, monkeypatch, failure, capsys):
    source = synthetic_repo(tmp_path / 'synthetic-source', protected=False)
    page = source / 'page.html'
    page.write_bytes(b'synthetic old page')
    before = page.stat().st_mtime_ns
    def fail(*args, **kwargs):
        assert isinstance(args[0], list) and 'shell' not in kwargs
        assert kwargs['timeout'] == 5
        assert not any(key.startswith('GIT_') for key in kwargs['env'])
        if failure == 'invalid-root':
            return subprocess.CompletedProcess(args[0], 0, stdout=b'', stderr=b'')
        error = {'missing': FileNotFoundError('synthetic missing git'),
                 'timeout': subprocess.TimeoutExpired('git', 5),
                 'execution': OSError('synthetic execution failure'),
                 'nonzero': subprocess.CalledProcessError(128, 'git')}[failure]
        raise error
    monkeypatch.setenv('GIT_DIR', '/synthetic/override')
    monkeypatch.setenv('GIT_INDEX_FILE', '/synthetic/index')
    monkeypatch.setattr(subprocess, 'run', fail)
    assert load_launcher(PROJECT / 'tax2').main(['--output', str(page)]) == 1
    assert 'Destination safety' in capsys.readouterr().err
    assert page.read_bytes() == b'synthetic old page' and page.stat().st_mtime_ns == before
    assert not (tmp_path / 'runtime').exists()


@pytest.mark.parametrize('failure', ['permission', 'broken-link', 'broken-file'])
def test_git_metadata_failures(tmp_path, monkeypatch, failure):
    destination = tmp_path / 'synthetic-marked'
    destination.mkdir()
    metadata = destination / '.git'
    if failure == 'broken-link':
        metadata.symlink_to(destination / 'missing')
    elif failure == 'broken-file':
        metadata.write_text('gitdir: missing\n')
    else:
        original = Path.lstat
        def lstat(path, *args, **kwargs):
            if path == metadata:
                raise PermissionError('synthetic metadata permission failure')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'lstat', lstat)
    assert load_launcher(PROJECT / 'tax2').main(['--output', str(destination / 'page.html')]) == 1
    assert not (tmp_path / 'runtime').exists()
    assert not (destination / 'page.html').exists()


def test_no_git_needed_for_unmarked_output_or_help(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('Git must not run outside marked ancestry')
    monkeypatch.setattr(subprocess, 'run', fail)
    launcher = load_launcher(PROJECT / 'tax2')
    with pytest.raises(SystemExit) as exit:
        launcher.main(['--help'])
    assert exit.value.code == 0
    assert launcher.main(['--no-browser']) == 0


@pytest.mark.parametrize('value, suppressed', [('',False),('0',False),('false',False),('FALSE',False),
    ('no',False),('No',False),('1',True),('yes',True),('anything',True)])
def test_browser_suppression_and_relative_uri(tmp_path, monkeypatch, value, suppressed):
    monkeypatch.setenv('UTILITIES_TESTING', value)
    monkeypatch.chdir(tmp_path)
    launcher = load_launcher(PROJECT / 'tax2')
    calls = []
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda uri: calls.append(uri) or True)
    assert launcher.main(['--output','page.html']) == 0
    assert calls == ([] if suppressed else [(tmp_path / 'page.html').as_uri()])


@pytest.mark.parametrize('throws', [False, True])
def test_browser_failure_is_nonfatal(tmp_path, monkeypatch, capsys, throws):
    monkeypatch.setenv('UTILITIES_TESTING', '0')
    launcher = load_launcher(PROJECT / 'tax2')
    def browser(uri):
        if throws: raise OSError('synthetic browser failure')
        return False
    monkeypatch.setattr(launcher.webbrowser, 'open', browser)
    assert launcher.main([]) == 0
    assert (tmp_path / 'runtime/tax2.html').exists()
    assert 'warning' in capsys.readouterr().err


@pytest.mark.parametrize('args', [['--port','9000'], ['positional-root'], ['--output']])
def test_usage_errors(tmp_path, args):
    result = run_launcher(PROJECT / 'tax2', *args)
    assert result.returncode == 2 and 'usage:' in result.stderr
    assert not (tmp_path / 'runtime').exists()


def test_missing_rules_preserves_old_page(tmp_path):
    page = tmp_path / 'page.html'
    page.write_bytes(b'synthetic old')
    before = page.stat().st_mtime_ns
    result = run_launcher(PROJECT / 'tax2', '--no-browser', '--output', str(page),
                          '--rules-dir', str(tmp_path / 'missing'))
    assert result.returncode == 1 and 'No federal rules' in result.stderr
    assert 'Traceback' not in result.stderr
    assert page.read_bytes() == b'synthetic old' and page.stat().st_mtime_ns == before


@pytest.mark.parametrize('asset', ['engine.js', 'styles.css', 'vendor/preact.LICENSE'])
def test_copied_launcher_unsafe_assets_preserve_page(tmp_path, asset):
    deployment = tmp_path / 'synthetic-deployment'
    deployment.mkdir()
    shutil.copy2(PROJECT / 'tax2', deployment / 'tax2')
    for directory in ('taxkit','web','rules'):
        shutil.copytree(PROJECT / directory, deployment / directory,
                        ignore=shutil.ignore_patterns('__pycache__'))
    (deployment / 'web' / asset).write_text('</ScRiPt> synthetic unsafe asset')
    page = tmp_path / 'page.html'
    page.write_bytes(b'synthetic old page')
    before = page.stat().st_mtime_ns
    result = run_launcher(deployment / 'tax2', '--no-browser', '--output', str(page))
    assert result.returncode == 1 and 'Unsafe inline asset' in result.stderr
    assert asset in result.stderr and 'Traceback' not in result.stderr
    assert page.read_bytes() == b'synthetic old page' and page.stat().st_mtime_ns == before


def test_custom_root_payload_escaping_and_asset_inlining(tmp_path):
    from tests.test_page_build import synthetic_root
    root = synthetic_root(tmp_path)
    home = tmp_path / 'runtime'
    home.mkdir(mode=0o700)
    config = home / 'config.yaml'
    config.write_text('default_states: [XF]\nqif_overrides:\n  XF:\n    state_expense: "</script> synthetic"\n')
    config.chmod(0o600)
    before = (config.read_bytes(), config.stat().st_mtime_ns)
    result = run_launcher(PROJECT / 'tax2', '--no-browser', '--rules-dir', str(root))
    assert result.returncode == 0, result.stderr
    page = (home / 'tax2.html').read_text()
    data = re.search(r'<script id="tax2-data" type="application/json">(.*?)</script>', page, re.S)
    assert data is not None
    assert '<' not in data.group(1) and '\\u003c' in data.group(1)
    payload = json.loads(data.group(1))
    assert payload['rules_source'] == 'custom'
    assert [state['code'] for state in payload['states']] == ['XE','XF']
    assert payload['config']['qif_overrides']['XF']['state_expense'] == '</script> synthetic'
    assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)=["\x27]https?://', page, re.I)
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before


def test_copied_deployment_success_uses_installed_assets(tmp_path):
    deployment = tmp_path / 'synthetic-deployment'
    deployment.mkdir()
    shutil.copy2(PROJECT / 'tax2', deployment / 'tax2')
    for directory in ('taxkit','web','rules'):
        shutil.copytree(PROJECT / directory, deployment / directory,
                        ignore=shutil.ignore_patterns('__pycache__'))
    result = run_launcher(deployment / 'tax2', '--no-browser')
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'runtime/tax2.html').read_bytes().startswith(b'<!doctype html>')


def test_corrupt_config_launcher_preserves_bytes_and_mtime(tmp_path):
    home = tmp_path / 'runtime'
    home.mkdir(mode=0o700)
    config = home / 'config.yaml'
    config.write_bytes(b': : synthetic invalid yaml')
    config.chmod(0o600)
    before = (config.read_bytes(), config.stat().st_mtime_ns)
    result = run_launcher(PROJECT / 'tax2', '--no-browser')
    assert result.returncode == 0 and UNREADABLE_WARNING in result.stderr
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before


def test_launcher_write_failure_preserves_page(tmp_path, monkeypatch, capsys):
    launcher = load_launcher(PROJECT / 'tax2')
    page = tmp_path / 'page.html'
    page.write_bytes(b'synthetic old page')
    before = page.stat().st_mtime_ns
    def fail(*args): raise OSError('synthetic publication failure')
    monkeypatch.setattr(os, 'replace', fail)
    assert launcher.main(['--no-browser','--output',str(page)]) == 1
    assert 'synthetic publication failure' in capsys.readouterr().err
    assert page.read_bytes() == b'synthetic old page' and page.stat().st_mtime_ns == before
    assert not list(tmp_path.glob('.page.html.*.tmp'))


def test_source_guard_does_not_read_config(tmp_path, monkeypatch):
    import taxkit.page
    source = synthetic_repo(tmp_path / 'synthetic-source')
    calls = []
    monkeypatch.setattr(taxkit.page, 'load_config', lambda: calls.append('read'))
    assert load_launcher(PROJECT / 'tax2').main(['--output',str(source / 'page.html')]) == 1
    assert calls == []
    assert not (tmp_path / 'runtime').exists()


def test_runtime_manifest_and_fleet_policy_drop_retired_dependencies():
    header = (PROJECT / 'tax2').read_text().split('# /// script\n',1)[1].split('# ///',1)[0]
    metadata = tomllib.loads('\n'.join(line.removeprefix('# ') for line in header.splitlines()))
    assert metadata == {'requires-python': '>=3.12', 'dependencies':['pydantic','pyyaml']}
    requirements = {line.split('>=',1)[0] for line in (PROJECT / 'requirements-dev.txt').read_text().splitlines()
                    if line and not line.startswith('#')}
    assert requirements == {'pydantic','pyyaml','pytest','playwright'}
    # Inspect the guard's declared policy as data; shared tooling executes only
    # with its own utility venv, rather than borrowing this project's Python.
    guard = Path(sys.modules['tools.testkit'].__file__).with_name('check_uv_headers.py')
    module = ast.parse(guard.read_text())
    policy = next(node.value for node in module.body if isinstance(node, ast.AnnAssign)
                  and isinstance(node.target, ast.Name) and node.target.id == 'DEPENDENCY_MANIFESTS')
    tax2_policy = next(value for key,value in zip(policy.keys,policy.values) if ast.literal_eval(key)=='tax2/tax2')
    assert ast.literal_eval(tax2_policy.elts[2].args[0]) == {'playwright','pytest'}


def test_git_index_query_failure_is_closed(tmp_path, monkeypatch):
    source = synthetic_repo(tmp_path / 'synthetic-source', protected=False)
    original = subprocess.run
    calls = []
    def fail_index(arguments, **kwargs):
        calls.append(arguments)
        if 'ls-files' in arguments:
            raise subprocess.CalledProcessError(128, arguments)
        return original(arguments, **kwargs)
    monkeypatch.setattr(subprocess, 'run', fail_index)
    assert load_launcher(PROJECT / 'tax2').main(['--output',str(source / 'page.html')]) == 1
    assert len(calls) == 2
    assert not (tmp_path / 'runtime').exists()


def test_invalid_rule_filename_and_fatal_output_preservation(tmp_path):
    from tests.test_page_build import synthetic_root
    root = synthetic_root(tmp_path)
    bad = root / 'federal/2026.yaml'
    bad.write_text('components: []\n')
    page = tmp_path / 'page.html'
    page.write_bytes(b'synthetic old page')
    before = page.stat().st_mtime_ns
    result = run_launcher(PROJECT / 'tax2','--rules-dir',str(root),'--output',str(page),'--no-browser')
    assert result.returncode == 1 and str(bad) in result.stderr
    assert 'Traceback' not in result.stderr
    assert page.read_bytes() == b'synthetic old page' and page.stat().st_mtime_ns == before
