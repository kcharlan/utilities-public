# Lessons learned

## 2026-10-17: Reject superseded snapshots at every consumer boundary

Protecting publication of a derived update list is insufficient if a rejected
filesystem snapshot is still returned to watch evaluation. Retry superseded
captures and retain the accepted snapshot; consume it only after the caller's
final await before persistence or notification. Regress a blocked check while
a later search observes an installation change, then assert saved installed
version, amber state and delivered notices, not only the Other updates list.

## 2026-10-17: Capture mutable cache state after other asynchronous work

A cache actor's identity can stay unchanged while another operation adds an
entry. Taking its snapshot before a suspended installation scan lets an older
check overwrite a newer add's saved ETag. Read the cache after the scan, retain
the cache-identity guard, and merge without another await. A controlled blocked
scan with a concurrent add must preserve both watches and both conditional
entries in actual saved state.

## 2026-10-17: Keep catalog caches proportional to the fields the app uses

Persist decoded Listing indexes and ETags, not raw JSON encoded as base64.
Typed decoding can discard large bottle/dependency metadata without constructing
a full Foundation object graph. Hold the indexes in an actor, read disk once,
and reuse decoded listings on 304. Regress cache size with large invented ignored
metadata and corrupt disk after loading to prove memory-backed revalidation.

## 2026-10-17: An empty bulk success must not erase a good catalog

HTTP 200 does not establish a usable catalog. Reject lists with zero usable
items and replace formula/cask indexes only after both validate. Preserve the
prior pair and ETags after partial, malformed, empty or failed refreshes.
Synthetic successful fixtures must contain usable items too.

## 2026-10-17: Scope a visibility setting to its own content

Other updates and prefix suggestions share the catalog but have different
visibility contracts. Turning off installed updates must leave suggestions
available during hydration, reload and refresh. Gate the installed section,
not the shared catalog resource.

## 2026-10-17: Capture installed state once away from the main actor

Inventory admission and installed-version lookup must share a single receipt
pass. Capture an installation snapshot off-main, reuse it for watched checks
and Other updates, and generation-check publication after suspension. A blocked
scan regression should prove UI state can change while it waits; a receipt-read
counter catches accidental inventory-plus-lookup passes.

## 2026-10-17: Avoid persistence and scans for unchanged state

Compare a normalized candidate with committed state before saving. Closing an
already acknowledged popover or selecting the current setting must not write.
Filter a captured installation snapshot after watch or visibility changes;
interval, skip and close commits do not require fresh filesystem inventory.

## 2026-10-17: Track successful checks separately from transport attempts

An entirely unreachable check must retain its previous successful timestamp.
Keep a separate attempt clock to bound retries, and let reconnect bypass that
transport floor even if a recent manual failure followed a successful check.
Start automatic scheduling behind a network gate until the path monitor answers.

## 2026-10-17: Failed saves need their own automatic retry floor

A successful request followed by rejected persistence must not repeat each
minute. Bound automatic requests by the configured interval from the failed
save, including across reconnects, while permitting an immediate manual retry.
Apply the same rule to catalog timestamps; injected clocks and request counts
prove cadence without sleeping or changing successful-check timestamps.

## 2026-10-17: Prune conditional caches at watch lifecycle boundaries

Persist only entries whose names are watched. Removal must evict the in-memory
conditional cache too, and an in-flight old cache snapshot must not be merged
after that boundary changes, even when Undo restores the same name. Regress
both saved bytes and outgoing ETags; search-only entries must never accumulate
in saved watch state.

## 2026-10-17: Expose persistence recovery kinds separately from message text

Setting aside corrupt state successfully is a recovery warning, not a failed
save. Expose explicit recovery-warning, blocked-load and failed-save states so
UI retry hints follow the actual recovery action without parsing error prose.

## 2026-10-17: Admit legacy casks only for absent receipts

Caskroom version directories can predate install receipts. Admit those legacy
casks in both lookup and inventory, preserving app-bundle lookup and the
Caskroom fallback for self-updating packages. Absence is an explicit exception:
existing malformed, unreadable, unknown or nonofficial receipts still exclude
the installation, as do version-directory symlinks. Keep formula receipts
mandatory and regress both admission paths with synthetic filesystem fixtures.

## 2026-10-17: Never assume Unicode scanner and classifier agree

Foundation's case-insensitive scanner can match Kelvin sign and long s through
ASCII letter patterns while its anchored classifier finds no match. External
folder and bundle versions must not trap on that disagreement. Fall back to a
string token instead of force-unwrapping the classifier, and retain actual
Unicode regressions beside the pinned upstream ASCII comparison matrix.

## 2026-10-17: Compare formula revisions after upstream versions

A formula keg suffix is a package revision, not another upstream version token.
Comparing `1.0_2` directly with `1.0.1` misses the newer upstream release.
Split only the last underscore followed entirely by ASCII digits, default to
revision zero, compare upstream versions first and numeric revisions on a tie.
Reuse this rule for status and highest-keg selection; preserve valid opt links,
cask ordering, deterministic ties and arbitrary-precision revision comparison.

## 2026-10-16: Merge awaited watch results into committed state

A check must apply results to the current committed watch state after its final
await. Capture each watch's generation when starting work and reject results
for removed or restored generations, even when the package name matches again.
Otherwise a late response can change an undone removal or overwrite a newer
skip or interval. A controlled transport regression should hold requests while
mutating all those fields, then inspect both persisted state and notifications.
Persist candidates before publishing state or posting notices; retain the
previous bytes and visible values on failed writes.

## 2026-10-16: Bound and identify asynchronous menu bar searches

Search, watched checks and additions need one shared lookup permit pool; separate
per-operation limits exceed the intended request bound when UI actions overlap.
Identify each query generation and publish only its current result. Derive the
watched flag from committed state at publication and refresh it on successful
watch mutations. Preserve a watched package's known kind during search instead
of falling back to a formula-first lookup. Controlled transports can hold one
query while a newer query or a watch mutation commits, without live inventory.

An undo action must consume its saved entry only after the restore commits.
Cancel its normal expiry after a failed restore so the user can retry; do not
replace that pending recovery with another removal. Route a same-name Watch
through restoration too, or a fresh add can strand the recovery as a duplicate
and lose its saved acknowledgements. Test the actual app action against the
real controller and failing atomic-replace seam, then retry successfully.

## 2026-10-16: Retain validated recovery bytes until activation finishes

A move-based native app activation can fail before the old bundle leaves its
live path, including across filesystems. Do not delete a verified backup copy
before that move succeeds: recovery then loses the app it needs to restore.
Keep the validated copy through all command, app and receipt transitions, and
inject failures both before moving the old app and after publishing each new
artifact. Compare independent byte/type/full-mode snapshots after restoration;
receipt hashes alone cannot prove that recovery preserved the original tree.

## 2026-10-16: Preserve explicit search intent and bound native result content

A catalog suggestion includes both name and kind. Preserve both in transient
search intent, and include kind in the text task's identity: selecting a cask
whose name already fills the field must requery even when the text is unchanged.
Editing clears that explicit choice; existing name-only watches retain their
known kind. Test the app's suggestion action through lookup and Watch against
colliding synthetic formula/cask responses, plus cancellation and late results.

Bound suggestions and multi-token results inside their own scroll viewport,
with the input and footer outside it. Follow keyboard selection with scrollTo.
For offscreen SwiftUI layout tests, separate presentation from its asynchronous
query task: creating a host for the whole section can restart the task, clear
results and accidentally measure empty content. Test the maintained presentation
component with populated results and verify that removing the bound makes the
test fail on real geometry. This does not establish native keyboard acceptance.

Native executable diagnostics require successful exit, exact stdout and empty
stderr. A signed executable can satisfy stdout while emitting an unexpected
warning. Regress each flag at both build and installed activation boundaries,
and compare the prior artifacts and retained recovery snapshots after failure.

## 2026-10-16: Keep catalog validation and persisted freshness separate

Bulk catalog lists form one usable snapshot. Validate both before replacing
the cache; a successful first list cannot replace half of a good pair when the
second fails. Conditional responses require validated prior bytes, and stale
fallback content must not advance the successful-fetch clock. Track attempts
separately to bound offline retries. Independent catalog and watched checks
must merge into current committed state after their final await, with tests
forcing both completion orders and state-save failures.

## 2026-10-16: Distinguish installation links from real version directories

A cask can have a genuine `latest` version directory. Exclude version symlinks
by filesystem type, not by a reserved-looking basename; otherwise an admitted
installation disappears from point lookup and inventory before app-bundle
lookup or unversioned status evaluation. Cover both real `latest` directories
and `latest` symlinks with synthetic installation fixtures.

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
