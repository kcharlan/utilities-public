import pytest
from src.converters.yaml_conv import load_yaml


def test_alias_expansion_is_bounded():
    text = 'a: &a [x, x, x, x, x, x, x, x, x, x]\n'
    for previous, current in zip('abcde', 'bcdef'):
        text += f'{current}: &{current} [' + ', '.join([f'*{previous}'] * 10) + ']\n'
    with pytest.raises(ValueError, match='expansion'):
        load_yaml(text)


def test_small_aliases_remain_usable():
    assert load_yaml('a: &a [x, y]\nb: [*a, *a]\n')['b'] == [['x', 'y'], ['x', 'y']]


def test_recursive_alias_is_bounded():
    with pytest.raises(ValueError, match='expansion'):
        load_yaml('a: &a [*a]\n')


def test_merge_alias_expansion_is_bounded_before_construction():
    text = 'a: &a {x: y}\n'
    for previous, current in zip('abcdef', 'bcdefg'):
        text += f'{current}: &{current} {{<<: [' + ', '.join([f'*{previous}'] * 10) + ']}\n'
    with pytest.raises(ValueError, match='expansion'):
        load_yaml(text)
