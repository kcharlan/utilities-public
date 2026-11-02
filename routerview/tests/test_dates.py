import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime, timezone

from test_csv_import import build_client, load_module


def test_previous_month_clamps_day(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    assert module._prev_month(datetime(2024, 3, 31)).day == 29


def test_last_year_on_leap_day(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 2, 29, tzinfo=timezone.utc)
    monkeypatch.setattr(module, 'datetime', Clock)
    assert module.parse_time_range('last_year', None, None, 'UTC')[0].startswith('2023-01-01')


def test_timeseries_export_and_historical_timezone(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    client, db_path = build_client(module, tmp_path)
    import sqlite3
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO generations (id, created_at, created_date, created_hour, cost_usd, model, model_short, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ('fake-1', '2024-01-01T04:30:00+00:00', '2024-01-01', 4, 1, 'fake-model', 'fake-model', '2024-01-01'))
    params = {'range': 'all', 'tz': 'America/New_York', 'bucket': 'day', 'group_by': 'none'}
    series = client.get('/api/timeseries', params=params).json()
    assert series['buckets'] == ['2023-12-31']
    exported = client.get('/api/export/csv', params={**params, 'view': 'timeseries'})
    assert '2023-12-31' in exported.text


def test_heatmap_converts_each_historical_timestamp(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    client, db_path = build_client(module, tmp_path)
    import sqlite3
    with sqlite3.connect(db_path) as db:
        for ident, created in [('fake-winter', '2024-01-01T04:30:00+00:00'), ('fake-summer', '2024-07-01T04:30:00+00:00')]:
            db.execute('INSERT INTO generations (id, created_at, created_date, created_hour, model, model_short, ingested_at) VALUES (?, ?, ?, 4, ?, ?, ?)', (ident, created, created[:10], 'fake', 'fake', created))
    matrix = client.get('/api/heatmap', params={'range': 'all', 'tz': 'America/New_York', 'metric': 'requests'}).json()['matrix']
    assert matrix[0][23] == 1
    assert matrix[1][0] == 1
