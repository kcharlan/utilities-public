# Development and validation

Release prerequisites and commands are in the [README](../README.md).
The full standalone suite uses macOS `sandbox-exec`, ripgrep, the project's
own Python 3.14 virtual environment, pytest 9.1.1, Playwright 1.63.0 and
cached Playwright Chromium. Release builds do not require those Python tools.

Create `.venv` only if absent, using an absolute Homebrew interpreter:

```sh
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv
.venv/bin/python -m pip install --no-index -r requirements-dev.txt
```

Try an available offline wheel source/cache first; `--no-index` does not
discover arbitrary cached wheels automatically. If packages are unavailable,
obtain approval before `.venv/bin/python -m pip install -r requirements-dev.txt`.
Browser downloads likewise require approval before
`.venv/bin/python -m playwright install chromium`. Existing Chromium in
`~/Library/Caches/ms-playwright` is reused. Never borrow another project's
venv or recreate an existing one. The approved setup for this clean project
uses the pinned packages in [requirements-dev.txt](../requirements-dev.txt).

```sh
make test
make sanitize
make tsan
make check-assets
make check-sort
```

`make test` runs the stable-sort guard, ten asset digests, all 130
C units, 20 collected CLI/integration cases and two Chromium cases.
`make sanitize` runs those same categories under ASan/UBSan;
`make tsan` covers all retained C units, including concurrency assertions.
Category targets are `make test-unit`, `make test-cli` and `make test-browser`.
These are standalone checks, not historical parity coverage or performance
evidence. The inherited help statement about native parity/performance tools
and explicit `private/` destinations describes the source project's tooling;
neither those tools nor their workflow is included here.

The [tests README](../tests/README.md) describes fixtures and browser guards.
Wrappers create invented homes/logs under `/tmp`, select the tested release
through `COLOPHON_BIN`, disable Python bytecode/pytest caches, and deny real
runtime/project writes and reads/writes of the source native checkouts and
sibling Python reference. Compilation precedes sandboxed runtime validation.
Keep all temporary data, reports and execution evidence outside the public
checkout; do not introduce real session data even into ignored directories.

Sandbox lesson: inherited macOS `TMPDIR` commonly points under `/var/folders`.
C `tmpfile()` followed that location and failed when the strict profile
allowed only `/tmp` scratch writes. Both wrappers now explicitly select
their fresh scratch directory as `TMPDIR`. Preserve this setting and the
sandbox boundary instead of widening writes to system temporary directories.

Optional Unicode maintenance uses
`.venv/bin/python -B tools/gen_unicode.py src/gen` only as a deliberate
maintainer action, with `PYTHONDONTWRITEBYTECODE=1` and Unicode 16.0.0.
Python 3.14's `unicodedata` must report that exact version; the generator
rejects other versions. Normal builds consume committed tables. This
generator must not regenerate the separate Unicode 17 pricing Numeric,
Extend/SpacingMark/ZWJ and Prepend ranges.

Asset refresh, font subsetting and public pricing updates are deliberate
maintainer actions requiring provenance review and the full suite; they are
not build steps or part of a private-state migration. No font generator or
historical pricing updater is shipped here. Preserve [notices](../THIRD_PARTY.md)
and the asset manifest when deliberately updating embedded inputs.

Pricing lesson: an incorrectly seeded long-context threshold must be corrected
in every existing curated-history row, not only in the resolver or a new dated
row; dated lookup otherwise keeps earlier usage incorrectly priced. Validate
raw tier keys/types and rate underflow in both catalog tier locations before
sanitization, and decode the complete array even after finding a matching tier.
