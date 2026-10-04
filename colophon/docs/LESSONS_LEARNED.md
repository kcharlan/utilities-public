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
