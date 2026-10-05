"""Print reproducible FONT_CSS from the pinned public release and OFL inputs.

This development-only program reads explicit local inputs, performs no fetch,
and never writes into the checkout. Run with the project's virtual environment.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ASSET_SHA256 = '483aa2d201a6c44610c0bdcf65eaf425b467d61e9ab606213eacef3e216c2a12'
OFL_SHA256 = 'ddafd2c3f37ef1d83ef284ca63e159befd3820850c5e9eded14ca52eee92c256'
UNICODES = 'U+0020-007E,U+00A0-00FF,U+2010-2027,U+2030-203A,U+2190-2193,U+2197,U+2212,U+2264-2265,U+2315,U+2318,U+25B2-25BC,U+2713'
FACES = [('MartianMono-StdLt.ttf', 300), ('MartianMono-StdRg.ttf', 400), ('MartianMono-StdMd.ttf', 500)]


def font_css(archive: Path, ofl: Path) -> str:
    asset, license_bytes = archive.read_bytes(), ofl.read_bytes()
    for label, value, expected in [('release archive', asset, ASSET_SHA256), ('license', license_bytes, OFL_SHA256)]:
        if hashlib.sha256(value).hexdigest() != expected:
            raise ValueError(f'{label} SHA-256 does not match the pinned v1.1.0 input')
    license_text = license_bytes.decode('utf-8')
    if '*/' in license_text:
        raise ValueError('License cannot be embedded as a CSS comment')
    css = ['/*' + license_text + '*/']
    with tempfile.TemporaryDirectory(prefix='colophon-subset-') as directory, zipfile.ZipFile(io.BytesIO(asset)) as release:
        root = Path(directory)
        for filename, weight in FACES:
            source = root / filename
            source.write_bytes(release.read(filename))
            output = source.with_suffix('.woff2')
            subprocess.run([sys.executable, '-m', 'fontTools.subset', str(source), '--flavor=woff2', '--layout-features=*', '--unicodes=' + UNICODES, '--output-file=' + str(output)], check=True)
            encoded = base64.b64encode(output.read_bytes()).decode('ascii')
            css.append('@font-face { font-family: "Martian Mono"; font-style: normal; font-weight: ' + str(weight) + '; font-display: swap; src: url(data:font/woff2;base64,' + encoded + ') format("woff2"); }')
    return '\n'.join(css)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--ofl', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(font_css(args.archive, args.ofl))
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'colophon-subset: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
