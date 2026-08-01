# Vanguard Composite CSV Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Vanguard's composite multi-table CSV export by selecting its embedded investment transaction table without changing Fidelity conversion behavior.

**Architecture:** Keep brokerage format knowledge in `BrokerageAdapter`. Discover all registered transaction-contract headers across the CSV, require one unique selected table, and make `read_source` advance to that table. End an embedded Vanguard transaction section only at a blank-separated, adapter-owned surrounding-section header so malformed transaction rows remain errors.

**Tech Stack:** Python 3.12+ standard library (`csv`, dataclasses, pathlib), pytest, the existing PEP 723 uv launcher.

---

### Task 1: Reproduce the Vanguard composite export regression

**Files:**
- Modify: `tests/test_div_conv.py`

- [ ] **Step 1: Add a synthetic composite-export fixture helper**

Add test-only Vanguard holdings and account-activity headers and a helper that writes three blank-record-separated sections: a conspicuously synthetic holdings section, a Vanguard transaction section using `VANGUARD_HEADERS` plus the real export's extra `Accrued Interest`, `Account Type`, and trailing empty columns, and a synthetic account-activity section. Keep every value unmistakably fake.

- [ ] **Step 2: Add the end-to-end regression test**

Create `test_vanguard_composite_export_selects_embedded_transaction_table`. Configure a synthetic Vanguard account/security, write one dividend in the embedded transaction section, run automatic brokerage detection through `run_cli`, and assert the command succeeds. Assert the cooked CSV contains only the transaction header and transaction row, preserves all extra columns, and the QIF contains one `MiscInc`. Assert the CLI summary cites the physical source row from the composite file and neither surrounding section appears in either artifact.

- [ ] **Step 3: Run the regression test and verify RED**

Run:

```sh
.venv/bin/python -m pytest tests/test_div_conv.py::test_vanguard_composite_export_selects_embedded_transaction_table -v
```

Expected: FAIL because the command returns 2 with `UNKNOWN CSV CONTRACT`; no output artifacts exist.

### Task 2: Discover and select embedded transaction contracts

**Files:**
- Modify: `div_conv`
- Test: `tests/test_div_conv.py`

- [ ] **Step 1: Add adapter-owned surrounding-section contracts**

Add public-schema constants for Vanguard's holdings header and account-activity header. Extend `BrokerageAdapter` with an immutable `surrounding_section_headers: tuple[tuple[str, ...], ...]`, defaulting to empty, and register those two contracts only on the Vanguard adapter. Do not change its transaction `required_headers` or Fidelity adapter behavior.

- [ ] **Step 2: Add contract-header discovery**

Add a focused helper that reads the CSV with `utf-8-sig`, normalizes each record by trimming cells, and returns every physical row number/header matching each registered adapter through `adapter_header_matches`. Wrap `OSError`, `UnicodeError`, and `csv.Error` in the existing actionable `UserError` style. Empty/no-match files remain distinguishable by the existing public errors.

Add a selected-header helper with the binding behavior:

- no match for an explicitly selected adapter: `<path> does not match the <brokerage> CSV contract`;
- more than one match for that adapter: reject the file with a specific multiple-transaction-sections error;
- one match: return its physical row number and normalized declared header.

- [ ] **Step 3: Route detection and account resolution through discovery**

Update `detect_brokerage`, `validate_brokerage_contract`, and `source_account_for` to use the discovered selected header. Automatic detection must still report unknown when no adapter appears and ambiguous when more than one brokerage appears, including when different contract headers occur on different physical rows. Fidelity History's sole-account resolution must check its selected header, not the first table in a file.

- [ ] **Step 4: Parse only the selected table**

Update `read_source` to obtain the selected header and advance `csv.reader` to its physical row before parsing. Preserve `reader.line_num` as `RawTransaction.source_row`. Once transaction parsing has started, a nonblank row after a blank separator ends the section only when it matches one of the selected adapter's `surrounding_section_headers`; otherwise feed it through the existing width/action/date/amount/output-safety validations. Keep Fidelity's single-cell notice handling unchanged.

- [ ] **Step 5: Run the regression test and verify GREEN**

Run the single test from Task 1. Expected: PASS with one cooked transaction row and one QIF transaction.

### Task 3: Lock down ambiguity and validation boundaries

**Files:**
- Modify: `tests/test_div_conv.py`

- [ ] **Step 1: Test duplicate embedded Vanguard transaction tables**

Add `test_vanguard_composite_export_rejects_multiple_transaction_tables`. Write a synthetic file containing the Vanguard transaction header twice, assert return code 2, assert the specific multiple-sections error, and assert no artifacts are committed.

- [ ] **Step 2: Test malformed data after a blank is not hidden**

Add `test_vanguard_composite_export_does_not_hide_malformed_transaction_row_after_blank`. Put a short transaction-shaped row after a blank within the selected table without a recognized surrounding-section header. Assert the existing missing-cell error reports the correct physical row and no artifacts are committed.

- [ ] **Step 3: Run all focused Vanguard and contract tests**

Run:

```sh
.venv/bin/python -m pytest tests/test_div_conv.py -v -k 'vanguard or contract or mixed_brokerage or union_header'
```

Expected: all selected tests PASS with no warnings or errors from pytest.

### Task 4: Document the composite export contract

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update CSV-contract documentation**

Explain that Vanguard downloads may contain blank-record-separated holdings, investment-transactions, and account-activity tables. State that `div_conv` locates one unique investment transaction table, uses only that table for cooked CSV/QIF output, preserves its extra columns, rejects duplicate transaction tables, and still validates every selected-table row.

- [ ] **Step 2: Review documentation for privacy and consistency**

Confirm no local paths, account identifiers, transactions, real securities, or generated artifacts appear in the diff. Confirm the exact-header and blank-row descriptions agree with the new behavior.

### Task 5: Complete verification and delivery

**Files:**
- Verify: `div_conv`
- Verify: `tests/test_div_conv.py`
- Verify: `README.md`

- [ ] **Step 1: Run the complete project test suite**

Run:

```sh
.venv/bin/python -m pytest tests -v
```

Expected: every collected test PASS; zero failures, errors, or skips.

- [ ] **Step 2: Run the launcher fleet drift guard**

From the monorepo root, run:

```sh
uv run --script tools/check_uv_headers.py
```

Expected: the guard reports all registered uv launchers valid with no dependency/header drift.

- [ ] **Step 3: Revalidate both provided local exports without output artifacts**

Use the project virtual environment to load `div_conv` through `runpy`, redirect converter warnings/output to an in-memory buffer, and call `detect_brokerage`, `load_config`, `selected_section`, `source_account_for`, `read_source`, and `cook_transactions` for each provided file. Print only synthetic status labels. Expected: Vanguard selects `vanguard` and cooks successfully; Fidelity selects `fidelity` and matches its successful pre-change baseline. Do not print source values, mapped values, amounts, counts, account identifiers, or local filenames.

- [ ] **Step 4: Inspect the complete diff and staged content for sensitive data**

Run `git diff --check`, inspect `git status --short`, review the complete diff, and search staged content for credentials, local paths, account identifiers, financial values, or other non-synthetic private data. Sanitize before staging if anything is uncertain.

- [ ] **Step 5: Commit the implementation**

Stage only `div_conv`, `tests/test_div_conv.py`, `README.md`, and this plan. Commit with a concise message describing Vanguard composite CSV support. Do not commit local exports, runtime configuration, generated CSV/QIF files, caches, or validation logs.
