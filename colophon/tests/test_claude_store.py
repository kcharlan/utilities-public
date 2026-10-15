"""Synthetic Claude cache/store lifecycle acceptance."""
import json
import pytest
from helpers import NativeRun


def test_claude_cache_disappearance_and_restore(tmp_path):
    run = NativeRun(tmp_path)
    path = run.claude_session()
    original = path.read_bytes()
    assert run.build().returncode == 0
    first = run.payload()
    assert first["meta"]["sources"]["claude"]["parsed"] == 1
    assert run.build().returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["cached"] == 1
    path.unlink()
    assert run.build().returncode == 0
    deleted = run.payload()
    assert "transcript_deleted" in deleted["sessions"][0]["flags"]
    assert deleted["meta"]["sources"]["claude"]["retained"] == 1
    assert run.build("--rebuild").returncode == 0
    assert "transcript_deleted" in run.payload()["sessions"][0]["flags"]
    path.write_bytes(original)
    assert run.build().returncode == 0
    assert "transcript_deleted" not in run.payload()["sessions"][0]["flags"]
    assert not list((run.runtime / "claude-retained").rglob("*.rec"))
    assert path.read_bytes() == original


def store_records(run, kind):
    return sorted(p for p in (run.runtime / kind).rglob("*.rec") if p.is_file())


def test_claude_empty_corrupt_cache_and_private_modes(tmp_path):
    run = NativeRun(tmp_path)
    path = run.claude_session()
    source = path.read_bytes()
    assert run.build().returncode == 0
    records = store_records(run, "cache-claude")
    assert len(records) == 1
    records[0].write_bytes(b"conspicuously synthetic corruption")
    assert run.build().returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["parsed"] == 1
    assert path.read_bytes() == source
    for item in [run.runtime / "cache-claude", records[0].parent]:
        assert item.stat().st_mode & 0o777 == 0o700
    assert records[0].stat().st_mode & 0o777 == 0o600
    path.write_bytes(b"")
    assert run.build().returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["retained"] == 0
    assert run.payload()["sessions"][0]["turns"] == []
    empty_bytes = records[0].read_bytes()
    path.unlink()
    assert run.build().returncode == 0
    assert store_records(run, "claude-retained")[0].read_bytes() == empty_bytes


def test_claude_retained_only_excluded_disabled_and_corruption(tmp_path):
    import shutil
    run = NativeRun(tmp_path)
    path = run.claude_session()
    assert run.build().returncode == 0
    installed = store_records(run, "cache-claude")[0]
    installed_bytes = installed.read_bytes()
    path.unlink()
    custom = run.home / "synthetic-other-config"
    assert run.build("--claude-home", str(custom)).returncode == 0
    assert installed.read_bytes() == installed_bytes
    assert not store_records(run, "claude-retained")
    assert run.build("--no-claude", "--rebuild").returncode == 0
    assert installed.read_bytes() == installed_bytes
    shutil.rmtree(run.home / ".claude")
    run.codex.rmdir()
    assert run.build().returncode == 0  # provisional candidate establishes presence
    retained = store_records(run, "claude-retained")[0]
    assert retained.read_bytes() == installed_bytes
    assert run.build("--claude-home", str(custom), "--rebuild").returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["retained"] == 1
    retained.write_bytes(b"synthetic retained corruption; preserve exactly")
    damaged = retained.read_bytes()
    run.codex.mkdir()
    assert run.build().returncode == 0
    assert str(retained) in run.payload()["diagnostics"]["claude_retained_unreadable"]
    assert retained.read_bytes() == damaged


def test_claude_failed_page_keeps_missing_record_installed(tmp_path):
    run = NativeRun(tmp_path)
    path = run.claude_session()
    assert run.build().returncode == 0
    installed = store_records(run, "cache-claude")[0]
    before = installed.read_bytes()
    path.unlink()
    (tmp_path / "synthetic-output-blocked").write_bytes(b"synthetic file blocks directory")
    failure = run.build("--rebuild", "--output", str(tmp_path / "synthetic-output-blocked/output.html"))
    assert failure.returncode == 1
    assert installed.read_bytes() == before
    assert not store_records(run, "claude-retained")
    assert run.build("--rebuild").returncode == 0
    assert store_records(run, "claude-retained")[0].read_bytes() == before


def test_claude_removed_locator_swap_and_nested_projects(tmp_path):
    import shutil
    run = NativeRun(tmp_path)
    directories = [run.home / ".claude/projects/synthetic/nested",
                   run.home / "Library/Application Support/Claude/local-agent-mode-sessions/synthetic-session/.claude/projects/synthetic",
                   run.home / ".claude-swap-backup/sessions/1-synthetic/projects/synthetic"]
    for i, directory in enumerate(directories):
        run.claude_session(name=f"synthetic-removal-{i}", directory=directory)
    assert run.build().returncode == 0
    saved = {p.name: p.read_bytes() for p in store_records(run, "cache-claude")}
    shutil.rmtree(run.home / ".claude/projects")
    shutil.rmtree(run.home / "Library/Application Support/Claude/local-agent-mode-sessions")
    shutil.rmtree(run.home / ".claude-swap-backup/sessions")
    assert run.build("--rebuild").returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["retained"] == 3
    assert {p.name: p.read_bytes() for p in store_records(run, "claude-retained")} == saved


def test_claude_unreadable_descendant_and_path_error_preserve_cache(tmp_path):
    run = NativeRun(tmp_path)
    path = run.claude_session()
    assert run.build().returncode == 0
    record = store_records(run, "cache-claude")[0]
    before = record.read_bytes()
    path.unlink()
    path.parent.chmod(0)
    try:
        assert run.build("--rebuild").returncode == 0
        assert run.payload()["diagnostics"]["skipped_files"]
        assert record.read_bytes() == before
        assert not store_records(run, "claude-retained")
    finally:
        path.parent.chmod(0o700)
    path.parent.rmdir()
    path.parent.write_bytes(b"synthetic non-directory ancestor")
    assert run.build("--rebuild").returncode == 0
    assert record.read_bytes() == before
    assert not store_records(run, "claude-retained")


def accounting_rows():
    return [{"type": "user", "sessionId": " synthetic-price-alias ",
             "timestamp": "2001-01-01T00:00:00Z", "cwd": "/synthetic/prices",
             "message": {"content": "Synthetic accounting request"}},
            {"type": "assistant", "sessionId": " synthetic-price-alias ",
             "requestId": "synthetic-request", "timestamp": "2001-01-01T00:00:01Z",
             "message": {"id": "synthetic-response", "model": "google/synthetic-store-model",
                         "usage": {"input_tokens": 17, "output_tokens": 3},
                         "stop_reason": "end_turn", "content": "Synthetic accounting answer"}}]


def compact(path):
    import json
    path.write_text("".join(json.dumps(json.loads(line), separators=(",", ":")) + "\n"
                            for line in path.read_text().splitlines()))


def test_claude_price_snapshots_retained_live_dedupe_and_aliases(tmp_path):
    import json
    import pytest
    run = NativeRun(tmp_path)
    run.runtime.mkdir()
    catalog_path = run.runtime / "pricing-cache.json"
    def catalog(models):
        catalog_path.write_text(json.dumps({"schema": 1, "url": run.env["COLOPHON_PRICING_URL"],
                                           "fetched_at_ms": 1, "catalog": {
                                               "openai": {"models": {}}, "google": {"models": models}}}))
    catalog({"synthetic-store-model": {"id": "synthetic-store-model", "cost": {"input": 11, "output": 13}}})
    path = run.claude_session(rows=accounting_rows())
    compact(path)
    source = path.read_bytes()
    assert run.build().returncode == 0
    first = run.payload()["sessions"][0]["own_usage"]
    assert first["input"] == 17 and first["output"] == 3
    assert first["cost_usd"] == pytest.approx((17 * 11 + 3 * 13) / 1e6)
    catalog({})
    assert run.build().returncode == 0
    assert run.payload()["sessions"][0]["own_usage"]["cost_usd"] == first["cost_usd"]
    path.unlink()
    assert run.build("--rebuild").returncode == 0
    assert run.payload()["sessions"][0]["own_usage"]["cost_usd"] == first["cost_usd"]
    copy = run.claude_session("synthetic-resumed-copy", rows=accounting_rows())
    compact(copy)
    assert run.build().returncode == 0
    payload = run.payload()
    assert sum(s["own_usage"]["input"] for s in payload["sessions"]) == 17
    assert payload["diagnostics"]["claude_duplicate_responses"] == {"key_count": 1, "row_count": 1}
    assert path.exists() is False
    assert source


def test_claude_sidecar_refreshes_on_cache_hit_and_retains_last_known(tmp_path):
    import json
    run = NativeRun(tmp_path)
    parent = run.claude_session("synthetic-parent")
    child = run.claude_session("agent-synthetic-child", directory=parent.parent / "synthetic-parent/subagents")
    sidecar = child.with_suffix(".meta.json")
    sidecar.write_text(json.dumps({"description": "Synthetic first", "agentType": "synthetic-first-type", "spawnDepth": 3}))
    assert run.build().returncode == 0
    sidecar.write_text(json.dumps({"description": "Synthetic refreshed", "agentType": "synthetic-refreshed-type", "spawnDepth": 5}))
    assert run.build().returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["cached"] == 2
    agent = run.payload()["subagents"]["synthetic-parent/agent-synthetic-child"]
    assert agent["label"] == "Synthetic refreshed"
    assert agent["depth"] == 5
    child.unlink()
    sidecar.write_text(json.dumps({"description": "Synthetic after deletion", "spawnDepth": 9}))
    assert run.build("--rebuild").returncode == 0
    agent = run.payload()["subagents"]["synthetic-parent/agent-synthetic-child"]
    assert agent["label"] == "Synthetic refreshed"
    assert agent["depth"] == 5
    assert "transcript_deleted" in agent["flags"]


def test_claude_unreadable_retained_stays_in_place(tmp_path):
    run = NativeRun(tmp_path)
    path = run.claude_session()
    assert run.build().returncode == 0
    path.unlink()
    assert run.build().returncode == 0
    record = store_records(run, "claude-retained")[0]
    before = record.read_bytes()
    record.chmod(0)
    try:
        assert run.build("--rebuild").returncode == 0
        assert str(record) in run.payload()["diagnostics"]["claude_retained_unreadable"]
        assert record.stat().st_mode & 0o777 == 0
    finally:
        record.chmod(0o600)
    assert record.read_bytes() == before


def test_claude_fingerprint_detects_same_size_same_mtime_change(tmp_path):
    import os
    run = NativeRun(tmp_path)
    path = run.claude_session()
    assert run.build().returncode == 0
    stamp = path.stat()
    before = path.read_bytes()
    after = before.replace(b"kite", b"ship")
    assert len(before) == len(after)
    path.write_bytes(after)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert run.build().returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["parsed"] == 1
    assert "ship" in run.payload()["sessions"][0]["title"]
    assert path.read_bytes() == after


def test_claude_removed_locator_session_and_swap_slot_keep_root_provenance(tmp_path):
    import hashlib
    import shutil
    for kind in ["project", "locator-session", "swap-slot"]:
        case = tmp_path / kind
        case.mkdir()
        run = NativeRun(case)
        if kind == "project":
            anchor = run.home / ".claude/projects"
            removed = anchor / "synthetic-project"
            directory = removed / "synthetic-nested"
        elif kind == "locator-session":
            anchor = run.home / "Library/Application Support/Claude/local-agent-mode-sessions"
            removed = anchor / "synthetic-session"
            directory = removed / ".claude/projects/synthetic-project"
        else:
            anchor = run.home / ".claude-swap-backup/sessions"
            removed = anchor / "1-synthetic-slot"
            directory = removed / "projects/synthetic-project"
        run.claude_session(directory=directory)
        assert run.build().returncode == 0
        expected = hashlib.sha256(str(anchor.resolve()).encode()).hexdigest()
        before = store_records(run, "cache-claude")[0].read_bytes()
        shutil.rmtree(removed)
        assert anchor.is_dir()
        assert run.build("--rebuild").returncode == 0
        retained, = store_records(run, "claude-retained")
        assert retained.parent.name == expected
        assert retained.read_bytes() == before
        assert run.payload()["meta"]["sources"]["claude"]["retained"] == 1


def test_claude_malformed_existing_file_is_live_not_deleted(tmp_path):
    run = NativeRun(tmp_path)
    path = run.claude_session()
    assert run.build().returncode == 0
    bad = b"conspicuously synthetic malformed transcript\n"
    path.write_bytes(bad)
    assert run.build("--rebuild").returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["retained"] == 0
    assert run.payload()["diagnostics"]["malformed_lines"]["total"] == 1
    assert run.payload()["sessions"][0]["turns"] == []
    assert path.read_bytes() == bad


def test_claude_unreadable_live_file_does_not_replay_or_destroy_unowned_cache_hit(tmp_path):
    run = NativeRun(tmp_path)
    path = run.claude_session()
    assert run.build().returncode == 0
    cached = store_records(run, "cache-claude")[0]
    before = cached.read_bytes()
    path.chmod(0)
    try:
        result = run.build()
        assert result.returncode == 0, result.stderr
        assert run.payload()["meta"]["sources"]["claude"]["retained"] == 0
        assert run.payload()["diagnostics"]["skipped_files"]
        assert run.payload()["sessions"] == []
        assert cached.read_bytes() == before
    finally:
        path.chmod(0o600)


def test_claude_valid_checksum_bad_map_cache_reparses_and_retained_diagnoses(tmp_path):
    import hashlib
    import json
    run = NativeRun(tmp_path)
    rows = [{"type": "user", "message": {"content": "Synthetic map request"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "synthetic-tool", "name": "mcp__syntheticbadmap__lookup"}]}}]
    source = run.claude_session(rows=rows)
    source_bytes = source.read_bytes()
    assert run.build().returncode == 0
    cached, = store_records(run, "cache-claude")
    def corrupt_map(path):
        header, _, body = path.read_bytes().split(b"\n", 2)
        value = json.loads(body)
        index = value.index("syntheticbadmap")
        value[index] = True
        changed = json.dumps(value, separators=(",", ":")).encode()
        damaged = header + b"\n" + hashlib.sha256(changed).hexdigest().encode() + b"\n" + changed
        path.write_bytes(damaged)
        return damaged
    corrupt_map(cached)
    assert run.build().returncode == 0
    assert run.payload()["meta"]["sources"]["claude"]["parsed"] == 1
    assert source.read_bytes() == source_bytes
    source.unlink()
    assert run.build().returncode == 0
    retained, = store_records(run, "claude-retained")
    damaged = corrupt_map(retained)
    assert run.build().returncode == 0
    assert str(retained) in run.payload()["diagnostics"]["claude_retained_unreadable"]
    assert retained.read_bytes() == damaged
def synthetic_rows():
    return [
        {'type': 'user', 'timestamp': '2026-01-02T12:00:00Z', 'cwd': '/synthetic/review-kite', 'sessionId': 'synthetic-review-session', 'message': {'content': 'First synthetic prompt'}},
        {'type': 'assistant', 'timestamp': '2026-01-02T12:00:01Z', 'requestId': 'synthetic-request-first', 'sessionId': 'synthetic-review-session', 'message': {'id': 'synthetic-message-first', 'model': 'claude-sonnet-4-5', 'content': [{'type': 'text', 'text': 'First synthetic answer'}], 'stop_reason': 'end_turn', 'usage': {'input_tokens': 10, 'output_tokens': 2}}},
        {'type': 'user', 'timestamp': '2026-01-02T12:01:00Z', 'cwd': '/synthetic/review-kite', 'sessionId': 'synthetic-review-session', 'message': {'content': 'Second synthetic prompt'}},
        {'type': 'assistant', 'timestamp': '2026-01-02T12:01:01Z', 'requestId': 'synthetic-request-second', 'sessionId': 'synthetic-review-session', 'message': {'id': 'synthetic-message-second', 'model': 'claude-sonnet-4-5', 'content': [{'type': 'text', 'text': 'Second synthetic answer'}], 'stop_reason': 'end_turn', 'usage': {'input_tokens': 20, 'output_tokens': 4}}},
    ]


def write(run, name, rows):
    source = run.home / '.claude/projects' / name / 'synthetic-review-session.jsonl'
    source.parent.mkdir(parents=True)
    source.write_text(''.join(json.dumps(r, separators=(',', ':'))+'\n' for r in rows))
    return source


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('retained', [False, True])
def test_same_stem_later_copy_preserves_new_turns(tmp_path, partial, retained):
    run = NativeRun(tmp_path)
    rows = synthetic_rows()
    old = write(run, 'a-old-copy', rows[:2])
    write(run, 'b-current-copy', rows[2:] if partial else rows)
    for step, args in enumerate([(), (), ('--rebuild',)]):
        if step == 1 and retained: old.unlink()
        result = run.build(*args)
        assert result.returncode == 0, result.stderr
        session, = run.payload()['sessions']
        assert session['own_usage']['input'] == 30
        assert len(session['turns']) == 2, session
        assert session['end_ms'] == 1767355261000
        assert session['outside_usage']['input'] == 0
        for turn, label, tokens in zip(session['turns'], ['First', 'Second'], [10, 20]):
            assert turn['requests'][0]['text'] == f'{label} synthetic prompt'
            assert turn['final_answer']['text'] == f'{label} synthetic answer'
            assert turn['usage']['input'] == tokens


def test_same_stem_uuid_identity_tools_answers_and_spawn(tmp_path):
    run = NativeRun(tmp_path)
    rows = synthetic_rows()
    rows[0]['uuid'] = 'synthetic-prompt-one'
    rows[2]['uuid'] = 'synthetic-prompt-two'
    # Identical text and clock must not merge conflicting UUIDs.
    rows[2]['timestamp'] = rows[0]['timestamp']
    rows[2]['message'] = rows[0]['message'].copy()
    mirrored = {'type': 'tool_use', 'id': 'synthetic-shared-tool', 'name': 'Bash'}
    first = {'type': 'tool_use', 'id': 'synthetic-first-tool', 'name': 'Bash'}
    second = {'type': 'tool_use', 'id': 'synthetic-second-tool', 'name': 'Bash'}
    rows[1]['message']['content'].extend([mirrored, first])
    write(run, 'a-old-copy', rows[:2])
    import copy
    later = copy.deepcopy(rows)
    later[1]['message']['content'] = [mirrored, second]
    later[1]['timestamp'] = '2026-01-02T12:00:02Z'
    later[1]['message']['usage']['input_tokens'] = 99
    write(run, 'b-current-copy', later)
    child = run.claude_session('agent-synthetic-child', directory=run.home / '.claude/projects/a-old-copy/synthetic-review-session/subagents')
    child.with_suffix('.meta.json').write_text(json.dumps({'toolUseId': 'synthetic-second-tool'}))
    for args in [(), (), ('--rebuild',)]:
        result = run.build(*args)
        assert result.returncode == 0, result.stderr
        session, = run.payload()['sessions']
        assert len(session['turns']) == 2
        assert session['turns'][0]['tools']['shell'] == 3
        assert session['turns'][0]['final_answer']['text'] == 'First synthetic answer'
        assert session['turns'][0]['end_ms'] == 1767355202000
        assert session['turns'][0]['usage']['input'] == 10  # D3 still prefers the earlier copy.
        agent = run.payload()['subagents']['synthetic-review-session/agent-synthetic-child']
        assert agent['spawn_turn'] == session['turns'][0]['id']


def test_same_stem_repeated_uuidless_prompts_keep_occurrences(tmp_path):
    run = NativeRun(tmp_path)
    rows = synthetic_rows()
    rows[2]['timestamp'] = rows[0]['timestamp']
    rows[2]['message'] = rows[0]['message'].copy()
    write(run, 'a-old-copy', rows)
    write(run, 'b-current-copy', rows)
    for args in [(), (), ('--rebuild',)]:
        assert run.build(*args).returncode == 0
        session, = run.payload()['sessions']
        assert len(session['turns']) == 2
        assert [t['usage']['input'] for t in session['turns']] == [10, 20]


def test_same_stem_promptless_winner_uses_duplicate_response_turn(tmp_path):
    run = NativeRun(tmp_path)
    rows = synthetic_rows()
    write(run, 'a-assistant-only', rows[1:2])
    write(run, 'b-complete', rows)
    for args in [(), (), ('--rebuild',)]:
        result = run.build(*args)
        assert result.returncode == 0, result.stderr
        session, = run.payload()['sessions']
        assert session['own_usage']['input'] == 30
        assert session['outside_usage']['input'] == 0
        assert [t['usage']['input'] for t in session['turns']] == [10, 20]


def test_distinct_stems_cannot_donate_response_display_turn(tmp_path):
    run = NativeRun(tmp_path)
    rows = synthetic_rows()
    write(run, 'a-assistant-only', rows[1:2])
    other = write(run, 'b-complete', rows[:2])
    other.rename(other.with_name('synthetic-other-session.jsonl'))
    for args in [(), (), ('--rebuild',)]:
        result = run.build(*args)
        assert result.returncode == 0, result.stderr
        sessions = {s['id']: s for s in run.payload()['sessions']}
        winner = sessions['synthetic-review-session']
        assert winner['outside_usage']['input'] == 10
        assert winner['own_usage']['input'] == 10
        assert sessions['synthetic-other-session']['turns'][0]['usage']['input'] == 0


def test_warm_claude_summary_reports_cache_hits(tmp_path):
    run = NativeRun(tmp_path)
    write(run, 'synthetic-copy', synthetic_rows())
    for args, parsed, cached in [((), 1, 0), ((), 0, 1), (("--rebuild",), 1, 0)]:
        result = run.build(*args)
        assert result.returncode == 0, result.stderr
        source = run.payload()['meta']['sources']['claude']
        assert (source['parsed'], source['cached']) == (parsed, cached)
        line = next(line for line in result.stdout.splitlines() if line.startswith('colophon: claude:'))
        assert f'{parsed} parsed, {cached} cached' in line, line


@pytest.mark.parametrize("selection", ["default", "explicit", "environment", "config-chain", "project-chain"])
@pytest.mark.parametrize("rebuild", [False, True])
def test_deleted_resolved_symlink_root_is_retained(tmp_path, selection, rebuild):
    import shutil
    run = NativeRun(tmp_path)
    target = tmp_path / 'synthetic-linked-projects'
    source = target / 'synthetic-project/synthetic-review-session.jsonl'
    source.parent.mkdir(parents=True)
    source.write_text(''.join(json.dumps(r, separators=(',', ':'))+'\n' for r in synthetic_rows()))
    config = run.home / '.claude'
    config.mkdir()
    (config / 'projects').symlink_to('../../synthetic-linked-projects', target_is_directory=True)
    if selection == 'project-chain':
        (config / 'projects').unlink()
        (run.home / 'synthetic-link').symlink_to('../synthetic-linked-projects', target_is_directory=True)
        (config / 'projects').symlink_to('../synthetic-link', target_is_directory=True)
    args = []
    if selection == 'explicit': args = ['--claude-home', str(config)]
    if selection == 'environment': run.env['CLAUDE_CONFIG_DIR'] = str(config)
    if selection == 'config-chain':
        link = run.home / 'synthetic-config-link'
        link.symlink_to('.claude', target_is_directory=True)
        args = ['--claude-home', str(link)]
    assert run.build(*args).returncode == 0
    before, = run.payload()['sessions']
    assert before['own_usage']['input'] == 30
    shutil.rmtree(target)
    run.codex.rmdir()  # provisional retained facts establish Claude-only presence
    result = run.build(*args, *(['--rebuild'] if rebuild else []))
    assert result.returncode == 0, result.stderr
    assert len(run.payload()['sessions']) == 1, run.payload()['diagnostics']
    retained, = run.payload()['sessions']
    assert 'transcript_deleted' in retained['flags']
    assert retained['own_usage'] == before['own_usage']


@pytest.mark.parametrize('mode', ['excluded', 'disabled', 'retargeted', 'permission'])
def test_dangling_symlink_root_requires_selected_unchanged_accessible_locator(tmp_path, mode):
    import shutil
    run = NativeRun(tmp_path)
    target = tmp_path / 'synthetic-target'
    run.claude_session(directory=target / 'synthetic-project')
    config = run.home / '.claude'
    config.mkdir()
    link = config / 'projects'
    link.symlink_to(target, target_is_directory=True)
    assert run.build().returncode == 0
    saved = {p: p.read_bytes() for p in store_records(run, 'cache-claude')}
    shutil.rmtree(target)
    args = []
    if mode == 'excluded': args = ['--claude-home', str(run.home / 'synthetic-excluded')]
    if mode == 'disabled': args = ['--no-claude']
    if mode == 'retargeted':
        link.unlink()
        link.symlink_to(tmp_path / 'synthetic-different-target', target_is_directory=True)
    if mode == 'permission': config.chmod(0)
    try:
        result = run.build('--rebuild', *args)
        assert result.returncode == 0, result.stderr
        assert run.payload()['sessions'] == []
        assert not store_records(run, 'claude-retained')
        assert {p: p.read_bytes() for p in store_records(run, 'cache-claude')} == saved
    finally:
        config.chmod(0o700)
