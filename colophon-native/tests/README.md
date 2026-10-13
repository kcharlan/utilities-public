# Standalone validation

Run `make test` for all 167 C units, fresh synthetic CLI and integration
checks (22 collected cases), two Chromium browser cases, and local
asset/stable-sort guards (ten asset digests).
Run `make sanitize` for the same categories with ASan/UBSan, `make tsan` for
the retained C units with TSan, and `make check-assets` for local digest checks.
These checks are independent acceptance checks, not captured-corpus parity or
performance evidence from the source project.

Request-ledger cases cover chronological near-before-exact ownership, exact
matching across boundaries, counter/history/restart rules, file-local replay,
session-wide response counts, and cross-copy paired/record/observation aliases.
Already-owned repeated snapshots preserve another response's pending partner.
The CLI cases verify mirrored requests count once while unmatched snapshots in
the same turn remain counted, including later exact duplicates without totals.

Individual categories are `make test-unit`, `make test-cli` and
`make test-browser`; `make check-sort` runs the stable-sort guard. See
[development](../docs/development.md) for environment setup and the inherited
help statement's reference to unavailable historical acceptance tools.

Create `.venv` only if absent using the absolute Homebrew Python 3.14 interpreter.
Install `requirements-dev.txt` into this project's venv, trying the offline cache
first. Downloads require approval. Existing cached Playwright Chromium is reused.
The test wrappers execute Python with `-B`, disable bytecode and pytest caches,
and select an absolute release executable through `COLOPHON_BIN`. A sanitizer
run selects its instrumented release executable through the same interface.

The sandbox denies project and real runtime writes, and reads/writes of both
old native checkouts and the sibling Python reference. Fixtures create fresh
synthetic homes and logs under `/tmp`, with private runtime modes checked.
Offline CLI runs disable browser opening; the catalog case serves only an
invented loopback endpoint. Browser cases open native-generated `file://` HTML,
block external requests and native action links, and fail on browser errors.
`browser_errors.py` preserves the bounded synchronous guard implementation from
the repository's `tools/testkit.py` without importing shared launcher helpers.
