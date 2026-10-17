# Brew Version implementation and acceptance record

## Outstanding acceptance

Native UI is unverified. The permitted computer-use tool reported the Mac was locked and required manual unlocking. No alternative GUI route was used. Current-system Settings, search/keyboard/Undo, notification permission/delivery/click, Other updates, login status and light/dark checks remain open. The minimum supported macOS runtime is also unavailable. Source/build/test success does not establish these runtime checks.

No live installation, deployment, push or merge was performed. Preserve this distinction in the final report.

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

## Validation record

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

Keep a validated copy of the old app before moving the live old bundle. Retain that copy if the move fails, including cross-device failure. The extra temporary copy costs disk I/O and protects the restoration path; failed activation must not destroy its own backup.

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
