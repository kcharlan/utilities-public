import os
from pathlib import Path

import pytest
import transcription_state as state
PROJECT_DIR = Path(__file__).resolve().parents[1]


def test_batch_is_private_and_outside_checkout():
    batch = state.new_upload_batch()
    try:
        assert batch.stat().st_mode & 0o777 == 0o700
        assert not batch.is_relative_to(PROJECT_DIR)
        assert not batch.is_relative_to(Path.cwd())
    finally:
        state.discard_upload_batch(batch)


@pytest.mark.parametrize('name', ['../escape.wav', 'a/b.m4a', '..', ''])
def test_write_upload_stays_in_batch(name):
    batch = state.new_upload_batch()
    try:
        path = state.write_upload(batch, 1, name, b'synthetic')
        assert path.parent == batch
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.read_bytes() == b'synthetic'
    finally:
        state.discard_upload_batch(batch)


def test_equal_names_do_not_collide():
    batch = state.new_upload_batch()
    try:
        a = state.write_upload(batch, 1, 'same.wav', b'a')
        b = state.write_upload(batch, 2, 'same.wav', b'b')
        assert a != b and a.read_bytes() == b'a' and b.read_bytes() == b'b'
    finally:
        state.discard_upload_batch(batch)


def test_discard_tolerates_none_and_absence(tmp_path):
    state.discard_upload_batch(None)
    state.discard_upload_batch(tmp_path / 'absent')
