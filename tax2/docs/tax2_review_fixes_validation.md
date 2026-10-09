# Tax2 review-fixes validation

The approved review-fixes plan is implemented on `codex/tax2-built-page`.
Validation used synthetic runtime homes outside the checkout; no deployed copy
or real user config was accessed. Publication and history rewriting remain
separate follow-up work.

## Final gates

| Gate | Result |
| --- | --- |
| Tax2 baseline, before fixes | 352 passed, zero skipped |
| Final `.venv/bin/python -m pytest -q -p no:cacheprovider` | 404 passed in 38.03s, zero skipped |
| uv header guard | OK, 19 launchers |
| Header-guard tests | 10 passed |
| Fleet deployment shell tests | PASS |
| Static deployment Node tests | 17 passed, zero skipped |
| Restored uv requirements test command, proved before the final test additions | 396 passed; no browser installation |

The actual uv launcher passed help, default and explicit-output builds, and a
warmed `UV_OFFLINE=1` rebuild. Runtime-home/config/page modes were
`0700/0600/0600`; explicit output was `0600`. A case-variant config destination
exited 1 with `Tax2: Output destination would replace config.yaml`, preserving
config bytes and nanosecond modification time.

Offline Chromium opened the actual launcher-built page and exercised earned
and unearned income, multiple states, and a 50% allocation. QIF, Markdown and
CSV downloads were verified, including matching QIF amounts and 10,001 CSV
data rows. Invalid income retained its visible indicator on focus and blur and
showed `Total unavailable — fix the highlighted inputs.` Allocation `0x10`
was rejected with `Enter 0–100`; correcting it restored results. There were
zero external requests and zero page or console errors. The owned acceptance
home was removed.

Bundled rules, frozen parity rules and JSON, vendor assets, and the original
visual reference are unchanged. The separate pre-refactor payload capture is
unchanged since its capture commit. Privacy searches, source-hygiene checks,
and the restricted deployment-document diff passed.

## Added tests

Every name below passed in the final full suite, including every parameterized
case. There are 39 new test functions; parameterization increases the suite
from 352 to 404 cases. Existing tests were also strengthened for exact error
messages, accepted decimal inputs, private screenshots and payload hygiene.

| Test | Status |
| --- | --- |
| `test_shared_rate_percent_rounds_up` | PASS |
| `test_allocation_decimal_only_and_keyboard_recovery` | PASS |
| `test_income_total_error_recovery_and_rate_display` | PASS |
| `test_invalid_indicator_and_valid_style_restoration` | PASS |
| `test_title_empty_zero_focus_and_independent_desktop_scroll` | PASS |
| `test_tablet_sidebar_spans_main_and_export` | PASS |
| `test_available_years_multi_year_format` | PASS |
| `test_non_mapping_config_warns` | PASS |
| `test_entry_matches_unicode_missing_and_existing_identity` | PASS |
| `test_config_resolution_preserves_link_dotdot_and_missing_tail` | PASS |
| `test_config_resolution_bounded_and_read_errors` | PASS |
| `test_missing_config_does_not_warn` | PASS |
| `test_schedule_manual_procedure_applies_credits_before_monthly_rounding` | PASS |
| `test_schedule_escapes_every_user_supplied_label_path` | PASS |
| `test_engine_digit_grouping_regex_has_one_shared_definition` | PASS |
| `test_live_annual_golden_baselines_match_exact_frozen_values` | PASS |
| `test_case_variant_config_output_rejected` | PASS |
| `test_case_variant_config_output_rejected_on_first_run` | PASS |
| `test_case_variant_missing_parent_rejected_early` | PASS |
| `test_case_variant_missing_target_parent_rejected` | PASS |
| `test_prepublish_recheck_rejects_conflict` | PASS |
| `test_dangling_config_symlink_target_rejected` | PASS |
| `test_unresolvable_config_chain_still_builds` | PASS |
| `test_intermediate_config_symlink_rejected` | PASS |
| `test_directory_symlink_in_config_path_rejected` | PASS |
| `test_config_symlink_loop_still_builds_default_output` | PASS |
| `test_display_name_falls_back_to_directory_name` | PASS |
| `test_broken_year_symlink_fails_build` | PASS |
| `test_non_regular_year_entry_fails_build` | PASS |
| `test_non_ascii_digit_year_ignored` | PASS |
| `test_bundled_payload_unchanged_by_discovery_refactor` | PASS |
| `test_fifo_year_entry_rejected_before_read` | PASS |
| `test_leading_zero_duplicate_precedence` | PASS |
| `test_regular_year_symlink_is_valid` | PASS |
| `test_shadowed_leading_zero_candidate_still_validates` | PASS |
| `test_discovery_single_implementation` | PASS |
| `test_discovery_groups_all_entry_types_in_filename_order` | PASS |
| `test_retired_config_key_source_inventory` | PASS |
| `test_tests_do_not_use_fixed_temporary_paths` | PASS |

## Development failures resolved

Intentional red regressions exposed the config-protection, discovery, UI,
schedule, escaping, grouping, fallback and source-hygiene defects before their
fixes. All final assertions passed. Intermediate harness errors were corrected:
wrong test working directory, a missing wait for theme application, nested
Playwright synchronous fixtures, and guessed browser selectors. An initial
manual probe expected Pennsylvania tax of $142.00; the correct upward-cent
result was $141.99, and the corrected probe passed. No assertions were removed
to suppress a product failure.

## Review record

Fresh specification and quality reviews gated each code task. The final
whole-diff review found no remaining material issues. Documentation and this
report received one full clean-context round: adversarial review, fixes, and
a fresh sanity check. Zero material findings and two polish findings were
fixed (a stale helper name and an unsupported formatting-description clause).
The sanity check approved the fixes and required no second round. No findings
were rejected or remain unresolved; no material edits followed the sanity
check. This review-record update only records its outcome.

## Tie-off

Fixes, each committed with the acceptance tests that pin it:

| Item | Change | Commit |
|---|---|---|
| I1 | Config existence is tested with `os.lstat` on the entry; an unreadable chain warns `Unable to read config.yaml; using defaults` once, uses defaults and still builds. README documents both config warnings in the launcher contract (P1). | `a577e60` |
| I5, I3 | `ensure_no_config_conflict` is the single conflict-then-raise step; the launcher no longer references `config_conflict`. The pre-publish recheck test blinds only the first real `config_conflict` call. | `a745d40` |
| I2 | Licence notices are escaped into a `<template>` and mounted at the end of the export column; the desktop document no longer scrolls. | `3552970` |
| P3 | Focused invalid inputs show a `--accent-tax-light` ring instead of the income glow. | `bdc611d` |
| I4, P2 | Non-vacuous schedule, `0x10` message, uppercase-extension discovery and `app.js` percent-regex assertions; explicit if/else in a launcher test. | `f061480` |
| Docs | Design spec §3, §5.1, §6.1, §6.2 and §9.2 updated, including the renamed layout test. | `b934045` |

Tests added: `test_unreadable_config_chain_still_builds`,
`test_unreadable_config_chain_unrelated_output_builds`,
`test_config_helpers_tolerate_permission_errors`,
`test_load_config_tolerates_raising_exists`,
`test_desktop_wheel_scroll_never_moves_window`,
`test_license_notices_reachable_at_all_widths` (3 sizes),
`test_config_conflict_raise_has_one_home` and
`test_invalid_focus_has_no_income_glow` (3 widths × 2 themes). Before the
fixes, 13 of these 15 cases failed; the licence-notice cases at 1024×700 and
390×844 already passed. Existing tests were strengthened as listed in the
design spec's §9.2 tie-off entry; the strengthened pre-publish recheck test
passed before the fixes as intended.

Results (2026-10-08):
- Full suite from `tax2/` with a fresh `TAX2_HOME`: 419 passed, 0 failed,
  0 skipped.
- `tools/check_uv_headers.py`: OK (19 launchers verified);
  `tools/tests/test_check_uv_headers.py`: 10 passed;
  `test_check_local_deployments.zsh`: PASS;
  `check_static_deployments.test.mjs`: 17 pass, 0 fail.
- Validation-matrix acceptance in a fresh private home: help exit 0; build
  modes 0700/0600/0600; `UV_OFFLINE=1` rebuild exit 0; explicit `--output`
  page 0600. Offline Chromium on the `file://` page: synthetic income,
  Georgia 60% and Pennsylvania 40%, an invalid allocation showing
  `Enter 0–100` with QIF disabled, then recovery and all three downloads;
  zero external requests and zero page or console errors. The home was
  removed.
- Repro checks: the chmod-000 config chain default build exits 0 with the
  warning once and leaves the blocked tree untouched; a real mouse-wheel
  probe over the export column at 1440×600 keeps `window.scrollY` at 0
  (document 600 px tall).
- The new and changed browser tests passed three consecutive runs (19 cases
  each): the 10 new cases (`test_desktop_wheel_scroll_never_moves_window`,
  `test_license_notices_reachable_at_all_widths` ×3,
  `test_invalid_focus_has_no_income_glow` ×6) plus the changed browser tests
  in `tests/test_browser_smoke.py`.
- An independent re-validation on the same day reproduced 419 passed with
  0 skipped, every repository gate, the validation-matrix acceptance, both
  repro checks and an offline Chromium pass, and found no material issues.
