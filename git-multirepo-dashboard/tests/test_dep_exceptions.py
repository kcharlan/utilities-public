"""Synthetic exception-file discovery and exclusion regressions."""
import git_dashboard as gd
from test_default_branch import make_repo


def test_exclude_skips_named_manifest_and_reports_inventory(tmp_path):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["package.json"]\nreason = "synthetic"\n')
    (repo / 'package.json').write_text('{ invalid')
    manifests, exceptions = [], []
    assert gd.parse_deps_for_repo(repo, manifests, exceptions) == []
    assert manifests == [dict(path='package.json', kind='package.json', dependencies=0, error=None, excluded_by='.gitfleet.toml')]
    assert exceptions[0].entries[0].status == 'applied'


def test_validation_rejects_whole_file_and_defaults_checks(tmp_path):
    path = tmp_path / '.gitfleet.toml'
    bad = [
        '', 'schema = true', 'schema = 2', 'schema = 1\nextra = 1',
        'schema = 1\nexclude = {}',
        'schema = 1\n[[exclude]]\npaths = []\nreason = "x"',
        'schema = 1\n[[exclude]]\npaths = ["../x"]\nreason = "x"',
        'schema = 1\n[[exclude]]\npaths = ["/x"]\nreason = "x"',
        'schema = 1\n[[exclude]]\npaths = ["C:/x"]\nreason = "x"',
        'schema = 1\n[[exclude]]\npaths = ["x"]\nreason = " "',
        'schema = 1\n[[exclude]]\npaths = ["x"]\nreason = "x"\nexpires = "2020-01-01"',
        'schema = 1\n[[exclude]]\npaths = ["x"]\nreason = "x"\nexpires = 2020-01-01T00:00:00Z',
        'schema = 1\n[[exclude]]\npaths = ["x"]\nreason = true',
        'schema = 1\n[[exclude]]\npaths = ["x"]\nreason = "x"\nextra = 1',
        'schema = 1\n[[exclude]]\npaths = ["x", 2]\nreason = "x"',
        'schema = 1\n[[exclude]]\npaths = ["x\\\\y"]\nreason = "x"',
        'schema = 1\n[[hold]]\nmanager = "pip"\npackage = "x"\nreason = "x"',
        'schema = 1\n[[hold]]\nmanager = "pip"\npackage = "x"\nreason = "x"\nlatest = "1"\nlatest_below = "2"',
        'schema = 1\n[[hold]]\nmanager = "fake"\npackage = "x"\nreason = "x"\nlatest = "1"',
        'schema = 1\n[[hold]]\nmanager = "pip"\npackage = "x"\nreason = "x"\nlatest_below = "bad version"',
        'schema = 1\n[[advisory]]\nmanager = "pip"\npackage = "x"\nreason = "x"\nversion = "1"\nids = []',
        'schema = 1\n[[unchecked]]\nmanager = "pip"\npackage = "x"\nreason = "x"\ndeclared = "x"\nchecks = ["invalid"]',
    ]
    for text in bad:
        path.write_text(text)
        result = gd.load_dep_exceptions(tmp_path, [path])[0]
        assert result.error and not result.entries, text
    path.write_text('schema = 1\n[[unchecked]]\nmanager = "pip"\npackage = "x"\nreason = "x"\ndeclared = "x"\nexpires = 2099-01-01\n')
    result = gd.load_dep_exceptions(tmp_path, [path])[0]
    assert result.error is None
    assert result.entries[0].checks == ['outdated', 'vulnerability']
    assert result.entries[0].expires.isoformat() == '2099-01-01'


def test_pattern_component_boundaries_and_long_globstars():
    assert gd._path_pattern_matches('a/**/b', 'a/b/file')
    assert gd._path_pattern_matches('./a//b', 'a/b/file')
    assert not gd._path_pattern_matches('a/b', 'a/beta/file')
    assert not gd._path_pattern_matches('A/*', 'a/file')
    assert gd._path_pattern_matches('/'.join(['**'] * 2000 + ['end']), 'a/b/end/file')


def test_git_status_literal_names_and_walk_pruning(tmp_path):
    from test_default_branch import git
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    for directory in ('tracked\nname', ':(special)', 'ignored'):
        (repo / directory).mkdir()
        (repo / directory / '.gitfleet.toml').write_text('schema = 1')
    (repo / '.gitignore').write_text('ignored/\n')
    git(repo, 'add', '--', 'tracked\nname/.gitfleet.toml')
    (repo / '.hidden').mkdir()
    (repo / '.hidden' / '.gitfleet.toml').write_text('schema = 1')
    paths = []
    gd.detect_dep_files(repo, paths)
    results = {f.path: f.git for f in gd.load_dep_exceptions(repo, paths)}
    assert results == {'tracked\nname/.gitfleet.toml': 'tracked', ':(special)/.gitfleet.toml': 'untracked', 'ignored/.gitfleet.toml': 'ignored'}
    assert gd._git_file_statuses(tmp_path, ['x']) == {'x': 'unknown'}


def test_nested_exclusions_includes_and_scripts(tmp_path):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["**/skip*", "nested/package.json"]\nreason = "synthetic"\n')
    (repo / 'requirements.txt').write_text('-r skip.txt\n-r kept.txt\n')
    (repo / 'skip.txt').write_text('-r child.txt\nINVALID @@@@\n')
    (repo / 'kept.txt').write_text('synthetic-package==1\n')
    (repo / 'child.txt').write_text('synthetic-child==1\n')
    (repo / 'skip.py').write_text('# /// script\n# dependencies = []\n# ///\n# /// script\n# dependencies = []\n# ///\n')
    (repo / 'skip_plain.py').write_text('print("synthetic")\n')
    (repo / 'nested').mkdir()
    (repo / 'nested' / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["package.json"]\nreason = "synthetic nested"\n')
    (repo / 'nested' / 'package.json').write_text('{ invalid')
    manifests, files = [], []
    rows = gd.parse_deps_for_repo(repo, manifests, files)
    assert [row['name'] for row in rows] == ['synthetic-package']
    inventory = {m['path']: m for m in manifests}
    assert 'child.txt' not in inventory and 'skip_plain.py' not in inventory
    assert inventory['skip.txt']['excluded_by'] == '.gitfleet.toml'
    assert inventory['skip.py']['excluded_by'] == '.gitfleet.toml'
    assert inventory['nested/package.json']['excluded_by'] == 'nested/.gitfleet.toml'
    assert all(e.status == 'applied' for f in files for e in f.entries)


def test_distinct_escaped_paths_survive_rescan_and_api(tmp_path, monkeypatch):
    import asyncio
    import errno
    import json
    import os
    import aiosqlite
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    raw = os.fsdecode(b'bad-\xff')
    literal = r'bad-\udcff'
    try:
        os.mkdir(os.fsencode(repo) + b'/bad-\xff')
    except OSError as exc:
        if exc.errno != errno.EILSEQ:
            raise
        admitted = False
    else:
        admitted = True
    (repo / literal).mkdir()
    if admitted:
        for name in (raw, literal):
            (repo / name / '.gitfleet.toml').write_text('schema = 1')
            (repo / name / 'requirements.txt').write_text('synthetic-package==1\n')
        manifests, files = [], []
        rows = gd.parse_deps_for_repo(repo, manifests, files)
    else:
        files = [gd.DepExceptionFile(name + '/.gitfleet.toml', name, 'untracked') for name in (raw, literal)]
        manifests = [dict(path=name + '/requirements.txt', kind='requirements', dependencies=1, error=None) for name in (raw, literal)]
        rows = [dict(manager='pip', name='synthetic-package', source_path=name + '/requirements.txt') for name in (raw, literal)]
    monkeypatch.setattr(gd, 'analyze_repo_deps', lambda _: gd.DepAnalysis(rows, False, [], manifests, files))
    async def exercise():
        async with aiosqlite.connect(':memory:') as db:
            await db.executescript(gd._SCHEMA_SQL)
            await db.execute('INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)', ('synthetic', 'synthetic', str(repo), '2026-01-01'))
            for _ in range(2):
                await gd.run_dep_scan_for_repo(db, 'synthetic', str(repo))
            detail = await gd.get_repo_detail('synthetic', db)
            fleet = await gd.get_fleet(db)
            cursor = await db.execute('SELECT source_path FROM dependencies ORDER BY source_path')
            stored = [r[0] for r in await cursor.fetchall()]
            assert len(stored) == 2 and len(set(stored)) == 2
            assert {m['path'] for m in detail['working_state']['dep_manifests']} == set(stored)
            assert len({f['path'] for f in detail['working_state']['dep_exceptions']}) == 2
            assert detail['working_state']['exception_warning_count'] == 2
            assert fleet['repos'][0]['exception_warning_count'] == 2
            json.dumps(detail, ensure_ascii=False).encode('utf-8')
    asyncio.run(exercise())


def test_invalid_and_oversized_files_and_symlinks_are_inventoried_safely(tmp_path):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / 'large').mkdir()
    (repo / 'large' / '.gitfleet.toml').write_bytes(b'x' * (gd.MAX_DEP_FILE_SIZE + 1))
    (repo / 'bad').mkdir()
    (repo / 'bad' / '.gitfleet.toml').write_bytes(b'\xff')
    (repo / 'link').mkdir()
    (repo / 'link' / '.gitfleet.toml').symlink_to(repo / 'large' / '.gitfleet.toml')
    paths = []
    gd.detect_dep_files(repo, paths)
    files = gd.load_dep_exceptions(repo, paths)
    assert {f.path for f in files} == {'bad/.gitfleet.toml', 'large/.gitfleet.toml'}
    assert all(f.error and not f.entries for f in files)


def test_exclusion_expiry_partial_and_missing_tool_suppression(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["package.json", "missing", "package.json"]\nreason = "synthetic"\n[[exclude]]\npaths = ["requirements.txt"]\nreason = "expired"\nexpires = 2000-01-01\n')
    (repo / 'package.json').write_text('{invalid')
    monkeypatch.setattr(gd, 'TOOLS', {})
    analysis = gd.analyze_repo_deps(repo)
    assert analysis.missing_tools == []
    assert analysis.any_error is False
    first, second = analysis.exceptions[0].entries
    assert first.paths == ['package.json', 'missing']
    assert first.status == 'partial' and first.detail['unused'][0]['part'] == 'missing'
    assert second.status == 'expired'


def test_git_timeout_returns_unknown_batch(tmp_path, monkeypatch):
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('git', 30)
    monkeypatch.setattr(gd.subprocess, 'run', timeout)
    assert gd._git_file_statuses(tmp_path, ['one', 'two']) == {'one': 'unknown', 'two': 'unknown'}


def test_excluded_include_does_not_hide_independently_reached_child_or_boundary_error(tmp_path):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["skip.txt", "missing.txt"]\nreason = "synthetic"\n')
    (repo / 'requirements.txt').write_text('-r skip.txt\n-r requirements-child.txt\n-r missing.txt\n-r owned.py\n')
    (repo / 'skip.txt').write_text('-r requirements-child.txt\n')
    (repo / 'requirements-child.txt').write_text('synthetic-child==1\n')
    (repo / 'owned.py').write_text('synthetic-owner==1\n')
    manifests, files = [], []
    rows = gd.parse_deps_for_repo(repo, manifests, files)
    inventory = {m['path']: m for m in manifests}
    assert {r['name'] for r in rows} == {'synthetic-child', 'synthetic-owner'}
    assert inventory['missing.txt']['error'] and 'excluded_by' not in inventory['missing.txt']
    assert inventory['owned.py']['kind'] == 'requirements'
    assert files[0].entries[0].status == 'partial'


def test_invalid_exception_file_does_not_apply_partial_entries(tmp_path):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["package.json"]\nreason = "synthetic"\n[[exclude]]\npaths = []\nreason = "synthetic"\n')
    (repo / 'package.json').write_text('{invalid')
    inventory, files = [], []
    gd.parse_deps_for_repo(repo, inventory, files)
    assert files[0].error and files[0].entries == []
    assert inventory[0]['error'] and 'excluded_by' not in inventory[0]


def test_kept_script_is_read_once(tmp_path, monkeypatch):
    from pathlib import Path
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    script = repo / 'synthetic.py'
    script.write_text('# /// script\n# dependencies = ["synthetic-package==1"]\n# ///\n')
    original = Path.read_text
    reads = []
    def counted(path, *args, **kwargs):
        if path == script:
            reads.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', counted)
    assert gd.parse_deps_for_repo(repo)[0]['name'] == 'synthetic-package'
    assert len(reads) == 1


def test_recursive_toml_failure_does_not_prevent_neighbor_exclusion(tmp_path):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n' + '.'.join(['nested'] * 2000) + ' = 1\n')
    (repo / 'child').mkdir()
    (repo / 'child' / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["package.json"]\nreason = "synthetic"\n')
    (repo / 'child' / 'package.json').write_text('{invalid')
    manifests, files = [], []
    gd.parse_deps_for_repo(repo, manifests, files)
    assert next(f for f in files if f.path == '.gitfleet.toml').error
    assert next(f for f in files if f.path.startswith('child/')).entries[0].status == 'applied'
    assert manifests[0]['excluded_by'] == 'child/.gitfleet.toml'


def test_parser_only_sources_do_not_consume_pattern_or_exclude_outside(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["**/outside.py"]\nreason = "synthetic"\n')
    (repo / 'package.json').write_text('{}')
    outside = tmp_path / 'outside.py'
    monkeypatch.setattr(gd, 'parse_package_json', lambda _: [
        dict(name='synthetic-inside', manager='npm', source_file=repo / 'synthetic' / 'outside.py'),
        dict(name='synthetic-outside', manager='npm', source_file=outside),
    ])
    files = []
    rows = gd.parse_deps_for_repo(repo, exceptions_out=files)
    assert [row['name'] for row in rows] == ['synthetic-outside']
    assert files[0].entries[0].status == 'stale'


def test_expiration_uses_one_date_and_has_no_misleading_no_match(tmp_path, monkeypatch):
    from datetime import date
    calls = []
    def changing_date():
        calls.append(None)
        return date(2026, 1, 1) if len(calls) == 1 else date(2026, 1, 2)
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["package.json"]\nreason = "synthetic"\nexpires = 2026-01-01\n[[exclude]]\npaths = ["missing"]\nreason = "expired"\nexpires = 2025-01-01\n')
    (repo / 'package.json').write_text('{}')
    monkeypatch.setattr(gd, '_dep_scan_date', changing_date, raising=False)
    files = []
    gd.parse_deps_for_repo(repo, exceptions_out=files)
    assert files[0].entries[0].status == 'applied'
    assert files[0].entries[1].status == 'expired'
    assert not files[0].entries[1].detail['unused']
    assert len(calls) == 1


def test_unreadable_exception_and_prelude_failure_do_not_consume(tmp_path, monkeypatch):
    from pathlib import Path
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    config = repo / '.gitfleet.toml'
    config.write_text('schema = 1\n[[exclude]]\npaths = ["broken.py", "plain.py"]\nreason = "synthetic"\n')
    broken = repo / 'broken.py'
    broken.write_text('# synthetic\n')
    (repo / 'plain.py').write_text('print("synthetic")\n')
    original_read = Path.read_text
    def fail_read(path, *args, **kwargs):
        if path == broken:
            raise PermissionError('synthetic prelude failure')
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', fail_read)
    manifests, files = [], []
    gd.parse_deps_for_repo(repo, manifests, files)
    assert manifests[0]['error'] == 'synthetic prelude failure'
    assert files[0].entries[0].status == 'stale'
    assert {u['part'] for u in files[0].entries[0].detail['unused']} == {'broken.py', 'plain.py'}
    original_open = Path.open
    def fail_open(path, *args, **kwargs):
        if path == config:
            raise PermissionError('synthetic config failure')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_open)
    result = gd.load_dep_exceptions(repo, [config])[0]
    assert result.error == 'synthetic config failure' and not result.entries


def test_excluded_script_named_include_keeps_requirements_ownership(tmp_path):
    repo = tmp_path / 'repo'
    make_repo(repo, 'main')
    (repo / '.gitfleet.toml').write_text('schema = 1\n[[exclude]]\npaths = ["owned.py"]\nreason = "synthetic"\n')
    (repo / 'requirements.txt').write_text('-r owned.py\n')
    (repo / 'owned.py').write_text('# /// script\n# dependencies = ["synthetic-package==1"]\n# ///\n')
    manifests, files = [], []
    assert gd.parse_deps_for_repo(repo, manifests, files) == []
    owned = next(m for m in manifests if m['path'] == 'owned.py')
    assert owned['kind'] == 'requirements' and owned['excluded_by'] == '.gitfleet.toml'
    assert files[0].entries[0].status == 'applied'
