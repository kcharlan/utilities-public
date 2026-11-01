import io
import logging

import pytest
from fastapi import HTTPException
from openpyxl import Workbook, load_workbook

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import load_launcher

def load_module(monkeypatch, runtime_home):
    monkeypatch.setenv("EXPENSE_DOCK_HOME", str(runtime_home))
    return load_launcher(Path(__file__).resolve().parents[1] / "expense_dock")


def payload(**changes):
    result = dict(date='2030-01-02', vendor='SYNTHETIC', amount='10', category='SYNTHETIC',
                  business_purpose='SYNTHETIC', paid_by='SYNTHETIC', payment_method='SYNTHETIC',
                  reimbursable='Yes', reimbursement_status='SYNTHETIC', notes='=1+1')
    result.update(changes)
    return result


@pytest.mark.parametrize('amount', ['nan', 'inf', '-inf', '1e999'])
def test_nonfinite_amount_rejected(monkeypatch, tmp_path, amount):
    module = load_module(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc:
        module.parse_submission(payload(amount=amount))
    assert exc.value.status_code == 400


def test_workbook_text_is_literal(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Expense Log'
    ws.append(module.EXPECTED_HEADERS)
    source = io.BytesIO()
    wb.save(source)
    submission = module.parse_submission(payload(vendor='=1+1'))
    output, _, _ = module.append_expense_row(source.getvalue(), 'Expense Log', submission,
                                               'https://example.test/receipt', 'synthetic.pdf')
    saved = load_workbook(io.BytesIO(output), data_only=False)['Expense Log']
    assert saved.cell(2, 3).value == '=1+1'
    assert saved.cell(2, 3).data_type == 's'
    assert saved.cell(2, 13).data_type == 's'


def test_receipt_name_distinguishes_content_and_is_stable(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    submission = module.parse_submission(payload())
    first = module.build_receipt_filename(submission, 'synthetic.pdf', b'first synthetic')
    assert first == module.build_receipt_filename(submission, 'synthetic.pdf', b'first synthetic')
    assert first != module.build_receipt_filename(submission, 'synthetic.pdf', b'second synthetic')


def test_httpx_does_not_log_upload_urls(monkeypatch, tmp_path):
    monkeypatch.setattr(logging.getLogger('httpx'), 'level', logging.INFO)
    load_module(monkeypatch, tmp_path)
    assert logging.getLogger('httpx').getEffectiveLevel() >= logging.WARNING


def test_interactive_login_has_timeout(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    class Client:
        def acquire_token_interactive(self, **kwargs):
            assert 0 < kwargs['timeout'] <= 300
            return {'access_token': 'SYNTHETIC'}
    monkeypatch.setattr(module, 'load_token_cache', lambda: object())
    monkeypatch.setattr(module, 'build_public_client', lambda *args: Client())
    monkeypatch.setattr(module, 'persist_token_cache', lambda cache: None)
    module.interactive_login({'client_id': 'SYNTHETIC'})


def test_receipt_filename_is_bounded_for_unicode_and_unsafe_extension(monkeypatch, tmp_path):
    import hashlib
    module = load_module(monkeypatch, tmp_path)
    submission = module.parse_submission(payload(vendor='SYNTHETIC' + '界' * 300,
                                                  business_purpose='TEST' * 300))
    content = b'SYNTHETIC CONTENT'
    name = module.build_receipt_filename(submission, 'receipt.' + '界' * 300, content)
    assert len(name.encode('utf-8')) <= 240
    assert name.startswith('2030-01-02_SYNTHETIC')
    assert name.endswith('_' + hashlib.sha256(content).hexdigest() + '.bin')
    assert '/' not in name and '\\' not in name
    short_ext = module.build_receipt_filename(submission, 'receipt.pdf', content)
    assert len(short_ext.encode('utf-8')) <= 240
    assert short_ext.endswith('_' + hashlib.sha256(content).hexdigest() + '.pdf')


def test_retry_preserves_legacy_receipt_filename(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    name = '2030-01-02_SYNTHETIC_10.00_SYNTHETIC.pdf'
    entry = {'submission': module.parse_submission(payload()), 'receipt_filename': name,
             'receipt_link': 'https://example.test/receipt'}
    workbook = Workbook()
    workbook.active.title = 'Expense Log'
    workbook.active.append(module.EXPECTED_HEADERS)
    buffer = io.BytesIO()
    workbook.save(buffer)
    class Graph:
        def __init__(self, token): self.saved = None
        def get_item_etag(self, *args): return '"synthetic"'
        def download_item_content(self, *args): return buffer.getvalue()
        def upload_item_content(self, drive, item, content, content_type, etag):
            saved = load_workbook(io.BytesIO(content))['Expense Log']
            assert saved.cell(2, 12).value == name
        def close(self): pass
    deleted = []
    monkeypatch.setattr(module, 'load_pending_operation', lambda operation_id: entry)
    monkeypatch.setattr(module, 'get_access_token', lambda config: 'SYNTHETIC')
    monkeypatch.setattr(module, 'GraphClient', Graph)
    monkeypatch.setattr(module, 'resolve_root_and_workbook', lambda *args: (None, {'id': 'SYNTHETIC'}, 'SYNTHETIC'))
    monkeypatch.setattr(module, 'delete_pending_operation', deleted.append)
    result = module.retry_pending_operation({'worksheet_name': 'Expense Log'}, 'abcdef123456')
    assert result['ok'] and result['receipt_filename'] == name
    assert deleted == ['abcdef123456']
