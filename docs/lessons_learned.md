# Lessons learned

## 2026-10-16: Preserve upstream token semantics in version comparisons

Homebrew's version ordering is asymmetric when zero tokens meet suffixes;
do not assume reversing operands negates the result. Its post-release pattern
also starts with a wildcard: `1post2` uses the first numeric run as the token
revision. Generate both ordered expectations from pinned upstream methods,
including wildcard and zero positions, before porting. Brew Version retains
these synthetic parity cases in `VersionOrderTests.homebrewParity`.

## 2026-10-16: Preserve confirmed popup state when status checks fail

A failed or rejected worker status reply does not establish that capture is
off or empty. Keep confirmed capture values explicitly stale, show unknown
values before the first successful reply, and disable affected actions until
recovery. Do not pass an empty synthetic payload through the success renderer.
Regress both worker messaging failures and rejected or incomplete replies,
including successful recovery without capture mutations.

An outside focus outline can disappear behind a rounded fold's overflow clip.
Use an inset outline and check collapsed summaries and full-width row buttons
in light and dark Chromium. Scope error notice colors to each skin so a later
skin-specific neutral selector cannot override the error tone.

## 2026-10-16: Verify extension popup typography and empty-state layout in Chromium

Chromium's extension stylesheet can give `body` a relative font size even when
the root declares the intended size. Explicitly inherit the root font on the
popup body and assert its computed size in browser tests. Empty states inside
structured lists also need selectors strong enough to override item layouts;
otherwise a plain message can be squeezed into a grid column. Keep light and
dark screenshots and computed-style regressions beside the popup behavior tests.

## 2026-10-15: Preserve calculator cache precedence during webserver updates

The live Nginx configuration had a calculator-specific `no-store` rule absent
from source. Keep that rule in the maintained configuration: its `^~` prefix
prevents the common asset regex from replacing calculator JavaScript's cache
policy. Preserve static-first delivery and the shared dynamic fallback inside
the prefix. Verify real response headers and routes with an isolated Nginx
fixture, including missing calculator assets and ordinary asset 404s. Docker
Desktop bind-mount deletions can propagate asynchronously; observe deletion
inside the disposable container before testing the missing-landing branch.

## 2026-10-15: Test temporal conversion policy across every CLI target

TOML and YAML parsers can produce native Python dates and datetimes; TOML also
produces native times. JSON and XML writers need explicit ISO serialization,
while YAML should normalize only times so its native date/datetime types survive.
Keep TOML's native writer and preserve ordinary strings, including YAML's quoted
time values. A shared temporal hook must reject unknown objects rather than
silently stringifying them.

The converter's [test_temporal_cli_matrix](../data_format_converter/tests/test_cli.py)
loads each source fixture, exercises every actual supported target, and compares
the complete parsed mapping and value types after unwrapping XML's synthetic
root. Retain nested direct-writer regressions and
[test_yaml_temporal_policy](../data_format_converter/tests/test_yaml_conv.py) /
[test_toml_temporal_policy](../data_format_converter/tests/test_toml_conv.py):
a substring check cannot detect type loss, dropped fields, or lost marker values.

Measure temporal types separately during dependency upgrades. The TOON baseline
already preserved dates and datetimes, but converted times and binary values to
null and rejected comment-only input. Its released writer now preserves times,
rejects binary through the CLI error path, and accepts comment-only input; keep
those regressions rather than claiming all temporal behavior changed together.

## 2026-10-15: Retain reference reconstruction guards in optimized variants

Reversible Skew's optimized transform accepted smaller periodic BWT payloads
that did not reconstruct the original bytes. Preserve the `rs.py:transform`
reconstruction guard when accelerating MTF/RLE operations, falling back to raw
blocks when comparison fails. Random-only tests exercise passthrough and miss
this failure: retain periodic and varied synthetic regressions, require the
varied case to take the transformed path, and cross-decode both implementations.
See [Reversible Skew's guide](../reversible-skew/README.md) for project validation.

## 2026-10-15: Compose inventory coverage and npm audit evidence across views

Manifest inventory failures are independent of declaration rows. Fleet cards and
per-repository summaries must consume persisted analysis errors and missing tools
even for empty results or fully checked rows, while declaration KPIs continue to
count only actual row states. Exercise both cases through the rendered browser.

npm outdated can report installed versions while audit evaluates the virtual
lock tree. Reuse lock-version evidence, require a concrete matching evaluated
version, and match the audit's affected node location before applying a finding.
A same-name nested vulnerable node does not implicate the direct declaration.
Mocks must include real affected-node evidence rather than validating name-only
attribution; retain valid current/outdated evidence when audit versions differ.
Select npm-shrinkwrap before package-lock in the same parser; invalid selected
shrinkwrap evidence must not silently certify a different fallback lock tree.

## 2026-10-15: Attribute package-manager checks to declaring projects and evaluated versions

A manifest path is part of a dependency declaration's identity and also selects
the package-manager working directory. Group checks by the resolved declaring
directory so a monorepo's nested projects cannot inherit root-project tool output.
An npm lock supplies a concrete version, not registry comparison evidence; require
an actual comparison even after successful empty outdated output. Treat audit
errors and required report fields as evidence boundaries, including lock-specific
failures, rather than promoting audit prerequisites to successful coverage.

Findings-only reports cannot prove that an absent declaration was evaluated.
Prefer explicit all-package comparison rows or evaluated module/version evidence,
and retain unchecked reasons where that evidence is unavailable. Current
govulncheck JSON is a versioned message stream: OSV database candidates are not
findings, SBOMs establish evaluated modules, and finding attribution includes the
version regardless of message order. When an audit contains several versions of
one name, preserve the matching version's advisory instead of the last name match.

## 2026-10-15: Preserve dependency declaration identity across manifests

Git Fleet previously deduplicated and stored dependency rows by repository,
manager, and package name, losing repeated declarations in nested manifests.
Include the manifest path in parsing, persistence, stale-row deletion, and
overlap attribution. Normalize Python names before deciding identity; preserve
fallback reference identifiers. Test schema migration against historical DDL,
including SQL NULL sources and normalized-name collisions, and invalidate
legacy health coverage rather than presenting old results as fresh evidence.

## 2026-10-15: Verify extension release identity during deployment

The extension repair was deployed with its previous manifest version, so the
browser still displayed `0.5.0` after a successful reload. Bump the manifest
version for a released extension change and verify it in both the source and
deployed manifest before handing off the browser reload. Matching source bytes
alone does not establish that the displayed release identity was updated.

## 2026-10-15: Redacted diagnostics still need text-only rendering

In `docker/llm_collector/extension`, decoding paths to redact identifiers also
decoded encoded markup. The popup interpolated that sanitized text into
`innerHTML`, creating an actual image and attempting an external request under
the extension CSP. Redaction removes sensitive content; it does not make text
safe for an HTML parser. Render every dynamic diagnostic field, neighboring
count row and identity value with `textContent` and DOM elements. Preserve the
sanitizer's byte limits independently. Keep the list present in renderer tests
and exercise observation, normalization and rendering together; verify the
actual popup in isolated Chromium with resource attempts intercepted.

## 2026-10-15: Treat diagnostic restoration and persistence as recoverable states

In `docker/llm_collector/extension`, waiting only for the enable setting let
completion events miss records whose session read was still pending. Register
listeners synchronously, sanitize bounded staging immediately, and serialize
events and controls after both initialization results settle. A failed read
means storage is unread, not empty: merge bounded staged records after reload,
or intentionally replace the owned key through a successful clear.

Session callback completion does not imply persistence success. Read
`chrome.runtime.lastError` inside each callback, keep failures observable in
status/export, and publish clear success only after the latest empty write.
Use generations so obsolete writes/retries cannot restore cleared content.
Bound count, serialized UTF-8 bytes, individual records and bodies separately;
Chrome's actual memory quota needs its own browser measurement. Evict even an
oversized singleton and remove additional owners of evicted in-flight records.
Preserve live redaction provenance rather than reparsing sanitized JSON prefixes
during every retention pass. Test Unicode, late growth, unread stores, failed
callbacks, deferred clear, and worker stop/wake with a fresh synthetic profile.
Check byte limits again after redaction: repeated short token values can expand
to longer replacement markers, including in standalone restored debug paths.

## 2026-10-15: Commit transport history with prompt accounting

In `docker/llm_collector/extension`, counting each Gemini WebChannel POST counts
transport retries repeatedly. Google's WireV8 encoder identifies messages as
`ofs + reqN`, where `N` is a relative message ID, not an array position; retry
reordering can lower the offset and leave sparse indexes. Join raw byte chunks
before decoding forms so keys, base64 prefixes and UTF-8 sequences remain whole.

Persist salted endpoint/SID hashes and interval history in the delivery owner's
same transaction as queued counts. Include non-prompt IDs, retain the salt and
history across extension and browser lifecycle boundaries, and fail closed at
bounds without eviction. Browser tab IDs and session-storage nonces cannot
establish durable transport identity. Known replays should need no write.
Exercise rejected persistence, mixed retries, lost acknowledgements, and explicit
queued-count clearing with an observation-identity conservation oracle.

## 2026-10-15: Persist immutable delivery identity before sending

In `docker/llm_collector`, serializing pending-count writes did not serialize
submissions. Two overlapping sends reused one sequence with different snapshots;
both replies subtracted counts although the collector accepted only the first.
Persist one immutable batch and keep newer observations in a separate queue.
Publish cloned state only after storage succeeds, and preserve an uncertain
batch across retries, clear actions and worker restarts. Persist a migration
baseline marker so an offline restart cannot submit before reconciliation.

Resetting a reporting period must retain deduplication receipts. Snapshot,
clearing and save need one lock boundary; otherwise a concurrent add can fall
between the snapshot and clear and disappear. Test conservation with observation
identities: accepted and uncertain in-flight sets may overlap after a lost reply,
so adding their counts is an invalid oracle.

Fetch resolving means headers arrived, not that body consumption succeeded.
Classify aborts and stream transport failures during JSON reading as retryable,
while treating malformed JSON as a protocol error. Publish a counted diagnostic
only after the observation commits. Keep rejected-recording diagnostics in the
session buffer and distinguish their errors from transient delivery errors;
an empty or unrelated successful drain cannot restore a rejected observation.

## 2026-10-15: Sanitize every diagnostic representation

In `docker/llm_collector/extension`, a credential-name regex applied to raw JSON
missed names supported by the form/query policy and values that were not strings.
Decoded URL containers, URL-valued headers, debug paths, and restored session
records provided additional ways around otherwise working capture redaction.

Use one sensitive-name classifier after parsing each recognized representation.
Bound structural inspection and decoding, omit uninspectable content, and use
own-property maps for untrusted member names. Treat session restoration as an
admission boundary: sanitize before publishing records and rewrite the safe
representation. Test the complete popup export and console boundary, including
when capture is off, because testing one capture field cannot establish that the
same credential is absent from neighboring diagnostic fields.

Review caught two boundary errors: recognizing one valid Link target does not
validate the remaining header, and reparsing a safe JSON prefix after truncation
loses long prompts. Consume an entire recognized container before publishing
any of it. Preserve live sanitation provenance outside serialized records, so
admission can distinguish a fully inspected prefix from untrusted restored text.

## 2026-10-15: Separate dependency findings from check coverage

An unchanged declaration after a missing or failed tool is not a clean health
result. Track outdated and vulnerability evidence separately, retain bounded
failure reasons, and derive display severity after enrichment. Preserve proven
findings when the other check is incomplete. Do not promote a declared version
constraint to an installed version. Persist missing tools and manifest inventory
even when parsing yields no rows, and keep quick scans from overwriting them.
Run blocking network and package-manager checks in a worker thread so requests
and scan progress remain responsive. Test that responsiveness with a worker
blocked on an event released by the server event loop.

Dependency snapshot persistence also needs explicit failure rollback. A caller
that catches a scan error and commits unrelated progress can otherwise publish
earlier metadata and row writes. Protect metadata, upserts and stale deletion
with a savepoint; roll back the savepoint on failure and preserve the caller's
outer transaction. Regress with real SQLite trigger failures, followed by the
caller's commit, and compare the complete previous snapshot.

Python direct-reference identity needs a distinct path from distribution-name
normalization. Parse URL authority before separating a VCS revision from its
path: an SSH user separator is not a revision, and revisions can contain slashes.
Keep extras and markers as declaration text and reject wildcard pins as concrete
versions. Filtering direct-reference result rows does not exclude their URLs
from an auditor that reads the original mixed manifest; filter the actual audit
input too. Regress the full parse-to-persistence path and inspect synthetic
auditor input, because parser-only tests miss later identity normalization and
whole-manifest external work.

### Git Fleet: declaration sources and discovery inventory

Manifest priority can silently discard independent Python declarations. Discover
pyproject, requirements variants and leading PEP 723 metadata together, and keep
resolved include-file provenance separate from the including file. A file inventory
must record attempted reads, empty files and failures independently of dependency
rows. Adjacent locks supply versions only; ambiguous versions must block checker
entry before any floating resolution can run. PEP 723 extraction needs its greedy
closing-line grammar, not a first-terminator scan or fixed prelude byte cutoff.

An arbitrary requirements include can also look like a discovered script. Parse
explicit manifests and their includes before script candidates, and let an existing
resolved-path inventory record own that file. A harmless metadata probe must never
replace or remove the include's empty, populated or failed record. Regress both
filename orders and assert one actual read, not merely one surviving declaration.

### Git Fleet: evaluate Python declarations and validate audit evidence

An unpinned declaration still has a registry evaluation: retain the highest allowed
usable release as a floating wanted version, without calling it installed or
current. Apply `SpecifierSet.filter` to the candidate set so explicit prerelease
constraints and fallback behavior follow packaging's semantics. Cache successes
and failures by normalized name for one scan, and distinguish connection failures
from HTTP/JSON errors before opening an offline breaker.

Auditing the original manifest can resolve extra dependencies and conflate versions
declared in different projects. Audit exact evaluated pins with dependency resolution
disabled, splitting conflicting versions of one normalized name into separate
batches. Treat process status and JSON as a joint evidence contract: missing entries,
skips, malformed advisories, duplicate names, version mismatches and status/advisory
contradictions cannot establish clean coverage. Regress matching across manifests
and limit failures to the affected batch. Synthetic auditor fixtures must use real
exit semantics and the requested versions so they cannot conceal these errors.

### Git Fleet: findings and coverage are independent report dimensions

A vulnerability or update headline does not prove both health checks ran. Count
unchecked declarations from the independent check states in SQL and the UI, and
allow a finding to appear in both Attention Required and Not Checked. Count
manifest reads from discovery inventory so empty or failed files survive reports.
Refresh metadata after a scan before publishing the report; stale parent props can
otherwise pair fresh rows with old missing-tool and inventory information. Browser
regressions should inspect real downloaded contents and use one shared synthetic
fixture to compute API, UI and report expectations.

A declaration timestamp is not a scan timestamp. An inventory-only scan can have
no declaration timestamps; label that absence explicitly instead of claiming the
repository was not scanned. Never substitute a quick-scan time for dependency
evaluation history.
