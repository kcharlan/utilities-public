# Clean-Room Public Utilities Repository Implementation Plan

> **Required workflow:** Use `superpowers:executing-plans` for the clean-room export and publication steps. Use `superpowers:subagent-driven-development` with test-driven development, specification review, and quality review for each bounded code task.

## Goal

Create `/Users/example/source/utilities-public` as a new repository with no Git relationship to the private `utilities` repository. Publish only audited source files, rebuild financial utilities so operational values live exclusively in local configuration, and create a new private GitHub repository that is made public only after fresh-clone verification.

The existing `example/utilities` repository remains private and quarantined. No history rewrite or force-push is required.

## Non-Negotiable Privacy Rules

- Never copy `.git/`, reflogs, branches, pull-request refs, or commit objects from the private repository.
- Never copy untracked files, ignored files, virtual environments, caches, runtime state, logs, generated reports, downloaded exports, or local configuration.
- Export from the recorded `origin/main` tree, not from the current working tree.
- Exclude `fid_div_conv/`, `van_div_conv/`, `qif_div_converter/`, and `etf_montecarlo/` during export. The first three remain absent. A sanitized ETF utility may be added later as new source.
- Do not copy the existing `div_conv/` implementation from the private feature branch. Rebuild it from the approved behavioral specification using conspicuously synthetic tests.
- Operational account names, account identifiers, institutions, transfer targets, categories, securities, ticker symbols, holdings, share counts, balances, transaction values, export filenames, and dates must never appear in tracked source.
- Local runtime configuration belongs under user-home runtime directories such as `~/.div_conv/` and `~/.etf_montecarlo/`, never beside the source.
- Tracked example configuration files contain only conspicuously synthetic placeholders and cannot perform a real brokerage operation without editing.
- Repository-root `README.md`, `agents.md`, and `CLAUDE.md` must prominently state that the repository is public-facing and sensitive data must never be placed in code, fixtures, documentation, examples, logs, generated artifacts, or commits.
- The private literal inventory stays in a mode-0700 temporary directory outside both repositories and is destroyed only after the new public repository passes fresh-clone verification.
- The new GitHub repository starts private. Public visibility is the final operation after all tests, privacy audits, reviews, and fresh-clone checks pass.

## Synthetic Vocabulary

Public fixtures and examples use only unmistakable placeholders:

```text
SYNTHETIC FIDELITY ACCOUNT
SYNTHETIC VANGUARD ACCOUNT
SYNTHETIC CHECKING
SYNTHETIC CASH
SYNTH1
SYNTH2
SYNTHETIC INCOME FUND
SYNTHETIC SETTLEMENT FUND
Synthetic:Dividends
TEST0000
2030-01-02 through 2030-01-05
10.00 through 40.00
```

No realistic-looking account identifiers or portfolio values are permitted.
Additional test-only labels must begin with `SYNTHETIC `, and parser unit tests may
use non-operational numeric strings needed to exercise accepted and rejected
number formats. These test-only values are not brokerage fixtures or examples.

---

## Task 1: Freeze the private source and prepare the clean destination

1. Confirm `example/utilities` is private and has no public forks.
2. Record the exact `origin/main` object ID and confirm the remote has not changed.
3. Confirm `/Users/example/source/utilities-public` does not exist, or stop if it contains any data.
4. Retain the existing restricted recovery mirror and private literal inventory until publication verification completes.
5. Verify the unrelated local worktree is clean before removing it later; do not copy from it.

## Task 2: Create an allowlisted, history-free source export

1. Create `/Users/example/source/utilities-public` with restrictive initial permissions.
2. Stream the tracked `origin/main` tree into the destination while excluding:
   - `.git/`
   - `fid_div_conv/`
   - `van_div_conv/`
   - `qif_div_converter/`
   - `etf_montecarlo/`
3. Confirm the destination contains no `.git` directory and none of the excluded paths.
4. Confirm no untracked or ignored source-repository file was copied.
5. Copy only the approved privacy design and this plan from the private feature branch after scanning them against the private literal inventory.

## Task 3: Establish repository-wide public-data policy

Modify the destination only:

- `README.md`
- `agents.md`
- Create `CLAUDE.md`
- `.gitignore`

Requirements:

1. Add a prominent public-repository privacy warning to all three documentation/instruction files.
2. Prohibit secrets and personal, financial, brokerage, health, location, authentication, customer, production, and other sensitive data in source, tests, fixtures, examples, documentation, logs, screenshots, generated artifacts, and commit history.
3. Require synthetic fixtures and local user-home configuration.
4. Require a staged-content privacy review before every commit.
5. Add targeted ignore rules for local configurations and runtime artifacts without broadly ignoring legitimate source files named `config.json` in unrelated projects.
6. Document the local configuration convention and the use of tracked `*.example.json` templates.

## Task 4: Rebuild `div_conv` with local-only configuration

Create a new `div_conv/` project using a stdlib-only uv launcher and pytest tests.

Required behavior:

1. One launcher handles Fidelity and Vanguard exports through shared processing and separate adapters.
2. Configuration lives at `~/.div_conv/config.json`, honoring `DIV_CONV_HOME` for tests and controlled overrides.
3. The launcher contains schema keys and empty configuration skeletons only. It contains no usable accounts, mappings, securities, categories, or transfer targets.
4. First run writes an incomplete skeleton atomically, prints a prominent configuration-required warning naming the config path, and exits before processing.
5. A missing brokerage section is backfilled with an empty skeleton and a prominent warning naming the config path and section. Another fully configured brokerage may continue; selecting the incomplete brokerage fails actionably.
6. No automatic migration from `~/.fid_div_conv`, `~/.van_div_conv`, adjacent files, or legacy environment variables.
7. Unknown top-level keys, unregistered brokerage sections, and unknown keys inside registered sections are preserved.
8. Config writes use a same-directory temporary file, flush, `fsync`, `os.replace`, and failure cleanup.
9. Auto-detection, explicit brokerage override, mixed-file rejection, cooked CSV output, QIF output, summaries, and error recovery match the approved converter behavior.
10. Tests and `config.example.json` use only the synthetic vocabulary above.
11. Register the launcher with `tools/check_uv_headers.py` and update root/project documentation.

Validation:

```bash
cd /Users/example/source/utilities-public/div_conv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -v
cd /Users/example/source/utilities-public
div_conv/.venv/bin/python -m pytest tools/tests -v
uv run --script tools/check_uv_headers.py
```

## Task 5: Rebuild ETF Monte Carlo inputs as local configuration

Re-add `etf_montecarlo/` as new source without copying its private history or hard-coded portfolio.

Required behavior:

1. Tickers, share counts, and all portfolio-specific parameters come from `~/.etf_montecarlo/config.json`, honoring `ETF_MONTECARLO_HOME` for tests.
2. First run writes an incomplete skeleton and exits with a prominent configuration-required warning.
3. No ticker symbol, share count, holding, balance, or plausible portfolio appears in source, tests, documentation, or defaults.
4. `config.example.json` uses only `SYNTH1` and `SYNTH2` with zero placeholder shares and clearly explains that the symbols must be replaced locally.
5. Preserve the legacy dividend-income behavior: load trailing-year dividend payments, infer payment frequency from the median annual count, bootstrap payments with replacement, and report P5/P25/P50/P75/P95 annual income per share and per configured holding plus a portfolio aggregate. Fail clearly before network access when configuration is absent or incomplete.
6. Add isolated tests for config lifecycle and validation. Mock or separate network-dependent behavior so tests do not contact finance services.

## Task 6: Whole-tree privacy and secret audit before Git initialization

Before the whole-tree audit, sanitize pre-existing financial artifacts:

1. Remove the generated `hysa-excel/CD_vs_HYSA_Model_TEMPLATE_MATCH.xlsx` workbook from source control.
2. Replace `hysa-excel/inputs.csv` with a tracked, conspicuously synthetic `inputs.example.csv`; load operational inputs from a user-home runtime path or an explicit CLI path.
3. Add tests that first-run setup creates an incomplete local input template and stops before generating a workbook.
4. Inspect `expense_dock/docs/Expense_Tracker_Template.xlsx` for private literals, credentials, personal metadata, and realistic transaction rows. Keep it only if all sample rows are conspicuously synthetic and its metadata is sanitized; otherwise rebuild a synthetic template.

1. Scan every destination file against the private literal inventory without printing literal values.
2. Review all filenames and paths for account identifiers, brokerage export names, personal names, dates, or generated-report patterns.
3. Enumerate configuration-like files. Each must be either application source configuration, a conspicuously synthetic example, or explicitly approved public test data.
4. Scan for private keys, tokens, passwords, credentials, high-entropy secrets, email addresses, home-directory paths, and other personal identifiers.
5. Review binaries and archives; remove unexplained or stateful artifacts.
6. Confirm excluded paths and old launcher/runtime-home names are absent except in explanatory migration documentation that contains no operational data.
7. Any unresolved candidate blocks Git initialization.

## Task 7: Complete test accountability

1. Inventory every test suite and validation command in the destination.
2. Run the complete applicable suite, including unit, integration, CLI, browser/Playwright, header guard, and project-specific smoke checks.
3. Do not dismiss any failure. Diagnose and fix every failure before continuing.
4. Record exact commands, exit codes, and test counts in the private work log.
5. Repeat the privacy scan after all test-generated artifacts are cleaned.

## Task 8: Initialize clean history and create the private GitHub repository

1. Initialize a new Git repository in `/Users/example/source/utilities-public` with default branch `main`.
2. Review the complete staged file list and staged diff.
3. Repeat the private-literal and secret scans against staged blobs.
4. Create one clean initial commit only after all gates pass.
5. Create `example/utilities-public` as a new **private** GitHub repository and push `main` normally.
6. Confirm the remote contains only the new `main` history and no pull-request refs, legacy objects, branches, or tags.

## Task 9: Fresh-clone verification and public release

1. Clone the new private remote into a new temporary directory.
2. Confirm the clone contains exactly one clean root history and none of the excluded paths.
3. Repeat whole-tree privacy, secret, filename, configuration, and binary/archive audits.
4. Run the complete applicable test and validation suite in the fresh clone.
5. Dispatch a final specification reviewer and a final code-quality/privacy reviewer. Resolve every finding and repeat verification.
6. Change `example/utilities-public` visibility to public only after every gate passes.
7. Verify anonymous/public repository visibility and recheck the published file tree.
8. Delete the restricted literal inventory and temporary export/audit artifacts only after public verification succeeds. Keep the original `utilities` repository private until the user decides to delete it.

## Completion Criteria

- The new repository has no shared Git objects or history with `example/utilities`.
- The new history begins with a clean initial commit.
- The root README and both agent instruction files contain prominent public-data warnings.
- The legacy converter projects and historical QIF converter are absent.
- `div_conv` and ETF Monte Carlo read operational values only from local user-home configuration.
- Every tracked example and fixture is conspicuously synthetic.
- Every applicable test and validation command passes.
- Whole-tree and staged-blob privacy audits report zero unresolved findings.
- A fresh clone independently passes the same gates before publication.
- The original repository remains private.
