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
15. Atomically cache both raw catalog lists and ETags in one envelope. Cost: a hypothetical external cache reader would need that schema; no such consumer exists.
16. Use one four-request permit pool across checks, additions and search. Cost: large searches may queue behind checks; cancelled queued work drops before transport.
17. Retain intended SwiftUI SettingsLink path pending actual runtime evidence; a locked desktop does not establish failure. Cost: the planned AppKit fallback may still be needed after an unlocked probe.
18. Failed Undo suspends normal expiry and blocks replacement removals until successful retry; same-name Watch restores the saved entry. Cost: another Stop watching action waits for recovery. Ordinary Undo still expires after five seconds.

## Validation record

The implementation task reviews are complete. Final whole-branch review is pending. These results describe the committed implementation before that review's fixes:

| Validation | Result |
| --- | --- |
| Complete Swift suite | 117 tests pass: 102 core, 11 CLI, 4 app |
| Release build and strict signatures | Pass for command and app; source, built plist and CLI version agree |
| Synthetic acceptance service / signed harness / Settings prototype | Pass for service test and builds; no GUI launch |
| All native/calculator installer suites | 53 tests pass, including 15 Brew Version cases |
| Static audit / complete fleet suite | 17 static tests pass; fleet reports PASS |
| Market Atlas complete suite | 423 Node tests and all six original browser runs pass |
| Market Atlas synthetic suite | 267 Node tests and 78 compiler tests pass |
| Full compiler discovery | 79 tests pass, including retained-input reproduction |

Market Atlas used the owner's already prepared external data and compiler environment. No data acquisition, dependency/browser download, environment replacement or installed-site acceptance was performed. Data-bearing evidence remains outside the checkout.

## Remaining recorded finding

Two task-review improvements await final triage: custom interval error text duplicates domain bounds, and compiled installer diagnostics should reject unexpected stderr as well as assert exit status/stdout.

## Installer recovery choice

Keep a validated copy of the old app before moving the live old bundle. Retain that copy if the move fails, including cross-device failure. The extra temporary copy costs disk I/O and protects the restoration path; failed activation must not destroy its own backup.
