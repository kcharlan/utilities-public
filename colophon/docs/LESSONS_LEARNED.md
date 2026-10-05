# Lessons learned

- Acceptance axes must match: a canonical git project can contain several raw
  working directories. Compare Colophon cwd groups with native source reports,
  preserve canonical CLI/native checks, and reconcile source days/models with
  their parent before summing any shared raw path. A matching overall total can
  conceal offsetting source-day or model-component errors.

- Native split emission has report scope: pinned `makeCodexBilledDayEntry`
  gates four branch fields on `hasModeSplit`, and `CostUsageModels.swift`'s
  `BreakdownAccumulator` skips nil file contributions while marking a field
  present if any file supplied it. A supplied directory field cannot certify
  complete split coverage. Keep daily-to-aggregate component conservation
  within every report mandatory; report every cross-boundary split discrepancy
  as native presentation evidence, separate from Colophon usage differences.
  Retain only observed omission evidence and each offsetting day, without
  reconstructing file contributions. Model identities, complete token/cost
  totals and agreement across native observations still fail when mismatched.
- Two distinct wrapper timestamps alone do not prove collapsed timing. The
  approved §15 item 6 decision keeps the multiple-identical-values rule and
  existing time provenance, unknown flags and duration fallbacks.

- Acceptance table checks must compare the actual ledger shape: long-context
  rates are flat fields beside `threshold`, while only standard rates live
  under `per_million`. A synthetic fixture that invents the verifier's shape
  can hide this mismatch until the pinned source check. Regression:
  `test_table_comparison_exact_decimal_history_and_priority`.
- Swift drift extraction must skip type-annotation delimiters before selecting
  a literal initializer or closure body. Match strings at bounded source
  offsets and cache declaration maps per file; slicing every remaining suffix
  turns a source scan quadratic. Regressions:
  `test_drift_typed_initializers_include_changed_values` and
  `test_drift_scanner_does_not_copy_unbounded_suffixes`.
- A cited source filename is not an enclosing-type citation. Remove filename
  tokens before matching declaration names, so a change to an uncited sibling
  does not appear as a change to every cited function. Regression:
  `test_drift_file_name_does_not_cite_same_named_enclosing_type`.

- Collapsed reader sections remain in the DOM. Assert their visibility and
  scope parent tool checks separately from miniature agent cards; hidden
  expand buttons still participate in `textContent`. Keep request-group labels,
  displayed text and nested tool coverage explicit. Regressions:
  `test_turn_requests_before_group_followups_voice_and_long_text` and
  `test_turn_header_tools_rate_periods_and_subagent_expansion`.
- "Your sessions" includes orphaned agents as top-level rows (Task11), while
  linked children roll up into their parent. Synthetic ranking fixtures must
  keep their own/bucket/turn/outside quantities and clocks consistent before
  testing ordering. Regressions:
  `test_list_day_groups_rows_and_top_level_sessions_include_orphans` and
  `test_list_fixture_usage_and_clock_invariants`.
- Compiler row order is not an identity contract. Assign reader fixture labels,
  fork flags and inferred links by explicit child ID, never dictionary iteration
  position. Token display must retain unknown malformed counters rather than
  truthiness-defaulting them to zero; validate both components and their sum
  with the existing safe-integer guard. Resize must repeat rendered label
  measurement, including second-row and tooltip fallback. Regressions:
  `test_timeline_lanes_ticks_fork_badges_and_inferred_border`,
  `test_malformed_token_components_remain_unknown_in_each_reader_surface`,
  `test_zero_token_components_are_known_zero`, and
  `test_timeline_labels_remeasure_on_resize`.
- A reader's active time is a complete interval union, unlike Overview's
  established window contributions. Any eligible clockless own turn makes
  that complete union unknown, even alongside known turns; keep its reported
  duration visible and agent time independent. Regressions:
  `test_reader_untimed_usage_unknown_span_and_reported_duration` and
  `test_reader_partial_unknown_clock_never_asserts_complete_active_union`.
- Mini-timeline tracks and label rows share one compact geometry. Reserving
  two label rows for every lane inflated the approved three-lane baseline
  from 74 to 174 px; use two shared measured rows and per-block tooltip fallback.
  Five equal text cells also center time labels at the wrong instants; anchor
  ticks to session endpoints and quarters. Regressions:
  `test_three_lane_timeline_preserves_approved_74_pixel_height` and
  `test_timeline_ticks_align_to_session_endpoints_and_quarters`.

- `_usage_payload` sets bucket cost to null if any grouped unit is unpriced;
  that bucket can still contain paid units. To prove running unpriced usage,
  compare all timed null-bucket input/output against all own input/output minus
  that turn's known unpriced volume, retaining paid competitors as capacity.
  Conversely, unknown own cost need not erase an affirmative paid witness:
  numeric buckets are a lower bound, and every other turn/outside component
  must have known paid cost or conserved wholly-unpriced input/output. Validate
  the exact component partition and cached reads as a subset of input. This
  pinned Codex row path passes zero billed cache-write tokens; reasoning is
  billed only through output. The target's cost may also be unknown: positive
  displayed numeric cost above all complete competing capacities suffices
  without using that null as numeric evidence. Partial unpriced usage remains
  unknown, and pricing refs alone prove neither paid cost nor zero capacity.
  Regressions:
  `test_compiled_mixed_null_bucket_keeps_paid_competing_capacity`,
  `test_compiled_paid_running_cost_survives_wholly_unpriced_closed_turn`,
  `test_paid_live_witness_requires_complete_other_capacity`, and
  `test_paid_live_witness_does_not_require_known_target_cost`.

- Bucket timestamps and all-dates turn usage cannot establish each other's
  provenance. A running turn contributes to window tokens only when the window
  volume exceeds all own volume minus that particular turn's volume; count each
  independently proved turn once. Prove numeric cost separately with complete
  nonnegative finite costs and an error margin scaled by magnitude and operation
  count: `.1 > (.3 - .2)` can be true without a contribution. Null costs remain
  unknown, while conserved unpriced-token volume can independently prove a
  contribution to `+ unpriced`. Negative, nonfinite and unsafe integer quantities
  provide no evidence, and a window exceeding all own capacity is inconsistent
  rather than proof. Conserved usage needs no invented running-turn timestamp;
  keep separate time-based markers dependent on known intervals. Regressions:
  `test_running_usage_outside_window_does_not_mark_completed_window_usage_live`,
  `test_running_untimed_usage_does_not_mark_completed_timed_usage_live`,
  `test_live_usage_requires_proof_for_each_running_turn`, and
  `test_live_usage_unknown_evidence_and_cost_roundoff_do_not_prove_contribution`.
  Unknown clock control: `test_proven_running_usage_needs_no_invented_turn_timestamp`.
  `_usage_payload` folds cost per usage unit, whose count is absent from the
  page schema. Bucket/turn counts therefore bound only local arithmetic, not
  compiler summation error. Require numeric evidence beyond both that local
  bound and §5.6's `1e-9 × cost + 1e-9` representation tolerance, conservatively
  scaled to the sum of comparison operands. Preserve displayed totals exactly;
  differences inside that threshold remain insufficient LIVE evidence.
  Regression: `test_live_cost_rejects_compiler_unit_accumulation_roundoff` uses
  independent 1,000- and 10,000-unit compiler-style folds.

- A null transient rate date is unknown, not the curated initial baseline.
  Render the source-specific meaning without changing the stored clock.
  Regression: `test_model_tooltip_uses_recorded_refs_without_inventing_bucket_attribution[override]`.
- A clickable tile or row includes its sublines and metadata, not just its
  title button. Delegate container clicks while excluding nested buttons so
  independent status links keep their own navigation. Regression:
  `test_complete_tile_and_recent_row_hit_areas_drill`.

- A running turn proves live session and turn counts, but its status alone is
  not usage evidence. Keep time markers for known clipped running intervals;
  token/cost markers also require recorded running-turn usage. Global disabled
  costs establish neither an unpriced model nor a numeric comparison: show
  "costs unavailable" in tooltips and suppress cost LIVE/delta figures.
  Regressions: `test_live_usage_tiles_require_running_usage_evidence` and
  `test_deltas_live_cost_and_separate_status_links`.

- Rate histories describe available periods, not proof that usage picked them.
  Overview tooltips must dereference recorded `Usage.priced_by` entries from
  contributing accounting rows and label their all-dates session scope. Buckets
  have no period reference, so never invent precise window attribution or call a
  numeric cost unpriced because its reference is unavailable. Regressions:
  `test_model_tooltip_uses_recorded_refs_without_inventing_bucket_attribution`.
- JavaScript's left-fold addition and Python's compensated `sum` can differ by
  a few ulps for identical bucket costs (`0.1 + 0.2 + 0.3`). Compare only monetary
  sums with `rel=0, abs=1e-12`, tighter than the documented pricing tolerance;
  keep counts, tokens, time, statuses and schema exact, and never round application
  bucket costs to satisfy the oracle. Regression:
  `test_every_kpi_and_panel_equals_independent_oracle` under Asia/Kolkata.

- Diagnostic object members cannot establish their schema: unknown record
  types are arbitrary data and may literally be named `files` or `total`.
  Guessing by those members crashed footer rendering and understated stderr
  counts. Dispatch by diagnostic category: only the three structured line
  categories use `total`/`files`; unknown types always sum and enumerate every
  type. Regressions: `test_unknown_record_names_are_data_in_footer_and_stderr`,
  `test_diagnostic_summary_counts_unknown_record_names_as_data`, and the
  structured-line count/item controls.

- `document.fonts.ready` waits for requested faces but does not load an unused
  weight. Empty pages use body Light and brand Medium, so the prescribed
  default-weight Regular check can fail even with valid embedded bytes. Request
  all three embedded faces during boot. Regression:
  `test_empty_topbar_font_and_offline`.
- Browser fixtures must derive synthetic dates from the documented frozen
  instant: 2030-01-15 noon UTC is `1894708800000`. A mislabeled epoch and a
  future fixture day can hide rows under later period filtering. Keep every
  source clock and mtime relative to that snapshot rather than assuming the
  comment is correct.
- Repeated URL keys establish a value only when all decoded values agree.
  Keeping the first contradictory filter invents evidence from ambiguous
  input. Drop conflicting keys, use ordinary defaults for defaulted controls,
  and retain identical repeats; failed escape decoding contributes no value.
  Regressions: `test_conflicting_duplicate_state_is_unknown_and_bad_unicode_is_removed`
  and `test_conflicting_filters_drop_but_identical_and_malformed_repeats_do_not`.

- Catalog change detection compares the four standard rates and long-context
  threshold/four rates, not whole rate objects. Accepted extra metadata must
  not trigger a catalog observation that displaces a manual correction. Keep
  duplicate validation's full JSON comparison separate. Regressions:
  `test_recording_ignores_rate_metadata_preserving_manual_correction`,
  `test_recording_known_rate_change_overrides_manual_despite_metadata`, and
  `test_recording_long_context_presence_compared`.

- Python container equality is not JSON-value equality: `True == 1` even
  inside nested lists or objects. Duplicate ledger comparison must distinguish
  booleans from numbers while preserving int/float numeric equality and raw
  entries. Regressions: `test_duplicate_metadata_json_types_conflict` and
  `test_duplicate_metadata_numbers_compare_as_json_numbers`.
- Unknown JSON metadata still belongs to the JSON validity boundary. Reject
  `NaN`/`Infinity` constants during parsing and recursively reject nonfinite
  direct inputs before append; known rate validation alone misses extra fields.
  Regressions: `test_nonfinite_metadata_is_not_json` and
  `test_append_rejects_nonstandard_json_constants`.
- JSONDecoder's large-context Decimal slow path loses fractional digits once
  its UInt128 mantissa fills, then compacts trailing zeros. Its internal
  integer conversion first sizes the compacted mantissa as UInt64, divides
  for negative exponents without checking a remainder, and sizes the positive
  magnitude before applying its sign. Preserve those stages: mathematical
  integrality rejects accepted `.1`/`.01` near 2^53, while blanket truncation
  accepts oversized mantissas that the source rejects. Boundary regressions extend
  `test_seed_raw_context_preserves_jsondecoder_acceptance`.

- Re-stat a reread ledger before decoding or parsing its bytes. An editor may
  leave partial JSON or invalid UTF-8 while saving; decoding first hides the
  required mtime-change warning behind a codec or JSON error. Regressions:
  `test_edit_during_reread_takes_precedence_over_invalid_json` and
  `test_edit_during_reread_takes_precedence_over_invalid_utf8`.
- The seed tool is also a raw catalog ingestion boundary. Preserve floating
  numeric lexemes until typed `limit.context` acceptance is checked; normalize
  accepted Int values exactly and skip invalid model children. Then restore
  ordinary float rates before passing to the existing resolver. The prior
  source probes show that plain float rounding loses accepted Int evidence
  near Int64 boundaries. Regression:
  `test_seed_raw_context_preserves_jsondecoder_acceptance`.

- Ledger optional objects are object-or-omitted, whereas the pricing resolver
  represents absent long context with null. Keep stored and picked entries
  JSON-equal; consumers use optional lookup rather than inserting null into
  the ledger or broadening validation. Regression:
  `test_picked_entry_without_long_context_prices_standard_rates`.
- D15's whole-second UTC rule governs `effective_from`, not observation
  metadata. Reusing its validator for `recorded_at` rejects valid fractional
  timestamps. Use RFC 3339 parsing for that metadata separately. Regression:
  `test_recorded_at_allows_rfc3339_fraction_metadata`.
- A dev seed generator must validate its input container before passing it
  to the typed catalog index. Valid JSON can still be a scalar or list; report
  a clear input error instead of leaking `AttributeError`. Regression:
  `test_seed_rejects_nonobject_snapshot`.
- String type alone does not establish a usable pricing identity, and a
  nonnegative arbitrary-precision integer need not fit the cost formula's
  floating representation. Validate normalized or complete override keys
  without rewriting them, and reject rates whose finite Double conversion
  fails. Regressions: `test_invalid_pricing_identity_never_establishes_history`
  and `test_oversized_rate_is_not_representable_price_evidence`.

- Port upstream verbatim. Cite the code, verify every restated rule against the function, never invent variants.

- JSON strings can contain lone surrogate code points after damaged logs
  are decoded. Serializing them with `ensure_ascii=False` then encoding as
  UTF-8 raises `UnicodeEncodeError`. Use JSON escaping so lone surrogates
  and ordinary Unicode round-trip without changing indentation, newline or
  private modes. Regression: `test_atomic_json_roundtrips_lone_surrogate_and_unicode`.
- Atomic writers own the descriptor returned by `mkstemp` until `fdopen`
  succeeds. Unlinking a temporary file alone does not close that descriptor
  when `fchmod` or `fdopen` fails. Track ownership explicitly, close only
  before transfer, and preserve the original exception. Regressions:
  `test_atomic_write_closes_untransferred_fd_on_failure` and
  `test_atomic_write_does_not_close_fd_after_transfer`.
- `datetime.fromisoformat` normalizes out-of-range offset minutes instead
  of rejecting them. Validate signed offset hours and minutes before
  parsing. Regressions check invalid minutes in both signs, invalid hours,
  and the valid `±23:59` boundaries.
- Synthetic fixture builders must distinguish omitted values from explicit
  empty dictionaries and lists; truthiness fallbacks silently change the
  intended record. Restrict custom log names to filenames so fixture writes
  stay within the supplied home. Regressions:
  `test_explicit_empty_arguments_and_receivers_are_preserved` and
  `test_filename_cannot_escape_supplied_home`.
- SQLite's connection context manager commits or rolls back a transaction;
  it does not close the connection. Combine `contextlib.closing` with the
  transaction context in fixture writers, and close test readers explicitly.
  Verify actual retained connections are closed on successful writes and
  binding failures without relying on garbage collection. Regression:
  `test_database_writers_close_real_connections_on_every_exit`.
- Reader tests must use the fixture generator's documented defaults rather
  than assuming an epoch constant, cwd or CLI identity. `CodexHome.log`
  defaults to 2030-01-07; pass `at` explicitly when a test needs a different
  instant. Keep expected metadata aligned with the existing synthetic
  generator contract, without changing the generator to fit test mistakes.
  Regressions: `test_true_first_meta_owns_identity_before_ancestor` and
  `test_metadata_fields_and_git_mapping`.
- An idless lifecycle start must allocate a new numbered turn. Current-turn
  fallback belongs to intervening records and ends; applying it to starts
  overwrites the previous turn and hides interruption. Regression:
  `test_missing_turn_id_gets_numbered_key`.
- Releasing a decoded record variable does not release the object when its
  `DecodedLine` container still references it. Drop that container immediately
  after extracting the object so phase two receives only compact scalar facts.
  Regression: `test_decoded_records_released_before_phase_two`.
- Python retains a `for` loop's final binding after exhaustion, including a
  skipped malformed or partial tail. Explicitly release the final raw-line
  holder at the phase boundary rather than assuming iteration freed its bytes.
  Regression: `test_raw_lines_released_before_phase_two`.
- An unknown start timestamp is different from an absent start record.
  Completion-only recovery checks `start_rec`, preserving logged starts whose
  clocks are unusable; reported-duration derivation can supply effective timing
  without rewriting those facts. Regression:
  `test_unknown_clock_start_record_prevents_completion_recovery`.
- A missing or invalid identity is not evidence of a different session.
  Path B requires usable nonempty selected string identities on both sides
  before starting an inherited run. Keep D18 metadata extraction unchanged,
  including legitimate fallback candidates, and apply this validation only
  to history evidence. Regressions:
  `test_path_b_invalid_later_identity_is_not_mismatch_evidence`,
  `test_path_b_invalid_original_identity_is_not_mismatch_evidence` and
  `test_path_b_selected_fallback_identity_remains_mismatch_evidence`.
- Nonempty strings can still be whitespace-only and provide no identity
  evidence. Reject those strings in the history-only predicate; use stripping
  only to test blankness, never to rewrite a nonblank selected identity or
  change D18 extraction. Regressions:
  `test_path_b_whitespace_identity_is_not_mismatch_evidence` and
  `test_path_b_nonblank_identity_strings_are_not_trimmed`.
- Empty question-answer parts still carry D11 classification evidence. Mark
  the assembled request as `answer` before discarding empty text fragments.
  Regression: `test_empty_answer_part_still_marks_assembled_request_as_answer`.
- A completion-only turn has no known start record, but its completion proves
  that a subsequent voice request is a follow-up. Keep the completion position
  transiently; requests before it retain unknown placement instead of inventing
  a start. Regressions: `test_voice_after_completion_only_turn_is_follow_up` and
  `test_voice_before_completion_only_turn_has_unknown_placement`.
- Dedup index sentinels must not overlap concrete log identifiers. Keep the
  all-kept `"*"` bucket separate from a literal `"*"` turn ID so incompatible
  concrete turns never match. Regressions:
  `test_reserved_star_turn_id_does_not_match_other_concrete_id` and
  `test_reserved_star_turn_id_matches_same_id_and_missing_id`.
- Follow the whole timestamp conversion chain before interpreting a rounding
  rule. CodexBar `3bbf6bc48`'s `parseNativeRFC3339` keeps only the first three
  fractional digits before `unixMilliseconds` rounds the parsed date; rounding
  the original higher-precision text changes pricing instants. Task 6's
  "round(ms)" refers to that parsed date, while Task 7 owns broader upstream
  timestamp routing. Regressions:
  `test_usage_timestamp_native_parser_truncates_beyond_three_digits` and
  `test_usage_timestamp_native_precision_at_ties_negative_epochs_and_second_boundary`.
- `str.removeprefix` leaves a string unchanged when the prefix is absent.
  Require the documented record container before checking structured item
  types, so unknown top-level names never count or suppress genuine raw tools.
  Regression: `test_unknown_top_level_type_cannot_trigger_structured_precedence`.
- Shell harnesses must use task-specific variables such as `task_test_rc`
  when retaining exit codes. In zsh, `status` is read-only; assigning it can
  fail the harness after the tests pass. Preserve both logs and diagnose the
  harness separately before rerunning.
- Occurrence scanners need identifier boundaries even when the called name
  has an ASCII-only contract. Exclude Unicode word characters, dollar signs
  and dots before `tools` or standalone `web`, so distinct prefixed objects
  cannot provide tool evidence. Require both server and tool in a JS MCP
  marker; incomplete MCP-shaped identifiers belong under Other. Regressions:
  `test_distinct_js_identifier_prefixes_are_not_tool_evidence`,
  `test_standalone_js_calls_still_count_at_valid_boundaries` and
  `test_incomplete_js_mcp_marker_is_other_not_group_evidence`.
- Root and missing-object sentinels must not share a nil-like value in a raw
  routing port. An object-presence check can turn a sentinel into subagent
  evidence. Pass the root explicitly and keep absent payload/source/history
  objects absent. Regressions: `test_metadata_fast_vs_fallback_empty_identity`
  and `test_invalid_timestamp_drops_token_but_not_meta`.
- Foundation timestamp validity and Python RFC3339 validity are different
  contracts. Port the day-key path separately and retain historical formatter
  normalization and prefix consumption. A standalone synthetic library probe
  can verify the platform behavior without running CodexBar or reading session
  homes. Regressions: `test_upstream_calendar_validity_is_not_display_rfc3339`
  and `test_historical_formatter_validity`.
- Port library number and whitespace semantics explicitly. Python float
  coercion loses NSNumber's lexical representation, Python strip omits U+200B,
  and Python isspace accepts extra control separators. Keep raw fast integers,
  Foundation fallback casts, Foundation trim and Swift Character whitespace
  separate. Regressions: `test_fallback_numeric_lexemes_preserve_nsnumber_cast`,
  `test_foundation_model_trim_set` and
  `test_truncated_swift_character_whitespace_excludes_control_separator`.
- Library Decimal compatibility includes representation loss before integer
  conversion. Foundation bounds its mantissa to UInt128 and its exponent to
  signed eight-bit range; Python's arbitrary precision would accept rejected
  JSON and retain digits already lost upstream. Its Int64 cast precedes
  fractional division, which truncates toward zero before applying Decimal's
  sign. Regressions: `test_foundation_decimal_exponent_boundaries`,
  `test_foundation_decimal_mantissa_truncation_boundaries` and
  `test_foundation_decimal_signed_mantissa_before_fractional_division`.
- A regex matching ordinary Foundation date spellings does not establish
  formatter equivalence. Synthetic large-year probes exposed nonmonotonic
  acceptance through ICU's numeric union and calendar arithmetic; other numeric
  fields and Unicode digits share that path. Port the fixed formatter slice
  from library source and verify it with synthetic probes before adding isolated
  exceptions. ICU's nominal Julian-day range is not its parser acceptance
  boundary: checked epoch subtraction and Double clock normalization matter.
  Regressions: `test_historical_formatter_source_numeric_and_calendar_slice`
  and `test_historical_formatter_double_and_literal_boundaries`.
- Representability state must not use an overlapping numeric sentinel. A
  positive overflow sentinel can become a valid minimum integer after applying
  a negative sign and take the wrong union branch. Preserve an explicit absent
  integer value until the floating representation is selected. Regression:
  `test_historical_formatter_double_and_literal_boundaries[oversized-negative-double-union]`.
- Module-level parser construction runs during import. Define its shared
  character sets before constructing a regex, and use the actual constant name;
  a missing or later-defined constant prevents every test from loading the
  launcher. The suite's module-import fixture covers this initialization order.
- Python Decimal's exponent limit is not ICU's scientific-number contract.
  Apply ICU's source-defined Int32 saturation before constructing Decimal:
  infinity/cleared zero still provide valid zero-valued field casts. Normalize
  Unicode exponent digits and remove leading zeros before bounded comparison,
  so padded small exponents neither overflow nor hit Python's digit limit.
  Regressions: `test_historical_scientific_exponent_saturation_retains_context`
  and `test_historical_scientific_exponent_leading_zeros_keep_small_magnitude`.
- JSONSerialization's nesting boundary counts nonempty containers, so an empty
  terminal container at depth 513 is accepted while a nonempty one is rejected.
  Preserve source object pairs during validation: a later duplicate key must
  not erase an already invalid nesting path. Apply the boundary only to the
  Foundation fallback; raw fast routing and truncated structural tails follow
  separate upstream contracts. Regressions: `test_foundation_container_depth_routing`,
  `test_foundation_depth_513_terminal_container`, and
  `test_foundation_depth_checks_overwritten_object_values`.
- Do not assume Foundation dictionaries share Python JSON's duplicate-key
  projection. Synthetic library probes show Foundation keeps the first value,
  while validating every pair, including an invalid discarded string. Preserve
  both behaviors in the fallback. Regressions:
  `test_foundation_duplicate_projection_keeps_first_value`,
  `test_foundation_duplicate_usage_fields_keep_first_value`, and
  `test_foundation_validates_overwritten_strings`.
- File path identity in a port is a source contract, not a generic filesystem
  convenience. `Path.resolve()` erases symlink spellings and conflicts with
  CodexBar's lexical `codexPathKey`, which only aliases `/private/var/` to `/var/`.
  Use that same key throughout parse, discovery and cache. Regressions:
  `test_path_key_preserves_symlink_spelling` and
  `test_path_key_only_private_var_alias`; the reader fingerprint test retains
  its independent path expectation and all snapshot assertions.
- Requested metadata properties do not imply a listing filter. Upstream asks
  for regular-file information but admits matching directories and retains
  candidates whose stat failed. Let open/read report unreadability rather than
  suppressing discovery candidates. Regressions:
  `test_directory_shaped_jsonl_is_discovered_and_reported` and
  `test_stat_failure_still_reports_unreadable_candidate`.
- Python booleans compare equal to integers. Validate cache parser versions
  and numeric keys by exact integer type before comparing their values.
  Regression: `test_bool_parser_version_is_not_valid_evidence`.
- Platform enumeration options carry resource-property semantics: hidden
  flags and packages on Darwin differ from dot-name-only corelibs traversal.
  Use platform properties with typed native calls and explicit ownership,
  rather than guessing suffixes or assuming `os.walk` is equivalent.
  Regressions: `test_foundation_package_descendants_and_symlinks`,
  `test_hidden_resource_flag_excludes_files_and_descendants`,
  `test_non_darwin_package_option_is_ignored`, and
  `test_package_property_releases_every_owned_reference`.
- Filtering an existing-directory optimization must preserve direct-path source
  semantics. CodexBar generates canonical day paths and filters only their
  entries, so hidden flags on year/month/day ancestors do not hide a visible
  log. Enumerate those ancestors without resource filtering. Regression:
  `test_hidden_partition_ancestor_does_not_hide_visible_day_entry`.
- A scan is not the cache transaction's commit point. Buffer until the caller
  has written the page, retaining the start inventory including unreadables
  for pruning. Regressions: `test_scan_buffers_until_caller_commit`,
  `test_successful_rebuild_scan_can_abort_before_commit`, and
  `test_scan_keeps_unreadable_live_paths_for_deferred_pruning`.
- Mark successful installation as committed before backup garbage cleanup.
  A partly deleted backup cannot be rolled back. Cleanup filesystem failures
  leave the installed cache valid and the remaining backup for dead-pid
  maintenance; interrupts expose the committed state to the caller.
  Regression: `test_post_install_cleanup_preserves_committed_state`.
- Closed and committed are different cache states. Abort closes the buffer but
  does not commit it; a post-install interruption has already committed.
  Keep an explicit committed marker that abort preserves. Regression:
  `test_cache_committed_marker_distinguishes_abort`.
- Filesystem renames and Python bookkeeping are separate interrupt points.
  An interrupt after the old cache moved but before a flag assignment can
  skip restoration; an interrupt after installation can falsely report an
  uncommitted cache. Capture directory device/inode identities before mutation
  and reconcile actual owned locations inside exception handling. Reject
  existing backups before recovery, preserve the original exception, and never
  infer ownership or successful installation from missing paths alone.
  Regressions: `test_interrupt_immediately_after_backup_rename_restores_old`,
  `test_interrupt_immediately_after_install_records_commit`,
  `test_rebuild_interrupt_swap_and_bookkeeping_boundaries`,
  `test_preexisting_backup_is_never_claimed_or_modified`, and
  `test_missing_install_path_does_not_prove_backup_ownership`.
- Abort cleanup can fail while handling another failure. Clear the buffer and
  mark the cache closed in `finally`; preserve the committed marker. Direct
  abort exposes its cleanup exception, while exceptional scan and FORMAT
  initialization preserve the original exception object, attach a cleanup
  note and retain the cleanup exception on the cache. Failed removal leaves
  the rebuild directory for the existing dead-pid maintenance path.
  Regressions: `test_direct_abort_cleanup_failure_always_closes`,
  `test_scan_interrupt_preserved_when_abort_cleanup_fails`, and
  `test_format_failure_preserved_when_abort_cleanup_fails`.
- SQLite `mode=ro` protects database data, but WAL reads can create side files
  and change shared-memory read marks. Synthetic probes established this;
  the user approved SQLite read coordination as the sole source-write
  exception on 2026-10-04. Keep normal locking and change detection rather
  than substituting immutable or exclusive modes. Regression:
  `test_live_wal_reads_latest_data_without_modifying_main_or_non_sqlite_files`.
- A nonblank cwd can have a whitespace-only final component. Require the
  basename itself to be nonblank before selecting it as a fallback title;
  preserve usable strings without stripping them. Regression:
  `test_title_fallbacks`.
- Assembly must retain spoken replies attached to session-level requests, not
  just standalone voice replies. The cached request retains reply text but no
  separate reply clock; emit a null clock rather than reusing the question's
  timestamp. Before-turn reply facts remain on the original FileRecord and
  never become a turn's final answer. Regressions:
  `test_no_turn_voice_reply_survives_without_inventing_reply_clock` and
  `test_before_turn_reply_facts_survive_without_becoming_final_answer`.
- Display-copy selection and upstream processing order are separate contracts.
  Select the display copy using full mtime precision with path tie-breaking;
  retain upstream millisecond/size/path ordering for accounting copies.
  Regression: `test_newest_display_uses_submillisecond_mtime`.
- Turn numbering uses assembled starts, including a start derived from reported
  duration, before falling back to end time and stable file order. Sorting the
  original logged start incorrectly numbers completion-only turns. Regression:
  `test_numbering_uses_effective_reported_start`.
- A standalone voice reply's cached turn key is placement evidence. Only
  replies with no turn key belong in session-level voice; retain attributed
  replies on the original FileRecord without inventing a request or final
  answer. Regression:
  `test_unprompted_in_turn_voice_reply_does_not_move_to_session_level`.
- Raw metadata IDs can spell generated file keys, including repeated `file:`
  prefixes. Group metadata identities and source paths in separate namespaces;
  reserve every true metadata ID before deterministically allocating string
  keys for file groups. Escape only conflicting generated keys, and retain
  the original source path for accounting and payload identity. Regression:
  `test_generated_file_identity_never_merges_with_true_metadata_id` checks
  both input orders, mtime orders and repeated-prefix conflicts.
- Selecting one final answer by scanning a whole transcript is suitable for
  single-turn callers, but repeating it for every assembled turn is quadratic.
  Build one answer index in file order per display record: last eligible spoken
  replies win until recorded finals override them, and later recorded finals
  replace earlier ones. Keep the single-turn interface and bound retained-fact
  visits in growing synthetic sessions rather than asserting volatile timings.
  Regressions: `test_assembly_bounds_retained_fact_visits_as_sessions_grow` and
  `test_final_answers_keep_recorded_precedence_and_last_eligible_voice`.
- A latest-spawn rule must select by timestamp before validating turn placement.
  Filtering unusable turns first borrows an older spawn and invents a link.
  Conflicting started activities likewise establish no unique turn; duplicate
  activities for the same turn remain evidence. Fall through to the next
  documented method. Regressions:
  `test_latest_spawn_with_unusable_turn_does_not_borrow_older_spawn` and
  `test_conflicting_started_activities_fail_over_but_duplicates_are_evidence`.
- Workspace fixtures must distinguish raw log keys from cached metadata:
  `git.repository_url` becomes `meta.git.origin_url`. The shared builder also
  supplies a synthetic remote unless `git={}` is explicit. Set raw inputs and
  absent evidence deliberately rather than changing source precedence or
  weakening fallback assertions. Regressions:
  `test_meta_precedes_db_origin_and_cwd_without_mutating_sources` and
  `test_missing_cwd_path_and_unknown_cwd_fallback`.
- URL parsers may silently remove embedded control characters, and lexical
  path prefixes admit `..` traversal. Reject these malformed workspace facts
  before normalizing or matching: damaged input must not establish a valid
  origin or alias. Regressions:
  `test_control_characters_do_not_become_origin_evidence` and
  `test_parent_traversal_path_does_not_invent_alias_match`.
- Swift's pricing normalizer searches complete Characters, not individual
  Python code points. An accented `@` is not an at-sign delimiter, an accented
  slash is not the `openai/` prefix, and non-ASCII regex digits include numeric
  graphemes such as superscripts and numeric CJK. Use the narrow, source-grounded
  Numeric/Grapheme_Cluster_Break slice; category M alone misses ZWJ, modifiers,
  tags and spacing-mark exceptions. Preserve canonical dictionary equality
  separately from the returned catalog spelling. Regressions:
  `test_non_character_at_sign_does_not_invent_base_candidate`,
  `test_non_character_slash_does_not_strip_provider_prefix`,
  `test_suffix_regex_uses_digit_graphemes_not_category_m`, and
  `test_unicode_equivalent_lookup_preserves_catalog_identity`.
- `math.isfinite` implicitly converts Python integers to float and can raise
  `OverflowError` for damaged oversized catalog values. Perform the bounded
  Double conversion explicitly, reject failed/nonfinite conversions as invalid
  typed model evidence, and keep valid neighboring models priceable. Regression:
  `test_unpriceable_or_malformed_models_are_not_evidence[bad9]`.
- Typed decode failure scope is part of the port: a wrapped provider map fails
  as a whole on any invalid provider, then falls back to top-level keys. Invalid
  model children instead remain individually skippable. Regression:
  `test_invalid_wrapper_provider_abandons_entire_wrapped_map`.
- A JSONDecoder Int field accepts integral decimal/exponent numbers rather than
  only integer-typed JSON. Check the decimal spelling and signed range; ordinary
  float integrality alone cannot establish boundary acceptance. Preserve raw
  catalog number lexemes until typed context validation at the fetch boundary,
  because Python float conversion can erase accepted source digits. Regression:
  `test_context_uses_jsondecoder_int_number_semantics`.
- A downstream resolver rejection does not necessarily end the caller's lookup
  chain. Codex pricing targets append normalized OpenAI fallback after the
  target resolver returns, including when its result is empty. Regression:
  `test_normalized_target_fallback_survives_resolver_rejection`.
- A harness must relativize cached log paths against the same lexical path key
  as discovery: macOS `/private/var/` keys become `/var/`. Normalize only that
  root with `codex_path_key`; resolving arbitrary symlinks would change the
  contract. Regression: all staged token-case comparisons in
  `tests/test_token_port.py` exercise copied temporary homes.
- A display timestamp parser cannot select an accounting timestamp branch.
  `parseNativeRFC3339` requires uppercase `T`, a year at least 1900, and no
  more than nine fraction digits. Historical parsing then preserves ICU's
  fraction arithmetic, Julian cutover, era years, and offset-prefix parsing.
  Select that source branch before reusing strict native conversion; render
  accounting days with the same hybrid Gregorian calendar. Regression:
  `test_accounting_timestamp_source_chain` pins six originally failing edges,
  plus named-offset and invalid-fixed-zone behavior.
- Compact stream tags can have different positional layouts. A truncated
  context's `XC[3]` is model evidence, while a regular line's slot 3 is its
  ordinal. Expand `XC` into a routed context with null timestamp and ordinal
  before suffix classification; never compare its model dictionary to an
  integer. Regression:
  `test_truncated_context_has_no_ordinal_in_explicit_subagent_suffix`.
- Snapshot withholding must follow the source predicate exactly.
  `isUnresolvedMissingParentFork` (ForkCoverage.swift 43–46) derives solely from
  the dependency key the child used (CacheHelpers.swift 1297–1308). The empty
  fork-timestamp guard (Scanner.swift 1692–1697) returns unresolved without
  clearing a previously resolved parent key, so a child can parse unresolved yet
  still offer snapshots. Adding the per-parse `has_unresolved_fork_baseline`
  flag to the withholding test was a stricter invention that dropped a
  grandchild's owned usage. Keep the flag as the result's own diagnostic only.
  Regressions: `test_retained_parent_key_offers_snapshots` and
  `test_retained_parent_key_resolves_grandchild_usage`.
- Swift `String` keys and set members compare canonically equivalent Unicode
  spellings as one identity. Raw Python parent keys split that identity,
  losing parent baselines or selecting an older duplicate copy. Use one NFC
  key consistently for parent indexing, lookup, memoization, recursion guards,
  dependency state and the parsed-identity assertion. Keep source metadata and
  diagnostics unchanged, and do not borrow the rollout classifier's trimming.
  Regressions: `test_canonical_equivalent_parent_lookup`,
  `test_canonical_duplicate_parent_newest_mtime`,
  `test_canonical_resolver_keys_share_memo_and_preserve_spelling`,
  `test_canonical_resolver_recursion_guard_stops_equivalent_identity`,
  `test_canonical_parent_dependency_retains_offered_snapshots`, and
  `test_canonical_parent_dependency_resolves_grandchild_usage`.
- Canonical equality must not rewrite a public normalized string.
  `normalizedSessionID` (RolloutShape.swift 222–227) returns trimmed source
  text, and its inferred-parent consumers expose that spelling. Compare NFC
  keys in both classifier overloads and deduplicate ancestors by those keys,
  retaining the first trimmed source value. A trim-only correction without
  canonical comparison would invent ancestors or erase a valid suffix boundary
  when leaf metadata uses an equivalent spelling. Regressions:
  `test_normalized_session_id_retains_trimmed_source_spelling`,
  `test_classifier_canonical_ancestors_retain_first_spelling`,
  `test_classifier_canonical_leaf_is_not_an_ancestor`,
  `test_classifier_and_usage_result_retain_inferred_parent_spelling`, and
  `test_classifier_canonical_leaf_metadata_preserves_suffix_candidate`.
- A SQLite numeric-to-text port cannot assume fifteen-digit formatting from
  an import name or use Python `str(float)`. SQLite 3.51 uses fifteen significant
  digits; 3.52 and later default to seventeen. Initial hand expectations and
  a fixed fifteen-digit native formatter disagreed with an independent CAST
  oracle. A standalone synthetic Swift `import SQLite3` probe confirmed the
  actual host backend (3.54) also uses seventeen, matching Python's 3.53.4
  backend. Resolve formatter symbols through the connection's own extension
  and apply its source-defined default; preserve allocation/free ownership
  on every exit. Regressions: `test_real_text_matches_sqlite_column_cast`,
  `test_sqlite_timestamp_column_text_contract`, and
  `test_native_sqlite_allocation_is_freed_on_every_exit`.
- Duplicate-file fixtures must assign distinct response ids when testing
  distinct primary responses. Ordinal-generated defaults can collide across
  copies and correctly trigger response deduplication, obscuring model or
  attribution assertions. Keep a separate overlap test with intentionally
  identical ids. Regressions: `test_model_context_is_file_local_strictly_before_and_clear`,
  `test_local_file_indices_and_inherited_attribution`, and
  `test_duplicate_files_union_primary_and_cross_file_fallback`.
- Duplicate parent diagnostics must report the pre-pass id and differing
  true-first display ids. An oversized metadata line can make those identities
  differ even while both files share one accounting parent key. Regression:
  `test_duplicate_prepass_diagnostic_includes_differing_display_ids`.
- Port trace searches and delimiters at the source's Character boundaries.
  Python scalar `find`, `partition` and quote slicing accepted markers joined
  to Prepend/Extend and truncated clustered punctuation into invented turn ids.
  Reuse the source-backed ASCII literal boundary matcher for every request,
  completion, submission, service-tier, name and quote search. Whitespace is a
  separate predicate: Swift inspects a Character's first scalar, so space plus
  Extend qualifies, Prepend plus space does not, and control whitespace/CRLF
  still breaks from preceding Prepend. Independent synthetic Swift helpers
  established these expectations before the repair. Regressions:
  `test_trace_value_uses_swift_character_boundaries`,
  `test_trace_value_character_whitespace_matrix`,
  `test_trace_value_only_whole_punctuation_delimits`,
  `test_trace_quoted_value_uses_whole_quote_characters`,
  `test_all_trace_markers_reject_clustered_boundaries`,
  `test_clustered_request_marker_falls_back_to_valid_submission`, and
  `test_character_correct_ids_reach_priority_and_completed_composition`.
- Primary usage must preserve the existing nonempty turn identity. Reusing
  history-boundary validation rejected whitespace-only ids that Task 4 and
  fallback accounting retain, causing primary and fallback tokens to count
  together and dropping primary display/priority attribution. Use `_identifier`
  locally in primary composition; keep the stricter history-only predicate
  separate. Task 15's per-turn source selection then replaces fallback usage
  with the primary record for that exact id. Regression:
  `test_whitespace_turn_identity_selects_primary_and_preserves_attribution`.
- A successful socket read does not finish a watchdog phase until cancellation
  and joining complete. The watchdog may fire between the read's flag check
  and cancellation; resetting the flag then loses a real timeout. Check again
  after joining, before starting the body or accepting its bytes. Regressions:
  `test_watchdog_firing_during_cancel_is_not_forgotten[headers]` and `[body]`.
- JSON syntax can contain a number whose Double conversion overflows, such as
  a synthetic `1e999` rate. Writing Python's resulting Infinity poisons the
  next strict cache load. Validate typed provider/model fields before converting
  ignored overflow metadata to null, skip invalid models independently, and
  preserve valid peers through offline reload. Regression:
  `test_nonfinite_typed_model_is_skipped_without_poisoning_cache`.
- `http.client` clears its connection socket for responses that close. Save the
  socket after explicit connect so the body watchdog can interrupt HTTP/1.0
  trickle responses; give body operations their own timeout. Regressions:
  `test_body_total_budget_uses_saved_http10_socket` and
  `test_complete_multichunk_body_with_distinct_body_socket_budget`.
- Preserve raw catalog context-number spelling at both network and cache
  ingestion. Double rounding can erase source Int acceptance or rejection;
  use the verified Foundation UInt128/UInt64 Decimal boundary before ordinary
  Double rate decoding. Regression:
  `test_raw_context_acceptance_survives_network_and_cache`.
- Raw catalog objects must project duplicate keys as Foundation does:
  `_setIfNil` retains the first value, including null, and Swift String
  canonical equality retains the first spelling. Python's default last-value
  projection changes rates and can decode a malformed value the source ignores.
  Regressions: `test_raw_duplicate_rate_retains_first_value`,
  `test_raw_duplicate_null_does_not_borrow_later_rate`,
  `test_raw_canonical_duplicate_keeps_first_key_spelling_and_value`, and
  `test_raw_discarded_duplicate_invalid_value_is_not_decoded`.
- A finite Python float is insufficient evidence of a valid source Double:
  Foundation rejects a nonzero raw coefficient rounded down to zero. Check
  known standard and long-context rate lexemes before float normalization;
  retain true zero and representable subnormals. The context Int slow path is
  separate and can accept underflow as zero; ignored metadata is not a rate.
  Regressions: `test_raw_underflow_in_typed_rate_rejects_only_its_model`,
  `test_raw_true_zero_and_representable_subnormal_rates_survive`,
  `test_raw_nonzero_underflow_coefficient_forms_are_not_free_rates`, and
  `test_raw_underflow_context_and_ignored_metadata_are_not_double_rate_fields`.
- Python JSON accepts escaped lone surrogates that Foundation's typed strings
  and object keys reject. Apply Unicode checks at the source's container/field
  boundaries: a bad model field rejects its child, a bad provider or model-map
  key rejects the provider, and a bad catalog key rejects the catalog. Preserve
  valid surrogate pairs and ignore unknown nested metadata, rather than globally
  rejecting strings or replacing malformed typed values with null. Equivalent
  synthetic Swift decoder probes confirmed these boundaries. Regressions:
  `test_raw_invalid_unicode_model_fields_and_keys_reject_only_its_model`,
  `test_raw_invalid_unicode_provider_fields_and_keys_reject_provider`,
  `test_raw_invalid_top_level_key_is_a_catalog_failure`,
  `test_raw_invalid_ignored_unicode_values_and_nested_keys_remain_ignored`, and
  `test_raw_valid_unicode_surrogate_pairs_and_scalar_keys_survive`.
- A discovered log path does not establish cache trust. When FORMAT is missing,
  retain only entries successfully replaced in the current commit before
  publishing the marker; otherwise an unreadable log's old JSON becomes trusted
  by the next process. With a valid marker, retain unreadable live entries as
  before. Regression:
  `test_unreadable_old_cache_entry_requires_trusted_marker`.
- Concurrent compilers can enumerate the same stale cache entry before either
  removes it. Treat its subsequent absence as successful pruning, while leaving
  permission and other deletion errors visible. Regressions:
  `test_concurrent_compilers_can_prune_same_stale_cache_entry` and
  `test_stale_cache_prune_keeps_other_delete_errors_visible`.
- A timeline label containing the word "forked" does not satisfy a badge
  contract. Include the established bordered tag in the measured label, with
  compact height that preserves the shared two-row collision fallback and
  74-pixel three-lane baseline. Assert the actual visible badge, border and
  geometry at narrow and wide widths. Regression:
  `test_timeline_lanes_ticks_fork_badges_and_inferred_border`.
- A fork link's display label and navigation target are separate facts.
  Look up the parent's usable title across the full sessions/subagents payload,
  including filtered-out rows, but navigate by its original ID. Missing,
  invalid or conflicting titles retain the ID fallback instead of inventing
  a title. Regressions: `test_fork_link_uses_known_title_outside_filtered_list_and_navigates_by_id`,
  `test_fork_link_invalid_parent_title_falls_back_to_id`,
  `test_fork_link_missing_parent_falls_back_to_id_and_preserves_navigation`, and
  `test_fork_link_conflicting_parent_titles_fall_back_to_id`.
- A parent button's tooltip does not establish the clipping contract for an
  ellipsized child span. Put full workspace/model text on the actual clipped
  node; allow two-digit hour axes to wrap when a narrow 24-column grid cannot
  fit their glyphs. Set minimum width zero on grid and flex children. Regression:
  `test_stress_has_no_overflow_or_fragment_overlap` checks direct-text per-line
  Range fragments, clipping ancestors and the prescribed one-pixel tolerance
  at all six widths, including expanded reader content. Its independent checker
  control proves that clipping, true overlap and unmarked scrolling are detected.
- Whole clickable list rows require their own Tab stop and Enter/Space handling;
  ignore bubbled keyboard events from the nested title button so one activation
  creates one navigation entry. Native links activate Enter but not Space;
  reader link handling supplies the required Space activation. Keep browser
  tests synthetic, intercept protocol defaults and stub clipboard writes.
  Regressions: `test_keyboard_list_reader_buttons_and_expanders` and
  `test_keyboard_overview_controls_tiles_and_every_heat_cell`.
- Synthetic stress must retain exact model membership and usage conservation:
  copying an agent without replacing its bucket model silently adds a forty-first
  model. Validate fixture shape and counters independently before measuring it.
  Hash-only browser navigation also completes asynchronously; wait for the
  rendered frame before asserting focus on newly rebuilt controls. Regression:
  `test_stress_fixture_has_exact_shape_and_conserved_usage`.
- Zero-dimensional boxes are not evidence that text is unpainted: a zero-height
  container can expose overlapping direct text, and a zero-width clipped box
  still requires an ellipsis and tooltip. Skip only non-rendered/hidden elements;
  apply the positive-client-width exception only to visible overflow. Regression:
  `test_checker_includes_painted_or_clipped_text_in_zero_dimension_boxes`.
- Progress formatting needs its own byte-to-MB and rounded-ETA contract rather
  than raw-byte arithmetic embedded in the CLI. Before any parsed bytes, no
  rate establishes an ETA; completed and empty workloads establish zero
  remaining work. Regression: `test_format_progress` and terminal/nonterminal
  cold-run controls.
- Clean compiler runs omit empty diagnostics, but local throughput acceptance
  must always report a summary. Preserve compiler messages and explicitly
  report no diagnostics for a clean run. Regression:
  `test_throughput_cold_measurement_uses_scan_bytes`.
- Invalid-baseline tests must mutate one field of an otherwise complete
  measurement. Missing keys alone never exercise finite-rate, clock or counter
  validation. Preserve the baseline on malformed input and on regression;
  reject unknown measurements instead of manufacturing comparison evidence.
  Regressions: `test_invalid_baseline_is_not_measurement_evidence`,
  `test_invalid_baseline_schema` and
  `test_throughput_cli_creates_then_preserves_baseline`.
- A carriage return moves the terminal cursor but does not erase the previous
  line. When an ETA shrinks from 100s to 0s, pad the replacement to the largest
  rendered width so no old suffix remains. Test actual two-file cold progress
  through an independent terminal-cell replay, with a CR-only defect control;
  raw output containing a correct new ETA alone cannot prove visible correctness.
  Regression: `test_cold_progress_clears_previous_longer_eta`.

### Task 24 — independent parity evidence

- Match all exported integer representations: activity is signed Int64, while
  native unmetered-day counters are positive bounded Swift Int. Valid negative
  activity is retained; agreeing out-of-range values are still malformed.
  Regression: `test_native_activity_requires_exact_signed_int64`.
- Native model rows originate from String-keyed accumulators, so duplicate NFC
  names cannot establish an oracle even when metrics agree. Reject ambiguity in
  every model scope without merging rows or rewriting raw names/order/optionals.
  Case, whitespace and compatibility characters remain distinct. Regression:
  `test_native_model_identity_duplicates_fail_in_every_scope`.
- Validate the source-defined nested model schema in every native scope and
  every daily request/coverage counter before comparing observations. Optional
  Codable omissions/nulls remain untouched; boolean, fractional, negative or
  overflowing counts and invalid money are not evidence. Check Int bounds before
  floating conversion, and reject an unrepresentable Double without an exception
  escaping the fail-closed path. Regression:
  `test_native_nested_models_fail_closed_in_every_scope`.
- Reject repeated acceptance JSON object keys before constructing dictionaries,
  even when values agree. Retain raw CLI/native stdout before decoding, so a
  contradictory ID or metric cannot disappear behind a selected last value.
  This decoder rule is separate from the application's source-ported JSON rules.
  Regression: `test_acceptance_json_rejects_repeated_object_keys`.
- Do not reuse the fragment-capable JSON helper for the fast quoted-string
  decoder. The pinned Foundation call omits `fragmentsAllowed`, so Unicode
  escapes provide no fast metadata/model evidence; raw UTF-8, simple escapes,
  full-object fallback and EOF fragments follow their own routes. This affects
  filename identity and retained prior-model pricing. Keep trimming fixtures
  explicit about which encoding route they exercise. Regressions:
  `test_pinned_default_foundation_scalar_is_not_escaped_metadata_evidence` and
  `test_escaped_context_replay_retains_prior_model_counts_and_source_price`.
- The native project oracle must retain its nullable model breakdowns and every
  source's totals, days and model breakdowns. Compare the CLI's shared nested
  metrics as well as aggregates; an unchanged project total can conceal source
  drift. Preserve native Codable nil omissions and direct optional nulls.
  Regression: `test_native_crosscheck_includes_cli_project_model_and_source_metrics`.
- Apply monetary tolerance to all source-named money fields, including native
  `standardCostUSD` and `priorityCostUSD`; token fields remain exact. Regression:
  `test_native_model_cost_components_use_declared_tolerance`.
- Native session spellings can be canonically equivalent without identical UTF-8.
  Normalize comparison keys and incomplete-oracle presence sets consistently,
  retain raw spellings in observations, and reject canonical duplicate owners.
  Regression: `test_native_reference_and_incomplete_presence_use_canonical_ids`.

- Inspect actual CLI JSON before designing comparison adapters. The pinned
  grouping commands emit daily/project reports without sessions. An external
  Swift test target calling the unchanged native scoped-cache path supplies an
  independent session oracle; a Python reconstruction does not. Ordinary pytest
  exercises only synthetic pure helpers and compiler wiring.
- Native dictionary iteration can choose different files at equal mtimes. Read
  all isolated file records to detect structural ties at each session's maximum
  mtime; never choose a winner. Agreement across three runs does not remove a
  structural tie, and a matching suffix cannot erase earlier disagreement.
  Regressions: `test_tied_agreeing_native_observations_still_fail_acceptance` and
  `test_matching_suffix_does_not_erase_native_disagreement`.
- Native cached-token null does not prove zero, even with complete coverage.
  Keep nullable metrics and fail closed on required unknowns. Deliberately
  unmetered-only days need exact native contributor predicates and day evidence;
  unproven, billed, duplicate or mixed contributors remain incomplete.
  Regressions: `test_complete_native_still_retains_null_without_explicit_zero_evidence`
  and `test_deliberate_unmetered_day_requires_exact_native_contributor_proof`.
- Preserve unknown project identity as a nullable report row, rather than a JSON
  object key that collides/coerces or fails sorting. Fingerprint actual source
  JSONL and explicit isolated cache/catalog/trace/window inputs; do not read
  authentication/config files or SQLite coordination files. Reject symlink logs
  before compiling or fingerprinting their contents.
- Swift initializer extraction must start after the assignment, not at delimiters
  in a type annotation. Citation filenames must not accidentally name enclosing
  declarations. Masking/extraction should scan each file once, avoiding repeated
  unbounded suffix copies. The synthetic drift regressions cover these failures.
- A consistent SQLite backup can retain WAL journal mode even without WAL
  sidecars. Finalize only the isolated trace snapshot in DELETE mode and verify
  the returned mode before handing it to the pinned read-only scanner. Keep the
  live source connection read-only and its journal mode unchanged. Regression:
  `test_trace_backup_finalizes_wal_snapshot_for_readonly_scanner`.
- A pinned scanner can repeat partial reports throughout its refresh debounce.
  Completion metadata must gate the CLI stability streak, and retries must
  respect that debounce rather than accepting repeated partial output. Retain
  every attempt's raw reports and metadata; fake clocks keep the synthetic
  retry regressions free of wall waits.
- Classify the CLI's named top-level Double cost fields as money as well as its
  nested cost fields. Apply the existing monetary tolerance without changing
  exact token comparisons or accepting invalid/unknown monetary values.

- Native action support must follow tested versions and cases. Archived viewing
  required unarchive, and direct CLI resume of an unloaded multi-agent v2
  subagent failed in the tested cases; hide those actions without generalizing
  to all historical agents. Read-only access to a desktop-owned live session
  does not prove writable continuation. Respect tool safety denials and retain
  separately recorded human observations as acceptance evidence. Regressions:
  `test_recursive_schema_and_usage_invariants` and
  `test_production_link_support_preserves_reader_actions`.
- A standalone copy's matching bytes, modes and installed version establish
  that artifact's deployment, not synchronization of the whole fleet. Report
  every read-only audit finding and diagnose without modifying deployments;
  require separate approval before repairing another deployment or removing
  its stale files.
- Lifecycle and agent identity are independent action restrictions. Selecting
  one category let archived linked and orphaned agents bypass the archived
  Open gate; giving archive precedence would instead bypass their CLI gate.
  Require every applicable support flag and test the intersections with actual
  compiled synthetic rows, including contradictory flags. Regressions:
  `test_production_actions_apply_archive_and_agent_restrictions` and
  `test_each_applicable_support_flag_can_hide_agent_action`.
