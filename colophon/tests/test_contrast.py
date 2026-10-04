"""WCAG AA over the exact thirty approved text/background token pairs."""
import re

import pytest


TEXT = ('--txt', '--hi', '--dim', '--muted', '--ws', '--g', '--amb')
BACKGROUNDS = ('--bg', '--panel', '--sel', '--hover')
PAIRS = [(text, background) for text in TEXT for background in BACKGROUNDS] + [
    ('--bg', '--g'), ('--g', '--fchip-bg')]


def tokens(css):
    block = re.search(r'/\* tokens:start \*/(.*?)/\* tokens:end \*/', css, re.S).group(1)
    return dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);', block))


def rgb(name, values):
    value = values[name].strip()
    if value.startswith('var('):
        return rgb(value[4:-1], values)
    assert re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', value), value
    channels = tuple(int(value[n:n+2], 16)/255 for n in (1, 3, 5))
    if len(value) == 9:
        alpha = int(value[7:9], 16)/255
        base = rgb('--bg', values)
        return tuple(channel*alpha + under*(1-alpha) for channel, under in zip(channels, base))
    return channels


def luminance(channels):
    linear = [x/12.92 if x <= .04045 else ((x+.055)/1.055)**2.4 for x in channels]
    return sum(channel*weight for channel, weight in zip(linear, (.2126, .7152, .0722)))


@pytest.mark.parametrize('text,background', PAIRS)
def test_declared_text_pairs_meet_wcag_aa(colophon, text, background):
    values = tokens(colophon.PAGE_CSS)
    light, dark = sorted((luminance(rgb(text, values)), luminance(rgb(background, values))), reverse=True)
    ratio = (light+.05)/(dark+.05)
    assert ratio >= 4.5, f'{text} on {background}: {ratio:.6f}:1 < 4.5:1'


def test_alpha_is_composited_over_page_before_luminance(colophon):
    values = tokens(colophon.PAGE_CSS)
    base = rgb('--bg', values)
    assert rgb('--grid-line', values) == pytest.approx(tuple(4/255 + x*(251/255) for x in base))
    assert luminance((0, 0, 0)) == 0
    assert luminance((1, 1, 1)) == 1
    assert len(PAIRS) == len(set(PAIRS)) == 30


def test_every_color_token_has_valid_relative_luminance(colophon):
    values = tokens(colophon.PAGE_CSS)
    for name in values:
        assert 0 <= luminance(rgb(name, values)) <= 1, name
