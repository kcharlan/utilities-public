"""Publication contracts using only private synthetic runtime directories."""
import json
import os
from pathlib import Path
import shutil
import sys
import re

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


def existing_page(tmp_path):
    """Seed a synthetic previous page at the fixed output path."""
    home = tmp_path / 'runtime'
    home.mkdir(mode=0o700, exist_ok=True)
    page = home / 'tax2.html'
    page.write_bytes(b'synthetic old page')
    return page, page.stat().st_mtime_ns


def assert_page_unchanged(page, before):
    assert page.read_bytes() == b'synthetic old page' and page.stat().st_mtime_ns == before


def test_help_has_no_side_effects(tmp_path):
    assert_launcher_help(PROJECT / 'tax2', expected_markers=(
        '--rules-dir', '--no-browser', 'TAX2_HOME', 'config.yaml', 'tax2.html'))
    assert not (tmp_path / 'runtime').exists()


def test_build_writes_fixed_page_with_private_modes(tmp_path, capsys):
    assert load_launcher(PROJECT / 'tax2').main(['--no-browser']) == 0
    page = tmp_path / 'runtime/tax2.html'
    assert capsys.readouterr().out.strip() == str(page)
    assert page.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / 'runtime').stat().st_mode & 0o777 == 0o700
    assert (tmp_path / 'runtime/config.yaml').stat().st_mode & 0o777 == 0o600


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


def test_config_symlink_loop_still_builds_default_output(tmp_path, caplog):
    home = tmp_path / 'runtime'
    home.mkdir()
    config = home / 'config.yaml'
    member = home / 'loop.yaml'
    config.symlink_to('loop.yaml')
    member.symlink_to('config.yaml')
    assert load_launcher(PROJECT / 'tax2').main(['--no-browser']) == 0
    assert (home / 'tax2.html').read_bytes().startswith(b'<!doctype html>')
    assert UNREADABLE_WARNING in caplog.text
    assert config.is_symlink() and member.is_symlink()


@pytest.mark.parametrize('value, suppressed', [('',False),('0',False),('false',False),('FALSE',False),
    ('no',False),('No',False),('1',True),('yes',True),('anything',True)])
def test_browser_suppression_and_relative_uri(tmp_path, monkeypatch, value, suppressed):
    monkeypatch.setenv('UTILITIES_TESTING', value)
    monkeypatch.setenv('TAX2_HOME', 'runtime')
    monkeypatch.chdir(tmp_path)
    launcher = load_launcher(PROJECT / 'tax2')
    calls = []
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda uri: calls.append(uri) or True)
    assert launcher.main([]) == 0
    assert calls == ([] if suppressed else [(tmp_path / 'runtime/tax2.html').as_uri()])


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


@pytest.mark.parametrize('args', [['--port','9000'], ['positional-root'], ['--output', 'page.html']])
def test_usage_errors(tmp_path, args):
    result = run_launcher(PROJECT / 'tax2', *args)
    assert result.returncode == 2 and 'usage:' in result.stderr
    assert not (tmp_path / 'runtime').exists()


def test_missing_rules_preserves_old_page(tmp_path):
    page, before = existing_page(tmp_path)
    result = run_launcher(PROJECT / 'tax2', '--no-browser', '--rules-dir', str(tmp_path / 'missing'))
    assert result.returncode == 1 and 'No federal rules' in result.stderr
    assert 'Traceback' not in result.stderr
    assert_page_unchanged(page, before)


@pytest.mark.parametrize('asset', ['engine.js', 'styles.css', 'vendor/preact.LICENSE'])
def test_copied_launcher_unsafe_assets_preserve_page(tmp_path, asset):
    deployment = tmp_path / 'synthetic-deployment'
    deployment.mkdir()
    shutil.copy2(PROJECT / 'tax2', deployment / 'tax2')
    for directory in ('taxkit','web','rules'):
        shutil.copytree(PROJECT / directory, deployment / directory,
                        ignore=shutil.ignore_patterns('__pycache__'))
    (deployment / 'web' / asset).write_text('</ScRiPt> synthetic unsafe asset')
    page, before = existing_page(tmp_path)
    result = run_launcher(deployment / 'tax2', '--no-browser')
    assert result.returncode == 1 and 'Unsafe inline asset' in result.stderr
    assert asset in result.stderr and 'Traceback' not in result.stderr
    assert_page_unchanged(page, before)


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
    page, before = existing_page(tmp_path)
    def fail(*args): raise OSError('synthetic publication failure')
    monkeypatch.setattr(os, 'replace', fail)
    assert launcher.main(['--no-browser']) == 1
    assert 'synthetic publication failure' in capsys.readouterr().err
    assert_page_unchanged(page, before)
    assert not list(page.parent.glob('.tax2.html.*.tmp'))


def test_invalid_rule_filename_and_fatal_output_preservation(tmp_path):
    from tests.test_page_build import synthetic_root
    root = synthetic_root(tmp_path)
    bad = root / 'federal/2026.yaml'
    bad.write_text('components: []\n')
    page, before = existing_page(tmp_path)
    result = run_launcher(PROJECT / 'tax2','--rules-dir',str(root),'--no-browser')
    assert result.returncode == 1 and str(bad) in result.stderr
    assert 'Traceback' not in result.stderr
    assert_page_unchanged(page, before)
