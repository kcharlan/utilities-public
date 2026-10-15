# Standalone validation

Claude cases cover filename identity/collisions, prompt and tool mapping,
root selection and symlink exclusions, read-only usable-history presence,
mixed/disabled providers, and preservation of unopened Codex cache bytes,
modes and recovery names during ordinary and rebuild runs. The reader
browser case prevents Claude rows from offering Codex actions. Wrappers
strip `CLAUDE_CONFIG_DIR`, deny real Claude-owned config/desktop/swap reads
and writes, and mutation-check each explicit deny under synthetic scratch.

Run `make test` for all retained C units, fresh synthetic CLI and integration
checks, Chromium browser cases, and local
asset/stable-sort guards (twelve asset digests).
Run `make sanitize` for the same categories with ASan/UBSan, `make tsan` for
the retained C units with TSan, and `make check-assets` for local digest checks.
These checks are independent acceptance checks, not captured-corpus parity or
performance evidence from the source project.

Compressed-log cases cover the pinned zstd decoder, concatenated frames,
large declared windows, exact output-buffer boundaries, empty files,
unterminated lines and unreadable corrupt/truncated/trailing data, including
a log that shrinks at a completed-frame boundary after discovery. Discovery
prefers a plain sibling and preserves compressed filename UUID/title
fallbacks. CLI cases cover active/archived compressed logs, cold/warm/rebuild
cache behavior, input preservation and nonfatal skipped-file diagnostics.

Request-ledger cases cover chronological near-before-exact ownership, exact
matching across boundaries, counter/history/restart rules, file-local replay,
session-wide response counts, and cross-copy paired/record/observation aliases.
Already-owned repeated snapshots preserve another response's pending partner.
The CLI cases verify mirrored requests count once while unmatched snapshots in
the same turn remain counted, including later exact duplicates without totals.
Thread-settings tests cover trimmed tiers, invalid/missing tiers and timestamps,
cache round trips, persistence and same-turn resumes, turnless starts, ledger
rows and file-local bare rows. The CLI checks the resulting Fast multiplier cost
and priority bucket.

Individual categories are `make test-unit`, `make test-cli` and
`make test-browser`; `make check-sort` runs the stable-sort guard. See
[development](../docs/development.md) for environment setup. Help lists the
shipped standalone checks; historical parity/performance tooling is unavailable.

Create `.venv` only if absent using the absolute Homebrew Python 3.14 interpreter.
Install `requirements-dev.txt` into this project's venv, trying the offline cache
first. Downloads require approval. Existing cached Playwright Chromium is reused.
The test wrappers execute Python with `-B`, disable bytecode and pytest caches,
and select an absolute release executable through `COLOPHON_BIN`. A sanitizer
run selects its instrumented release executable through the same interface.

The sandbox allows active project/binary/dependency reads, denies project and
real runtime writes, and denies reads/writes of protected historical checkouts.
Regression checks read active source/binary bytes, write only scratch data and
evaluate source and real-home write policies without creating canaries. The
wrapper proves the explicit `PROJECT_DIR` deny independently under canonical
scratch: the protected profile passes and removal of that deny fails. Both
profiles run in separate sandbox invocations, with output trapped under `/tmp`.
Fixtures create fresh
synthetic homes and logs under `/tmp`, with private runtime modes checked.
Offline CLI runs disable browser opening; the catalog case serves only an
invented loopback endpoint. Browser cases open native-generated `file://` HTML,
block external requests and native action links, and fail on browser errors.
`browser_errors.py` preserves the bounded synchronous guard implementation from
the repository's `tools/testkit.py` without importing shared launcher helpers.

Claude store checks in `test_claude_store.py` and the retained C codec/store
units cover cold/warm/rebuild accounting, strict deletion proof, removed search
roots and descendants, partial traversal, root-wide commit rechecks, failed page
output, interrupted partial commits, empty/malformed live files, restoration,
retained/live response deduplication, last-known sidecars, extraction price
snapshots and source byte/mode preservation. Immutable synthetic CLCD1 decoder
inputs in `fixtures/claude_codec/` are copied to scratch before decoding. They
are the narrow exception to the runtime-fixtures-in-scratch rule.
