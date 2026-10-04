"""Offline asset, license and theme contracts for the embedded shell."""
import base64
import re
import hashlib
import zipfile
from pathlib import Path

import pytest
from tools.testkit import load_launcher

ROOT = Path(__file__).resolve().parents[1]
NAMED = r'\b(?:white|black|red|green|blue|yellow|orange|purple|gray|grey|silver|lime|navy|teal|aqua|fuchsia|maroon|olive)\b'


def test_theme_uses_one_complete_token_block(colophon):
    css = colophon.PAGE_CSS.strip()
    assert css.startswith('/* tokens:start */')
    assert css.count('/* tokens:start */') == css.count('/* tokens:end */') == 1
    block, rest = css.split('/* tokens:end */')
    names = 'bg grid-line panel line line-soft dim muted ws txt hi g amb sel hover chip-line tag-line fchip-bg fchip-line tool-bg tool-line heat-0 heat-1 heat-2 heat-3 heat-4 bar-from bar-to tl-turn tl-sub focus'.split()
    assert set(re.findall(r'(--[\w-]+)\s*:', block)) == {'--' + n for n in names}
    for asset in (rest, colophon.PAGE_JS):
        assert not re.search(r'#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(', asset)
    for value in re.findall(r':([^;{}]+)[;}]', rest):
        assert not re.search(NAMED, value, re.I)
    for string in re.findall(r'"([^"\n]*)"|\x27([^\x27\n]*)\x27', colophon.PAGE_JS):
        assert not re.search(NAMED, ' '.join(string), re.I)
    assert 'getComputedStyle(document.documentElement)' in colophon.PAGE_JS
    assert 'getPropertyValue' in colophon.PAGE_JS


def test_assets_have_unique_placeholders_and_safe_dom(colophon):
    for marker in ('@@DATA@@', '/*@@CSS@@*/', '/*@@FONTS@@*/', '/*@@JS@@*/'):
        assert colophon.PAGE_TEMPLATE.count(marker) == 1
        for asset in (colophon.PAGE_CSS, colophon.FONT_CSS, colophon.PAGE_JS):
            assert marker not in asset
    for asset in (colophon.PAGE_CSS, colophon.FONT_CSS, colophon.PAGE_JS):
        assert '"""' not in asset
    assert not re.search(r'innerHTML|outerHTML|insertAdjacentHTML|document\.write', colophon.PAGE_JS)
    blocks = re.findall(r'// --- ([^\n]+)', colophon.PAGE_JS)
    expected = ['data', 'time', 'state', 'filters', 'aggregates', 'format', 'dom', 'views/overview', 'views/list', 'views/reader', 'boot']
    assert [b for b in blocks if b in expected] == expected


def test_embedded_font_license_and_three_static_weights(colophon):
    assert (ROOT / 'OFL.txt').exists()
    license_text = (ROOT / 'OFL.txt').read_text()
    assert '*/' not in license_text
    assert colophon.FONT_CSS.startswith('/*' + license_text + '*/')
    faces = re.findall(r'@font-face\s*\{([^}]+)\}', colophon.FONT_CSS)
    assert len(faces) == 3
    for face, weight in zip(faces, (300, 400, 500)):
        assert f'font-weight: {weight}' in face
        encoded = re.search(r'data:font/woff2;base64,([A-Za-z0-9+/=]+)', face).group(1)
        assert base64.b64decode(encoded, validate=True).startswith(b'wOF2')


def test_font_tool_rejects_changed_public_inputs(tmp_path, monkeypatch):
    tool = load_launcher(ROOT / 'tests/tools/subset_font.py')
    archive, ofl = tmp_path / 'synthetic-font.zip', tmp_path / 'synthetic-OFL.txt'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('synthetic-font.ttf', b'Synthetic font bytes')
    ofl.write_text('Synthetic license')
    with pytest.raises(ValueError, match='release archive SHA-256'):
        tool.font_css(archive, ofl)
    monkeypatch.setattr(tool, 'ASSET_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='license SHA-256'):
        tool.font_css(archive, ofl)


def test_font_license_matches_pinned_approved_source():
    assert hashlib.sha256((ROOT / 'OFL.txt').read_bytes()).hexdigest() == 'ddafd2c3f37ef1d83ef284ca63e159befd3820850c5e9eded14ca52eee92c256'
