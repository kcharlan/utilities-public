"""Hand-derived routing observations from CodexBar 3bbf6bc48 (no reference fixtures)."""
import json

import pytest

TS = '2030-01-07T00:00:00Z'
META = {'session_id': 'synthetic-leaf', 'forked_from_id': None, 'fork_ts': None,
        'project_path': None, 'is_subagent': False, 'history_start_ordinal': None,
        'history_base_thread_id': None}


def encode(obj):
    return json.dumps(obj, separators=(',', ':')).encode()


def observe(module, rows, *, terminated=True):
    builder_type = getattr(module, 'TokenStreamBuilder', None)
    assert callable(builder_type), 'Task 7 TokenStreamBuilder is missing'
    builder = builder_type()
    for index, row in enumerate(rows):
        data = encode(row) if isinstance(row, dict) else row
        builder.feed(index, data, None, terminated=terminated)
    return builder.result()


def context(payload, **extra):
    return {'type': 'turn_context', 'timestamp': TS, 'payload': payload, **extra}


def token(info, **extra):
    return {'type': 'event_msg', 'timestamp': TS,
            'payload': {'type': 'token_count', 'info': info}, **extra}


def test_all_regular_tags_and_ordinals(colophon):
    # Scanner 3700–3912, 4822–5005: fast M,C,I,S,T; B consumes usage first.
    rows = [{'type': 'session_meta', 'ordinal': 11, 'payload': {'id': 'synthetic-leaf'}},
            context({'model': ' synthetic-model '}, ordinal=12),
            {'type': 'inter_agent_communication_metadata', 'timestamp': TS,
             'ordinal': 13, 'payload': {'trigger_turn': True}},
            {'type': 'event_msg', 'timestamp': TS, 'ordinal': 14,
             'payload': {'type': 'task_started', 'turn_id': 'synthetic-turn'}},
            token({'last_token_usage': {'input_tokens': 7}}, ordinal=15),
            {'timestamp': TS, 'usage': {'input_tokens': 8, 'output_tokens': 2}}]
    assert observe(colophon, rows) == {'observations': [
        ['P', META], ['M', 0, 0, 11, META],
        ['C', 1, 1, 12, TS, {'set': 'synthetic-model'}],
        ['I', 2, 2, 13, True], ['S', 3, 3, 14, 'synthetic-turn'],
        ['T', 4, 4, 15, TS, None, None, [7, 0, 0, None], None],
        ['B', 5, 5, TS, None, [8, 0, 2, None]]], 'unconsumed_tail': False}


@pytest.mark.parametrize('payload,model', [
    ({'model': ' ', 'model_name': ' synthetic-next '}, {'set': 'synthetic-next'}),
    ({'model': '', 'info': {'model_name': '\n'}}, {'clear': True}),
    ({}, None), ({'model': 7, 'model_name': False, 'info': {'model': []}}, None),
    ({'info': {'model': ' synthetic-info ', 'model_name': 'synthetic-last'}}, {'set': 'synthetic-info'}),
])
def test_context_model_tristate(colophon, payload, model):
    # Scanner 3458–3475: skip absent/non-string; first nonblank wins; blank clears.
    assert observe(colophon, [context(payload)])['observations'] == [['C', 0, 0, None, TS, model]]


@pytest.mark.parametrize('info,payload_model,root_model,expected', [
    ({'model': ' synthetic-info ', 'model_name': 'synthetic-name'}, 'synthetic-payload', 'synthetic-root', 'synthetic-info'),
    ({'model': ' ', 'model_name': 'synthetic-name'}, 'synthetic-payload', 'synthetic-root', 'synthetic-name'),
    ({'model': ''}, 'synthetic-payload', 'synthetic-root', 'synthetic-payload'),
    ({}, ' ', 'synthetic-root', 'synthetic-root'),
])
def test_token_model_evidence_order(colophon, info, payload_model, root_model, expected):
    # Scanner 3866–3888: info.model, info.model_name, payload.model, root.model.
    row = token(info, model=root_model)
    row['payload']['model'] = payload_model
    assert observe(colophon, [row])['observations'] == [['T', 0, 0, None, TS, expected, None, None, None]]


def test_totals_clamp_and_cached_max(colophon):
    # Scanner 3646–3675 / tokenTotals 4977–4989: max caches; reasoning <= output.
    row = token({'last_token_usage': {'input_tokens': -4, 'cached_input_tokens': 3,
        'cache_read_input_tokens': 8, 'output_tokens': 5, 'reasoning_output_tokens': 9},
        'total_token_usage': {'input_tokens': 11, 'cached_input_tokens': -2,
        'cache_read_input_tokens': -3, 'output_tokens': -1, 'reasoning_output_tokens': -5}})
    assert observe(colophon, [row])['observations'] == [
        ['T', 0, 0, None, TS, None, None, [0, 8, 5, 5], [11, 0, 0, 0]]]


def test_invalid_timestamp_drops_token_but_not_meta(colophon):
    # Scanner 3393–3400, 4849–4877: M bypasses validity, other tags need valid ts.
    rows = [token({}, timestamp='synthetic-invalid'),
            {'type': 'session_meta', 'timestamp': 'synthetic-invalid', 'payload': {'id': 'synthetic-leaf'}}]
    meta = {**META, 'fork_ts': 'synthetic-invalid'}
    assert observe(colophon, rows)['observations'] == [['P', meta], ['M', 1, 1, None, meta]]


@pytest.mark.parametrize('ts', ['2030-02-31T25:61:62Z', '2030-01-07T00:00:00+0060',
                              '2030-01-07T00:00:00Zsynthetic-suffix'])
def test_upstream_calendar_validity_is_not_display_rfc3339(colophon, ts):
    # Timestamp 105–180: Calendar normalizes components; zone scanned backward;
    # there is no strict range/fraction/suffix validation in dayKeyFromTimestamp.
    assert observe(colophon, [context({}, timestamp=ts)])['observations'] == [['C', 0, 0, None, ts, None]]
    assert colophon.parse_rfc3339_ms(ts) is None


def test_bare_billed_input_aliases_and_data_model(colophon):
    # Scanner 3918–3972: first canonical container, cached key priority, billed subtraction.
    row = {'data': {'model': ' synthetic-data ', 'usage': {'prompt_tokens': 10.9,
           'completion_tokens': 4, 'cached_input_tokens': 3, 'cache_read_input_tokens': 8}}}
    assert observe(colophon, [row])['observations'] == [['B', 0, 0, None, 'synthetic-data', [7, 3, 4, None]]]


@pytest.mark.parametrize('row', [token({'usage': {}}), context({'usage': {}}),
    {'usage': {'input_tokens': 3, 'output_tokens': 2}, 'type': None},
    {'type': 'event_msg', 'timestamp': TS, 'payload': {'type': 'agent_message'}},
    {'type': 'unknown', 'payload': {'type': 'token_count'}, 'timestamp': TS}])
def test_usage_branch_and_fast_filters_consume_dropped_lines(colophon, row):
    # Scanner 4822–4854: usage requires absent type (null is present), then drops;
    # only four raw type markers; compact irrelevant event messages are filtered.
    assert observe(colophon, [row])['observations'] == []


def test_uidx_counts_whitespace_but_not_zero_bytes(colophon):
    # Jsonl 358–359 + Scanner 4773–4774: zero-byte lines never reach onLine.
    rows = [b'', b' \t', context({}), b'\r', context({})]
    assert observe(colophon, rows)['observations'] == [
        ['C', 2, 1, None, TS, None], ['C', 4, 3, None, TS, None]]


def test_truncated_context_and_meta(colophon):
    # TruncatedPrefix 4–43; Scanner 4783–4820: only canonical root tags survive.
    huge = 'x' * (262144 + 1)
    rows = [{'type': 'session_meta', 'payload': {'id': 'synthetic-leaf', 'source': 'subagent'}},
            context({'model': 'synthetic-model', 'synthetic_padding': huge}),
            {'type': 'session_meta', 'payload': {'id': 'synthetic-ancestor', 'synthetic_padding': huge}},
            token({'synthetic_padding': huge})]
    meta = {**META, 'is_subagent': True}
    assert observe(colophon, rows)['observations'] == [['P', meta], ['M', 0, 0, None, meta],
        ['XC', 1, 1, {'set': 'synthetic-model'}], ['XM', 2, 2, 'synthetic-ancestor']]


@pytest.mark.parametrize('payload,expected', [({'model': '', 'synthetic_padding': 'x'*262145}, None),
                                            ({'model': ''}, {'clear': True})])
def test_truncated_blank_model_requires_complete_payload(colophon, payload, expected):
    # TruncatedPrefix 40–43: blank may clear only when entire payload object is retained.
    row = context(payload, synthetic_padding='x'*262145)
    assert observe(colophon, [row])['observations'] == [['XC', 0, 0, expected]]


def test_truncated_escaped_strings_use_literal_escape_removal(colophon):
    # TruncatedPrefix parseJSONString 162–185 removes backslash, not JSON unescaping.
    row = context({'model': 'synthetic\\nmodel', 'synthetic_padding': 'x'*262145})
    assert observe(colophon, [row])['observations'] == [['XC', 0, 0, {'set': 'synthetic\\nmodel'}]]


def test_prepass_skips_oversized_meta_and_is_first(colophon):
    # Scanner 4027–4105: first <=256KiB fast/fallback metadata anywhere, before replay.
    rows = [{'type': 'session_meta', 'payload': {'id': 'synthetic-huge', 'padding': 'x'*262145}},
            context({}), {'type': 'session_meta', 'payload': {'id': 'synthetic-leaf'}}]
    assert observe(colophon, rows)['observations'][0] == ['P', META]


def test_prepass_checks_unterminated_incomplete_segment(colophon):
    # Scanner 4099–4105: prepass fast parser independent of scanBounded tail commit.
    data = b'{"type":"session_meta","payload":{"id":"synthetic-leaf"},"padding":"'
    assert observe(colophon, [data], terminated=False) == {'observations': [['P', META]], 'unconsumed_tail': True}


@pytest.mark.parametrize('data,unconsumed', [(b'123', True), (b'123 ', False), (b' \t\r', True),
    (b'{"a":NaN}', True), (b'{"a":Infinity}', True), (b'{"a":"\\ud800"}', True),
    (b'{"\\ud800":0}', True), (b'{"a":["\\ud800"]}', True),
    (b'{"a":"\\ud83d\\ude00"}', False), (b'true', False), (b'false', False),
    (b'null', False), (b'"synthetic"', False), (b'{"a":', True),
    (b'x' * 262145, False), (b'{"a":"'+b'x'*262145, True)], ids=['number', 'delimited-number', 'whitespace', 'nan', 'infinity', 'surrogate-value', 'surrogate-key', 'nested-surrogate', 'paired-surrogate', 'true', 'false', 'null', 'string', 'container-incomplete', 'truncated-invalid', 'truncated-incomplete'])
def test_tail_commit_rules(colophon, data, unconsumed):
    # Jsonl 45–270, 383–392: numbers require delimiter; invalid scalar complete;
    # small tails need Foundation JSON too, rejecting constants/unpaired surrogates.
    assert observe(colophon, [data], terminated=False) == {'observations': [], 'unconsumed_tail': unconsumed}


def test_complete_context_tail_routes(colophon):
    # Jsonl 383–392, 400–417: structurally complete + valid small JSON tail is routed.
    assert observe(colophon, [context({})], terminated=False) == {
        'observations': [['C', 0, 0, None, TS, None]], 'unconsumed_tail': False}


def test_raw_glued_routing_is_independent_of_recovery(colophon, codex_home):
    # FastJSON extractJSONByteField scans bytes without JSON validation; a prefix
    # with no braces leaves recovered object's type at depth1 (Scanner 4857–4877).
    data = b'synthetic-debris' + encode(context({'model': 'synthetic-model'}))
    direct = observe(colophon, [data])
    assert direct['observations'] == [['C', 0, 0, None, TS, {'set': 'synthetic-model'}]]
    path = codex_home / 'sessions' / 'synthetic-glued.jsonl'
    path.write_bytes(data+b'\n')
    result = colophon.parse_log_file(path, size=path.stat().st_size, mtime_ns=0, archived=False)
    assert result['lines']['recovered'] == 1
    assert result['token_stream'] == direct
    # Unmatched opening brace shifts depth, so recovery must not feed the suffix.
    path.write_bytes(b'{"type":"synthetic-broken",'+encode(context({}))+b'\n')
    result = colophon.parse_log_file(path, size=path.stat().st_size, mtime_ns=0, archived=False)
    assert result['lines']['recovered'] == 1
    assert result['token_stream']['observations'] == []


def test_fast_byte_integer_prefix_and_fallback_number_cast(colophon):
    # FastJSON parseJSONByteInt 170–196 reads prefix; escaped root type forces
    # Scanner 4887/4970–4989 Foundation NSNumber path including bool -> 1.
    row = token({'last_token_usage': {'input_tokens': 12.9, 'output_tokens': True}}, ordinal=3.5)
    assert observe(colophon, [row])['observations'] == [['T', 0, 0, 3, TS, None, None, [12, 0, 0, None], None]]
    data = encode(row).replace(b'"type":"event_msg"', b'"t\\u0079pe":"event_msg"')
    assert observe(colophon, [data])['observations'] == [['T', 0, 0, 3, TS, None, None, [12, 0, 1, None], None]]


def test_metadata_fast_vs_fallback_empty_identity(colophon):
    # Scanner 3595–3620 fast skips empty id; dict metadata 3994–4005 keeps it.
    row = {'type': 'session_meta', 'id': 'synthetic-root', 'payload': {'id': '', 'source': {'subagent': ''}}}
    fast = {**META, 'session_id': 'synthetic-root'}
    fallback = {**META, 'session_id': '', 'is_subagent': True}
    assert observe(colophon, [row])['observations'] == [['P', fast], ['M', 0, 0, None, fast]]
    data = encode(row).replace(b'"type"', b'"t\\u0079pe"', 1)
    assert observe(colophon, [data])['observations'] == [['P', fallback], ['M', 0, 0, None, fallback]]


@pytest.mark.parametrize('timestamp,valid', [
    ('2030-1-7T0:0:0Z', True), ('2030-1-7T0:0:0.0015Z', True),
    ('2030-01-07T00:00:00z', True), ('2030-01-07t00:00:00z', False),
    ('2030-02-30T00:00:00z', True), ('2030-02-32T00:00:00z', False),
    ('2030-01-07T24:01:00z', True), ('2030-01-07T25:00:00z', False),
    ('2030-01-07T00:60:00z', False), ('2030-01-07T00:00:60z', False),
    ('2030-01-07T00:00:00UTC', True), ('2030-01-07T00:00:00+0', True),
    (' 2030-01-07T00:00:00z', True), ('2030-01-07T00 :00:00z', True),
    ('2030-01-07T00:00:00', False), ('20300107T000000Z', False),
])
def test_historical_formatter_validity(colophon, timestamp, valid):
    # Timestamp parseISO 22–32 calls native then historical formatter; historical
    # is Foundation internet-date-time withFractional then plain. Hand-derived
    # expected observations follow those option contracts; standalone synthetic
    # Foundation probes corroborate calendar normalization / prefix consumption.
    expected = [['C', 0, 0, None, timestamp, None]] if valid else []
    assert observe(colophon, [context({}, timestamp=timestamp)])['observations'] == expected


def test_metadata_scalar_projection_and_fast_turn_id(colophon):
    # Scanner 3476–3628, 3709–3744: aliases trimmed for fork/history, absolute cwd
    # standardized, payload id preferred, source object with subagent marks child.
    row = {'type': 'session_meta', 'id': 'synthetic-root', 'ordinal': 21,
           'timestamp': TS, 'payload': {'id': 'synthetic-leaf', 'session_id': 'synthetic-tree',
               'forked_from_id': ' ', 'parentSessionId': ' synthetic-parent ',
               'timestamp': 'synthetic-fork-ts', 'cwd': ' /synthetic/a/../b/ ',
               'source': {'subagent': {}}, 'subagent_history_start_ordinal': 7,
               'historyBase': {'threadId': ' synthetic-base '}}}
    meta = {**META, 'forked_from_id': 'synthetic-parent', 'fork_ts': 'synthetic-fork-ts',
            'project_path': '/synthetic/b', 'is_subagent': True,
            'history_start_ordinal': 7, 'history_base_thread_id': 'synthetic-base'}
    assert observe(colophon, [row])['observations'] == [['P', meta], ['M', 0, 0, 21, meta]]


def test_fast_turn_id_skips_empty_while_fallback_keeps_empty(colophon):
    # Scanner 3575–3593 fast vs 5266–5274 dictionary nil-coalescing.
    row = {'type': 'event_msg', 'timestamp': TS, 'payload': {'type': 'task_started',
           'turn_id': '', 'info': {'turnId': 'synthetic-info-turn'}}}
    assert observe(colophon, [row])['observations'] == [['S', 0, 0, None, 'synthetic-info-turn']]
    data = encode(row).replace(b'"type":"event_msg"', b'"t\\u0079pe":"event_msg"')
    assert observe(colophon, [data])['observations'] == [['S', 0, 0, None, '']]


def test_fast_integer_overflow_falls_back_to_zero_component(colophon):
    # FastJSON 185–191 positive magnitude overflow returns nil; the fast line
    # still routes, so no Foundation recast takes place for that component.
    row = token({'last_token_usage': {'input_tokens': 9223372036854775808,
                                    'output_tokens': 1}})
    assert observe(colophon, [row])['observations'] == [['T', 0, 0, None, TS, None, None, [0, 0, 1, None], None]]


def test_truncated_prefix_must_not_find_late_models(colophon):
    # Jsonl appendSegment 342–350 retains first prefixBytes, not last bytes.
    row = context({'synthetic_padding': 'x'*262145, 'model': 'synthetic-too-late'})
    assert observe(colophon, [row])['observations'] == [['XC', 0, 0, None]]


def test_truncated_prompt_markers_cannot_override_root(colophon):
    # TruncatedPrefix 8–11/25–29 root-depth field checks, not substring routing.
    row = {'type': 'synthetic-other', 'payload': {'type': 'turn_context',
           'timestamp': TS, 'model': 'synthetic-model', 'padding': 'x'*262145}}
    assert observe(colophon, [row])['observations'] == []


def test_exact_line_limit_uses_regular_routing(colophon):
    # Jsonl 351–353 truncates strictly > maxLineBytes, not >=.
    base = encode(context({'model': 'synthetic-model'}))
    data = base + b' '*(262144-len(base))
    assert observe(colophon, [data])['observations'] == [['C', 0, 0, None, TS, {'set': 'synthetic-model'}]]


def test_inter_agent_missing_trigger_falls_back_to_false(colophon):
    # Scanner 3678–3696 fast needs bool; dictionary 4908–4922 defaults false.
    row = {'type': 'inter_agent_communication_metadata', 'timestamp': TS, 'payload': {}}
    assert observe(colophon, [row])['observations'] == [['I', 0, 0, None, False]]


def test_token_without_info_falls_back_and_routes_null_totals(colophon):
    # Scanner fast 3852–3863 requires info; dictionary 4964–4999 does not.
    row = {'type': 'event_msg', 'timestamp': TS, 'payload': {'type': 'token_count'}}
    assert observe(colophon, [row])['observations'] == [['T', 0, 0, None, TS, None, None, None, None]]


def test_json_tail_rejects_exponent_overflow(colophon):
    # Jsonl 391–392 uses JSONSerialization, which rejects overflow into infinity.
    assert observe(colophon, [b'{"synthetic":1e999}'], terminated=False) == {
        'observations': [], 'unconsumed_tail': True}


def test_fallback_nsnumber_signed_width(colophon):
    # Scanner tokenTotals 4970–4989 uses NSNumber.intValue (signed platform Int).
    # 2**63 wraps to Int.min in Foundation, then input is clamped to zero.
    row = token({'last_token_usage': {'input_tokens': 9223372036854775808, 'output_tokens': 1}})
    data = encode(row).replace(b'"type":"event_msg"', b'"t\\u0079pe":"event_msg"')
    assert observe(colophon, [data])['observations'] == [['T', 0, 0, None, TS, None, None, [0, 0, 1, None], None]]


@pytest.mark.parametrize('raw,expected', [('\u200b', {'clear': True}),
    ('\u200bsynthetic-model\u200b', {'set': 'synthetic-model'}),
    ('\x1c', {'set': '\x1c'})])
def test_foundation_model_trim_set(colophon, raw, expected):
    # Scanner codexModelEvidence 3453–3456 uses Foundation
    # CharacterSet.whitespacesAndNewlines, including 200B but excluding 001C.
    assert observe(colophon, [context({'model': raw})])['observations'] == [['C', 0, 0, None, TS, expected]]


def test_foundation_metadata_trim_set(colophon):
    # Scanner 3476–3519/3546–3571/3621–3628 uses that same CharacterSet.
    row = {'type': 'session_meta', 'payload': {'id': 'synthetic-leaf',
        'forked_from_id': '\u200bsynthetic-parent\u200b',
        'history_base': {'thread_id': '\u200bsynthetic-base\u200b'},
        'source': '\u200bSUBAGENT\u200b', 'cwd': '\u200b/synthetic/project/\u200b'}}
    meta = {**META, 'forked_from_id': 'synthetic-parent', 'history_base_thread_id': 'synthetic-base',
        'is_subagent': True, 'project_path': '/synthetic/project'}
    assert observe(colophon, [row])['observations'] == [['P', meta], ['M', 0, 0, None, meta]]


def test_truncated_swift_character_whitespace_excludes_control_separator(colophon):
    # TruncatedPrefix skipJSONWhitespace 205–209 uses Character.isWhitespace;
    # unlike Python isspace it excludes U+001C and unlike Foundation trim it
    # excludes U+200B. Neither byte can sit between key colon and value.
    for separator in ('\x1c', '\u200b'):
        data = encode(context({'model': 'synthetic-model', 'padding': 'x'*262145}))
        data = data.replace(b'"model":', b'"model":'+separator.encode())
        assert observe(colophon, [data])['observations'] == [['XC', 0, 0, None]]


def test_prepass_metadata_is_independent_of_usage_routing_filter(colophon):
    # Scanner prepass 4027–4035 ignores onLine's usage substring consumption
    # (4822–4835). Metadata is selected even though M is not routed later.
    row = {'type': 'session_meta', 'payload': {'id': 'synthetic-leaf', 'usage': {}}}
    assert observe(colophon, [row])['observations'] == [['P', META]]


@pytest.mark.parametrize('data,complete', [(b'-', False), (b'0', False), (b'1.', False),
    (b'1.0', False), (b'1e', False), (b'1e+', False), (b'1e2', False), (b'1e2 ', True),
    (b'00', True), (b'tr', False), (b'true ', True), (b'truex', True), (b'[]', True),
    (b'[}', True), (b'"synthetic\\"', False), (b'"synthetic\\\\"', True)])
def test_json_tail_state_transitions(colophon, data, complete):
    # Jsonl NumberState 103–140 / appendContainer 229–251: scalar numbers
    # require whitespace; invalid scalar and mismatched container closes count
    # structurally complete (the separate JSONSerialization gate still runs).
    state = colophon.JSONTailState()
    for byte in data:
        state.append(byte)
    assert state.is_structurally_complete is complete


@pytest.mark.parametrize('literal,expected', [('1e20', 9223372036854775807),
    ('9223372036854775808.0', 0), ('100000000000000000000.5', 387582001968421274),
    ('123456789012345.678', 123456789012345)])
def test_fallback_numeric_lexemes_preserve_nsnumber_cast(colophon, literal, expected):
    # Scanner 4970–4989 casts JSONSerialization's NSNumber, not a Python float.
    # Scientific short mantissas use floating saturation; >17 mantissa digits
    # use NSDecimalNumber with fixed-width mantissa conversion before scaling.
    data = (b'{"t\\u0079pe":"event_msg","timestamp":"'+TS.encode()+
            b'","payload":{"type":"token_count","info":{"last_token_usage":'
            b'{"input_tokens":'+literal.encode()+b',"output_tokens":1}}}}')
    assert observe(colophon, [data])['observations'] == [['T', 0, 0, None, TS, None, None,
                                                      [expected, 0, 1, None], None]]


def test_negative_exponent_overflow_is_foundation_fragment(colophon):
    # Jsonl 391–392 Foundation JSONSerialization accepts negative exponent
    # overflow as NSNumber(-infinity); positive exponent overflow is rejected.
    assert observe(colophon, [b'{"synthetic":-1e999}'], terminated=False) == {
        'observations': [], 'unconsumed_tail': False}


def test_foundation_project_path_collapses_double_root_slash(colophon):
    # Scanner normalizedCodexProjectPath 3621–3628 uses standardizedFileURL.
    row = {'type': 'session_meta', 'payload': {'id': 'synthetic-leaf', 'cwd': '//synthetic//a/./b/../'}}
    meta = {**META, 'project_path': '/synthetic/a'}
    assert observe(colophon, [row])['observations'] == [['P', meta], ['M', 0, 0, None, meta]]
