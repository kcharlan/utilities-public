# Local market data maintenance

The public project contains compiler code and [`sources.json`](sources.json),
not historical workbooks or observations. The compiler requires an explicit
external `--output-dir` and writes `market-data.js`/`market-data.csv` together.
It never writes outputs beside application source. Ignore entries are defense
in depth, not permission to place real inputs, outputs, builds or exports in
Git. See [`../DATA_SOURCES.md`](../DATA_SOURCES.md) for attribution, lineage,
retained snapshot identities and local-use restrictions.

## Setup and immutable local selection

The owner runs setup; agents never acquire data (see the
[project guide](../README.md)). From the project directory, run
`npm run setup:data`. Cold setup creates an
external `.venv` with `python3.14 -m venv --copies`, installs the complete
reviewed lock, acquires only missing official workbooks, compiles a private
candidate and runs the historical acceptance gate. Use `--python EXECUTABLE`
if the supported interpreter has another command name. Subprocess arguments
are structured and bounded; no shell or system Python probes/pip are used.
Timeout and cancellation terminate the process group, including descendants
that resist termination, before setup releases its private resources.

`npm run setup:data -- --offline` reuses a current verified recipe with zero
Python/acquisition/dependency calls. `--shiller PATH` or `--damodaran PATH` always
forces candidate validation, even with a valid current generation. Supply both
with a ready venv for entirely offline manual compilation. A missing offline
input, incompatible venv or missing locked dependency gives a preparation
error. `--offline --refresh` fails before mutation. `--refresh` uses a separate
candidate cache, retains all old inputs/generations and selects only a verified
candidate. Recipe changes reuse the exact retained inputs without refresh.

New generation dates use the actual compiler date. `--generated-date YYYY-MM-DD`
is an explicit reproduction option: use the exact recorded inputs, not a new
download. `current.json` selects a bundle only after hash, pair parity,
range/quality, provenance and historical controls pass. Compile, validation,
interruption or selection failures preserve the prior selector and referenced
bytes. A private exclusive lock serializes mutations; an unexplained existing
lock is refused and must be investigated, not blindly deleted. Read-only
consumers never acquire this lock. No pruning is performed.

The shared read-only `tools/data_contract.mjs` verifies actual pair and recipe
snapshot bytes without requiring raw-workbook access. Its separate
`verifyRetainedInputs` checks actual input objects on mutation/reproduction
paths; corruption fails without redownload. `dataId` identifies the sorted output pair; `recipeId`
identifies the explicit reviewed source inventory; `bundleId` also binds the
approved source identifiers, exact workbook hashes and generated date.
Provenance uses schema-controlled relative object names. Each generation
retains allowlisted recipe source bytes under `recipe/`, allowing independent
verification after source changes; callers can additionally require equality
with the current source recipe. Selector claims alone are never trusted.
Downloaded JavaScript is parsed only as a JSON assignment, never evaluated.
Compiler, lock installation and the historical checker use the captured private
recipe source bytes. If the working source recipe changes during setup, selection
fails without changing current; an output cannot be mislabeled with an earlier
recipe hash. Acquisition is a distinct `--acquire-only` compiler phase using
the existing bounded official-source logic; it validates supplied workbooks and
never transforms or emits a pair. All manual, retained and newly acquired
workbook bytes are copied into private compilation snapshots before parsing.
Provenance binds those captured bytes. Candidate snapshots, original sources
and retained objects are checked through publication; changes fail without
repairing or replacing originals. Cancellation is checked again immediately
before selector promotion, including after writing its temporary file.

The recipe inventory is the compiler, `data/sources.json`,
`data/requirements.lock`, setup/contract/historical-checker code, and the
engine/statistics acceptance dependencies. Changes to any of these invalidate
the recipe. Identical output bytes from another recipe/input get their own
bundle and provenance. Setup logs only bounded status, identities and count.

Existing directories and consumed files are checked for ordinary types and
readability; symbolic links are refused on managed data paths. Exact owner,
permission modes, ACLs, flags and extended attributes (including
`com.apple.macl`) are not admission gates. No existing ancestor permissions
or metadata are changed. New private containers and files use `0700`/`0600`.
Setup preserves unrelated site, temporary and legacy entries beneath the data
home and validates only the files it consumes. Explicit managed sources remain
restricted to verified `inputs/<sha256>/source.xls` objects and the two known
fixed-name compatibility caches. Hash-mismatched objects fail without replacing
the originals. Standard venv interpreter links are used only for execution;
their external targets are never chmodded.

## Environment and tests

Python execution and installation require a virtual environment. The tested
maintainer environment is Python 3.14.7 on macOS arm64. Source syntax requires
Python 3.10 or newer; other interpreter/platform combinations remain unverified. Setup checks Python
3.10 or newer, an isolated venv and the pinned installed dependencies rather
than requiring the maintainer patch version or CPU identity.
`requirements.txt` retains the direct requirements pandas 2.3.2 and xlrd 2.0.2.
`requirements.lock` records the complete tested resolution; pandas was built
from its source distribution. Do not run the script's shebang directly.

`MARKET_ATLAS_DATA_HOME` defaults to `~/.cache/market-atlas`; a nonempty override
selects the external local data root. Setup places its compiler venv in `.venv`,
raw immutable inputs in `inputs/<sha256>/source.xls`, immutable compiled bundles
in `datasets/<bundleId>`, atomic selection in `current.json`, and local builds
in the flat `site/` directory. Runtime builds are local data-bearing artifacts,
not public distributables. Preserve older inputs and bundles after refresh.

Prefer the setup wrapper. For manual maintainer preparation, use a new owned
private external directory under an existing writable parent. The following
`mkdir` deliberately refuses an existing data home:

```sh
MARKET_ATLAS_DATA_HOME="${MARKET_ATLAS_DATA_HOME:-$HOME/.cache/market-atlas}"
mkdir -m 700 "$MARKET_ATLAS_DATA_HOME"
python3.14 -m venv --copies "$MARKET_ATLAS_DATA_HOME/.venv"
chmod 700 "$MARKET_ATLAS_DATA_HOME/.venv"
"$MARKET_ATLAS_DATA_HOME/.venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple -r data/requirements.lock
"$MARKET_ATLAS_DATA_HOME/.venv/bin/python" -m pip check
(cd data && PYTHONDONTWRITEBYTECODE=1 "$MARKET_ATLAS_DATA_HOME/.venv/bin/python" -B -m unittest -v test_compile_market_data test_external_compiler)
"$MARKET_ATLAS_DATA_HOME/.venv/bin/python" data/compile_market_data.py --help
```

The named-module command above is focused invented compiler validation; it does
not satisfy full discovery or the complete synthetic command. After setup has
selected actual data, run the full discovery command in the test instructions.

System Python is used only for `-m venv`. Subsequent Python/pip/compiler/test
work uses the venv. Existing directories are not chmodded.
Never acquire dependencies/data from deployment, recovery, audit or browser startup.

`npm run test:synthetic` first validates a ready external venv, then runs its
whole-file invented Node subset and exactly `test_compile_market_data` plus
`test_external_compiler` from `data/` (invented cases). Select the
interpreter with `MARKET_ATLAS_TEST_PYTHON`, or use `<DATA_HOME>/.venv/bin/python`.
Run the root audit suites independently as described in the test instructions. Tests never create a
venv, install dependencies or acquire actual history. Missing
prerequisites fail; a Node-only result cannot satisfy the synthetic command.
See [test commands and browser prerequisites](../tests/README.md).

Full `unittest discover` additionally includes `test_retained_reproduction.py`:
with bytecode disabled, it checks the current-recipe selected/pinned bundle and
both retained input hashes through the Node contract, compiles in the same
compatible venv using both explicit workbooks, the recorded generated date and
end year 2025, then compares exact JS/CSV bytes/hashes in private external output.
Inputs, selector and generation must remain unchanged. This is selected-current
bundle reproduction; the original August 20 snapshot evidence below remains a
separate check. Full discovery fails when real prerequisites are absent, without
skips or downloads. Use `PYTHONDONTWRITEBYTECODE=1` and `-B` on compiler/test
commands to keep bytecode outside the public source tree.

## Compiler contract and reproduction

`emit(rows, generated, output_dir)` requires an external output directory. The CLI requires `--output-dir PATH`, supports `--shiller PATH` and
`--damodaran PATH`, and uses `--end-year 2025` by default. Only the reviewed recipe
end year is accepted. Later workbook years are fully parsed and validated
against their matching published geometric anchor before output selection;
reconciliation remains exactly 1928–2022. Selection retains the 154-row
1872–2025 output and does not silently advance history. Source recipe/range
advancement requires review and full historical/browser verification.

For exact reproduction from the recorded old hash-addressed inputs:

```sh
"$MARKET_ATLAS_DATA_HOME/.venv/bin/python" data/compile_market_data.py \
  --shiller "$MARKET_ATLAS_DATA_HOME/inputs/SHILLER_SHA256/source.xls" \
  --damodaran "$MARKET_ATLAS_DATA_HOME/inputs/DAMODARAN_SHA256/source.xls" \
  --output-dir "$MARKET_ATLAS_DATA_HOME/reproduction-candidate" \
  --end-year 2025 --generated-date 2026-08-20
```

`SHILLER_SHA256` and `DAMODARAN_SHA256` are conspicuous placeholders: select the
recorded input hashes from the source notice. `--generated-date` accepts only
a valid exact `YYYY-MM-DD` calendar date and otherwise uses today's date.
It changes metadata only. Backdating is reserved for reproduction from exact
identified retained inputs, not new acquisition. Explicit-date compiler tests
prove repeatable bytes; full historical controls are validated separately.

## Acquisition, privacy and recovery

Known legacy filenames `ie_data.xls` and `histretSP.xls` remain supported directly
under the external cache. Cache hits validate the workbook and do not download.
Manual source files are read without changes; symlinks and nonregular files are
refused. Canonical repository/webroot destinations, configured serving aliases,
symlinked cache/output paths fail before writes. New private
directories use `0700`, candidates `0600`; existing paths are not chmodded.
Explicit manually supplied legacy
inputs are read-only sources and need not have controlled-file permissions
before setup copies them into private storage.

The recipe pins verified official HTTPS identifiers and redirect origins.
Acquisition retains certificate verification, a 60-second timeout, streaming
and a 32 MiB maximum. HTML, OLE mismatch, unreadable workbooks and changed sheets
fail with manual-input flags; there is no arbitrary mirror/TLS bypass. Tests
use invented frames/bytes and controlled responses, never upstream downloads.

The low-level compiler's `--refresh` atomically replaces a validated compatibility
cache file. Setup must use a separate private candidate cache and preserve old
originals by hash; never invoke refresh against the sole retained old inputs.
A failed candidate cannot change selected state. Pair emission stages both
files and restores the old pair if replacement fails. Owned candidate/backup
paths are recorded as soon as they are created; failed writes/copies clean
partial files before any promotion. Failed downloads preserve
the old cache. If restoration itself fails, the compiler raises a failure and
retains the unresolved old backup bytes in the private candidate directory for
manual recovery. No pruning is part of this port.

The unchanged financial controls include Damodaran's 1928–2025 geometric anchor
and independent-source MAE, bias, standard-deviation-ratio and geometric-mean
thresholds. Return calculations, rounding, splice choice, monthly completeness,
chronology and finite-value checks remain binding. Aggregate reconciliation
logging remains; setup reports status/count/hash without row/private path dumps.

Before every commit, run `node tools/check_admission.mjs` from the project and
inspect the complete staged inventory/diff. The guard checks stage-zero project
objects plus all staged additions/modifications, including renamed data outside
the project. It rejects prohibited local data/runtime paths, ordinary workbook/
archive signatures and recognizable materialized JSON/CSV datasets, including
force-added files. Reports give counts/categories rather than observations or
untrusted path payloads. Recursive encoding/container inspection is retired.
This is defense in depth: contextual staged review remains mandatory.
