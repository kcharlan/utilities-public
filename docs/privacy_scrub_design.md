# Clean-Room Public Repository Design

## Decision

The existing `example/utilities` repository remains private and quarantined. It will not be history-rewritten or made public again.

A new repository, `example/utilities-public`, will be built at `/Users/example/source/utilities-public` from an audited, history-free export of tracked source. It starts private and becomes public only after tests, privacy audits, review, and fresh-clone verification succeed.

## Why this replaces history rewriting

GitHub-managed pull-request refs and cached commits can keep rewritten sensitive objects reachable. A brand-new repository has no shared commit graph, pull-request refs, reflogs, or objects with the private repository. This makes the publication boundary a file-admission problem instead of a history-rewrite problem.

The old public exposure cannot be revoked from third-party clones, caches, or downloads. Keeping the old repository private contains the remaining GitHub-hosted copy while the new repository publishes only sanitized content.

## Trust boundary

The private repository and its restricted recovery mirror are untrusted sources of potentially sensitive material. Files cross into the public repository only through an explicit allowlisted export and subsequent audit.

Never copy:

- Git metadata or history;
- untracked or ignored files;
- local configuration, runtime state, caches, logs, exports, reports, or virtual environments;
- any financial utility directory known to contain embedded accounts, holdings, mappings, or transaction data.

The export omits `fid_div_conv/`, `van_div_conv/`, `qif_div_converter/`, and `etf_montecarlo/`. Sanitized `div_conv` and ETF Monte Carlo projects are added later as new code.

## Configuration model

Operational data belongs in user-home runtime configuration:

- `~/.div_conv/config.json`
- `~/.etf_montecarlo/config.json`
- `~/.md-autotax/config.json` and its private tax table
- `~/.hysa-excel/inputs.csv`
- `~/.config/moneydance-backup-rotation/config`

Environment variables may override those homes for controlled testing. Financial launchers contain schemas and incomplete skeletons only. The dividend and ETF launchers write an incomplete skeleton on first run, emit a prominent warning, and stop before processing or network access. Other tools document their private local inputs and never silently substitute tracked operational defaults.

Tracked example configuration uses unmistakable synthetic placeholders and is documentation only. It cannot silently function as a real default.

## Public-repository policy

The root `README.md`, `agents.md`, and `CLAUDE.md` state that the repository is public-facing and prohibit sensitive data in code, tests, fixtures, documentation, examples, logs, screenshots, generated output, or commits. Synthetic fixtures and staged-content privacy review are mandatory.

Targeted `.gitignore` rules prevent project-local runtime files from being staged accidentally. Runtime homes outside the repository remain the primary control; ignore rules are defense in depth.

## Verification gates

Before Git initialization and again before every push:

1. scan all file content against the private literal inventory without printing values;
2. review filenames, configuration-like files, binaries, and archives;
3. run credential and high-entropy secret scans;
4. verify excluded paths and legacy runtime names are absent;
5. run every applicable automated test and validation command;
6. resolve every finding and failure.

After pushing to the new private remote, repeat the same checks from a fresh clone. Public visibility is the final external mutation and occurs only after independent specification, code-quality, and privacy review approve the clone.

## Recovery and deletion

The old repository stays private throughout migration. The restricted literal inventory and recovery mirror remain available until the new public repository is verified. They are deleted only after successful publication. Deleting the old private GitHub repository is a later user decision and is not required for the clean repository to be safe.
