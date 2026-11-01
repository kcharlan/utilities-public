import os
import subprocess

import pytest

from conftest import jtree_mod


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
