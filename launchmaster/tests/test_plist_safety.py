import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import plistlib
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import load_launcher


@pytest.fixture
def lm(tmp_path, monkeypatch):
    monkeypatch.setenv('LAUNCHMASTER_HOME', str(tmp_path / 'home'))
    module = load_launcher(Path(__file__).resolve().parents[1] / 'launchmaster')
    jobs = tmp_path / 'jobs'
    jobs.mkdir()
    monkeypatch.setattr(module, 'PLIST_DIRS', {'user-agent': str(jobs)})
    async def load(*args):
        return {'success': True, 'message': 'stubbed'}
    async def refresh():
        pass
    monkeypatch.setattr(module, 'load_job', load)
    monkeypatch.setattr(module, '_refresh_jobs', refresh)
    monkeypatch.setattr(module, 'get_launchctl_state', lambda: {})
    monkeypatch.setattr(module, 'get_disabled_labels', lambda: set())
    return module, jobs


def run_async(coro):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def xml(label, **extra):
    return plistlib.dumps({'Label': label, **extra}).decode()


def test_containment_and_overwrite_backups(lm, tmp_path):
    m, jobs = lm
    for label in ('../escape', ['bad'], '/absolute'):
        assert not run_async(m.create_job({'Label': label}, 'user-agent'))['success']
        assert not run_async(m.import_job(xml(label), 'user-agent'))['success']
    outside = tmp_path / 'outside.plist'
    outside.write_text(xml('outside', Program='unchanged'))
    (jobs / 'com.example.link.plist').symlink_to(outside)
    assert not run_async(m.import_job(xml('com.example.link'), 'user-agent'))['success']
    target = jobs / 'com.example.fake.plist'
    target.write_text(xml('com.example.fake', Program='old'))
    assert run_async(m.import_job(xml('com.example.fake', Program='new'), 'user-agent'))['success']
    backup = next(Path(m.BACKUP_DIR).glob('*.plist'))
    assert plistlib.loads(backup.read_bytes())['Program'] == 'old'
    backup.write_text(xml('../escape'))
    result = run_async(m.api_restore_backup(backup.name))
    assert not result['success']
    backup.write_text(xml('com.example.link'))
    assert not run_async(m.api_restore_backup(backup.name))['success']
    assert plistlib.loads(outside.read_bytes())['Program'] == 'unchanged'
    backup.write_text(xml('com.example.fake', Program='restored'))
    assert run_async(m.api_restore_backup(backup.name))['success']
    assert any(plistlib.loads(p.read_bytes()).get('Program') == 'new' for p in Path(m.BACKUP_DIR).glob('*.plist'))
    assert not (tmp_path / 'escape.plist').exists()


def test_atomic_symlink_save_and_unique_backups(lm, tmp_path, monkeypatch):
    m, jobs = lm
    target = jobs / 'real.plist'
    target.write_text(xml('com.example.fake'))
    link = jobs / 'link.plist'
    link.symlink_to(target)
    first = m.backup_plist(str(target))
    second = m.backup_plist(str(target))
    assert first != second
    replace = m.os.replace
    calls = []
    def recording_replace(src, dst):
        calls.append(dst)
        replace(src, dst)
    monkeypatch.setattr(m.os, 'replace', recording_replace)
    assert run_async(m.save_plist(str(link), xml('com.example.fake', Program='new')))['success']
    assert link.is_symlink()
    assert calls == [str(target.resolve())]
    assert plistlib.loads(target.read_bytes())['Program'] == 'new'


def test_bad_plists_do_not_hide_good_jobs(lm):
    m, jobs = lm
    (jobs / 'good.plist').write_text(xml('com.example.good'))
    (jobs / 'bad.plist').write_text('invalid')
    (jobs / 'label.plist').write_text(xml(['unhashable']))
    (jobs / 'calendar.plist').write_text(xml('com.example.calendar', StartCalendarInterval={'Hour': 'bad', 'Weekday': []}))
    result = m.build_job_list()
    assert any(j['label'] == 'com.example.good' for j in result)
    assert any(j['parse_error'] for j in result)


def test_invalid_poll_settings_and_continued_polling(lm, monkeypatch):
    m, _ = lm
    Path(m.DATA_DIR).mkdir()
    Path(m.CONFIG_FILE).write_text(json.dumps({'poll_interval': 'x'}))
    assert m._load_config()['poll_interval'] == 5
    response = run_async(m.api_put_settings({'poll_interval': 'x'}))
    assert response.status_code == 400
    calls = []
    async def sleep(interval):
        calls.append(interval)
        if len(calls) == 2:
            raise asyncio.CancelledError()
    monkeypatch.setattr(m.asyncio, 'sleep', sleep)
    m._config = {'poll_interval': 'x'}
    with pytest.raises(asyncio.CancelledError):
        run_async(m._poll_loop())
    assert calls == [5, 5]


def test_log_reads_are_bounded(lm, tmp_path, monkeypatch):
    m, _ = lm
    path = tmp_path / 'fake.log'
    path.write_text('first\nsecond\nthird\n')
    assert run_async(m.read_log_file(str(path), 2)) == ['second', 'third']
    assert run_async(m.read_log_file(str(path), 0)) == []
    path.write_text('x' * (2 * 1024 * 1024) + '\n' + 'line\n' * 1500)
    lines = run_async(m.read_log_file(str(path), 10000000))
    assert lines == ['line'] * 1000
    path.write_text('x' * (2 * 1024 * 1024))
    assert len(run_async(m.read_log_file(str(path), 1))[0]) == 1024 * 1024


def test_blank_poll_field_is_rejected(server, page):
    page.goto(server, wait_until='networkidle')
    page.locator('.topbar-right .icon-btn').last.click()
    modal = page.locator('.modal')
    modal.locator("input[type='number']").fill('')
    modal.get_by_role('button', name='Save & Close').click()
    expect(modal).to_be_visible()
    expect(page.locator('.toast.error')).to_contain_text('Poll interval')
