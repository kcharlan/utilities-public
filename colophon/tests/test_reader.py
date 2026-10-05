"""Snapshot-bounded reading and synthetic crash damage."""
import hashlib
import io
import json
from pathlib import Path

import pytest

from fixturegen import CodexHome


def api(module, name):
    value = getattr(module, name, None)
    assert callable(value), f'Task 3 interface {name} is missing'
    return value


def parse(module, path, *, size=None, archived=False):
    stat = path.stat()
    return api(module, 'parse_log_file')(path, size=stat.st_size if size is None else size,
        mtime_ns=stat.st_mtime_ns, archived=archived)


def test_iter_lines_snapshot_and_indexes(colophon):
    data = b'\n  \n{"type":"world_state"}\npartial\nignored'
    limit = len(b'\n  \n{"type":"world_state"}\npart')
    stream = io.BytesIO(data)
    lines = list(api(colophon,'iter_log_lines')(stream,limit))
    assert [(v.index,v.data,v.terminated) for v in lines] == [
        (0,b'',True),(1,b'  ',True),(2,b'{"type":"world_state"}',True),(3,b'part',False)]
    assert stream.tell() == limit


def test_iter_lines_chunk_boundaries_and_short_reads(colophon):
    class ShortReader(io.BytesIO):
        def read(self,size=-1):
            assert 0 < size <= 1024*1024
            return super().read(min(size,70001))
    data = b'x'*(1024*1024+7)+b'\n\nend\n'
    lines = list(api(colophon,'iter_log_lines')(ShortReader(data),len(data)+50))
    assert [(v.index,len(v.data),v.terminated) for v in lines] == [(0,1024*1024+7,True),(1,0,True),(2,3,True)]


@pytest.mark.parametrize('data,status,obj',[(b'', 'blank',None),(b' \t\r','blank',None),
    (b'not synthetic json','malformed',None),(b'[]','malformed',None),(b'null','malformed',None),
    (b'12','malformed',None),(b'"text"','malformed',None),(b'\xff','malformed',None),
    (b'{"type":"world_state"}','ok',{'type':'world_state'})])
def test_decode_lines(colophon,data,status,obj):
    result = api(colophon,'decode_line')(data)
    assert (result.status,result.obj) == (status,obj)


@pytest.mark.parametrize('prefix',[b'partial',b'{"type":"broken"',b'{"timestamp":bad'])
@pytest.mark.parametrize('record',[{'timestamp':'2025-01-01T00:00:00Z','type':'world_state'},{'type':'compacted'}])
def test_decode_glued_fragment_recovers_full_record(colophon,prefix,record):
    result = api(colophon,'decode_line')(prefix+json.dumps(record).encode())
    assert (result.status,result.obj) == ('recovered',record)


@pytest.mark.parametrize('tail',[b'{"type":',b'partial{"type":"world_state"}',b'[]',b' '])
def test_partial_tail_never_malformed_or_recovered(colophon,codex_home,tail):
    path = CodexHome(codex_home).log().meta().write(partial_tail=tail)
    result = parse(colophon,path)
    assert result['lines'] == {'malformed':0,'recovered':0,'partial_final_line':True}
    assert result['status'] == 'header_only'


def test_complete_unterminated_object_counts(colophon,codex_home):
    result = parse(colophon,CodexHome(codex_home).log().raw(b'{"type":"world_state"}').write())
    assert result['status'] == 'ok'
    assert result['lines'] == {'malformed':0,'recovered':0,'partial_final_line':False}


def test_damage_counts_and_recovered_meta_used(colophon,codex_home):
    path = CodexHome(codex_home).log().raw(
        b'\n \t\nmalformed\npartial{"type":"session_meta","payload":{"id":"synthetic-recovered"}}\n'
    ).world_state().write()
    result = parse(colophon,path)
    assert result['lines'] == {'malformed':1,'recovered':1,'partial_final_line':False}
    assert result['meta']['id'] == 'synthetic-recovered'


@pytest.mark.parametrize('length',[0,37,4096,5000])
def test_snapshot_tail_fingerprint_single_open(colophon,codex_home,monkeypatch,length):
    path = CodexHome(codex_home).log().raw(b' '*length).write()
    snapshot = path.read_bytes()
    path.write_bytes(snapshot+b'\n{"type":"world_state"}\n')
    original = Path.open
    handles = []
    def tracked(target,*args,**kwargs):
        fh = original(target,*args,**kwargs)
        if target == path:
            assert args == ('rb',)
            handles.append(fh)
        return fh
    monkeypatch.setattr(Path,'open',tracked)
    result = parse(colophon,path,size=length,archived=True)
    assert len(handles)==1 and handles[0].closed
    # CodexBar codexPathKey aliases /private/var without resolving symlinks.
    expected_path = str(path.absolute())
    if expected_path.startswith('/private/var/'):
        expected_path = expected_path[len('/private'):]
    assert result['key'] == {'path':expected_path,'size':length,'mtime_ns':path.stat().st_mtime_ns,
        'tail_sha256':hashlib.sha256(snapshot[max(0,length-4096):length]).hexdigest()}
    assert result['archived'] is True and result['status']=='empty'
    assert result['parser_version']==colophon.PARSER_VERSION


def test_tail_read_precedes_stream_and_handle_closes_on_error(colophon, codex_home, monkeypatch):
    path = CodexHome(codex_home).log().meta().world_state().write()
    size = path.stat().st_size
    original = Path.open
    operations = []
    handles = []

    class TrackedHandle:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.fh.close()

        def seek(self, position):
            operations.append(('seek', position))
            return self.fh.seek(position)

        def read(self, count):
            operations.append(('read', count))
            return self.fh.read(count)

    def tracked(target, *args, **kwargs):
        fh = original(target, *args, **kwargs)
        handles.append(fh)
        return TrackedHandle(fh)

    monkeypatch.setattr(Path, 'open', tracked)
    parse(colophon, path)
    assert operations == [('seek', 0), ('read', size), ('seek', 0), ('read', size)]
    assert len(handles) == 1 and handles[0].closed

    def fail_decode(data):
        raise OSError('Synthetic read failure')

    monkeypatch.setattr(colophon, 'decode_line', fail_decode)
    with pytest.raises(OSError, match='Synthetic read failure'):
        parse(colophon, path)
    assert len(handles) == 2 and handles[1].closed
