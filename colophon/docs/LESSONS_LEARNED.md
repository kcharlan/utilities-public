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
