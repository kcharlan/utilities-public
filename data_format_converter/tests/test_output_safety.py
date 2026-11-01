import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import data_convert
from converters.xml_conv import dump_xml, load_xml


@pytest.mark.parametrize('alias', ['same', 'symlink', 'hardlink'])
def test_input_alias_is_refused(tmp_path, alias):
    source = tmp_path / 'source.json'
    source.write_text('{"value": "synthetic"}')
    dest = source if alias == 'same' else tmp_path / 'output.json'
    if alias == 'symlink':
        dest.symlink_to(source)
    elif alias == 'hardlink':
        os.link(source, dest)
    with pytest.raises(SystemExit):
        data_convert.main(['--input', str(source), '--to', 'jsonc', '--output', str(dest)])
    assert source.read_text() == '{"value": "synthetic"}'


def test_replace_failure_preserves_destination(tmp_path):
    source = tmp_path / 'source.json'
    dest = tmp_path / 'output.json'
    source.write_text('{"value": "synthetic"}')
    dest.write_text('old destination')
    with patch('data_convert.os.replace', side_effect=OSError('synthetic failure')):
        with pytest.raises(SystemExit) as error:
            data_convert.main(['--input', str(source), '--to', 'json', '--output', str(dest)])
    assert error.value.code == 5
    assert dest.read_text() == 'old destination'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['output.json', 'source.json']


def test_default_output_cannot_replace_input(tmp_path, monkeypatch):
    source = tmp_path / 'source.json'
    source.write_text('{"value": "synthetic"}')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        data_convert.main(['--input', 'source.json', '--to', 'jsonc'])
    assert source.read_text() == '{"value": "synthetic"}'


def test_xml_special_text_round_trips():
    value = 'synthetic <tag> & "quoted"'
    assert load_xml(dump_xml({'root': {'value': value}})) == {'root': {'value': value}}


@pytest.mark.parametrize('name', ['bad name', 'item attr="synthetic"'])
def test_invalid_xml_element_name_is_rejected(name):
    with pytest.raises(ValueError):
        dump_xml({'root': {name: 'synthetic'}})
