from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_empty_registry(tmp_path):
    from tools.run_project_tests import load_project_tests
    path = tmp_path / 'registry.toml'
    path.write_text('[projects]\n')
    assert load_project_tests(path) == {}


def test_invalid_registry_is_rejected(tmp_path):
    from tools.run_project_tests import load_project_tests
    path = tmp_path / 'registry.toml'
    path.write_text('[projects.bad]\nproject = "missing"\n')
    with pytest.raises(ValueError, match='bad'):
        load_project_tests(path)


def test_probe_rejects_cached_interpreter_mismatch(tmp_path, monkeypatch):
    from tools import run_project_tests as runner
    from subprocess import CompletedProcess
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    synthetic_launcher(tmp_path)
    monkeypatch.setattr(runner, 'REPO_ROOT', tmp_path)
    outputs = iter(['/opt/homebrew/bin/python3.12\n3.12.0\n', '/opt/homebrew/bin/python3.12\n', '/opt/homebrew/other/python\n3.12.0\n'])
    monkeypatch.setattr(runner.subprocess, 'run', lambda *args, **kwargs: CompletedProcess(args[0], 0, next(outputs), ''))
    with pytest.raises(ValueError, match='interpreter mismatch'):
        runner.verify_interpreter(entry, '/opt/homebrew/bin/python3.12', {})


def synthetic_launcher(tmp_path, dependencies='[]'):
    launcher = tmp_path / 'launcher'
    launcher.write_text('#!/usr/bin/env -S uv run --script\n# /// script\n# requires-python = ">=3.12"\n# dependencies = ' + dependencies + '\n# ///\n')
    launcher.chmod(0o755)
    return launcher


def test_extensionless_header_supplies_packages(tmp_path, monkeypatch):
    import importlib
    import subprocess
    from tools import run_project_tests as runner
    launcher = synthetic_launcher(tmp_path, '["packaging"]')
    contamination = tmp_path / 'contamination'
    contamination.mkdir()
    (contamination / 'undeclared_synthetic_sentinel.py').write_text('value = "synthetic"\n')
    monkeypatch.syspath_prepend(str(contamination))
    assert importlib.import_module('undeclared_synthetic_sentinel').value == 'synthetic'
    sys.modules.pop('undeclared_synthetic_sentinel')
    monkeypatch.setenv('PYTHONPATH', str(contamination))
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'cache'))
    env = runner.clean_environment()
    interpreter = runner.resolve_interpreter(launcher)
    command = ['uv', 'run', '--no-project', '--isolated', '--no-python-downloads', '--python', interpreter, '--with-requirements', str(launcher), 'python', '-c']
    positive_env = env.copy()
    positive_env['PYTHONPATH'] = str(contamination)
    positive = subprocess.run(command + ['import undeclared_synthetic_sentinel'], cwd=tmp_path, env=positive_env, capture_output=True, text=True)
    assert positive.returncode == 0, positive.stderr
    result = subprocess.run(command + ['import packaging, importlib.util; assert importlib.util.find_spec("undeclared_synthetic_sentinel") is None'], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_empty_header_is_accepted(tmp_path, monkeypatch):
    import subprocess
    from tools import run_project_tests as runner
    launcher = synthetic_launcher(tmp_path)
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'cache'))
    interpreter = runner.resolve_interpreter(launcher)
    result = subprocess.run(['uv', 'run', '--no-project', '--isolated', '--no-python-downloads', '--python', interpreter, '--with-requirements', str(launcher), 'python', '-c', 'print("synthetic-ok")'], cwd=tmp_path, env=runner.clean_environment(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'synthetic-ok'


def test_resolution_after_script_cache_is_warmed(tmp_path, monkeypatch, capsys):
    import subprocess
    from tools import run_project_tests as runner
    launcher = synthetic_launcher(tmp_path, '["packaging"]')
    with launcher.open('a') as script:
        script.write('print("synthetic help")\n')
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(runner, 'REPO_ROOT', tmp_path)
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    first = runner.resolve_interpreter(launcher)
    result = subprocess.run(['uv', 'run', '--no-python-downloads', '--script', str(launcher), '--help'],
                            cwd=tmp_path, env=runner.clean_environment(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'synthetic help'
    second = runner.resolve_interpreter(launcher)
    assert runner.is_approved_interpreter(Path(second))
    assert Path(first).resolve() == Path(second).resolve()
    runner.verify_interpreter(entry, second, runner.clean_environment(), suite=False)
    assert 'Actual base interpreter:' in capsys.readouterr().out


def test_existing_venv_cannot_supply_undeclared_package(tmp_path, monkeypatch):
    import subprocess
    from tools import run_project_tests as runner
    launcher = synthetic_launcher(tmp_path)
    venv = tmp_path / 'venv'
    subprocess.run(['uv', 'venv', '--seed', '--no-python-downloads', '--python', '/opt/homebrew/bin/python3.12', str(venv)], check=True, capture_output=True)
    site = next(venv.glob('lib/python*/site-packages'))
    (site / 'synthetic_sentinel.py').write_text('value = 1\n')
    assert subprocess.run([str(venv / 'bin/python'), '-c', 'import synthetic_sentinel'], capture_output=True).returncode == 0
    monkeypatch.setenv('VIRTUAL_ENV', str(venv))
    monkeypatch.setenv('PYTHONPATH', str(site))
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'cache'))
    interpreter = runner.resolve_interpreter(launcher)
    result = subprocess.run(['uv', 'run', '--no-project', '--isolated', '--no-python-downloads', '--python', interpreter, '--with-requirements', str(launcher), 'python', '-c', 'import importlib.util; assert importlib.util.find_spec("synthetic_sentinel") is None'], cwd=tmp_path, env=runner.clean_environment(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_resolution_ignores_activated_and_parent_venvs(tmp_path, monkeypatch):
    import subprocess
    from tools import run_project_tests as runner
    launcher = synthetic_launcher(tmp_path)
    venv = tmp_path / '.venv'
    subprocess.run(['uv', 'venv', '--seed', '--no-python-downloads', '--python', '/opt/homebrew/bin/python3.12', str(venv)], check=True, capture_output=True)
    monkeypatch.setenv('VIRTUAL_ENV', str(venv))
    monkeypatch.setenv('PATH', str(venv / 'bin') + ':' + __import__('os').environ['PATH'])
    monkeypatch.chdir(tmp_path)
    resolved = runner.resolve_interpreter(launcher)
    assert not Path(resolved).is_relative_to(venv)
    assert str(venv / 'bin') not in runner.clean_environment()['PATH'].split(':')
    monkeypatch.delenv('VIRTUAL_ENV')
    monkeypatch.setenv('PATH', runner.clean_environment()['PATH'])
    assert not Path(runner.resolve_interpreter(launcher)).is_relative_to(venv)


def test_cached_environment_interpreter_is_checked(tmp_path, monkeypatch, capsys):
    from tools import run_project_tests as runner
    launcher = synthetic_launcher(tmp_path)
    monkeypatch.setattr(runner, 'REPO_ROOT', tmp_path)
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'cache'))
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    interpreter = runner.resolve_interpreter(launcher)
    runner.verify_interpreter(entry, interpreter, runner.clean_environment())
    assert 'Actual base interpreter:' in capsys.readouterr().out
    original = runner.build_test_command
    monkeypatch.setattr(runner, 'build_test_command', lambda entry, requested, command, extra: original(entry, interpreter, command, extra))
    with pytest.raises(ValueError, match='interpreter mismatch'):
        runner.verify_interpreter(entry, '/opt/homebrew/bin/python3.12' if Path(interpreter).resolve() != Path('/opt/homebrew/bin/python3.12').resolve() else '/opt/homebrew/bin/python3.14', runner.clean_environment())


def test_build_command_keeps_optional_requirements_and_extra(tmp_path, monkeypatch):
    from tools import run_project_tests as runner
    monkeypatch.setattr(runner, 'REPO_ROOT', tmp_path)
    entry = runner.ProjectTests('project', 'project/launcher', None, (('pytest', '-q'),), ('--help',), None)
    command = runner.build_test_command(entry, '/opt/homebrew/bin/python3.12', entry.test_commands[0], ['-k', 'sample'])
    assert command == ['uv', 'run', '--no-project', '--isolated', '--no-python-downloads', '--python', '/opt/homebrew/bin/python3.12', '--with-requirements', str(tmp_path / 'project/launcher'), 'python', '-m', 'pytest', '-q', '-k', 'sample']
    from dataclasses import replace
    with_requirements = runner.build_test_command(replace(entry, test_requirements='project/dev.txt'), '/base', ('pytest',), [])
    assert with_requirements[9:11] == ['--with-requirements', str(tmp_path / 'project/dev.txt')]


def test_registry_checks_paths_fields_and_smoke(tmp_path, monkeypatch):
    from tools import run_project_tests as runner
    monkeypatch.setattr(runner, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(runner, 'LAUNCHERS', ['project/launcher'])
    (tmp_path / 'project').mkdir()
    (tmp_path / 'project/launcher').touch()
    path = tmp_path / 'registry.toml'
    prefix = '[projects.example]\nproject = "project"\nlauncher = "project/launcher"\ntest_commands = [["pytest"]]\n'
    path.write_text(prefix + 'smoke_skip_reason = "no safe help"\n')
    assert runner.load_project_tests(path)['example'].smoke_skip_reason == 'no safe help'
    for tail in ('', 'smoke_skip_reason = ""\n', 'smoke_args = ["--help"]\nsmoke_skip_reason = "both"\n', 'smoke_args = ["--version"]\n', 'smoke_args = ["--help"]\nunknown = true\n'):
        path.write_text(prefix + tail)
        with pytest.raises(ValueError, match='example'):
            runner.load_project_tests(path)
    path.write_text(prefix.replace('project/launcher', '../escape') + 'smoke_args = ["--help"]\n')
    with pytest.raises(ValueError, match='example'):
        runner.load_project_tests(path)


def test_print_command_and_unknown_key_do_not_start_processes(monkeypatch, capsys):
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest', '-q'),), None, 'unsafe help')
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: pytest.fail('unexpected subprocess'))
    assert runner.main(['demo', '--print-command', '--', '-k', 'example']) == 0
    output = capsys.readouterr().out
    assert 'unsafe help' in output and '<resolved-interpreter>' in output and '-k example' in output
    assert runner.main(['missing', '--print-command']) == 1
    assert 'unknown project' in capsys.readouterr().err


def test_separator_forwards_target_and_control_looking_flags(monkeypatch):
    from subprocess import CompletedProcess
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), None, 'unsafe help')
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    monkeypatch.setattr(runner, 'resolve_interpreter', lambda path: '/opt/homebrew/bin/python3.12')
    monkeypatch.setattr(runner, 'verify_interpreter', lambda *a, **kw: None)
    calls = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda args, **kw: calls.append(args) or CompletedProcess(args, 0))
    extra = ['tests/test_launcher.py::test_example', '-q', '--install-browsers']
    assert runner.main(['demo', '--', *extra]) == 0
    assert calls[0][-3:] == extra
    monkeypatch.setattr(runner.sys, 'argv', ['run_project_tests.py', 'demo', '--', *extra])
    assert runner.main() == 0
    assert calls[1][-3:] == extra


def test_separator_keeps_runner_validation_before_it(monkeypatch, capsys):
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), None, 'unsafe help')
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    assert runner.main(['--print-command', 'demo', '--', '-q']) == 0
    assert '-q' in capsys.readouterr().out
    for args in (['demo', '--unknown', '--', '-q'], ['demo', '--smoke-only', '--', '-q'],
                 ['demo', '--install-browsers', '--', '-q']):
        with pytest.raises(SystemExit) as exc:
            runner.main(args)
        assert exc.value.code == 2


def test_smoke_failure_stops_suite_and_preserves_status(monkeypatch):
    from subprocess import CompletedProcess
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    monkeypatch.setattr(runner, 'resolve_interpreter', lambda path: '/opt/homebrew/bin/python3.12')
    probes = []
    monkeypatch.setattr(runner, 'verify_interpreter', lambda *a, **kw: probes.append(kw['suite']))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 7)
    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main(['demo']) == 7
    assert probes == [False] and len(calls) == 1 and calls[0][-1] == '--help'


def test_skipped_smoke_and_ordered_suite_failure(monkeypatch, capsys):
    from subprocess import CompletedProcess
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('first',), ('second',), ('third',)), None, 'unsafe help')
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    monkeypatch.setattr(runner, 'resolve_interpreter', lambda path: '/opt/homebrew/bin/python3.12')
    monkeypatch.setattr(runner, 'verify_interpreter', lambda *a, **kw: None)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert kwargs['env']['UV_PYTHON_DOWNLOADS'] == 'never'
        return CompletedProcess(args, 4 if args[-1] == 'second' else 0)
    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main(['demo']) == 4
    assert [x[-1] for x in calls] == ['first', 'second']
    assert 'unsafe help' in capsys.readouterr().out


def test_smoke_only_does_not_probe_suite_or_run_suite(monkeypatch):
    from subprocess import CompletedProcess
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', 'dev.txt', (('pytest',),), ('--help',), None)
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    monkeypatch.setattr(runner, 'resolve_interpreter', lambda path: '/opt/homebrew/bin/python3.12')
    probes = []
    monkeypatch.setattr(runner, 'verify_interpreter', lambda *a, **kw: probes.append(kw['suite']))
    calls = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda args, **kw: calls.append(args) or CompletedProcess(args, 0))
    assert runner.main(['demo', '--smoke-only']) == 0
    assert probes == [False] and len(calls) == 1


def test_missing_uv_and_incompatible_options(monkeypatch, capsys):
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    def missing(path):
        raise FileNotFoundError('uv not found')
    monkeypatch.setattr(runner, 'resolve_interpreter', missing)
    assert runner.main(['demo']) == 1
    assert 'uv not found' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        runner.main(['demo', '--smoke-only', '--install-browsers'])


def test_environment_removes_python_overrides_but_retains_application_settings(tmp_path, monkeypatch):
    from tools import run_project_tests as runner
    venv = tmp_path / 'venv'
    (venv / 'bin').mkdir(parents=True)
    (venv / 'pyvenv.cfg').touch()
    monkeypatch.setenv('VIRTUAL_ENV', str(venv))
    monkeypatch.setenv('PATH', str(venv / 'bin') + ':/usr/bin')
    monkeypatch.setenv('PYTHONPATH', '/synthetic/path')
    monkeypatch.setenv('PYTHONHOME', '/synthetic/home')
    monkeypatch.setenv('PYTHONUSERBASE', '/synthetic/userbase')
    monkeypatch.setenv('STORAGE_MONITOR_WALKER', '/synthetic/walker')
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', '/synthetic/browsers')
    monkeypatch.setenv('UV_CACHE_DIR', '/synthetic/cache')
    env = runner.clean_environment()
    assert not {'VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE'} & env.keys()
    assert env['PATH'] == '/usr/bin'
    assert env['STORAGE_MONITOR_WALKER'] == '/synthetic/walker'
    assert env['PLAYWRIGHT_BROWSERS_PATH'] == '/synthetic/browsers'
    assert env['UV_CACHE_DIR'] == '/synthetic/cache'
    assert env['UV_PYTHON_DOWNLOADS'] == 'never'
    alias = tmp_path / 'venv-alias'
    alias.symlink_to(venv / 'bin')
    monkeypatch.delenv('VIRTUAL_ENV')
    monkeypatch.setenv('PATH', str(alias) + ':/usr/bin')
    assert runner.clean_environment()['PATH'] == '/usr/bin'


def test_install_browser_runs_only_install_command(monkeypatch):
    from subprocess import CompletedProcess
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    monkeypatch.setattr(runner, 'resolve_interpreter', lambda path: '/opt/homebrew/bin/python3.12')
    monkeypatch.setattr(runner, 'verify_interpreter', lambda *a, **kw: None)
    calls = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda args, **kw: calls.append(args) or CompletedProcess(args, 0))
    assert runner.main(['demo', '--install-browsers']) == 0
    assert len(calls) == 1 and calls[0][-3:] == ['playwright', 'install', 'chromium']


def test_registry_rejects_symlink_escape_and_bad_commands(tmp_path, monkeypatch):
    from tools import run_project_tests as runner
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'project').mkdir()
    (tmp_path / 'outside').write_text('')
    (root / 'project' / 'launcher').symlink_to(tmp_path / 'outside')
    monkeypatch.setattr(runner, 'REPO_ROOT', root)
    monkeypatch.setattr(runner, 'LAUNCHERS', ['project/launcher'])
    path = root / 'registry.toml'
    prefix = '[projects.demo]\nproject="project"\nlauncher="project/launcher"\nsmoke_args=["--help"]\n'
    path.write_text(prefix + 'test_commands=[["pytest"]]\n')
    with pytest.raises(ValueError, match='invalid file'):
        runner.load_project_tests(path)
    (root / 'project' / 'launcher').unlink()
    (root / 'project' / 'launcher').touch()
    for commands in ('[]', '[[]]', '[[1]]', '["pytest"]'):
        path.write_text(prefix + 'test_commands=' + commands + '\n')
        with pytest.raises(ValueError, match='test_commands'):
            runner.load_project_tests(path)


def test_discovery_failure_preserves_exit_status(monkeypatch, capsys):
    import subprocess
    from tools import run_project_tests as runner
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    monkeypatch.setattr(runner, 'load_project_tests', lambda path: {'demo': entry})
    def fail(path):
        raise subprocess.CalledProcessError(8, ['uv', 'python', 'find'], stderr='no approved interpreter')
    monkeypatch.setattr(runner, 'resolve_interpreter', fail)
    assert runner.main(['demo']) == 8
    assert 'no approved interpreter' in capsys.readouterr().err


def test_discovery_rejects_virtualenv_interpreter(tmp_path):
    from tools import run_project_tests as runner
    venv = tmp_path / 'venv'
    (venv / 'bin').mkdir(parents=True)
    (venv / 'pyvenv.cfg').touch()
    interpreter = venv / 'bin' / 'python'
    interpreter.touch()
    assert not runner.is_approved_interpreter(interpreter, tmp_path)
    (venv / 'pyvenv.cfg').unlink()
    assert runner.is_approved_interpreter(interpreter, tmp_path)
    interpreter.unlink()
    interpreter.symlink_to('/usr/bin/true')
    assert not runner.is_approved_interpreter(interpreter, tmp_path)


def test_actual_version_must_satisfy_launcher_constraint(tmp_path, monkeypatch):
    import subprocess
    from tools import run_project_tests as runner
    launcher = synthetic_launcher(tmp_path)
    launcher.write_text(launcher.read_text().replace('>=3.12', '>=99'))
    monkeypatch.setattr(runner, 'REPO_ROOT', tmp_path)
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'cache'))
    entry = runner.ProjectTests('.', 'launcher', None, (('pytest',),), ('--help',), None)
    with pytest.raises(subprocess.CalledProcessError):
        runner.verify_interpreter(entry, '/opt/homebrew/bin/python3.12', runner.clean_environment(), suite=False)
