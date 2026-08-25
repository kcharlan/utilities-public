# Moneydance NAS Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Moneydance retention require every configured NAS share, diagnose a unique stale-address replacement without leaking private values to persistent logs, and provide an explicit interactive `--repair-config` workflow that atomically updates only `NAS_SERVER` and never performs cleanup.

**Architecture:** Extend the existing standalone Zsh script rather than introducing repository runtime dependencies. Parse the mount table once into exact host/share maps, reuse one backup-directory validator for both the configured host and candidate hosts, and keep terminal-only detail separate from `log_message`. Repair mode is a mutually exclusive early-exit path that independently discovers one candidate, confirms through a TTY, atomically replaces the selected private config, and returns before retention enumeration.

**Tech Stack:** macOS Zsh, BSD command-line tools, the existing synthetic Zsh test harness, Git, and the repository's read-only deployment audit.

---

## Binding Context and Constraints

- Approved design: `docs/superpowers/specs/2026-08-24-moneydance-nas-repair-design.md`.
- Canonical source: `moneydance backup rotation/moneydance_rotate_backups.sh`.
- Deployed standalone copy: `~/Library/Scripts/moneydance_rotate_backups.sh`; it must be byte-for-byte identical to canonical source after deployment.
- Private runtime config: `${XDG_CONFIG_HOME:-$HOME/.config}/moneydance-backup-rotation/config`; it must never be copied into or printed from the public repository.
- Public source, docs, fixtures, assertions, and commit messages must use conspicuously synthetic host, share, directory, file, user, and path values.
- Persistent output means every non-terminal stdout/stderr stream, `log_message`, `LOG_FILE`, syslog, captured child-command diagnostic, and launch-agent output. These paths must remain redacted. Runtime host/share/directory/path detail may be emitted only by a dedicated terminal function after `[[ -t 1 ]]` succeeds. Every external command that can mention a private path must have stderr suppressed or captured and replaced with a generic redacted error.
- Use the current `codex/moneydance-nas-repair` feature branch. The project explicitly prefers feature branches and forbids creating a worktree unless the user asks for one.
- Follow TDD within each behavior task: add focused failing assertions, run the suite and confirm the expected failure, implement the minimum coherent behavior, then rerun the complete Moneydance suite.
- Do not weaken or delete existing retention, privacy, hostile-environment, standalone-copy, race-revalidation, or deletion-containment assertions.
- Commit this corrected plan before implementation. Track task progress in the controller's session plan; do not edit committed checkboxes during implementation. The Git worktree must be clean before the first code task and before live deployment.

## File and Interface Map

### Files modified

- `moneydance backup rotation/moneydance_rotate_backups.sh`
  - Add `REQUIRED_NAS_SHARES` and `MONEYDANCE_REQUIRED_NAS_SHARES` handling.
  - Add CLI mode state for `--repair-config`.
  - Add required-share normalization, exact mount inventory, host validation, candidate discovery, terminal-only detail, repair preflight, and atomic config replacement functions.
  - Keep retention classification and deletion logic semantically unchanged after a validated backup directory is selected.
- `moneydance backup rotation/tests/run_tests.zsh`
  - Extend environment isolation and fixture helpers.
  - Add synthetic multi-share, candidate-discovery, privacy, PTY repair, cancellation, atomic replacement, and failure-path assertions.
- `moneydance backup rotation/config.example`
  - Add a synthetic `REQUIRED_NAS_SHARES` example.
- `moneydance backup rotation/README.md`
  - Document the new config/environment setting, mount invariant, diagnostic privacy boundary, repair mode, exit behavior, and deployment-safe workflow.
- `docs/moneydance_nas_repair_implementation_plan.md`
  - Track execution checkboxes and adversarial-review corrections.

### Private deployment changes outside Git

- `~/.config/moneydance-backup-rotation/config`
  - Add the operator-approved two-share `REQUIRED_NAS_SHARES` value only after the compatible canonical script has been copied to `~/Library/Scripts`.
  - Preserve mode `0600` and all existing private values.

### Script interfaces to add

The implementer may adjust local variable names to match surrounding Zsh style, but these functional boundaries and contracts are binding:

- `normalize_required_shares VALUE`
  - Populate global array `required_nas_shares` in configured order.
  - Trim each comma-delimited item using `trim_config_value`.
  - Reject empty entries, duplicates, unsupported characters, and a list that does not contain `NAS_SHARE_NAME` exactly once.
- `parse_mount_inventory MOUNT_OUTPUT`
  - Populate a per-key mount-point collection/count and unique ordered array `mount_hosts`.
  - Use a composite key such as `${host}|${share}`; validation already excludes `|` from both components.
  - Accept only mount lines whose option/type field identifies `smbfs`, with sources `//host/share` or `//user@host/share`; decode only literal `\040` in share and mount-point fields.
  - Preserve first-seen host order and configured required-share order for deterministic diagnostics. Ignore malformed or non-SMB lines.
  - Treat more than one mount point for the same exact host/required-share pair as ambiguous and invalid. Never silently select the first or last duplicate.
- `host_has_required_shares HOST`
  - Return success only when every exact normalized required share has a map entry for the same host.
- `validate_backup_directory_for_host HOST`
  - Resolve the `NAS_SHARE_NAME` mount point and apply the existing accessible-directory, non-symlink, and containment prerequisites.
  - On success set `validated_backup_dir` and `resolved_validated_backup_dir`; on failure return nonzero without logging private values.
- `discover_replacement_candidates`
  - Examine hosts other than `NAS_SERVER`.
  - Populate `replacement_hosts` and per-host validated backup-directory data only for hosts satisfying all required shares and backup-directory checks.
- `terminal_detail MESSAGE...`
  - Print only when stdout is a TTY.
  - Never call `log_message`, `logger`, or write `LOG_FILE`.
- `validate_repair_preconditions`
  - Require stdin and stdout TTYs; an existing readable/writable regular non-symlink config owned by `EUID`; exactly one active `NAS_SERVER` assignment; no set `MONEYDANCE_NAS_SERVER` (empty or nonempty); and no `--dry-run` combination.
- `create_owned_config_temp CONFIG_PATH`
  - Set `umask 077`, inventory pre-existing exact-prefix candidates, and ask `MKTEMP_BIN` for a same-directory filename.
  - Before recording any cleanup target, require a canonical absolute direct child of the canonical config directory, the exact repair basename prefix, no pre-existence, a path different from the config, a regular non-symlink file, link count `1`, and owner `EUID`.
  - A hostile or malformed returned path must never be opened, truncated, chmodded, renamed, or removed.
- `repair_config_server OLD_HOST NEW_HOST CONFIG_PATH`
  - Acquire an exclusive same-directory repair lock validated with the same ownership/path discipline; a second cooperating repair exits operationally without mutation.
  - Create a private byte-for-byte snapshot of the config before parsing and capture device, inode, owner, group, mode, size, and content identity.
  - Generate the candidate from the snapshot. Match the loader's trimmed-key grammar, preserve all non-assignment bytes plus LF/CRLF/final-newline state, and reject NUL/binary input.
  - Immediately before replacement require full metadata identity and `cmp -s` byte equality between the live config and snapshot, then atomically rename. This cooperative lock and final comparison reduce races but do not claim compare-and-swap protection against an uncooperative writer in the final stat/rename window.
  - Remove only its own validated temporary file on failure.
  - Never invoke backup enumeration or deletion commands.

### Critical mount-selection flow

```text
load and validate config
normalize REQUIRED_NAS_SHARES
read mount table exactly once
parse exact host/share inventory and reject duplicate required-share mounts

if configured host has every required share
   and its primary share yields a safe backup directory:
    if repair mode: report that no repair is needed and exit 0
    otherwise: pass the validated directory into unchanged retention flow
else:
    discover fully valid replacement hosts
    emit only a redacted persistent warning
    emit detailed results only through terminal_detail
    if normal mode: exit 0 without cleanup or config mutation
    if repair mode and candidate count != 1: exit nonzero without mutation
    if repair mode and candidate count == 1:
        show terminal-only proposal
        prompt [y/N]
        on cancellation: exit 0 unchanged
        on approval: atomically update NAS_SERVER and exit 0 without cleanup
```

### Critical atomic-replacement flow

```text
acquire one validated same-directory exclusive repair lock
create a validated private byte snapshot before parsing
capture config device/inode/owner/group/mode/size identity
create and validate a new temp with mktemp in config's own directory
write from the snapshot, replacing only the single active NAS_SERVER assignment
preserve LF/CRLF and final-newline state for all other bytes
apply original mode to temp
verify original config still has the full captured metadata and is byte-equal to snapshot
rename temp over config with injected MV_BIN
clear temp ownership variable so EXIT cleanup cannot target the replacement
release only the validated owned repair lock
```

Use injected `MONEYDANCE_MV_BIN`, `MONEYDANCE_CHMOD_BIN`, and `MONEYDANCE_CMP_BIN` paths, defaulting to `/bin/mv`, `/bin/chmod`, and `/usr/bin/cmp`, so activation, mode, and content-revalidation failures are testable. Add all names to the test runner's ambient-environment clearing list. Split command preflight into common commands, normal-retention-only commands, and repair-only commands; repair must not require or invoke `FIND_BIN` or backup `RM_BIN`, while normal mode must not require repair-only commands.

## Adversarial Review Corrections

One independent adversarial review was completed before implementation. This corrected plan incorporates every finding:

- validated hostile-temp defenses before any write or cleanup target is accepted;
- private snapshot, full metadata plus byte revalidation, cooperative repair locking, and an explicit residual-race statement;
- atomic live deployment with protected rollback snapshots for both script and private config;
- duplicate mount rejection and deterministic inventory ordering;
- exact non-assignment byte preservation, including line endings and final-newline state;
- stderr and child-diagnostic privacy coverage;
- mixed-TTY, timeout, prompt-count, and exact-exit-status tests;
- mode-specific command preflight;
- a committed immutable plan with session-based progress tracking;
- whole-implementation review before deployment, with mandatory re-review after any later source change;
- a non-disclosing fixed-pattern privacy scan;
- set-but-empty environment-override refusal.

## Task 1: Required-share configuration contract

**Files:**

- Modify: `moneydance backup rotation/tests/run_tests.zsh` environment list, `make_config`, config-validation cases, environment-only case, and synthetic example validation.
- Modify: `moneydance backup rotation/moneydance_rotate_backups.sh` defaults, help, config loader, environment overrides, and `validate_config` area around current lines 13-188.
- Modify: `moneydance backup rotation/config.example` near current lines 3-5.

- [ ] **Step 1: Add failing configuration tests**

Add synthetic assertions covering:

- `REQUIRED_NAS_SHARES` is mandatory for file and environment-only configuration.
- A valid comma-delimited list containing `NAS_SHARE_NAME` passes.
- Whitespace around items is normalized.
- Empty items, duplicate items, unsupported characters, and omission of `NAS_SHARE_NAME` exit `2` before the mount mock is called.
- `MONEYDANCE_REQUIRED_NAS_SHARES` overrides the file value and is included in ambient-environment isolation.
- `config.example` remains valid and non-destructive.

Keep fixture values synthetic, for example `SYNTHETIC_PRIMARY,SYNTHETIC_COMPANION`.

- [ ] **Step 2: Run the suite and verify the new assertions fail for missing functionality**

Run:

```bash
cd "moneydance backup rotation"
./tests/run_tests.zsh
```

Expected: nonzero status with failures showing the unknown/missing `REQUIRED_NAS_SHARES` contract or absent environment override. Existing assertions must not be edited merely to obtain this failure.

- [ ] **Step 3: Implement the normalized required-share contract**

Add the config key, environment override, validation function, help text, and normalized global array described in the interface map. Track active `NAS_SERVER` assignment count while parsing, without changing normal-mode duplicate-key behavior; repair mode will consume the count later.

The loader must continue treating config as data, not shell code. Do not use `source`, `eval`, regex substitution on untrusted values, or delimiter characters permitted by validation.

- [ ] **Step 4: Update the synthetic example**

Add a conspicuously synthetic two-share `REQUIRED_NAS_SHARES` value next to `NAS_SHARE_NAME`. Do not add real operational values.

- [ ] **Step 5: Run the complete Moneydance suite**

Run `./tests/run_tests.zsh` from `moneydance backup rotation/`.

Expected: exit `0`, all assertions pass, and the summary reports `0 failed`.

- [ ] **Step 6: Commit Task 1**

```bash
git add -- "moneydance backup rotation/moneydance_rotate_backups.sh" \
  "moneydance backup rotation/tests/run_tests.zsh" \
  "moneydance backup rotation/config.example"
git commit -m "Require complete Moneydance NAS share configuration"
```

## Task 2: Exact mount inventory and fail-closed multi-share validation

**Files:**

- Modify: `moneydance backup rotation/tests/run_tests.zsh` mount mock helpers and mount-validation cases around the existing exact-host and escaped-space tests.
- Modify: `moneydance backup rotation/moneydance_rotate_backups.sh` mount-table and backup-directory selection area around current lines 204-261.

- [ ] **Step 1: Add failing inventory and configured-host tests**

Extend the mount mock to emit multiple synthetic lines. Add assertions for:

- All required shares on the configured host allow retention analysis.
- Either required share missing produces a safe no-op and preserves purge candidates.
- Required shares split across hosts do not qualify.
- Similar host/share names, case differences, and partial names do not qualify.
- Username-qualified sources and literal `\040` decoding still work for both required shares and mount points.
- The configured host may coexist with other fully populated hosts; configured host wins when valid.
- The backup directory must validate under `NAS_SHARE_NAME`, not a companion share.
- Duplicate primary or companion mounts for one exact host/share pair fail closed, including combinations where one duplicate is inaccessible.
- Malformed lines and `//host/share`-looking lines not marked `smbfs` are ignored.
- `MOUNT_BIN` is invoked exactly once per script run.

- [ ] **Step 2: Run the suite and verify failure**

Run `./tests/run_tests.zsh`.

Expected: nonzero with the new missing/split companion-share assertions failing because the current script validates only one host/share pair.

- [ ] **Step 3: Implement one-pass exact mount inventory**

Replace the single-match loop with `parse_mount_inventory`, `host_has_required_shares`, and `validate_backup_directory_for_host`. Read `MOUNT_BIN` once. Preserve exact matching and supported escape decoding. Do not log inventory values from reusable validators.

Bind the existing retention flow to `validated_backup_dir` and `resolved_validated_backup_dir`; do not change classification, retention-day, purge-candidate, or deletion revalidation semantics.

- [ ] **Step 4: Run the complete Moneydance suite**

Expected: exit `0` and `0 failed`, including every pre-existing deletion-safety test.

- [ ] **Step 5: Commit Task 2**

```bash
git add -- "moneydance backup rotation/moneydance_rotate_backups.sh" \
  "moneydance backup rotation/tests/run_tests.zsh"
git commit -m "Validate complete Moneydance NAS mount sets"
```

## Task 3: Candidate discovery and privacy-separated diagnostics

**Files:**

- Modify: `moneydance backup rotation/tests/run_tests.zsh` candidate and logging fixtures.
- Modify: `moneydance backup rotation/moneydance_rotate_backups.sh` after configured-host validation and before retention enumeration.

- [ ] **Step 1: Add failing discovery and privacy tests**

Add synthetic assertions for:

- Exactly one other host with all required shares and a valid backup directory is recognized.
- A partial host, split shares, invalid backup directory, and multiple valid hosts do not produce a repair recommendation.
- Normal mode exits `0`, does not call `RM_BIN`, does not mutate config, and preserves backup files for every mismatch outcome.
- Captured noninteractive stdout and stderr, `LOG_FILE`, a recording `LOGGER_BIN`, and captured child-command diagnostics do not contain synthetic private host/share/directory/path tokens.
- A PTY-backed normal invocation displays the detailed configured host, unique candidate, required shares, backup directory, and `--repair-config` instruction only on the terminal transcript.

Use `/usr/bin/script -q /dev/null ...` to allocate a PTY on macOS. Keep the command in a timeout-bounded test helper that returns child status and transcript separately, counts prompts, and can independently construct `(TTY stdin, non-TTY stdout)` and `(non-TTY stdin, TTY stdout)` cases. Repair tests must reuse this helper rather than inferring success from transcript text.

- [ ] **Step 2: Run the suite and verify failure**

Expected: nonzero because candidate discovery and terminal-only detail do not yet exist.

- [ ] **Step 3: Implement candidate discovery and terminal-only detail**

Add `discover_replacement_candidates` and `terminal_detail` from the interface map. Persistent messages must describe only outcomes and counts. They must not interpolate `NAS_SERVER`, share names, backup directory names, candidate hosts, mount points, config paths, or raw mount lines.

For interactive normal mode, detailed text must bypass `log_message` entirely. If stdout is not a TTY, omit details even when stderr is a TTY.

- [ ] **Step 4: Run the complete Moneydance suite**

Expected: exit `0`, `0 failed`, detailed PTY transcript assertions pass, and persistent-output redaction assertions pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add -- "moneydance backup rotation/moneydance_rotate_backups.sh" \
  "moneydance backup rotation/tests/run_tests.zsh"
git commit -m "Diagnose Moneydance NAS address changes privately"
```

## Task 4: Interactive atomic `--repair-config` mode

**Files:**

- Modify: `moneydance backup rotation/tests/run_tests.zsh` CLI, PTY, config identity, atomic-write, failure-injection, and no-cleanup cases.
- Modify: `moneydance backup rotation/moneydance_rotate_backups.sh` command paths, help, CLI parsing, repair preconditions, prompt, atomic replacement, and early-exit control flow.

- [ ] **Step 1: Add failing CLI and precondition tests**

Cover:

- Help documents `--repair-config` and exits without reading mounts.
- `--repair-config --dry-run` exits `2` before mount access.
- Noninteractive stdin or stdout is refused separately with exit `2`; EOF cannot hang.
- Missing, unreadable/unwritable, non-regular, and symlink configs are refused without mutation.
- Set-but-empty and nonempty `MONEYDANCE_NAS_SERVER` both cause repair refusal.
- Zero or multiple active `NAS_SERVER` assignments are refused.
- A valid configured host reports no repair needed and performs no cleanup.
- Zero or multiple replacement candidates exit `1` without mutation.
- Missing/failing `FIND_BIN` and `RM_BIN` do not prevent repair and are never invoked; normal mode does not require `MV_BIN`, `CHMOD_BIN`, or `CMP_BIN`.

- [ ] **Step 2: Add failing confirmation and atomicity tests**

Using PTY fixtures, cover:

- Default/negative confirmation exits `0`, leaves exact config bytes and mode unchanged, and never calls `FIND_BIN` or `RM_BIN`.
- Exact affirmative confirmation changes only the active `NAS_SERVER` assignment, preserves every other byte and the original mode, and never calls retention commands. Byte fixtures cover no final newline, CRLF, blank/comment lines, whitespace around the key and `=`, `NAS_SERVER_EXTRA`, commented assignments, and values containing the key text; NUL/binary config input is rejected.
- Terminal transcript contains the detailed proposal; configured log and fake syslog remain redacted.
- A hostile `MKTEMP_BIN` return naming the config itself, an outside path, pre-existing file, symlink, directory, multi-link file, wrong-owner file, or malformed-prefix path is rejected without opening, changing, or removing that path.
- Injected temp creation, chmod, write, snapshot comparison, metadata revalidation, and rename failures exit `1`, leave original bytes unchanged, and remove only validated owned temporary files.
- Same-inode content mutation, mode/owner/group mutation, or device/inode replacement after snapshot creation aborts instead of overwriting the changed file.
- The exclusive repair lock rejects a second cooperating invocation; tests also document the residual final comparison-to-rename race against uncooperative writers rather than claiming it is eliminated.
- Every path-bearing failure is redacted across stdout, stderr, configured log, fake syslog, and captured child diagnostics.
- Exact exit codes are asserted: `2` for CLI/config/precondition errors; `1` for discovery ambiguity or operational/write failure; `0` for no repair needed, cancellation, and successful update. Prompt count is exactly one for a repairable candidate.

- [ ] **Step 3: Run the suite and verify failure**

Expected: nonzero because the CLI mode and atomic replacement do not exist.

- [ ] **Step 4: Implement repair-mode CLI and preconditions**

Add `REPAIR_CONFIG=0`, parse `--repair-config`, reject its combination with `--dry-run`, and add `MV_BIN`/`CHMOD_BIN`/`CMP_BIN` injection. Split command preflight into common, normal-only, and repair-only sets. Validate repair-specific filesystem, ownership, lock, and environment constraints after general CLI parsing but before loading config values. Use `(( ${+MONEYDANCE_NAS_SERVER} ))` semantics so an exported empty override is still refused. In repair mode, snapshot the validated live config before parsing and pass the snapshot to `load_config`; retain the original path only as the eventual revalidated replacement target. Ensure `--help` still avoids config and mount inspection.

- [ ] **Step 5: Implement prompt and atomic replacement**

Follow the critical snapshot, validated-temp, cooperative-lock, full-revalidation, and replacement flow. Accept only `y` or `yes` case-insensitively after trimming; empty or any other response cancels. Never include private proposal values or child-command diagnostics in non-terminal stdout/stderr, `log_message`, syslog, or the configured log.

The repair branch must exit before creation of retention scan temp files and before any `FIND_BIN`, backup `STAT_BIN` classification, or deletion call.

- [ ] **Step 6: Run the complete Moneydance suite**

Expected: exit `0`, `0 failed`, all PTY and failure-injection tests pass, and all pre-existing retention tests remain green.

- [ ] **Step 7: Commit Task 4**

```bash
git add -- "moneydance backup rotation/moneydance_rotate_backups.sh" \
  "moneydance backup rotation/tests/run_tests.zsh"
git commit -m "Add explicit Moneydance NAS config repair mode"
```

## Task 5: Public documentation and repository privacy audit

**Files:**

- Modify: `moneydance backup rotation/README.md` privacy, requirements, setup, configuration, options, behavior, tests, and notes sections.
- Verify: `moneydance backup rotation/config.example`.

- [ ] **Step 1: Update public documentation**

Document:

- `REQUIRED_NAS_SHARES` format and exact/same-host invariant.
- `MONEYDANCE_REQUIRED_NAS_SHARES` environment override.
- Normal-mode candidate diagnostics and the separation between redacted persistent output and terminal-only details.
- `--repair-config` preconditions, unique-candidate requirement, prompt, atomic single-key update, exit-without-cleanup behavior, and required subsequent normal run.
- The fact that the utility discovers only already-mounted SMB shares and never scans or mounts the network.
- The private-config deployment order and the prohibition on committing operational values.

- [ ] **Step 2: Run privacy and formatting scans**

Run:

```bash
git diff --check
rg -n 'T[B]D|T[O]DO|F[I]XME|X[X]X' \
  "moneydance backup rotation/README.md" \
  "moneydance backup rotation/config.example"
git diff -- "moneydance backup rotation/README.md" \
  "moneydance backup rotation/config.example"
```

Expected: `git diff --check` is silent; placeholder scan returns no matches; diff contains only synthetic examples and the approved public behavior.

- [ ] **Step 3: Run the complete Moneydance suite**

Expected: exit `0` and `0 failed`.

- [ ] **Step 4: Commit Task 5**

```bash
git add -- "moneydance backup rotation/README.md" \
  "moneydance backup rotation/config.example"
git commit -m "Document Moneydance NAS repair workflow"
```

## Task 6: Final branch verification and whole-implementation review

**Files:** Verify every file changed from `main`; modify only when a review or verification failure identifies a root cause.

- [ ] **Step 1: Run the final verification matrix**

```bash
cd "moneydance backup rotation"
zsh -n moneydance_rotate_backups.sh
./tests/run_tests.zsh
cd ..
git diff --check main...HEAD
git status --short
```

Expected: syntax and tests exit `0`, summary reports `0 failed`, diff check is silent, and worktree is clean.

- [ ] **Step 2: Inspect branch scope and history**

```bash
git diff --stat main...HEAD
git diff --name-status main...HEAD
git log --oneline --decorate main..HEAD
```

Expected tracked scope:

- approved design spec;
- this implementation plan;
- Moneydance script;
- Moneydance tests;
- synthetic config example;
- Moneydance README.

No private config, deployed artifact, deployment backup, unrelated utility, or generated file may appear.

- [ ] **Step 3: Run a non-disclosing private-value scan**

Create a validated private temporary directory under a narrow temp parent with `umask 077`, canonical direct-child, owner, type, and non-preexistence checks equivalent to `tools/check_local_deployments.zsh:17-89`. Inside it, build a mode-`0600` fixed-string pattern file by reading only the private config's active location values and splitting its required-share list; never place those values in command arguments or print them.

Define the public scan set exactly with `git diff --name-only -z main...HEAD`. Run `rg -l -F -f "$pattern_file"` only against that NUL-delimited tracked-file set, report only matching public pathnames/counts, and fail on any match without printing lines or patterns. Remove only the validated owned temp directory. Expected: zero matching public files.

- [ ] **Step 4: Dispatch final whole-implementation review**

Provide the reviewer the approved design, corrected plan, complete `main...HEAD` diff, and fresh syntax/test/privacy evidence. Resolve every correctness, privacy, safety, or maintainability issue in dedicated commits and rerun the entire Task 6 matrix and whole-implementation review until approved.

- [ ] **Step 5: Freeze the reviewed deployment candidate**

Require a clean worktree, record the exact reviewed `HEAD`, and confirm the canonical script bytes at that commit match the working tree. Any later tracked change to the script, tests, config example, or README invalidates review evidence and returns execution to Task 6 before deployment.

## Task 7: Atomic private deployment and live dry run

**Files:**

- Deploy reviewed source: `moneydance backup rotation/moneydance_rotate_backups.sh` -> `~/Library/Scripts/moneydance_rotate_backups.sh`.
- Modify private config: `~/.config/moneydance-backup-rotation/config`.
- Create rollback snapshots only under `~/.utilities-deploy-backups/`.
- Do not modify the deployment-audit mapping unless verification reveals an actual mapping defect; none is expected.

- [ ] **Step 1: Validate live targets and initialize rollback storage**

Require a clean Git worktree still at the exact Task 6 reviewed commit. Resolve the deployed-script and private-config parents without following target symlinks. Reject missing, symlink, non-regular, wrong-owner, or unexpectedly permissive targets. Require the config at exact mode `0600` and the script executable.

Create a timestamped narrowly scoped rollback directory under `~/.utilities-deploy-backups/`, validate it as an owned canonical direct child, and set it to `0700`. Copy the exact pre-deployment bytes and full modes of both live targets into mode-`0600` backup files before replacing either target. Validate both backups byte-for-byte against their sources.

- [ ] **Step 2: Build and validate same-directory deployment candidates**

With `umask 077`, create validated, non-pre-existing, owned, single-link regular temp files in each target's own directory using the same hostile-return defenses as `create_owned_config_temp`.

- Copy the reviewed canonical script into the script candidate, apply the intended executable mode, verify `cmp -s` against canonical source, run `zsh -n` on the candidate, and run its `--help` smoke test without inspecting mounts.
- Generate the config candidate from the exact backed-up bytes, adding one active `REQUIRED_NAS_SHARES` assignment containing the two operator-approved private share names while preserving every other byte and final-newline state. Apply mode `0600`. Never print or commit the private values.

Immediately before each activation, revalidate the corresponding live target's full metadata and `cmp -s` equality against its rollback snapshot.

- [ ] **Step 3: Activate in compatible order with rollback**

Atomically rename the validated script candidate over the deployed script first, then atomically rename the validated config candidate over the private config. This creates only a brief fail-closed interval in which the new script can reject the not-yet-updated config.

If config activation fails after script activation, atomically restore the script from a validated same-directory candidate built from its rollback snapshot. If either post-activation validation fails, restore both targets from their validated rollback bytes and report failure. Never use a direct truncating copy over either live target.

- [ ] **Step 4: Run live safe verification**

Run the deployed script with `--dry-run` using its default private config. Expected:

- exit `0`;
- both required live shares are recognized on the configured NAS;
- the configured backup directory is inspected;
- no files are deleted;
- no config repair is proposed;
- non-terminal stdout/stderr and persistent logs remain redacted.

Then run `zsh tools/check_local_deployments.zsh` from the repository root and confirm the Moneydance mapping reports no drift.

- [ ] **Step 5: Verify and record deployment state without committing private data**

Verify canonical and deployed scripts are byte-for-byte identical, private config mode is `0600`, both rollback snapshots remain protected, Git is still at the reviewed commit with a clean worktree, and no private/deployment artifact appears in Git status.

Do not commit the private config, deployed copy, rollback snapshot, temp file, or any command output containing private values. If a post-review source change becomes necessary, stop, return to Task 6, obtain fresh whole-implementation approval, and repeat all deployment steps.
