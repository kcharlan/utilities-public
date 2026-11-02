import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import jtree_mod


def test_save_refuses_file_changed_on_disk_since_open(loaded_client, sample_json_file, tmp_path):
    external = b'{"external": "synthetic"}\n'
    Path(sample_json_file).write_bytes(external)
    assert loaded_client.put('/api/node', params={'path': '["name"]'}, json={'value': 'changed'}).status_code == 200
    response = loaded_client.post('/api/save')
    assert response.status_code == 409
    assert 'changed on disk' in response.json()['detail']
    assert Path(sample_json_file).read_bytes() == external
    assert loaded_client.get('/api/status').json()['dirty'] is True
    rescue = loaded_client.post('/api/save-as', json={'path': str(tmp_path / 'rescued.json')})
    assert rescue.json()['ok'] is True


def test_consecutive_saves_are_not_conflicts(loaded_client, sample_json_file):
    for value in ('first', 'second'):
        assert loaded_client.put('/api/node', params={'path': '["name"]'}, json={'value': value}).status_code == 200
        assert loaded_client.post('/api/save').status_code == 200
    assert '"second"' in Path(sample_json_file).read_text()


def test_surrogate_save_preserves_file_and_reports_error(loaded_client, sample_json_file):
    before = open(sample_json_file, 'rb').read()
    manager = jtree_mod.JSONManager(sample_json_file)
    manager.data = {'invalid': '\ud800'}
    with pytest.raises(UnicodeError):
        manager.save()
    assert open(sample_json_file, 'rb').read() == before


def test_nonfinite_save_preserves_file(loaded_client, sample_json_file):
    before = open(sample_json_file, 'rb').read()
    manager = jtree_mod.JSONManager(sample_json_file)
    manager.data = {'number': float('inf')}
    with pytest.raises(ValueError):
        manager.save()
    assert open(sample_json_file, 'rb').read() == before


def test_failed_replacement_preserves_file(loaded_client, sample_json_file, monkeypatch):
    before = open(sample_json_file, 'rb').read()
    def fail(*args):
        raise OSError('synthetic write failure')
    monkeypatch.setattr(jtree_mod.os, 'replace', fail)
    response = loaded_client.post('/api/save')
    assert response.status_code == 500, response.text
    assert open(sample_json_file, 'rb').read() == before


def test_failed_write_preserves_file(loaded_client, sample_json_file, monkeypatch):
    before = open(sample_json_file, 'rb').read()
    def fail(*args):
        raise OSError('synthetic write failure')
    monkeypatch.setattr(jtree_mod.os, 'fsync', fail)
    assert loaded_client.post('/api/save').status_code == 500
    assert open(sample_json_file, 'rb').read() == before


def test_process_death_during_write_preserves_original_and_metadata(tmp_path):
    target = tmp_path / 'original.json'
    target.write_bytes(b'{"original": "unchanged"}\n')
    subprocess.run(['xattr', '-w', 'org.jtree.synthetic', 'synthetic', str(target)], check=True)
    subprocess.run(['chmod', '+a', 'everyone allow read', str(target)], check=True)
    os.chmod(target, 0o640)
    before = target.read_bytes()
    before_stat = target.stat()
    before_acl = subprocess.check_output(['ls', '-le', str(target)], text=True).splitlines()[1:]
    repo = Path(__file__).resolve().parents[2]
    child = r'''
import builtins
import os
import sys

sys.path.insert(0, sys.argv[1])
from tools.testkit import load_launcher

module = load_launcher(os.path.join(sys.argv[1], 'jtree', 'jtree'))
target = sys.argv[2]
manager = module.JSONManager(target)
manager.data = {'replacement': 'a longer synthetic value'}
real_open = builtins.open
real_fdopen = os.fdopen

class InterruptedWrite:
    def __init__(self, stream):
        self.stream = stream

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, data):
        self.stream.write(data[:max(1, len(data) // 2)])
        self.stream.flush()
        os.write(2, b'partial write reached\n')
        os._exit(73)

def open_target(path, mode='r', *args, **kwargs):
    stream = real_open(path, mode, *args, **kwargs)
    if os.fspath(path) == target and any(flag in mode for flag in 'wax'):
        return InterruptedWrite(stream)
    return stream

def open_fd(fd, mode='r', *args, **kwargs):
    stream = real_fdopen(fd, mode, *args, **kwargs)
    return InterruptedWrite(stream) if 'w' in mode else stream

builtins.open = open_target
os.fdopen = open_fd
manager.save()
'''
    result = subprocess.run(
        [sys.executable, '-c', child, str(repo), str(target)],
        capture_output=True, timeout=30,
    )
    assert result.returncode == 73, result.stderr.decode(errors='replace')
    assert b'partial write reached\n' in result.stderr
    assert target.read_bytes() == before
    after_stat = target.stat()
    assert (after_stat.st_mode, after_stat.st_uid, after_stat.st_gid) == (
        before_stat.st_mode, before_stat.st_uid, before_stat.st_gid,
    )
    assert subprocess.check_output(['ls', '-le', str(target)], text=True).splitlines()[1:] == before_acl
    assert subprocess.check_output(['xattr', '-p', 'org.jtree.synthetic', str(target)], text=True).strip() == 'synthetic'
    staged = list(tmp_path.glob('.jtree-*'))
    assert len(staged) == 1
    assert 0 < len(staged[0].read_bytes()) < len(b'{"replacement": "a longer synthetic value"}')


def test_missing_copied_metadata_rejects_replacement(loaded_client, sample_json_file, monkeypatch):
    before = open(sample_json_file, 'rb').read()
    subprocess.run(['xattr', '-w', 'org.jtree.synthetic', 'synthetic', sample_json_file], check=True)
    monkeypatch.setattr(jtree_mod, '_copy_metadata', lambda src, dst: None)
    assert loaded_client.post('/api/save').status_code != 200
    assert open(sample_json_file, 'rb').read() == before


def test_save_preserves_darwin_metadata(loaded_client, sample_json_file):
    subprocess.run(['xattr', '-w', 'org.jtree.synthetic', 'synthetic', sample_json_file], check=True)
    subprocess.run(['chmod', '+a', 'everyone allow read', sample_json_file], check=True)
    os.chmod(sample_json_file, 0o640)
    before_acl = subprocess.check_output(['ls', '-le', sample_json_file], text=True).splitlines()[1:]
    response = loaded_client.post('/api/save')
    assert response.status_code == 200, response.text
    assert subprocess.check_output(['xattr', '-p', 'org.jtree.synthetic', sample_json_file], text=True).strip() == 'synthetic'
    assert subprocess.check_output(['ls', '-le', sample_json_file], text=True).splitlines()[1:] == before_acl
    assert os.stat(sample_json_file).st_mode & 0o777 == 0o640


def test_changed_save_advances_mtime_and_preserves_security_metadata(loaded_client, sample_json_file):
    subprocess.run(['xattr', '-w', 'org.jtree.synthetic', 'synthetic', sample_json_file], check=True)
    subprocess.run(['chmod', '+a', 'everyone allow read', sample_json_file], check=True)
    os.chmod(sample_json_file, 0o640)
    os.utime(sample_json_file, ns=(1_000_000_000, 1_000_000_000))
    assert loaded_client.post('/api/open', json={'path': sample_json_file}).status_code == 200
    before = os.stat(sample_json_file)
    before_acl = subprocess.check_output(['ls', '-le', sample_json_file], text=True).splitlines()[1:]
    assert loaded_client.put('/api/node', params={'path': '["name"]'}, json={'value': 'changed'}).status_code == 200
    response = loaded_client.post('/api/save')
    assert response.status_code == 200, response.text
    assert '"changed"' in open(sample_json_file).read()
    after = os.stat(sample_json_file)
    assert after.st_mtime_ns > before.st_mtime_ns
    assert (after.st_uid, after.st_gid, after.st_mode & 0o777) == (before.st_uid, before.st_gid, before.st_mode & 0o777)
    assert subprocess.check_output(['ls', '-le', sample_json_file], text=True).splitlines()[1:] == before_acl
    assert subprocess.check_output(['xattr', '-p', 'org.jtree.synthetic', sample_json_file], text=True).strip() == 'synthetic'


def test_metadata_copy_error_preserves_original(loaded_client, sample_json_file, monkeypatch):
    before = open(sample_json_file, 'rb').read()
    def fail(source, destination):
        raise OSError('synthetic metadata failure')
    monkeypatch.setattr(jtree_mod, '_copy_metadata', fail)
    response = loaded_client.post('/api/save')
    assert response.status_code == 500
    assert open(sample_json_file, 'rb').read() == before


def test_missing_copied_acl_rejects_replacement(loaded_client, sample_json_file, monkeypatch):
    before = open(sample_json_file, 'rb').read()
    subprocess.run(['chmod', '+a', 'everyone allow read', sample_json_file], check=True)
    copy_metadata = jtree_mod._copy_metadata
    def lose_acl(source, destination):
        copy_metadata(source, destination)
        subprocess.run(['chmod', '-N', destination], check=True)
    monkeypatch.setattr(jtree_mod, '_copy_metadata', lose_acl)
    response = loaded_client.post('/api/save')
    assert response.status_code == 500
    assert open(sample_json_file, 'rb').read() == before
    assert 'everyone allow read' in subprocess.check_output(['ls', '-le', sample_json_file], text=True)


def test_lossy_load_warns(client):
    response = client.post('/api/open-content', json={'content': '{"x": 1, "x": 2, "n": 1.234567890123456789}', 'fileName': 'synthetic.json'})
    assert response.status_code == 200
    assert response.json()['warning']


@pytest.mark.parametrize('content', ['{"n": 1e999}', '{"s": "\\ud800"}'])
def test_invalid_values_do_not_replace_open_document(loaded_client, content):
    before = loaded_client.get('/api/node').json()
    response = loaded_client.post('/api/open-content', json={'content': content, 'fileName': 'invalid.json'})
    assert response.status_code == 400
    assert loaded_client.get('/api/node').json() == before


@pytest.mark.parametrize('body', [b'{"value": 1e999}', b'{"value": "\\ud800"}'])
def test_invalid_mutations_do_not_change_open_document(loaded_client, body):
    before = loaded_client.get('/api/download').text
    response = loaded_client.put('/api/node', params={'path': '["name"]'}, content=body, headers={'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert loaded_client.get('/api/download').text == before
    assert not loaded_client.get('/api/status').json()['dirty']


def test_invalid_unicode_filename_does_not_replace_open_document(loaded_client):
    before = loaded_client.get('/api/node').json()
    response = loaded_client.post('/api/open-content', content=b'{"content":"{}","fileName":"\\ud800"}', headers={'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert loaded_client.get('/api/node').json() == before


def test_save_rejects_hardlinked_target(loaded_client, sample_json_file, tmp_path):
    linked = tmp_path / 'other-link.json'
    os.link(sample_json_file, linked)
    before = linked.read_bytes()
    assert loaded_client.post('/api/save').status_code != 200
    assert linked.read_bytes() == before
    assert os.stat(sample_json_file).st_ino == os.stat(linked).st_ino


def test_save_through_symlink_preserves_link(tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('{"a": 1}')
    link = tmp_path / 'link.json'
    link.symlink_to(target)
    manager = jtree_mod.JSONManager(str(link))
    manager.set_value(['a'], 2)
    manager.save()
    assert link.is_symlink()
    assert '2' in target.read_text()
