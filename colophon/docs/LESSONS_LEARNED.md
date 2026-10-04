# Lessons learned

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
