"""Exact taxonomy, embedded clocks and first-header identity."""
import json

import pytest

from fixturegen import CodexHome, iso
from tests.test_reader import api, parse

T0 = 1735689600000


EXPECTED_KEYS = frozenset({
    'session_meta','turn_context','token_usage_record','world_state','compacted',
    'inter_agent_communication_metadata','realtime_item','bare_usage',
    'event_msg/task_started','event_msg/task_complete','event_msg/turn_aborted',
    'event_msg/thread_settings_applied','event_msg/token_count','event_msg/user_message','event_msg/agent_message',
    'event_msg/item_completed/UserMessage','event_msg/item_completed/AgentMessage',
    'event_msg/item_completed/CommandExecution','event_msg/item_completed/FileChange',
    'event_msg/item_completed/McpToolCall','event_msg/item_completed/WebSearch',
    'event_msg/item_completed/ImageView','event_msg/item_completed/Extension',
    'event_msg/item_completed/SubAgentActivity','event_msg/item_completed/CollabAgentToolCall',
    'event_msg/item_completed/Reasoning','event_msg/item_completed/ContextCompaction','event_msg/item_completed/Plan',
    'response_item/message','response_item/function_call','response_item/custom_tool_call',
    'response_item/local_shell_call','response_item/web_search_call','response_item/tool_search_call',
    'response_item/function_call_output','response_item/custom_tool_call_output','response_item/local_shell_call_output',
    'response_item/reasoning','response_item/tool_search_output','response_item/agent_message',
})


def test_known_keys_literal_set_and_classification(colophon):
    actual = getattr(colophon,'KNOWN_RECORD_KEYS',None)
    assert isinstance(actual,frozenset)
    assert actual == EXPECTED_KEYS
    fn = api(colophon,'record_type_key')
    for key in EXPECTED_KEYS:
        parts=key.split('/')
        record={'type':parts[0]}
        if key=='bare_usage': record={'usage':{}}
        elif len(parts)>1:
            record['payload']={'type':parts[1]}
            if len(parts)>2: record['payload']['item']={'type':parts[2]}
        assert fn(record)==key


@pytest.mark.parametrize('container',[None,'data','result','response'])
def test_bare_usage_containers(colophon,container):
    record={'usage':{}} if container is None else {container:{'usage':{}}}
    assert api(colophon,'record_type_key')(record)=='bare_usage'
    record['type']='synthetic_unknown'
    assert colophon.record_type_key(record)=='synthetic_unknown'


@pytest.mark.parametrize('record',[{}, {'usage':None},{'data':{'usage':3}},{'payload':{'usage':{}}},{'data':[]}])
def test_nonusage_untyped_record_unknown(colophon,record):
    assert api(colophon,'record_type_key')(record) not in EXPECTED_KEYS


def test_unknown_types_counted_without_raw_records(colophon,codex_home):
    path=CodexHome(codex_home).log().meta().unknown().unknown().raw(
        b'{"type":"event_msg","payload":{"type":"item_completed","item":{"type":"SyntheticItem"}}}\n'
    ).reasoning().agent_message_ia().world_state().compacted().write()
    result=parse(colophon,path)
    assert result['unknown_types']=={'synthetic_unknown':2,'event_msg/item_completed/SyntheticItem':1}
    assert 'records' not in result and 'raw_records' not in result


@pytest.mark.parametrize('case',['empty','headers','no_meta','late_meta','normal'])
def test_status_and_no_meta(colophon,codex_home,case):
    log=CodexHome(codex_home).log()
    if case=='headers': log.meta().meta()
    elif case=='no_meta': log.world_state()
    elif case=='late_meta': log.world_state().meta()
    elif case=='normal': log.meta().world_state()
    result=parse(colophon,log.write())
    assert result['status']=={'empty':'empty','headers':'header_only'}.get(case,'ok')
    assert result['no_session_meta']==(case in {'empty','no_meta'})
    assert (result['meta'] is None)==(case in {'empty','no_meta'})


@pytest.mark.parametrize('kind,key',[('task_started','started_at_ms'),('task_started','started_at'),
    ('task_complete','completed_at_ms'),('task_complete','completed_at'),
    ('turn_aborted','completed_at_ms'),('turn_aborted','completed_at'),('item_completed','completed_at_ms')])
def test_each_embedded_clock(colophon,kind,key):
    expected=123456 if key.endswith('_ms') else 123456250
    assert api(colophon,'event_time')({'timestamp':iso(T0)},{'type':kind,key:123456.25})==(expected,key)


@pytest.mark.parametrize('kind,prefix',[('task_started','started'),('task_complete','completed'),('turn_aborted','completed')])
def test_clock_precedence_and_invalid_values(colophon,kind,prefix):
    fn=api(colophon,'event_time')
    record={'timestamp':iso(T0)}
    assert fn(record,{'type':kind,f'{prefix}_at_ms':0,f'{prefix}_at':1})==(0,f'{prefix}_at_ms')
    for invalid in [True,False,None,'123',float('nan'),float('inf'),[],{}]:
        assert fn(record,{'type':kind,f'{prefix}_at_ms':invalid,f'{prefix}_at':1})==(1000,f'{prefix}_at')
        assert fn(record,{'type':kind,f'{prefix}_at':invalid})==(T0,'record_timestamp')


@pytest.mark.parametrize('kind,key',[('task_started','started_at'),('task_complete','completed_at'),('turn_aborted','completed_at')])
@pytest.mark.parametrize('delta,wrapper_wins',[(1.9,True),(-1.9,True),(2.0,False),(-2.0,False)])
def test_seconds_clock_strict_boundary(colophon,kind,key,delta,wrapper_wins):
    result=api(colophon,'event_time')({'timestamp':iso(T0)},{'type':kind,key:T0/1000+delta})
    assert result==((T0,'record_timestamp') if wrapper_wins else (T0+int(delta*1000),key))


def test_clock_fallback_type_specific_keys(colophon):
    fn=api(colophon,'event_time')
    assert fn({'timestamp':iso(T0)},{'type':'world_state','started_at_ms':2,'completed_at':3})==(T0,'record_timestamp')
    assert fn({'timestamp':'invalid'},{})==(None,'record_timestamp')
    assert fn({}, {'completed_at_ms':2})==(2,'completed_at_ms')
    assert fn({'timestamp':iso(T0)},{'completed_at_ms':T0-1900})==(T0-1900,'completed_at_ms')


@pytest.mark.parametrize('times,expected',[([], (0,0)),([T0],(1,1)),([T0]*3,(3,1)),([T0,T0+1],(2,2)),([T0+i for i in range(5)],(5,3))])
def test_wrapper_counts_and_collapsed(colophon,codex_home,times,expected):
    log=CodexHome(codex_home).log()
    for instant in times: log.world_state(at=instant)
    result=parse(colophon,log.write())
    assert result['wrapper_ts']=={'count':expected[0],'distinct':expected[1]}
    assert (result['wrapper_ts']['count']>1 and result['wrapper_ts']['distinct']==1)==(len(times)>1 and len(set(times))==1)


@pytest.mark.parametrize('winner',range(6))
def test_d18_identity_order(colophon,codex_home,winner):
    record={'type':'session_meta','payload':{}}
    candidates=[(record['payload'],'id'),(record,'id'),(record['payload'],'session_id'),
        (record['payload'],'sessionId'),(record,'session_id'),(record,'sessionId')]
    for index,(obj,key) in enumerate(candidates): obj[key]=99 if index<winner else f'synthetic-id-{index}'
    path=CodexHome(codex_home).log().raw((json.dumps(record)+'\n').encode()).write()
    assert parse(colophon,path)['meta']['id']==f'synthetic-id-{winner}'


@pytest.mark.parametrize('oversized',[False,True])
def test_true_first_meta_owns_identity_before_ancestor(colophon,codex_home,oversized):
    log=CodexHome(codex_home).log('synthetic-child').meta(at=T0,session_id='synthetic-tree-root',
        thread_name='Synthetic child',synthetic_padding='x'*(262145 if oversized else 0))
    log.meta(id='synthetic-ancestor',timestamp=iso(T0-10000),thread_name='Synthetic ancestor').world_state()
    result=parse(colophon,log.write())
    assert result['meta']['id']=='synthetic-child'
    assert result['meta']['rollout_title']=='Synthetic child'
    assert result['meta']['created_at_ms']==T0
    assert result['extra_meta_count']==1


def test_metadata_fields_and_git_mapping(colophon,codex_home):
    spawn={'parent_thread_id':'synthetic-parent','depth':2,'agent_path':'/synthetic/root/reviewer',
        'agent_nickname':'Agent-Alpha','agent_role':'synthetic-reviewer'}
    path=CodexHome(codex_home).log('synthetic-child').meta(at=T0,source={'subagent':{'thread_spawn':spawn}},
        forked_from_id='synthetic-parent',title='Synthetic title',
        git={'branch':'synthetic-branch','repository_url':'https://example.invalid/synthetic/repo.git','commit_hash':'synthetic-sha'}).write()
    meta=parse(colophon,path)['meta']
    assert meta=={'id':'synthetic-child','created_at_ms':T0,'timestamp_raw':iso(T0),
        'cwd':'/synthetic/projects/alpha','originator':'Codex Desktop','cli_version':'0.0.0-synthetic',
        'forked_from_id':'synthetic-parent','is_subagent':True,**spawn,
        'git':{'branch':'synthetic-branch','origin_url':'https://example.invalid/synthetic/repo.git','sha':'synthetic-sha'},
        'rollout_title':'Synthetic title'}


def test_meta_invalid_timestamp_falls_back_to_event_clock(colophon,codex_home):
    path=CodexHome(codex_home).log().meta(timestamp='invalid',completed_at_ms=12345).write()
    assert parse(colophon,path)['meta']['created_at_ms']==12345


@pytest.mark.parametrize('payload', [None, [], 'synthetic', {'source': {'subagent': []}, 'git': []}])
def test_metadata_malformed_optional_shapes_are_safe(colophon, codex_home, payload):
    record = {'type': 'session_meta', 'timestamp': iso(T0), 'payload': payload}
    path = CodexHome(codex_home).log().raw((json.dumps(record) + '\n').encode()).write()
    result = parse(colophon, path)
    assert result['meta']['id'] is None
    assert result['meta']['created_at_ms'] == T0
    assert result['meta']['is_subagent'] is False
    assert result['meta']['git'] == {'branch': None, 'origin_url': None, 'sha': None}


@pytest.mark.parametrize('source', [' SUBAGENT ', {'subagent': 'synthetic'}, {'subagent': {}}])
def test_upstream_subagent_source_shapes(colophon, codex_home, source):
    path = CodexHome(codex_home).log().meta(source=source).write()
    assert parse(colophon, path)['meta']['is_subagent'] is True


def test_seconds_boundary_before_millisecond_truncation(colophon):
    payload = {'type': 'task_started', 'started_at': T0 / 1000 - 1.9999}
    assert api(colophon, 'event_time')({'timestamp': iso(T0)}, payload) == (T0, 'record_timestamp')
