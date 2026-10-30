#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.16"
# dependencies = []
# ///
"""Package a staged Model Sentinel source tree as the standalone zipapp.

`install_standalone.sh` stages the source and runs this script through uv, so
the build runs on an interpreter uv selects from the header above rather than
whatever `python3` is first on PATH. The archive itself still starts with
`/usr/bin/env python3`: the standalone runtime is stdlib-only.
"""

from __future__ import annotations

import argparse
import zipapp
from pathlib import Path

STANDALONE_INTERPRETER = "/usr/bin/env python3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="staged source directory containing __main__.py")
    parser.add_argument("target", type=Path, help="archive path to write")
    args = parser.parse_args(argv)
    zipapp.create_archive(args.source, args.target, interpreter=STANDALONE_INTERPRETER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
