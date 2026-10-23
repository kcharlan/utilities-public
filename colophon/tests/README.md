# Standalone validation

Antigravity reader units and `test_antigravity.py` create only invented UUID
databases/annotations in external private scratch. `fixtures/antigravity/`
contains only the public qualified protobuf schema projection with its producing
binary SHA-256, an exception analogous to OpenCode's public DDL fixture.
The reader tests cover wire bounds/types/unknown fields and repeated integers,
empty/zero-step databases, malformed-record isolation, transaction rollback,
independent metadata identities, archive defaults/precedence/fallback, surface
duplicates, title-only summaries, lock failures, large unrelated database data,
source database/WAL/annotation byte/mode preservation and unopened Codex caches.
The corpus acceptance case asserts source counts, runtime initialization and
zero-turn sessions while every other provider is disabled/absent.
Regressions bound FIFO/directory sidecar checks for both database kinds, merge
repeated singular summary annotations, and preserve usage/payload blobs under
malformed optional SQL enums while rejecting invalid row indexes. Raw enum
states distinguish valid integers, absent NULLs and invalid dynamic types.
Privacy canaries exercise unrelated tables/settings and excluded prompt/thinking
text. Wrappers strip all three ignored Antigravity environment names and deny
real Gemini root reads/writes. A separate mutation invocation proves removing
that explicit deny fails the policy regression under existing canonical scratch.

Antigravity corpus units pin every descriptor status, mixed error/cancellation
precedence, earlier/final turns, missing completion and quiet thresholds; SQL
enum authority, explicit payload fallback and conflicts; pre-prompt steps,
zero-step sessions, singular nested-message merges, prompt/image/answer rules,
MCP/tool mapping and malformed arguments, workspace URI decoding and retained
git roots, parentless subagents and cross-provider collisions. Native cases cover
archived/unarchived sessions on all surfaces, summary-only archive, annotation
default false, mixed/disabled providers and repeated empty composition/refresh.
Chromium cases cover source filters/KPIs/calendar/workspaces, APP/CLI/IDE tags,
capabilities and copy, source remedies, independent database footer state,
4.5:1 provider contrast and 375px overflow, with browser-error/request guards.
Set COLOPHON_SCREENSHOT_DIR to fresh private external scratch to retain the
synthetic app overview/list/reader images during that browser case.

`test_antigravity_ccusage_usage_oracle` and the output/model C cases retain
self-contained, invented expectations captured from native ccusage 20.0.42;
normal suites neither locate nor require a private oracle executable. The
public enum/oracle fixture records both descriptor and oracle provenance.
Coverage includes all four direct/retry locations, alias namespaces/transitive
bridges, global first ownership, component maxima, strict number rejection,
output reasoning presence, model fallbacks, step clocks/TTFT and repeat compose.
`test_antigravity_cached_pricing` seeds only invented `pricing-cache.json` rates
before an offline build, verifying alias resolution, context tiers and unknown
unpriced identities without a catalog socket. Chromium covers known/unpriced
Antigravity-only and All totals, mixed availability word layout, phone overflow
and native reader output. Its screenshot option retains priced overview/reader
and partial-availability states at desktop/phone widths in external scratch.
Opaque trajectory metadata TEXT keys are retained independently of INTEGER/NULL
compatibility and required numeric step/generator indexes. DB and native CLI
regressions pin blob validation plus workspace/creation and a resolvable
provider-local parent. Cached-price and unit regressions cover high/low effort
aliases followed by each pinned routing suffix, not only individual suffixes.

History acceptance covers exact canonical/unique-alias resolution, ambiguous
owners and collision-skipped aliases across deletion/rebuild, Codex filename
fallback collisions, malformed fields, chronological grouping and the actual
token-data boundary. Browser cases cover the independent `h` toggle, tags,
direct hashes, period/hour-grid prompt activity and history reader action gates.
Period dial cases pin the browser to America/New_York and a synthetic snapshot
so month, quarter and year boundaries, offsets, Custom shifts and KPI
comparison labels are deterministic.

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

OpenCode reader units use only the public, schema-only projection in
`fixtures/opencode/` (Homebrew OpenCode 2.0.32). This DDL is a documented
exception to runtime-fixtures-in-scratch; all invented rows, database/WAL
files and canaries are created in fresh external scratch and removed by the
fixture helper. Tests cover schema/migration rejection, optional columns,
row-versus-payload identity/clocks, independent token/cost validity,
authorizer exclusions, transaction staging/deduplication, lock timeout, WAL
visibility and unchanged database/WAL bytes. Shared-memory side files retain
SQLite's normal coordination allowance. Cancellation and partial-read failures
use the existing test-only fault infrastructure; descriptor counts and map
teardown are checked across repeated successful and failed reads.

`test_opencode.py` adds native CLI integration for primary/sorted-sibling and
explicit path precedence, normalized duplicates, preview skips, environment
semantics, source-only/mixed/disabled/absent/error-only builds, structured
diagnostics, archive precedence, recorded and missing costs, finite provider
aggregate overflow and collision-excluded counters. All SQLite rows and WAL
files are invented under the case's scratch HOME through this project's
venv sqlite3. Tests preserve database/WAL bytes, leave unopened Codex caches
untouched across rebuild, and prevent credential/unrelated-kv canaries from
entering runtime artifacts. The wrapper strips OpenCode environment overrides
and mutation-checks all five real-home OpenCode read/write denies separately.
