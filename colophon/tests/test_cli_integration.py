"""End-to-end compilation, failure recovery and concurrent synthetic runs."""
import concurrent.futures
import http.server
import json
import os
import re
import stat
import threading
import time

import pytest

from catalogs import catalog, model
from fixturegen import CodexHome
from test_payload import NOW, entry, extract


def log(root, identifier='synthetic-root', **meta):
    return CodexHome(root).log(identifier).meta(**meta).task_started().turn_context(model='gpt-5.4').user_item().usage_record(usage={'input_tokens':100,'output_tokens':10}).task_complete()


def args(c, root, *flags):
    return c.build_arg_parser().parse_args(['--offline','--no-open','--codex-home',str(root),*flags])


def compiled(home):
    return extract((home/'colophon.html').read_bytes())


def cache_bytes(home):
    return {p.name:p.read_bytes() for p in (home/'cache').iterdir()}


def test_cli_empty_private_files_and_summary(run_cli, home, codex_home, tmp_path):
    output = tmp_path/'synthetic-output'/'page.html'
    r = run_cli('--offline','--no-open','--output',str(output),home=home,codex_home=codex_home)
    assert r.returncode == 0, r.stderr
    assert extract(output.read_bytes())['sessions'] == []
    assert re.fullmatch(r'colophon: 0 sessions · 0 subagents · 0 logs \(0 parsed, 0 cached\) · 0 tokens · \$0\.00 est\. · page [0-9.]+ MB → .+\n',r.stdout)
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    for path in [output,*home.rglob('*')]:
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    assert {p.name for p in home.iterdir()} >= {'price-history.json','workspaces.example.json','priority-turns.json','cache'}


def test_growth_cache_hit_rebuild_and_page_size(colophon, run_cli, home, codex_home, monkeypatch):
    builder = log(codex_home)
    builder.write()
    r = run_cli('--offline','--no-open',home=home,codex_home=codex_home)
    assert r.returncode == 0, r.stderr
    assert compiled(home)['sessions'][0]['own_usage']['input'] == 100
    r = run_cli('--offline','--no-open',home=home,codex_home=codex_home)
    assert '(0 parsed, 1 cached)' in r.stdout
    builder.task_started('synthetic-turn-2').turn_context().usage_record(usage={'input_tokens':200}).task_complete().write()
    r = run_cli('--offline','--no-open','--rebuild',home=home,codex_home=codex_home)
    assert r.returncode == 0, r.stderr
    assert compiled(home)['sessions'][0]['own_usage']['input'] == 300
    assert '(1 parsed, 0 cached)' in r.stdout
    monkeypatch.setattr(colophon,'PAGE_SIZE_WARN_BYTES',100)
    assert colophon.run(args(colophon,codex_home),now_ms=NOW,stderr_tty=False) == 0
    p = compiled(home)
    assert p['diagnostics']['page_size_bytes'] == (home/'colophon.html').stat().st_size
    assert p['diagnostics']['page_size_over_limit'] is True


@pytest.mark.parametrize('rebuild',[False,True])
def test_page_failure_preserves_cache_and_page(colophon, home, codex_home, monkeypatch, capsys, rebuild):
    log(codex_home).write()
    assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 0
    old_cache, old_page = cache_bytes(home),(home/'colophon.html').read_bytes()
    log(codex_home,'synthetic-new').write()
    replace = colophon.os.replace
    def fail(source,dest):
        if dest == home/'colophon.html':
            raise OSError('Synthetic page failure')
        return replace(source,dest)
    monkeypatch.setattr(colophon.os,'replace',fail)
    assert colophon.run(args(colophon,codex_home,*(['--rebuild'] if rebuild else [])),now_ms=NOW) == 1
    assert cache_bytes(home) == old_cache
    assert (home/'colophon.html').read_bytes() == old_page
    assert not list(home.glob('.*.tmp'))
    assert not list(home.glob('cache.rebuild-*'))
    assert 'cannot write' in capsys.readouterr().err


def test_interrupt_rebuild_from_progress_preserves_cache(colophon, home, codex_home, monkeypatch, capsys):
    log(codex_home).write()
    assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 0
    old = cache_bytes(home)
    original = colophon.scan_logs
    def scan(root,cache,*,progress):
        def interrupt(done,total):
            progress(done,total)
            raise KeyboardInterrupt
        return original(root,cache,progress=interrupt)
    monkeypatch.setattr(colophon,'scan_logs',scan)
    assert colophon.run(args(colophon,codex_home,'--rebuild'),now_ms=NOW,stderr_tty=True) == 1
    assert cache_bytes(home) == old
    assert 'colophon: interrupted; rebuild did not complete; previous cache kept' in capsys.readouterr().err


@pytest.mark.parametrize('failure',[False,True])
def test_browser_failure_is_success(colophon, home, codex_home, monkeypatch, capsys, failure):
    def opening(uri):
        assert uri == (home/'colophon.html').resolve().as_uri()
        if failure:
            raise OSError('Synthetic browser error')
        return False
    monkeypatch.setattr(colophon.webbrowser,'open',opening)
    a = args(colophon,codex_home)
    a.no_open = False
    assert colophon.run(a,now_ms=NOW) == 0
    assert f'colophon: open {home / "colophon.html"} in a browser' in capsys.readouterr().err


def test_error_diagnostics_and_invalid_ledger(colophon, run_cli, home, codex_home):
    builder = log(codex_home).unknown().raw(b'Synthetic malformed line\n')
    builder.raw(b'Synthetic glued fragment {"type":"synthetic_recovered","payload":{}}\n').write(partial_tail=b'{"synthetic":',mtime=time.time()-colophon.LIVE_QUIET_MS/1000-600)
    CodexHome(codex_home).log('synthetic-empty').write()
    (codex_home/'state_5.sqlite').write_bytes(b'Synthetic invalid SQLite')
    home.mkdir()
    ledger = {'schema':1,'entries':[dict(entry('gpt-synthetic-invalid',at='2030-01-01T00:00:00Z'),per_million={'input':-1})]}
    raw = json.dumps(ledger)
    (home/'price-history.json').write_text(raw)
    (home/'workspaces.json').write_text('{ Synthetic invalid aliases')
    r = run_cli('--offline','--no-open',home=home,codex_home=codex_home)
    assert r.returncode == 0, r.stderr
    p = compiled(home)
    d = p['diagnostics']
    assert d['malformed_lines']['total'] == 1
    assert d['recovered_lines']['total'] == 1
    assert d['truncated_lines']['total'] == 1
    assert d['unknown_record_types']['synthetic_unknown'] == 1
    assert any(f['reason']=='empty' for f in d['skipped_files'])
    assert d['metadata_errors']
    assert d['workspaces_file'] and 'line 1' in r.stderr
    assert 'price-history.json' in r.stderr and 'entry 0' in r.stderr
    assert (home/'price-history.json').read_text() == raw
    assert p['meta']['costs']['available'] is False
    assert p['sessions'][0]['own_usage']['input'] == 100
    assert p['sessions'][0]['own_usage']['cost_usd'] is None


def test_orphan_db_thread_unpriced_history_and_priority(colophon, run_cli, home, codex_home):
    ch = CodexHome(codex_home)
    builder = log(codex_home,parent_thread_id='synthetic-missing-parent')
    builder.turn_context(model='gpt-synthetic-unpriced').usage_record(usage={'input_tokens':50},response_id='synthetic-distinct-response').write()
    ch.state_db([{'id':'synthetic-no-log','title':'Synthetic DB title'}])
    ch.trace_db([ch.priority_request_row('synthetic-turn-1',thread_id='synthetic-root',model='gpt-synthetic-unpriced',ts=1)])
    home.mkdir()
    (home/'price-history.json').write_text(json.dumps({'schema':1,'entries':[entry('gpt-5.4',at='2029-01-01T00:00:00Z')]}))
    r = run_cli('--offline','--no-open',home=home,codex_home=codex_home)
    assert r.returncode == 0, r.stderr
    p = compiled(home)
    assert p['sessions'][0]['kind'] == 'orphan'
    assert p['diagnostics']['db_threads_without_logs'] == 1
    assert p['diagnostics']['unpriced_models'] == [{'model':'gpt-synthetic-unpriced','tokens':50}]
    assert p['diagnostics']['priority_without_multiplier'] == [{'model':'gpt-5.4','input_tokens':100}]


@pytest.mark.parametrize('corrupt',['format','entry','missing_format'])
def test_corrupt_cache_reparsed(run_cli, home, codex_home, corrupt):
    log(codex_home).write()
    assert run_cli('--offline','--no-open',home=home,codex_home=codex_home).returncode == 0
    path = home/'cache'/'FORMAT' if corrupt in ('format','missing_format') else next((home/'cache').glob('*.json'))
    if corrupt=='missing_format':
        path.unlink()
    else:
        path.write_text('Synthetic corrupt cache')
    r = run_cli('--offline','--no-open',home=home,codex_home=codex_home)
    assert r.returncode == 0, r.stderr
    assert '(1 parsed, 0 cached)' in r.stdout


def test_two_concurrent_runs_parse_final_page(run_cli, home, codex_home):
    log(codex_home).write()
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(run_cli,'--offline','--no-open',home=home,codex_home=codex_home) for _ in range(2)]
        for future in futures:
            result = future.result()
            assert result.returncode == 0, result.stderr
    assert compiled(home)['sessions'][0]['own_usage']['input'] == 100


@pytest.fixture
def server():
    state = {'status':200,'rate':2,'requests':[]}
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state['requests'].append(dict(self.headers))
            body = json.dumps(catalog({'gpt-synthetic-1':model(input=state['rate'],output=7)})).encode() if state['status']==200 else b''
            self.send_response(state['status'])
            self.send_header('ETag','"synthetic-etag"')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self,*a):
            pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=srv.serve_forever,daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{srv.server_port}/synthetic.json',state
    srv.shutdown()
    srv.server_close()
    thread.join()


def test_offline_no_network_even_with_local_url(run_cli, home, codex_home, server):
    url,state = server
    r = run_cli('--offline','--no-open',home=home,codex_home=codex_home,env={'COLOPHON_PRICING_URL':url})
    assert r.returncode == 0, r.stderr
    assert state['requests'] == []


@pytest.mark.parametrize('mode',['fetched','not_modified','cached','offline'])
def test_catalog_status_recording_fetch_date_and_idempotence(colophon, home, codex_home, monkeypatch, server, mode):
    url,state = server
    monkeypatch.setenv('COLOPHON_PRICING_URL',url)
    colophon.ensure_runtime_home(home)
    fetch_at = NOW-100_000
    if mode!='fetched':
        colophon.atomic_write_json(home/'pricing-cache.json',{'schema':1,'url':url,'etag':'"synthetic-etag"','fetched_at_ms':fetch_at,'catalog':catalog()})
        state['status'] = 304 if mode=='not_modified' else 500
    a = args(colophon,codex_home)
    a.offline = mode=='offline'
    assert colophon.run(a,now_ms=NOW) == 0
    p = compiled(home)
    assert p['meta']['catalog']['status'] == mode
    entries = json.loads((home/'price-history.json').read_text())['entries']
    expected = NOW if mode=='fetched' else fetch_at
    assert entries and all(e['effective_from']==colophon.format_rfc3339(expected) for e in entries)
    before = (home/'price-history.json').read_bytes()
    assert colophon.run(a,now_ms=NOW+1000) == 0
    assert (home/'price-history.json').read_bytes() == before


def test_refresh_rebuild_and_preservation_of_earlier_ledger(colophon, run_cli, home, codex_home, monkeypatch, server):
    url,state = server
    monkeypatch.setenv('COLOPHON_PRICING_URL',url)
    for n in range(3):
        a = args(colophon,codex_home,'--rebuild')
        a.offline = False
        a.refresh_prices = True
        state['rate'] = 2+n
        prior = json.loads((home/'price-history.json').read_text())['entries'] if n else []
        assert colophon.run(a,now_ms=NOW+1000*n) == 0
        entries = json.loads((home/'price-history.json').read_text())['entries']
        assert entries[:len(prior)] == prior
        assert len(entries) == n+1
        assert 'If-None-Match' not in state['requests'][-1]
    r = run_cli('--refresh-prices','--rebuild','--no-open',home=home,codex_home=codex_home,env={'COLOPHON_PRICING_URL':url})
    assert r.returncode == 0, r.stderr
    assert 'If-None-Match' not in state['requests'][-1]


def test_ledger_changed_warning_transient_and_pricing_before_accounting(colophon, home, codex_home, monkeypatch, server, capsys):
    url,state = server
    monkeypatch.setenv('COLOPHON_PRICING_URL',url)
    builder = log(codex_home)
    builder.turn_context(model='gpt-synthetic-1').usage_record(usage={'input_tokens':50}).write()
    original_append = colophon.append_user_ledger
    def changed(path,new,mtime):
        os.utime(path,ns=(mtime+1,mtime+1))
        return original_append(path,new,mtime)
    monkeypatch.setattr(colophon,'append_user_ledger',changed)
    a = args(colophon,codex_home)
    a.offline = False
    assert colophon.run(a,now_ms=NOW) == 0
    p = compiled(home)
    assert p['diagnostics']['unrecorded_catalog_rates'] == ['gpt-synthetic-1']
    assert 'changed during the run' in capsys.readouterr().err
    assert json.loads((home/'price-history.json').read_text())['entries'] == []
    assert p['sessions'][0]['own_usage']['input'] == 150
    assert p['sessions'][0]['own_usage']['cost_usd'] is not None


def test_unreadable_log_and_locked_metadata_fallback(colophon, home, codex_home, monkeypatch):
    builder = log(codex_home)
    path = builder.write()
    blocked = CodexHome(codex_home).log('synthetic-unreadable').meta().task_started().write()
    ch = CodexHome(codex_home)
    dbpath = ch.state_db([{'id':'synthetic-root','title':'Synthetic unavailable DB title'}])
    import sqlite3
    db = sqlite3.connect(dbpath)
    db.execute('BEGIN EXCLUSIVE')
    original = colophon.parse_log_file
    def parse(path,**kw):
        if path.name==blocked.name:
            raise PermissionError('Synthetic unreadable log')
        return original(path,**kw)
    monkeypatch.setattr(colophon,'parse_log_file',parse)
    try:
        assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 0
    finally:
        db.rollback()
        db.close()
    p = compiled(home)
    assert p['diagnostics']['skipped_files'] == [{'path':colophon.codex_path_key(blocked),'reason':'unreadable'}]
    assert p['diagnostics']['metadata_errors']
    assert p['sessions'][0]['title_source'] == 'first_user_message'
    assert p['sessions'][0]['title_full'] == 'Synthetic request 1'


def test_history_begins_and_unresolved_fork(colophon, home, codex_home):
    builder = log(codex_home,'synthetic-history')
    builder.turn_context(model='gpt-synthetic-history').usage_record(usage={'input_tokens':30}).write()
    fork = CodexHome(codex_home).log('synthetic-unresolved').meta(forked_from_id='synthetic-missing',history_base_thread_id='synthetic-missing',history_start_ordinal=99)
    fork.user_response().write()
    home.mkdir()
    colophon.atomic_write_json(home/'price-history.json',{'schema':1,'entries':[entry('gpt-synthetic-history',at='2031-01-01T00:00:00Z')]})
    assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 0
    p = compiled(home)
    assert p['diagnostics']['history_begins'] == [{'model':'gpt-synthetic-history','from_ms':colophon.parse_rfc3339_ms('2031-01-01T00:00:00Z')}]
    assert p['diagnostics']['unresolved_history_boundaries'] == ['synthetic-unresolved']
    row = next(row for row in p['sessions'] if row['id']=='synthetic-unresolved')
    assert row['turns'] == []


def test_catalog_thread_join_fallback_bounded_and_started_before_scan(colophon, home, codex_home, monkeypatch):
    release,entered = threading.Event(),threading.Event()
    budgets = []
    original_thread = threading.Thread
    class BudgetThread(original_thread):
        def join(self,timeout=None):
            budgets.append(timeout)
            return super().join(0)
    monkeypatch.setattr(colophon.threading,'Thread',BudgetThread)
    original_fetch = colophon.fetch_catalog
    def fetch(url,path,**kw):
        if not kw['offline']:
            entered.set()
            release.wait(2)
        return original_fetch(url,path,**dict(kw,offline=True))
    original_scan = colophon.scan_logs
    def scan(root,cache,**kw):
        assert entered.wait(1), 'Catalog daemon must start before scanning'
        return original_scan(root,cache,**kw)
    monkeypatch.setattr(colophon,'fetch_catalog',fetch)
    monkeypatch.setattr(colophon,'scan_logs',scan)
    monkeypatch.setattr(colophon,'CONNECT_TIMEOUT_S',0)
    monkeypatch.setattr(colophon,'BODY_TIMEOUT_S',0)
    a = args(colophon,codex_home)
    a.offline = False
    try:
        assert colophon.run(a,now_ms=NOW) == 0
        assert budgets == [5]
        assert 'did not finish' in compiled(home)['diagnostics']['catalog'][-1]
    finally:
        release.set()


def test_interrupt_after_rebuild_commit_reports_installed(colophon, home, codex_home, monkeypatch, capsys):
    log(codex_home).write()
    assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 0
    original = colophon.ParseCache.commit
    def commit(cache,paths):
        original(cache,paths)
        raise KeyboardInterrupt
    monkeypatch.setattr(colophon.ParseCache,'commit',commit)
    assert colophon.run(args(colophon,codex_home,'--rebuild'),now_ms=NOW) == 1
    error = capsys.readouterr().err
    assert 'interrupted; rebuild cache installed' in error
    assert 'previous cache kept' not in error


def test_original_error_survives_abort_failure(colophon, home, codex_home, monkeypatch, capsys):
    def fail(*a,**kw):
        raise ValueError('Synthetic original failure\nsecond line')
    def abort(cache):
        raise OSError('Synthetic cleanup failure')
    monkeypatch.setattr(colophon,'build_corpus',fail)
    monkeypatch.setattr(colophon.ParseCache,'abort',abort)
    assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 1
    assert capsys.readouterr().err == 'colophon: ValueError: Synthetic original failure second line\n'


def test_unknown_time_cli_null_bucket_and_visible_diagnostic(colophon, home, codex_home, capsys):
    builder = log(codex_home)
    # Root wrapper clock is genuinely absent, not a fabricated zero epoch.
    builder.raw(json.dumps({'type':'token_usage_record','timestamp':None,'payload':{
        'thread_id':'synthetic-root','turn_id':'synthetic-turn-1','response_id':'synthetic-untimed-response',
        'usage':{'input_tokens':30,'output_tokens':0}}}).encode()+b'\n')
    builder.write()
    assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 0
    p = compiled(home)
    assert p['diagnostics']['untimed_usage'] == [{'model':'gpt-5.4','tokens':30}]
    assert any(b[0] is None and b[3]==30 for b in p['sessions'][0]['buckets'])
    assert 'priced at current rates: usage has no timestamp (30 tokens)' in capsys.readouterr().err


def test_missing_cache_marker_is_not_published_before_untrusted_entries_replace(colophon,home,codex_home):
    log(codex_home).write()
    assert colophon.run(args(colophon,codex_home),now_ms=NOW) == 0
    (home/'cache'/'FORMAT').unlink()
    first = colophon.ParseCache.open(home,rebuild=False)
    try:
        second = colophon.ParseCache.open(home,rebuild=False)
        try:
            assert second.get(colophon.discover_logs(codex_home)[0]) is None
        finally:
            second.abort()
    finally:
        first.abort()
