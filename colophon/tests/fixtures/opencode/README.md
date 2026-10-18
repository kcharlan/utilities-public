# Synthetic OpenCode schema

`schema_v2.sql` is schema only, containing no captured rows or identifiers.
It projects the public bundled `schema` from Homebrew OpenCode **2.0.32**,
through migration `20261010180456_project_time_archived`. Relevant declared
types, nullability, defaults, primary keys and foreign keys are preserved;
unqueried columns/tables and indexes are omitted. The migration table comes
from the public database bootstrap. This tracked DDL is a narrow exception to
the runtime-fixtures-in-scratch policy. `tests/unit/opencode_fixture.c` builds
invented rows and databases under fresh `opencode-unit.*` homes inside the wrapper's external `TMPDIR`.

The required query columns are:

| Table | Required | Optional |
| --- | --- | --- |
| `session_v2` | `id`, `project_id`, `parent_id`, `directory`, `title`, `version`, `agent`, `model`, `cost`, `tokens_input`, `tokens_output`, `tokens_reasoning`, `tokens_cache_read`, `tokens_cache_write`, `time_created`, `time_updated`, `time_idle`, `idle_outcome` | `fork_session_id`, `time_archived` |
| `session_message` | `id`, `session_id`, `type`, `seq`, `time_created`, `data` | none |
| `project` | `id` | `time_archived` |
| `migration` | `id` | none |
| `kv` | `key`, `value` | none |

Required columns may contain SQL NULL where the upstream schema permits it;
a nullable title/model remains absent. Missing optional columns project SQL
NULL at fixed indexes. A left join preserves sessions whose project is absent.
The reader's single column lists define compatibility and explicit SELECTs.
Legacy generation presence is inspected through `sqlite_master` names only.
When `session` exists, only the exact `migration.v1-v2` value is inspected,
and its JSON phase must be `completed`. Unknown `migration.*` keys and unknown
`session*` generation tables reject the database. A structurally compatible
migration later than the pin is accepted with an untested-schema flag.

Tests pin all eleven public message literals: `agent-switched`,
`model-switched`, `location-switched`, `user`, `synthetic`, `system`, `skill`,
`shell`, `assistant`, `compaction`, `idle`. Assistant content literals are
`text`, `reasoning`, `tool`. Tool failures use the serialized `error` state;
child metadata accepts current `sessionID` and legacy `sessionId`.
Only text and image counts are projected; file bytes, tool input/output,
provider state, error messages/bodies and credential tables are never copied.

Token components accept mathematically integral decimal/exponent spellings
within signed 64-bit range, using their original decimal spelling. Fractions
that binary64 would round to an integer remain invalid. Recorded cost has an
independent finite nonnegative numeric contract, with no token-integer bound.

Every read uses a normal read-only SQLite connection, a 1,000 ms busy timeout
and one transaction; immutable mode would lose committed WAL visibility.
Tests compare database and WAL bytes. SQLite shared-memory coordination files
may be created or updated, as documented in `docs/runtime.md`.
