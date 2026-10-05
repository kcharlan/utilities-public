# Maintainer native session oracle

The pinned CLI emits daily/project JSON for all three grouping commands, without
a session list. This harness calls the unmodified Core scoped-cache API and
exports native session IDs and optional metrics. It implements no file selection
or pricing. Ordinary Colophon pytest never builds or executes it.

Prepare a separate clone outside utilities-public, at exact commit
`3bbf6bc48c20d8e507b30ed93dbdce19ed928bb6`. Keep upstream `Sources/` unchanged.
Use a symlink-free work directory under `/private/var/tmp`; macOS `/private/tmp`
is suitable for private output, but the pinned scanner's path normalization can
prevent catch-up when source/fake-home inputs live there.

```sh
git clone --no-hardlinks --no-checkout <local-CodexBar-repository> <external-clone>
git -C <external-clone> checkout --detach 3bbf6bc48c20d8e507b30ed93dbdce19ed928bb6
```

Copy `ColophonNativeOracleTests.swift` into the clone's
`Harness/ColophonNativeOracleTests/` directory. With an editor or `apply_patch`,
append this dedicated target inside the clone's `Package.swift` `targets`
closure, immediately before its `return targets`:

```swift
targets.append(.testTarget(name: "ColophonNativeOracleTests",
    dependencies: ["CodexBarCore"], path: "Harness/ColophonNativeOracleTests"))
```

Build only; never execute unfiltered upstream tests, which can access real homes.

```sh
cd <external-clone>
swift build --build-tests --disable-keychain --force-resolved-versions -j 8
```

Find the resulting `ColophonNativeOracleTests.xctest` bundle in the clone's
`.build` tree. Record provenance after that successful build:

```sh
PYTHONDONTWRITEBYTECODE=1 colophon/.venv/bin/python colophon/tests/parity/compare_codexbar.py \
  --native-clone <external-clone> --native-bundle <test-bundle> \
  --native-provenance <private-provenance.json> --record-native-provenance
```

The manifest records the exact pin, tracked/copied harness SHA-256, bundle
SHA-256 and build command. Rebuild and rerecord after changing the harness.
The tool checks the pin, all upstream source changes (including staged/untracked),
copied harness identity and bundle identity before any native execution.

Only run the comparison after explicit human authorization, with CodexBar quit:

```sh
PYTHONDONTWRITEBYTECODE=1 colophon/.venv/bin/python colophon/tests/parity/compare_codexbar.py \
  --approved --codex-home <authorized-source-home> --colophon-home <authorized-runtime-home> \
  --native-clone <external-clone> --native-bundle <test-bundle> \
  --native-provenance <private-provenance.json> --output-dir <new-private-output-directory>
```

`--approved` records authorization; it does not obtain it. Real homes/data need
separate approval and `--real-data-approved`. The tool copies only Colophon's
ledger/catalog/sticky memory into a temporary home, obtains one public catalog
snapshot there, and seeds the guarded CLI with that same snapshot. Use
`--offline-catalog` only when the selected pricing cache already contains the
public snapshot; the synthetic fixture catalog is never an acceptance catalog.
Colophon then compiles offline, without opening a browser or modifying its
selected runtime home. The live trace is backed up consistently through a read-only
SQLite connection; the native and cold fallback paths use that copy.
The isolated backup is finalized in DELETE journal mode so the pinned read-only
SQLite opener does not require WAL sidecars. Source data and journal mode are
unchanged; permitted SQLite read coordination still applies.
CLI stability requires three complete observations. Partial scans cannot satisfy
the stability streak; retries respect the pinned scanner's 60-second debounce
within the existing attempt limit. Every attempt's raw grouped output and scan
metadata remain in the private report directory.

Task 26's separately approved reproducibility procedure can capture all scanner
JSONLs and the specified metadata/SQLite inputs into a private directory under
`/private/var/tmp`, mode `0700`. Each non-SQLite file must remain unchanged while
copied, with its original mtime preserved; SQLite uses consistent read-only
backups. The manifest records hashes, sizes, mtimes, and SQLite completion times.
This is a collection of individually stable captures, not an atomic whole-home
snapshot. Exhausted JSONL retries stop acceptance and require a user decision;
no truncation or source exclusion is permitted. Both implementations use the
same captured corpus, and the imported guard denies and tests real Codex-home
reads. Preserve every oracle check. Report the private snapshot path until
parity is clean, then delete it while retaining its manifest as private evidence.

All CLI/native execution uses the imported `codexbar_expected.py` runner,
including its sandbox self-test, fake `HOME` and `CFFIXED_USER_HOME`, and
before/after real-cache/preferences fingerprints. `run_native.sh` captures full
XCTest stdout/stderr inside the fake home. Only
`testExportScopedSnapshot` executes during acceptance. The separate
`testSyntheticCountsAndWindow` requires synthetic expected IDs/input counts in
`native-input.json`; its corpus must be historical, have at least two IDs, and
use conspicuously synthetic names. Run that method only through the same imported
guard when performing synthetic native harness checks.

Native day/project costs cross-check with CLI at relative tolerance `1e-10`,
absolute tolerance `1e-12`. Parity uses the plan's bound
`abs(delta) <= 1e-9*abs(reference)+1e-9 USD`. Preserve all nullable native fields.
Required unknown metrics make the oracle incomplete; a null cached count does
not prove zero even in a completed scan. Structural ties are detected from every
isolated cache file record, including records outside the current snapshot.
Any tie or material disagreement in any observation fails completeness, even
after later matching observations. A custom CLI's differences are class (d),
never explained. Missing sessions and unproven differences remain explicit gaps.

Raw project observations retain nullable model breakdowns and source-level totals,
days and model breakdowns. Their CLI-emitted numeric counterparts also cross-check;
CLI JSON omits `standardCostUSD`, `priorityCostUSD`, `standardTokens` and
`priorityTokens`. Those four fields are validated by conservation within each
native report and agreement across native observations; CLI core checks remain
mandatory. Native money retains the declared stability tolerance. Codable
nil omissions remain omitted and direct project/source optionals remain null.
Session comparison keys use canonical Unicode identity while raw native spellings
remain visible in observations; canonical duplicates fail validation.

The Colophon comparison's `project-source` axis uses the original working
directory: native `projects[].sources[].path` against session `cwd`. Canonical
projects remain separate native evidence and cross-check with CLI project JSON.
Every source reconciles with its parent per local day for input/cached/output/
total tokens and cost, for aggregate total tokens/cost, and for supplied daily
and aggregate model identities and totals/costs. Within each individual report,
daily and aggregate model `standardCostUSD`, `priorityCostUSD`, `standardTokens`
and `priorityTokens` reconcile too, following the pinned `BreakdownAccumulator`:
nil/inactive component contributions are skipped and an entirely unobserved
component remains nil. No zero-valued model rows or omitted aggregate activity
fields are reconstructed. Tokens remain exact with native overflow bounds;
costs retain the native tolerance.

Across the source/parent boundary, every discrepancy in one of those four fields
is reported without failing acceptance, even when all contributing directory
rows supplied it or the parent is nil. Pinned `CostUsageModels.swift`'s
`BreakdownAccumulator` skips nil file contributions and marks a field present
if any file supplied it; a merged directory row cannot certify complete split
coverage. `makeCodexBilledDayEntry` also gates split emission by trusted
`hasModeSplit`. No hidden per-file omissions or contributions are reconstructed.
Every discrepancy is retained in JSON and Markdown as native presentation evidence, separately
from Colophon usage differences: parent path, scope/day, model, field, parent
value, observed source sum and every observed omitted source path/value (an
empty list when all source rows supplied the field). Offsetting days
remain individually visible. Component agreement between native observations,
within-report conservation, CLI core crosschecks and all oracle safeguards stay
mandatory. Missing model identities and complete token/cost mismatches fail.

If mandatory reconciliation later aborts, already validated presentation records
remain separate report-owned evidence, explicitly incomplete/aborted with the
failure retained in JSON and Markdown. Per-observation collections remain visible.
No later field, day or aggregate diagnostic is inferred, no partial reference
metrics are published, and neither usage classification nor acceptance is granted.
The shared-path section also distinguishes not-established/incomplete assessment
from absence: only a completed known-empty assessment reports `none`; a completed
nonempty assessment lists every shared path. Aborted or uncollected evidence
includes its reason and never proves that no shared paths exist.

Spec §15 item 6 is resolved: only multiple identical wrapper timestamps establish
collapsed logs. Two distinct values alone do not justify extending that rule;
existing provenance, unknown-time flags and duration fallbacks remain intact.

Missing or unconserved source evidence prevents acceptance. Raw nulls and the
existing explicit unmetered checks remain intact. Reject duplicate source paths
within a parent. When the same exact raw path occurs under several parents,
sum every validated source contribution and retain every parent association;
the private JSON/Markdown report lists all such paths even if no difference
remains. Those associations never relabel Colophon usage or reconstruct native
session/file selection. Native observations remain unchanged in the report.

Source-defined model/day metrics are validated in every nested scope before
stability comparison. Optional encoder omissions and nulls remain unchanged;
invalid count/money types or values make the oracle incomplete. Repeated JSON
object keys fail decoding for both native and CLI evidence, even when their
values agree. Raw stdout is retained before decoding.

Native activity values must fit signed Int64, including valid negative times;
unmetered-day fact counts must be positive bounded native Int. Model rows come
from native String-keyed accumulators: duplicate NFC model names fail in every
scope, even with agreeing metrics. Raw order/names/optionals remain unchanged;
no native rows are rewritten and no trimming, case folding or compatibility
normalization is applied. Reference aggregation only sums independently validated
source contributions for their exact original-directory identity.

Private `report.json`, `report.md`, raw CLI/native output, Colophon page/logs and
fingerprints stay outside the repository. A failing or incomplete report exits
nonzero. Never commit these outputs or use them to regenerate protected fixtures.
