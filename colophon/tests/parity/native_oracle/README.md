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
native-only monetary components retain the declared stability tolerance. Codable
nil omissions remain omitted and direct project/source optionals remain null.
Session comparison keys use canonical Unicode identity while raw native spellings
remain visible in observations; canonical duplicates fail validation.

Source-defined model/day metrics are validated in every nested scope before
stability comparison. Optional encoder omissions and nulls remain unchanged;
invalid count/money types or values make the oracle incomplete. Repeated JSON
object keys fail decoding for both native and CLI evidence, even when their
values agree. Raw stdout is retained before decoding.

Private `report.json`, `report.md`, raw CLI/native output, Colophon page/logs and
fingerprints stay outside the repository. A failing or incomplete report exits
nonzero. Never commit these outputs or use them to regenerate protected fixtures.
