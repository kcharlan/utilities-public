# Maintenance to-do

This list holds real repairs and features only. Anything that needs the owner goes
here with its reason, not in a plan or the PKM. Sign-offs, acceptance checks and
evidence gaps are not tracked; breakage found in use gets fixed then.

## Storage Monitor: Time Machine snapshot timestamp convention
`collect_snapshot_section` reads each local snapshot name's timestamp as UTC (`storage_monitor/storage_monitor:2152`). If macOS names snapshots in local wall-clock time, every displayed snapshot date is off by the UTC offset. A synthetic fixture can't settle which convention macOS uses.
- Options: (a) keep the UTC reading until authoritative documentation or a separately authorized check of a real snapshot (compare its name with `tmutil` creation time) settles it; (b) switch to local time now.
- Recommendation: (a). Once the convention is known, change the parse at `:2152` and add a regression test with a fixed `TZ`.

## Transcription: retire the manual counter migration
`transcription/README.md` "Manual counter migration" and its tests in `transcription/tests/test_state.py` (`test_readme_migration_block` and the `test_migration_*` tests) exist only to move legacy counters from `~/transcription` once.
- Options: (a) after you confirm your counters are migrated, delete the README section and those tests; (b) keep both.
- Recommendation: (a), after you confirm. The migration is one-off, and the tests protect only that README snippet.
