# Brew Version implementation and acceptance record

## Outstanding acceptance

Native UI is unverified. The permitted computer-use tool reported the Mac was locked and required manual unlocking. No alternative GUI route was used. Current-system Settings, search/keyboard/Undo, notification permission/delivery/click, Other updates, login status and light/dark checks remain open. The minimum supported macOS runtime is also unavailable. Source/build/test success does not establish these runtime checks.

No live installation, deployment, push or merge was performed.

## Decisions to preserve

1. Use the plan's exact feature branch in the existing checkout; preserve the supplied plan in its own initial documentation commit. Cost: branch can be renamed; one extra documentation commit.
2. Keep the upstream BSD notice with the comparator port and signed bundle. Cost: an extra notice resource and packaging copy.
3. Preserve the running SwiftPM helper's absolute executable and bundle arguments for the isolated-PATH test. Cost: another toolchain may require adapting only this test launcher.
4. Preserve legacy eager option handling, interval replacement semantics and duplicate argument positions. The added release flag follows eager help handling.
5. Preserve pinned Homebrew ordering, including asymmetry; select tied folders deterministically. A real cask latest directory is admitted, while version-directory symlinks are excluded; valid formula opt links still select their keg. Independent ordered-pair fixtures caught the post-token first-number bug.
6. Keep uninstalled acknowledgement separate from notification deduplication. Cost if wrong: confusing repeated-poll/acknowledgement behavior.
7. Restore allocates a new generation; results requested before removal cannot mutate the restored entry. Cost: refreshed listing may wait for the next check.
8. Merge into committed state after the final await and save without suspension before publishing/notifying. Cost if wrong: concurrent user actions could be erased.
9. Ignore retryLoad during an active add/check. Cost: retry may need repeating after active work finishes.
10. Keep quarantine recovery warning until valid reload or successful save. Cost: warning can remain visible longer.
11. Persist an explicit failed watch request as an error row; first later success still baselines silently. Cost: direct callers can leave a misspelled watch until removal.
12. Reject inconsistent nested saved values and listing/name mismatches. Cost: incompatible manual edits are quarantined rather than partly admitted.
13. Use a narrow internal I/O seam for failure tests. Cost: a new failure category may require another seam; no production simulation switch exists.
14. Make hydrateCatalog async so cache I/O/decoding is off MainActor and startup can await content. This changes the plan's synchronous signature. Cost: callers must await hydration.
15. Atomically cache both slim Listing indexes and ETags in a versioned envelope. Ignore the legacy raw/base64 format. Cost: the first launch with an old cache fetches fresh lists; no external cache consumer exists.
16. Use one four-request permit pool across checks, additions and search. Cost: large searches may queue behind checks; cancelled queued work drops before transport.
17. Retain intended SwiftUI SettingsLink path pending actual runtime evidence; a locked desktop does not establish failure. Cost: the planned AppKit fallback may still be needed after an unlocked probe.
18. Failed Undo suspends normal expiry and blocks replacement removals until successful retry; same-name Watch restores the saved entry. Cost: another Stop watching action waits for recovery. Ordinary Undo still expires after five seconds.
19. Preserve an explicitly selected suggestion's kind in transient `SearchInput`, including task identity when text is unchanged. Editing clears it; an existing watch's known kind takes precedence. Saved watches remain name-only identities. Cost: a colliding package of the other kind must be unwatched before switching kinds.
20. Use a fixed 300-point search viewport for suggestions and results, with input/footer outside and selection-following scrolling. Cost: short queries retain blank viewport space. Offscreen layout proves the bound, while live arrow navigation remains an unmet native gate.
21. Expose interval bounds once in `CheckInterval` and format the validation copy from them using the current locale. Cost: grouping follows system locale rather than always using English punctuation.
22. Reject any stderr from signed CLI diagnostics for all three help/version flags, at build and activation. Cost: a future intentional CLI warning must be considered explicitly before changing this contract.
23. Use the normal interval retry floor after transport or persistence failure. Reconnect bypasses transport backoff but preserves failed-save backoff. Cost: a reconnected machine with a save failure waits until that interval floor or a manual retry.
24. Keep a Quit footer action for a Dock-less temporary app. Harness-only appearance and synthetic service injection remain outside production composition. Cost: extra footer width and a separately built acceptance entry point.
25. Encode installer app-tree identity with sorted paths, entry types, full modes and content hashes, including directories/root. Derive expected version and golden help from admitted tracked inputs. Cost: metadata-only mode changes require a matching release; these checks establish identity, not compiler reproducibility.
26. Displace the live bundle inside apps-directory staging; retain the separately copied durable backup until recovery is no longer needed. Cost: both temporary staging and a retained backup consume space during activation.
27. Validate every saved backup payload against captured source identities and publish the path before activation. Preserve both errors if recovery fails. Cost: another complete app-tree read and more explicit operator recovery evidence.
28. Print running-app relaunch guidance only after replacement, including explicit rollback. Name the process-detector override BREW_VERSION_DEPLOY_TEST_ONLY_PGREP. Cost: tests must use the explicit override name.
29. Add standalone Node release integration checks after Swift Testing, building only in private OS temporary space and invoking release rather than test. Hold old executable descriptors and rebuild signed stale bundles. Cost: two isolated release builds plus synthetic acceptance/prototype builds per full test run.
30. Make synthetic acceptance a required category and use plain mktemp -d for both harnesses. Require golden help at the fleet inventory boundary too. Cost: operators clean up the printed temporary homes after native acceptance.
31. Collect cleanup failures through the installer operation boundary, including staging, restoration and shared atomic-file publication. Attempt all remaining cleanup, then report primary errors, every failed path and the durable backup. A completed deploy or rollback with cleanup failure retains the selected release and exits 1 with an explicit completion message. Cost: failed scratch paths remain for operator cleanup and an otherwise valid deployment still needs attention.

## Historical validation record

The counts and review statements below describe their individual earlier waves;
they are not current Task 10 validation or final whole-branch review evidence.

The implementation task reviews, whole-branch review and scoped review of all
four final fixes are complete. All four findings are addressed, with no new
breakage identified. Native runtime acceptance remains outstanding.

| Validation | Result |
| --- | --- |
| Complete Swift suite | 121 tests pass: 104 core, 11 CLI, 6 app |
| Release build and strict signatures | Pass for command and app; source, built plist and CLI version agree |
| Synthetic acceptance service / signed harness / Settings prototype | Pass for service test and builds; no GUI launch |
| All native/calculator installer suites | 59 tests pass, including 21 Brew Version cases |
| Static audit / complete fleet suite | 17 static tests pass; fleet reports PASS |
| Market Atlas complete suite | 423 Node tests and all six original browser runs pass |
| Market Atlas synthetic suite | 267 Node tests and 78 compiler tests pass |
| Full compiler discovery | 79 tests pass, including retained-input reproduction |

Market Atlas used the owner's already prepared external data and compiler environment. Its complete results precede the final native app/installer fixes, which did not change its code or the shared audit runner. No data acquisition, dependency/browser download, environment replacement or installed-site acceptance was performed. Data-bearing evidence remains outside the checkout.

## Final review fix wave

All four accepted final-review findings are implemented and the scoped
re-review is clean. Suggestion kind now survives lookup and Watch, multi-name search has
a bounded scrolling region, interval validation copy derives from domain bounds,
and CLI activation rejects unexpected stderr.

Regression evidence: removing explicit kind propagation resolves and watches the
synthetic shared token as a formula instead of a cask. Removing the production
search viewport produces 5,294-point offscreen content for 100 results instead
of 300 points. Query-generation, cancellation and known-watch-kind regressions
remain in the complete suite. Interval tests exercise bounds and US/German
grouping. Six signed synthetic executable cases reject stderr from all three
flags at build and activation and preserve prior artifacts and recovery copies.
The transient action checks cancellation before both lookup and empty-query
clearing; a cancelled empty task cannot erase a newer result.

The initial offscreen whole-section probe measured cleared content because its
query task restarted on hosting. The maintained `SearchResults` presentation is
now tested directly with all 100 rows present, without starting that task.
This establishes layout only. Native acceptance now explicitly includes a large
multi-token query, arrow scrolling, reachable input/footer and Return/Command-C.
The locked-desktop and unavailable macOS 14 gates remain unmet.

Fresh automated validation for the fix wave (no skips): 121 Swift tests
(104 core, 11 CLI, 6 app), 59 combined native/calculator installer tests and
17 static-audit tests pass. Release build and strict signatures, the one-test
synthetic acceptance service and signed harness, signed Settings prototype,
and offline CLI help/version smoke checks pass. Source plist, release plist
and CLI report the same initial release version. The complete fleet suite
reports PASS. The installer-only change does not alter the shared
static audit or its child runner, so Market Atlas's previously recorded complete
results were not rerun or presented as fresh results for this wave.

## Installer recovery choice

The earlier implementation retained a copy of the old app but did not validate
the copied tree before activation. Task 10 now re-reads and validates the app,
command, receipt and metadata against captured source identities before live
mutation. It prints the recovery backup first. Displace the old live bundle
inside the apps-directory staging folder so its move stays on the same device;
the durable backup may live on another device. Retain that verified copy through
activation and report both activation and restoration errors plus its path if
recovery fails. The cost is extra disk I/O and a retained backup per attempt.

## Catalog and scheduling follow-up

The cache now persists schema-1 slim Listing indexes with each list's ETag.
`CatalogClient` is an actor: `cached()` requires `await`, disk hydration runs once
per client, and 304 reuses decoded indexes. Bulk and individual API responses
share typed Listing field decoding; ignored API metadata is not retained.
Empty or unusable successful lists preserve the previous pair. The synthetic
acceptance service now supplies a usable cask list instead of treating `[]` as
a valid successful catalog.

Other updates visibility no longer controls catalog suggestions. Installation
snapshots and update derivation run off-main with stale-generation rejection;
watch filtering uses the retained derived list. Each rack is admitted once,
including the previously corrected legacy-cask and formula-revision behavior.
Unchanged state does not save. Conditional listing persistence is pruned to
watched names, and removal replaces the cache boundary so suspended old work
cannot reintroduce a removed watch's ETag after Undo.

The controller exposes `PersistenceIssue` separately from its message. Recovery
warnings, blocked loads and failed saves have distinct values. Its new
`networkAvailable` initializer argument and async `setNetworkAvailable(_:)`
support startup gating and immediate unreachable-check retries on reconnect,
while failed saves retain an automatic interval floor. App/SystemEvents and
retry-hint UI wiring is part of the following native-UI task.

Fresh validation: 144 Swift tests pass (127 core, 11 CLI, 6 app), the signed
release and strict signatures pass, CLI help matches the golden fixture with
empty stderr, and source/built plist/CLI versions agree at 1.0.0. The synthetic
acceptance service's one test and signed harness build pass. No GUI was launched
for this core task; release footprint and native acceptance are separate gates.

Scoped review found two asynchronous consumer gaps in that follow-up. A rejected
installation capture could still reach watch evaluation, and an earlier cache
snapshot could overwrite a concurrent addition. Superseded captures now retry
before returning; watch/search publication reads the accepted installed snapshot
after its final await. Checks capture conditional cache entries after the
installation await and retain the cache-identity guard. Controlled regressions
assert actual saved installed versions, amber state, notices and both saved
ETags. Fresh fix-round validation passes 146 Swift tests (129 core, 11 CLI,
6 app), release/signature and CLI checks, and the one-test synthetic acceptance
service plus signed harness build. Native and final footprint gates remain
separate from this fix round.

A second scoped review found that a newer shared installation snapshot may lack
a pending caller's cask auto-update/app-artifact metadata. The final cache await
allowed that substitution to persist Caskroom version 1 instead of app-bundle
version 2. Add and check now retain their exact accepted caller-metadata snapshot
through commit without further suspension. `ListingCache.snapshot()` is a
nonisolated synchronous value copy from small private NSLock-protected storage;
get/store remain actor-bound, and no mutable storage escapes the lock. The
internal cache dependency seam enables controlled actor-executor regression
without a production simulation mode. Both real synthetic cask variants and
concurrent stores/snapshots pass alongside all earlier race regressions.
Fresh validation passes 148 Swift tests (131 core, 11 CLI, 6 app), release and
signature checks, CLI output/stderr checks, and synthetic acceptance service and
signed harness build. Source, built plist and CLI remain 1.0.0; this core round
does not publish a release or establish new native/footprint acceptance.

## Installer and build follow-up validation

Task 10 addresses review items Should 9–13. The backup/device/recovery choices
above are exercised by signed synthetic lifecycle tests: a device-boundary
EXDEV update succeeds, genuine activation failure restores the old release,
corruption or failure of any backup payload leaves live artifacts untouched,
and failed restoration preserves both errors and the recovery path. Running-app
guidance covers replacement, already-current and explicit rollback paths.
The fleet now rejects a committed source inventory missing golden help before
running the native child audit.

The release target clears the bounded old app bundle, then copies each
executable to a unique temporary sibling before renaming. The full test target
adds three isolated Node integration checks for stale signed resources, held
executable inodes/bytes, and private OS-temporary acceptance/prototype homes.
No production UI source changed in this task.

Fresh Task 10 automated results, without skips:

| Validation | Result |
| --- | --- |
| Complete Swift suite | 148 pass: 131 core, 11 CLI, 6 app |
| Release build integration | 3 pass, including both synthetic harness builders |
| Release / strict signatures / offline CLI | Pass; golden help and version have empty stderr |
| Synthetic acceptance / Settings prototype | 1 service test passes; both signed builds pass; no GUI launch |
| Four native/calculator installer suites | 71 pass, including 33 Brew Version cases |
| Static audit / complete fleet suite | 17 pass / PASS |
| Market Atlas complete | 423 Node tests and all six original browser runs pass |
| Market Atlas synthetic / full compiler | 267 Node + 78 compiler / 79 compiler pass |

Source plist, release plist and CLI agree at 1.0.0. This task did not deploy or
publish a release. Market Atlas used only the prepared external data, locked
Node dependencies, managed Chromium and prepared compiler venv, with bytecode
disabled. No data, dependency or browser acquisition occurred. Data-bearing
logs stay in a fresh mode-0700 OS temporary directory outside the checkout.
Native UI interactions and final cold/cache memory measurements remain
controller-owned acceptance after the following UI task.

### Cleanup recovery review follow-up

Cleanup in an installer finally block could replace activation/restoration
errors and skip the remaining cleanup. Six signed synthetic regressions were
RED before the fix: compound deploy and rollback failures, completed deploy
and rollback with cleanup-only failure, failed app staging copy, and atomic
publication with failed staging cleanup. Cleanup now accumulates through the
operation boundary, including shared `atomicFile`, which serves every native
installer. Every owned cleanup is attempted, and the final error retains the
primary failures, each failed cleanup path and the durable backup path.

Cleanup-only failure after completed deploy or rollback keeps the selected
release active, returns status 1, and reports that activation completed. It
does not undo successful rollback merely because removing its staging folder
failed. A strengthened atomic-publication regression also requires the backup
path after successful restoration; the operation boundary supplies it.

Fresh full follow-up validation passes without skips: 148 Swift tests and
3 release integration tests, signed release and CLI help/version checks, the
one-test synthetic acceptance service and both signed harness builds,
77 combined installer tests (39 Brew Version), 17 static tests and the complete
fleet suite. Market Atlas passes 423 Node tests and six original browser runs,
267 synthetic Node plus 78 compiler tests, and all 79 full compiler tests.
Prepared external data, locked Node dependencies, managed Chromium and the
prepared venv were reused without acquisition or environment changes. Source,
release plist and CLI remain 1.0.0. No GUI, live deployment or final memory
acceptance was performed by this follow-up.
