# TP-Link Router-Instance Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TP-Link Archer system-log ingestion, router-instance-scoped health/security and snapshot-count baselines, portable device discovery, and semantic snapshot deduplication without changing existing NETGEAR findings, scores, reports, or management workflows.

**Architecture:** Keep the copy-installed runtime in `router_log_analyze.py`, but introduce in-file NETGEAR and TP-Link adapters that produce one normalized `ParsedRouterLog`. Upgrade SQLite schema v3 to v4 with explicit router identity, registration/observation provenance, snapshot metrics, boot sessions, and many-to-many occurrence/run links. Resolve format and router identity before scoped duplicate lookup; classify boot/clock and novel/repeated occurrences before any incident, anomaly, score, or learning calculation. Device identity remains global, while router behavior is keyed by router instance, firmware profile, and baseline epoch.

**Tech Stack:** Python 3.12 via the existing uv PEP 723 launcher, stdlib dataclasses/regex/hashlib/sqlite3, existing PyMuPDF/pypdf input support, pytest, and SQLite schema migrations.

---

## Binding References and Constraints

The executor must treat these as authoritative, in this order:

1. `docs/superpowers/specs/2026-08-25-tp-link-router-instance-support-design.md` — approved and adversarially amended behavior.
2. This implementation plan — sequencing, interfaces, schema, invariants, and acceptance checks.
3. `README.md` and `FUTURE_MULTI_VENDOR_SUPPORT.md` — current user contract and historical architectural context.
4. Repository `AGENTS.md` — public-repository privacy, complete-test accountability, uv launcher, and installation rules.

Non-negotiable constraints:

- Keep `router_log_analyze.py` standalone. Do not add runtime sidecar modules or profile files.
- Never copy the private router export, its real addresses, device names, firmware values, or derived baselines into the repository, tests, docs, snapshots, comments, commit messages, or generated artifacts.
- All committed test data must use unmistakably synthetic names, locally administered unicast MAC addresses, documentation-only IPv4 ranges, and future synthetic timestamps/firmware identifiers.
- Bump `SCHEMA_VERSION` from `3` to `4`. Only structurally valid v3 databases migrate in place. Empty databases are created directly as v4; older, newer, partially stamped, or structurally unexpected databases fail closed.
- Preserve existing NETGEAR parser outputs and legacy `unknown_device` / `blocked_device_activity` CRITICAL defaults. The new MEDIUM device-discovery default belongs to the new adapter-independent stable-identity path and remains subject to explicit policy suppression, caps, and escalation.
- Retain the PKM-backed metric-learning invariant: exclusions caused only by `dhcp_anomaly` or `event_volume_anomaly` remain eligible for future numeric metric profiles; partial, reset, blocked, unknown/security, timing, and behavior exclusions remain quarantined.
- Snapshot client-count evidence receives a hard LOW ceiling after all policy evaluation. Counts alone never create or identify a device.
- Complete source lines may exist in memory for the current report, but must never be inserted into SQLite.
- Do not implement code until the user explicitly approves this plan.

## Current Code Map

| Area | Current code | Required evolution |
| --- | --- | --- |
| CLI | `parse_args()` at `router_log_analyze.py:323` | Add automatic/explicit format selection and router identity/label options; update NETGEAR-only wording and version. |
| Normalized event | `Event`, `ParseStats` at `router_log_analyze.py:168` and `:192` | Extend event evidence and add normalized parse, capability, router identity, snapshot, and detection dataclasses without breaking named construction in existing tests. |
| NETGEAR parser | `parse_timestamp_from_line()` through `parse_log_text()` at `router_log_analyze.py:1496-1664` | Move behind `NetgearLogAdapter`; retain `parse_log_text()` as a NETGEAR compatibility wrapper for existing callers/tests. |
| Persistence | `StateStore.ensure_schema()` and methods at `router_log_analyze.py:518-1353` | Replace unconditional schema stamping with empty/v3/v4 dispatch, explicit migration, v4 provenance tables, scoped run lookup, and summary refresh helpers. |
| Aggregation | `aggregate_events()` at `router_log_analyze.py:1738` | Aggregate only detector-eligible events; preserve a complete parsed set for reporting and a novel/eligible set for analysis. |
| Incident analysis | `detect_network_incidents()` at `router_log_analyze.py:1930` | Gate confirmed/inferred paths by adapter capabilities and supported canonical recovery keys. |
| Policy/severity | `enforce_policy_severity()` at `router_log_analyze.py:2414` | Reuse existing override precedence for new finding kinds; apply count LOW ceiling after this function. |
| Device findings | `detect_unknown_devices()` / `detect_blocked_devices()` at `router_log_analyze.py:2472-2549` | Preserve NETGEAR legacy behavior; add portable stable-identity discovery and consolidated new+rejected behavior. |
| Learned profiles | `compute_numeric_profile()`, history fetchers, subject behavior at `router_log_analyze.py:2201-3387` | Add router snapshot history and router+firmware subjects; explicitly filter by capability, trust, router instance, firmware, and epoch. |
| Reprocess flow | `main()` and `persist_analysis()` at `router_log_analyze.py:4809-5160` | Move duplicate/replace handling ahead of state-dependent analysis and run the entire delete-rebuild-analyze-persist sequence in one `BEGIN IMMEDIATE` transaction. |
| Reports | `build_report_data()` plus text/Markdown/HTML renderers at `router_log_analyze.py:3913-4773` | Add router/format/capability/count/coverage/clock/occurrence sections consistently across JSON and rendered formats. |
| Tests | `test_router_log_analyze.py` | Extend the existing full project suite; add only synthetic fixture files/builders. |

## Target Runtime Contracts

Define the following logical contracts in `router_log_analyze.py`. Local field names may follow surrounding style, but serialized keys and semantics below are binding.

### Stable format identifiers

- JSON/database format IDs: `netgear` and `tp_link_archer`.
- CLI values: `auto`, `netgear`, and `tp-link-archer`.
- `--format` defaults to `auto`.
- Automatic selection requires a top score of at least `0.80`. If two adapters score at least `0.80` and differ by less than `0.15`, fail as ambiguous. The error lists adapter names and scores, never raw input.
- Explicit selection bypasses ambiguity, but parsing still validates the selected format's required structure and fails without mutating the database when it is not plausible.

### Dataclasses and adapter methods

Add these concepts near the existing dataclasses:

- `RouterCapabilities`: booleans for stable client identity, client DHCP equivalence, client access-decision equivalence, comparable device-event coverage, router/system events, WAN transitions, snapshot counts, and potentially trustworthy router-local time; sets of supported canonical event keys/families; plus an internal snapshot-buffer semantic-dedup flag. Serialize sets as sorted lists.
- `RouterIdentityCandidate`: canonical vendor namespace, normalized LAN MAC when valid, router-owned interfaces, identity warning(s), and whether persistence is safe without an override.
- `RouterSnapshotMetrics`: raw total/Wi-Fi values, derived wired value, eligibility flag, and exclusion reason for the correlated set.
- `ClockSegment` / `BootSessionCandidate` (or equivalent small dataclasses): enough evidence to keep clock trust and boot grouping independent.
- `ParsedRouterLog`: `format_id`, capabilities, identity candidate, model/hardware/firmware metadata, export timestamp, snapshot metrics, all normalized events, `ParseStats`, coverage/order/clock statistics, boot candidates, and warnings.
- `RouterLogAdapter.detect(text) -> float` and `RouterLogAdapter.parse(text, source) -> ParsedRouterLog`.
- `select_router_adapter(text, requested_format) -> RouterLogAdapter` and `parse_router_log(text, source, requested_format) -> ParsedRouterLog`.

Extend `Event` with optional, defaulted fields so existing named test construction remains valid:

- actor scope (`router` or `device`) and optional stable client identity;
- component, process identifier, syslog severity, vendor event code;
- normalized privacy-reduced message and structured evidence;
- source sequence, raw timestamp text, clock-trust class, clock-segment identifier;
- boot context/session identifiers and occurrence digests.

Keep `raw_line` for current-run reporting only. No persistence helper may accept or serialize `raw_line`.

### Router identity

- A valid TP-Link instance key is `sha256("router-instance:v1\0tp-link\0" + normalized_lan_mac)`.
- Validate MACs as six octets, unicast, non-broadcast, and non-zero. Tighten `is_real_mac()` or add a separate identity-grade validator without changing legacy parsing expectations unexpectedly.
- Model and firmware are metadata, never identity inputs.
- Router-owned LAN and WAN MACs are excluded from client discovery and device observations.
- `--router-instance` takes precedence over an adapter-derived candidate and derives an opaque key from the trimmed user value using `sha256("router-instance-override:v1\0" + value)`. Reject empty/control-character values; do not store the raw override.
- `--router-label` affects only the friendly display label. Same label never merges instances; label/model changes never split an instance.
- For NETGEAR compatibility, migrated and new default NETGEAR runs without an explicit override use one deterministic legacy instance key. This is the sole compatibility exception to the stable-hardware-identity requirement and preserves existing history.
- A TP-Link parse with no valid identity and no override may render a non-persistent report. It must not import configuration, create a run, create devices, or change any learned state.

### Router behavior subject

Use an opaque subject key derived from router instance and firmware profile, with `subject_type = "router"`. Firmware profile is a digest of normalized firmware metadata, with `unknown-firmware` and `unknown-legacy-firmware` sentinels. Never include a raw MAC in the subject key or friendly label.

### New finding kinds

Add deterministic ordering, rendering, score grouping, and policy support for:

- `new_device` — MEDIUM before policy on the adapter-independent discovery path.
- `new_rejected_device` — one consolidated HIGH before policy; no separate discovery/rejection score contribution.
- `router_client_count_anomaly` — one correlated finding, hard-capped LOW after policy.
- `router_firmware_change` — LOW before policy.
- `router_new_event_type` — MEDIUM before policy after warm-up.
- `router_state_change` — MEDIUM before policy for learned running/enabled to stopped/disabled transitions.
- `router_security_event` — severity from explicit canonical mapping plus policy; direct high-confidence evidence remains eligible during warm-up.

Do not rename or reinterpret existing finding kinds.

## Target v4 Persistence Contract

Retain existing tables unless the migration below explicitly rebuilds or re-keys them. Add the following tables/columns with foreign keys and indexes; choose standard SQLite types consistent with the current schema.

### `router_instances`

- `id` primary key;
- unique opaque `instance_key`;
- `canonical_vendor`, `identity_source`, friendly `label`;
- cached `first_seen` / `last_seen`.

### `device_registrations`

- primary key, `mac`, `registration_source`, deterministic `source_key`;
- optional `epoch_id`;
- registered name/status/connection type;
- `first_seen` / `last_seen` evidence timestamps;
- unique `(mac, registration_source, source_key)`.

Baseline registration source keys use the baseline epoch ID; config registrations use a digest of the imported file bytes. Re-import is idempotent. Registration is durable evidence separate from observed presence.

### Run-owned observation tables

- `device_observations`: `run_id`, `mac`, `seen_at`, `evidence_kind`, privacy-reduced attributes; indexed by MAC/time and unique per equivalent run evidence.
- `router_metadata_observations`: one row per run containing router instance, observation/export time, model, hardware, firmware, and privacy-reduced metadata.
- `router_snapshot_metrics`: one row per run containing router instance, epoch, export time, raw total/Wi-Fi, derived wired, correlated eligibility, and exclusion reason.

### `runs` additions/rebuild

Add:

- non-null `router_instance_id` and `format_id`;
- nullable router-local `export_timestamp`;
- non-null serialized `capabilities_json`;
- nullable `body_digest`;
- `novel_event_count` / `repeated_event_count` defaults of zero.

Replace global `UNIQUE(file_hash)` with `UNIQUE(router_instance_id, file_hash)`. All lookup/reprocess methods require both values. Preserve existing run IDs during migration and preserve the target run ID during `--reprocess` replacement.

### Boot and occurrence provenance

- `router_boot_sessions`: router instance, optional trusted local anchor, canonical startup signature, created timestamp, and an opaque database identifier. Index anchor/signature matching fields; do not force two genuinely distinct anchorless boots with the same signature into one session.
- `run_router_boot_sessions`: many-to-many run/session provenance.
- `router_event_occurrences`: router instance, unique semantic digest within that instance, optional boot session, parsed router-local timestamp, clock trust, component, PID, vendor code, syslog severity, normalized message, canonical key/family, actor scope/identity, and privacy-reduced structured evidence. Clock trust controls calendar/timing eligibility; a resolved boot occurrence may retain its untrusted raw local timestamp inside session-scoped identity without treating it as a historical date.
- `run_event_occurrences`: `(run_id, occurrence_id)` primary key plus ingest-time `novel` / `repeated` classification and diagnostic source-sequence/count fields.

Canonical occurrence rows are evidence, not proof of novelty. Novelty is determined only by surviving run links. Orphan occurrences/sessions are pruned after successful replacement persistence, never before replacement classification.

### Existing summary/catalog tables

- Keep `devices` and `behavior_subjects` as derived caches/catalogs for compatibility.
- Refresh device and router first/last seen with chronological `MIN`/`MAX` over explicit registrations and surviving observations, not ingestion order.
- Delete summary-only devices/subjects that have no registration and no surviving observation/history.
- Preserve legacy `__SYSTEM__` daily rows for audit, but exclude them from router-history and baseline-export queries.
- Re-key migrated system behavior catalog/daily rows to the deterministic legacy NETGEAR router plus `unknown-legacy-firmware` profile.

## Implementation Tasks

### Task 1: Lock Existing NETGEAR Behavior with Characterization Tests

**Files:**

- Modify: `test_router_log_analyze.py`
- Add if useful: `tests/fixtures/netgear_synthetic_regression.log`

- [ ] Add a conspicuously synthetic multi-day NETGEAR fixture or builder that exercises DHCP, allowed/rejected WLAN, WAN disconnect/reconnect, a system event, duplicate suppression, malformed/noise accounting, and known/unknown/blocked devices.
- [ ] Assert the exact normalized event projection currently returned by `parse_log_text()`: timestamps, MACs, event keys/families, IPs, and duplicate/spam counts.
- [ ] Run it through `main()` with a disposable SQLite database and normalize only genuinely variable fields (absolute temporary paths, database-generated IDs, ingestion timestamps). Assert an explicit legacy projection of the existing JSON keys, finding kinds, severities, score, status, risk breakdown, device summary, and incident attribution exactly. Later additive v4 keys must not require weakening that legacy projection.
- [ ] Add exact text/Markdown/HTML contract assertions for the sections that later work must preserve. Prefer structured whole-section assertions over brittle whitespace unrelated to behavior.
- [ ] Assert existing `unknown_device` and `blocked_device_activity` remain CRITICAL before their existing policy overrides.
- [ ] Run the full current suite before production edits. Expected: all tests pass and the new characterization tests pass against v3 behavior.
- [ ] Commit only synthetic tests/fixtures.

### Task 2: Introduce the Adapter Boundary Without Changing NETGEAR Semantics

**Files:**

- Modify: `router_log_analyze.py`
- Modify: `test_router_log_analyze.py`

- [ ] Write failing tests for NETGEAR detection confidence, explicit `--format netgear`, `auto` selection, low-confidence failure, ambiguous selection, and explicit-format structural failure before database creation/mutation.
- [ ] Add the target dataclasses, stable format IDs, detection thresholds, adapter registry, and selection functions described above.
- [ ] Move `reconstruct_wrapped_log_lines()`, `build_event_objects()`, and NETGEAR-specific timestamp/label/family/IP rules behind `NetgearLogAdapter` while keeping the existing helpers available where tests or internal callers still rely on them.
- [ ] Keep `parse_log_text(text, source)` as a compatibility wrapper that explicitly invokes the NETGEAR adapter and returns `(events, ParseStats)`.
- [ ] Give NETGEAR precise capabilities matching current evidence: stable MAC identity when present, client DHCP, access decisions, device-event coverage, supported current keys/families, WAN transitions, and trustworthy local timestamps; no snapshot counts and no rolling-buffer semantic dedup.
- [ ] Ensure the adapter's normalized events are byte-for-byte/report-equivalent at all existing comparison points. New optional fields may be populated, but cannot affect existing aggregation, incidents, findings, sorting, scoring, or output yet.
- [ ] Add `--format`, `--router-label`, and `--router-instance` parsing, but defer persistent identity changes until the v4 task. Management-only commands retain their current behavior and do not persist these presentation/ingestion options.
- [ ] Run the complete suite. Expected: all characterization and pre-existing tests pass.
- [ ] Commit the adapter boundary separately from TP-Link parsing.

### Task 3: Parse and Normalize Synthetic TP-Link Snapshots In Memory

**Files:**

- Modify: `router_log_analyze.py`
- Modify: `test_router_log_analyze.py`
- Add: `tests/fixtures/tp_link_archer_synthetic.log`
- Add variant fixtures only as needed under: `tests/fixtures/`

- [ ] Create a synthetic fixture matching the observed structure, not its private values:
  - banner `# ... System Log`;
  - `# Time = YYYY-MM-DD HH:MM:SS`;
  - `# H-Ver = ... ; S-Ver = ...`;
  - LAN/WAN `I`, `M`, and `MAC` fields plus the WAN gateway/DNS continuation;
  - `# Clients connected: N ; WI-FI : N`;
  - newest-first records shaped as `timestamp component[pid]: <severity> code message`.
- [ ] Write failing tests for high-confidence detection and parsing of model/export time/hardware/firmware/interfaces/counts, reverse-to-chronological order, line coverage, malformed/ignored counts, and missing optional header warnings.
- [ ] Parse body records with one anchored expression equivalent to:

  ```text
  timestamp + component + optional [pid] + ':' + '<severity>' + numeric code + message
  ```

  Accept component tokens actually evidenced by the format; do not make the expression consume arbitrary email/PDF noise as a record.
- [ ] Normalize WAN DHCP discover/offer/request/ack/release as router-scoped keys such as `WAN_DHCP_DISCOVER`; never emit client `DHCP_IP` for these records.
- [ ] Map evidenced internet-up/down actions to `INTERNET_CONNECTED` / `INTERNET_DISCONNECTED` and attach boot context. Unknown codes use a deterministic key from component, numeric code, and normalized action, while retaining code/severity and privacy-reduced evidence.
- [ ] Implement normalized-message privacy reduction before digest/persistence boundaries: replace MAC/IP/IPv6-like tokens and adapter-extracted actor names with typed placeholders, normalize whitespace, and keep structured values separately. Test that persisted candidates do not contain complete raw lines or unstructured address/name tokens.
- [ ] Register parsed LAN/WAN MACs as router-owned and prove they never become client actors even when present in WAN DHCP text.
- [ ] Parse counts as one correlated set. If a count is missing/non-integer/negative or Wi-Fi exceeds total, retain raw diagnostic values, set the entire set ineligible, and do not derive wired.
- [ ] Implement clock segmentation in emission order (reverse of file order):
  - large correction threshold: at least 24 hours;
  - near-export window: no more than 48 hours before and no more than five minutes after export time;
  - backward correction threshold: more than five minutes;
  - multiple/backward corrections: only the final monotonic segment reaching the near-export window is trusted;
  - firmware-date startup cluster followed by a qualifying large forward correction is pre-synchronization.
- [ ] Keep router-local timestamps naive; never attach UTC or infer an offset. Untrusted records have no observation date, timing eligibility, or run-span effect.
- [ ] Detect adapter-defined startup markers regardless of clock trust. Build session-independent trusted match digests and canonical startup signatures from stable component/code/action tokens, excluding timestamps, PID, full message, and complete-buffer membership.
- [ ] Add synthetic variants for already-correct boot time, genuine later reboot, truncated pre-sync fragment, backward correction, and multiple corrections.
- [ ] Run the complete suite. Expected: NETGEAR goldens unchanged and all in-memory TP-Link parser/clock tests pass.
- [ ] Commit TP-Link in-memory parsing separately from persistence.

### Task 4: Implement Schema v4 Creation, Validation, and Atomic v3 Migration

**Files:**

- Modify: `router_log_analyze.py`
- Modify: `test_router_log_analyze.py`

- [ ] Build failing tests that create v3 databases through SQL/test builders at runtime. Do not commit binary databases or copies of local state.
- [ ] Test: empty database creates direct v4; valid populated v3 migrates; second open is a no-op; versions below 3, above 4, missing metadata, and malformed v3 structures fail closed with recovery guidance.
- [ ] Test preservation of every existing v3 table's row counts and IDs, especially `runs`, baseline epochs/seeds, policies, incidents, device/event/subject daily rows, and device catalog entries.
- [ ] Test legacy baseline/config device rows become explicit registrations; real-MAC daily rows become run-owned observations; `__SYSTEM__` rows remain auditable but are excluded by new queries.
- [ ] Test the runs constraint changes from global file hash to `(router_instance_id, file_hash)` while legacy run IDs and dependent references remain unchanged.
- [ ] Test migrated behavior subjects/catalog entries use the deterministic legacy NETGEAR router and `unknown-legacy-firmware` profile.
- [ ] Test foreign-key enforcement is ON for every normal connection and `PRAGMA foreign_key_check` is empty after creation/migration.
- [ ] Test injected failure after table rebuild but before schema-version write rolls back all logical changes and leaves v3 usable and still stamped v3. Refactor validation into a patchable private step rather than weakening production validation.
- [ ] Replace `ensure_schema()` with explicit dispatch:
  1. inspect table presence and `metadata.schema_version` without stamping;
  2. create a new v4 schema only when the database is truly empty;
  3. validate and accept an existing v4;
  4. validate then migrate exactly v3;
  5. fail all other states.
- [ ] Enable `PRAGMA foreign_keys = ON` immediately for normal connections. For v3 rebuild only: validate first, commit any implicit read/setup transaction, record prior pragma, disable foreign keys outside a transaction and verify it took effect, `BEGIN IMMEDIATE`, rebuild/copy/validate, write version last, commit, restore ON in `finally`, and validate again.
- [ ] Rebuild `runs` safely without rewriting child IDs: create `runs_v4`, copy the same primary keys plus deterministic legacy defaults, drop old `runs` with foreign keys temporarily disabled, rename `runs_v4` to `runs`, and recreate indexes. Existing child table declarations continue to reference the final `runs` name.
- [ ] Create all target v4 tables/columns/indexes from the persistence contract. Add explicit orphan, non-null router, composite uniqueness, source/destination count, and foreign-key checks before the version update.
- [ ] Backfill deterministic registration `source_key` values and preserve legacy first/last evidence. Refresh caches using chronological extrema.
- [ ] Do not call `set_metadata("schema_version", ...)` until every migration validation passes.
- [ ] Run the complete suite. Expected: all migration rollback/idempotence/integrity cases and all prior tests pass.
- [ ] Commit schema/migration work on its own.

### Task 5: Resolve Router Identity and Persist Boot/Occurrence Provenance Before Analysis

**Files:**

- Modify: `router_log_analyze.py`
- Modify: `test_router_log_analyze.py`

- [ ] Write failing tests for stable TP-Link identity, distinct same-model/different-LAN instances, model/label changes without identity splits, invalid/all-zero/broadcast/multicast LAN MACs, explicit override precedence, opaque/default labels, and router-owned interface exclusion.
- [ ] Write failing tests proving identical file bytes may exist once under each of two explicit router instances, while a second import under the same instance is whole-file deduplicated.
- [ ] Add `StateStore` methods that resolve/create router instances and look up runs only by `(router_instance_id, file_hash)`. Detection and identity resolution must occur before calling them.
- [ ] Persist router metadata as run-owned observations. A changed model for the same instance emits a warning/observation; firmware changes do not create an instance.
- [ ] Implement boot-session resolution against surviving provenance in this order:
  1. shared trusted match digest linked to a persisted session;
  2. exact trusted candidate anchor plus canonical startup signature;
  3. a complete explicit boot marker creates a session, using the first trusted boot occurrence as anchor when available;
  4. a truncated pre-synchronization fragment with neither overlap, reliable anchor, nor a complete explicit marker stays report-only and does not enter occurrence learning.
- [ ] Ensure a truncated snapshot reuses the persisted session through overlapping trusted evidence and a later real reboot, including one with already-correct time, receives a distinct session.
- [ ] Compute occurrence digests only after router/session resolution. The digest tuple is exactly router instance, parsed router-local timestamp, boot session for boot events, component, PID, vendor code, syslog severity, normalized message, actor scope, and actor identity. Non-boot occurrences require a trusted timestamp; untrusted occurrences require a resolved boot session and remain ineligible for calendar/timing learning.
- [ ] Collapse identical tuples at one-second source resolution within a run. Keep PID in occurrence identity; exclude PID from learned behavior key. Source sequence remains diagnostic and does not create multiplicity.
- [ ] Before incidents/findings/scoring, classify each eligible parsed occurrence as repeated iff a surviving `run_event_occurrences` link exists after excluding the target reprocess run; otherwise novel. Canonical-row existence without a surviving link is not repetition.
- [ ] Preserve the full parsed event set for coverage, boot matching, and repeated counts. Pass only novel, trusted, capability-eligible occurrences to body-event incident/anomaly/learning paths. Snapshot header metrics remain independently eligible.
- [ ] Scope semantic occurrence deduplication to adapters declaring rolling snapshot-buffer semantics. NETGEAR retains its current event analysis and exact whole-file behavior.
- [ ] Test repeated and mixed-overlap snapshots, changed headers, exact tuple collapse, PID distinction, repeated rejection/security evidence producing no new finding/score, and privacy-reduced persisted occurrence fields.
- [ ] Run the complete suite. Expected: occurrence classification precedes all body findings, NETGEAR goldens remain exact, and TP-Link overlap cases pass.
- [ ] Commit identity/boot/occurrence work separately.

### Task 6: Make Reprocessing Provenance-Safe and Fully Atomic

**Files:**

- Modify: `router_log_analyze.py`
- Modify: `test_router_log_analyze.py`

- [ ] Add failing tests in which the target run is the sole evidence for a client, model, firmware, router/subject timestamp, snapshot metric, boot link, and occurrence; reprocessing without that evidence removes every stale derived fact.
- [ ] Add a test where an explicit baseline/config registration survives reprocess even when all run observations disappear.
- [ ] Add a test proving the replacement does not treat a device observed only by the removed version of that same run as already known.
- [ ] Add many-to-many occurrence tests: deleting/reprocessing one run does not remove an occurrence/session still referenced by another run; orphan evidence is pruned only after successful replacement.
- [ ] Add rollback tests that fail after deletion, after analysis, and during persistence. The original run ID, links, observations, summaries, findings inputs, and learned rows must remain intact.
- [ ] Refactor `main()` / `persist_analysis()` so the mutation boundary is one explicit `BEGIN IMMEDIATE` transaction:

  ```text
  parse and resolve adapter/router without mutation
  BEGIN IMMEDIATE
  find scoped existing run
  if --reprocess: remove all target-owned rows/links but retain orphan canonical evidence temporarily
  refresh effective device/router/subject summaries from registrations + other runs
  reload effective snapshots/history
  resolve boot sessions against surviving links
  classify occurrence novelty against surviving links
  run incidents -> findings -> scoring on eligible novel evidence
  insert replacement using the original run ID when replacing
  insert observations, metrics, links, daily rows, and incidents
  recompute summaries; prune unreferenced occurrences/sessions
  validate local referential invariants
  COMMIT
  ```

- [ ] If an identical scoped run exists without `--reprocess`, do not create a new run or mutate learning. Build a deduplicated report in which body occurrences and header metrics are not scored again.
- [ ] Replace `delete_run()` with a complete run-owned deletion helper covering current and new tables in dependency-safe order. Keep it transaction-neutral: callers own commit/rollback.
- [ ] Make every summary refresh use `MIN`/`MAX`, including older evidence ingested after newer evidence.
- [ ] Keep configuration/baseline management transactions separate and complete before log-analysis replacement begins.
- [ ] When a logfile is present, perform input loading, format detection, parsing, and router-identity validation before opening/migrating a database or executing combined management imports. This preserves the requirement that unknown/ambiguous formats fail before any database mutation. Management-only invocations may open the store immediately as they do today.
- [ ] Run the complete suite. Expected: all injected failures restore the exact prior logical state and no stale provenance remains after success.
- [ ] Commit the atomic reprocess refactor separately.

### Task 7: Add Capability-Gated Device, Incident, Count, and Router Behavior Analysis

**Files:**

- Modify: `router_log_analyze.py`
- Modify: `test_router_log_analyze.py`

#### Device and detector gating

- [ ] Add failing tests for every capability-matrix row in the approved design. Missing capabilities must yield report status `unavailable`, skip the detector, and persist no synthetic zero/daily row.
- [ ] Centralize detector eligibility rather than scattering format-name checks. Format checks are allowed only for the explicit NETGEAR severity compatibility path and adapter parsing.
- [ ] Preserve `detect_unknown_devices()` / `detect_blocked_devices()` for NETGEAR exactly. Add an adapter-independent stable-client discovery pass for other capable adapters.
- [ ] Resolve knownness from explicit registrations plus surviving device observations loaded after any reprocess deletion. Known devices update observation detail without a discovery finding.
- [ ] Emit `new_device` at MEDIUM, then call `enforce_policy_severity()` so finding/device-name/device/event policy may suppress, cap, or escalate it.
- [ ] When the same new identity has adapter-approved rejected/blocked evidence, emit only `new_rejected_device` at HIGH before policy. Do not also emit discovery/rejection score groups.
- [ ] A registered or previously observed blocked client is not “new,” but adapter-approved blocked/rejected activity remains an actionable security finding through the established/policy-mapped access path. Known allowed presence alone remains informational.
- [ ] Do not turn ambiguous/non-stable identifiers or anonymous count changes into device rows/findings.
- [ ] Gate per-device DHCP, total-volume, timing, type/rarity/behavior, cluster, and reset paths by the exact capabilities and supported keys/families. Do not reuse cross-vendor `total_events` history unless comparable coverage is true.
- [ ] Confirmed resets require WAN transitions plus supported recovery keys; inferred resets require stable identity plus client DHCP/recovery equivalence. Startup transitions retain boot context so startup is not automatically classified as an outage.

#### Snapshot counts

- [ ] Add `StateStore.fetch_router_snapshot_history(router_instance_id, epoch_id, before_export_timestamp, limit)` returning the seven most recent eligible observations, not calendar days and not firmware-scoped.
- [ ] Require three earlier eligible snapshots before scoring. Earlier snapshots are stored/displayed without findings.
- [ ] Build per-metric profiles with existing `compute_numeric_profile()` using history only and the existing `stddev_floor`. Evaluate total/Wi-Fi/wired, but combine deviations into one `router_client_count_anomaly` with per-metric observed/range/direction detail.
- [ ] Apply tolerance, choose the strongest correlated pre-policy severity, call `enforce_policy_severity()`, then apply `min_severity(result, "low")`. Suppression remains `normal`; escalation cannot bypass the hard post-policy LOW ceiling.
- [ ] Store valid correlated sets even when they are metric-only anomalies so the count baseline adapts. Invalid correlated sets remain report-only/ineligible with one exclusion reason.
- [ ] Ensure count findings contribute at most one risk group per snapshot and never infer device identity.

#### Router/firmware behavior

- [ ] Key router behavior by router instance + firmware profile + active epoch. Firmware changes do not reset portable device history or snapshot counts.
- [ ] Define an eligible router behavior observation as a run containing at least one novel, trusted, router-scoped occurrence for that profile. Repeated-only buffers remain valid reports but do not advance warm-up or relearn events.
- [ ] The first three eligible observations populate the router event inventory without history-dependent new-type/state-change findings.
- [ ] On a later eligible observation, emit `router_new_event_type` MEDIUM before policy for a previously unseen canonical/unknown deterministic behavior key.
- [ ] Normalize stable state transitions (for example running/enabled vs stopped/disabled) in structured evidence. Emit `router_state_change` MEDIUM before policy only when history learned the prior running/enabled state.
- [ ] A firmware change on an existing instance emits `router_firmware_change` LOW before policy and selects a new firmware profile/warm-up.
- [ ] Define an explicit in-code map for high-confidence firewall/access-control/rejection/security actions. Emit `router_security_event` during warm-up when direct evidence warrants it; vendor syslog severity may inform but never solely determine analyzer severity.
- [ ] Keep expected boot service churn within boot context and profile it instead of repeatedly alerting.
- [ ] Extend exclusion maps so stable metric-only anomalies remain numerically adaptive while security/timing/behavior/partial/reset evidence remains quarantined in the affected profile.
- [ ] Run the complete suite. Expected: all capability, new-device policy, count ceiling/adaptation, firmware isolation, warm-up, and security tests pass with NETGEAR goldens unchanged.
- [ ] Commit analysis behavior separately.

### Task 8: Complete Reporting, Baseline, CLI, and Documentation Contracts

**Files:**

- Modify: `router_log_analyze.py`
- Modify: `test_router_log_analyze.py`
- Modify: `README.md`
- Modify: `FUTURE_MULTI_VENDOR_SUPPORT.md` only if implementation status wording needs adjustment

- [ ] Update `build_report_data()` with stable JSON sections for:
  - router label/vendor/model/hardware/firmware/format/export time;
  - capabilities and named unavailable checks;
  - snapshot counts, eligibility, history count, learned ranges, and change finding detail;
  - novel/repeated/report-only body counts;
  - router/system/security changes and new devices;
  - clock segments, boot-session resolution warnings;
  - parse coverage, ignored/malformed/noise counts.
- [ ] Preserve all existing JSON keys and semantics; add fields rather than renaming/removing old ones. NETGEAR reports may add router/capability metadata but must preserve existing finding lists, score/status, adjustments, summaries, and rendered content asserted in Task 1.
- [ ] Make text, Markdown, and HTML render the same new facts and clearly distinguish `unavailable`, `zero`, `normal`, and `repeated`. A fully repeated body with a fresh valid header says so and still presents the new metrics.
- [ ] Ensure default labels expose only vendor/model plus a short opaque digest, never a visible substring of a hardware address or a raw override.
- [ ] Update `finding_security_priority()`, `FINDING_KIND_ORDER`, render helpers, detail fields, priority selection, and risk grouping for every new finding kind.
- [ ] Confirm baseline export remains a portable bootstrap: devices/clusters, learned numeric ranges, and current descriptive event profiles only. Exclude router instances, metadata/history, firmware profiles, occurrences, boot sessions, and snapshot metrics. Document descriptive event profiles as non-round-trippable in this scope.
- [ ] Keep the router security-config importer explicitly NETGEAR-specific in help/README. Do not invent TP-Link config import.
- [ ] Update CLI help/epilog and README examples for supported formats, `--format`, `--router-label`, `--router-instance`, scoped reprocessing, format capabilities, router-local clock caveats, schema v3 migration, and private-log handling.
- [ ] Bump the CLI version from `0.4.0` to `0.5.0`.
- [ ] Change `FUTURE_MULTI_VENDOR_SUPPORT.md` status from “not implemented” to the exact implemented state while retaining it as historical context.
- [ ] Add cross-renderer assertions that JSON/text/Markdown/HTML agree on router identity label, counts, availability, occurrence totals, and severity.
- [ ] Run the complete suite. Expected: all report/CLI/docs-linked behavior tests pass.
- [ ] Commit reporting/docs work separately.

### Task 9: Full Regression, Migration, Privacy, and End-to-End Validation

**Files:**

- Modify only if validation exposes a defect: files above

- [ ] Inspect `git status --short` and the complete diff. Confirm no private log, database, reports, real MAC/IP/device names, local paths, or other sensitive artifacts are tracked or untracked inside the public project.
- [ ] Create the project virtual environment without using system/Homebrew Python for project execution:

  ```zsh
  uv venv .venv
  uv pip install --python .venv/bin/python -r requirements-dev.txt
  ```

- [ ] Run the complete project suite (no selection, skips, or omissions):

  ```zsh
  .venv/bin/python -m pytest -q
  ```

  Expected: every test in `test_router_log_analyze.py` and every added test passes; zero failures/errors/skips.

- [ ] Run the repository launcher dependency/header drift guard because the uv-managed launcher changed:

  ```zsh
  uv run --script ../tools/check_uv_headers.py
  ```

  Expected: success with no launcher/manifest drift.

- [ ] Exercise the repository launcher directly:

  ```zsh
  uv run --script router_log_analyze.py --version
  uv run --script router_log_analyze.py --help
  ```

  Expected: version `0.5.0`; help lists supported formats and router options without NETGEAR-only log wording.

- [ ] Run a synthetic two-snapshot end-to-end sequence against a disposable database outside tracked fixtures: first snapshot persists occurrences/counts; second has an overlapping body plus changed header count and stores only novel body evidence while retaining the second metric observation.
- [ ] Run a v3 migration end-to-end against a disposable synthetic database and verify `PRAGMA foreign_keys`, `PRAGMA foreign_key_check`, schema version, preserved IDs/counts, and a successful post-migration NETGEAR analysis.
- [ ] After all synthetic validation passes, manually analyze the user-supplied private TP-Link log in place with a disposable database outside the repository. Do not print or save its raw body into repository artifacts. Confirm the report format/router/count/clock/novel-repeated fields satisfy the approved acceptance criteria.
- [ ] Re-run the complete suite and uv-header guard after any validation fix.
- [ ] Before every implementation commit, inspect `git diff --cached --name-only` and `git diff --cached` specifically for sensitive data. Do not commit when any value is uncertain.

## Required End-State Assertions

Implementation is ready for review only when all of the following are demonstrated by tests or the private local smoke check:

- Existing NETGEAR normalized events, finding kinds/severities, score/status, report JSON, rendered report contracts, management commands, and exact-file behavior remain stable.
- TP-Link header/body parsing matches the observed structure, uses router-local naive time, and does not confuse WAN DHCP with client DHCP.
- Router identity is stable across label/model/firmware changes and isolated across physical/explicit instances.
- Portable known devices remain known across router replacement; a new stable client is MEDIUM before explicit policy, and new+rejected is one HIGH finding before policy.
- Missing device telemetry is `unavailable`, never zero; no synthetic zeros enter history.
- Snapshot counts use three-prior-observation warm-up, seven most recent eligible snapshots, one correlated finding, metric adaptation, and an unbypassable post-policy LOW ceiling.
- Router event inventory/state/security learning is router+firmware+epoch scoped; repeated-only buffers do not advance it; direct security evidence remains active during warm-up.
- Semantic occurrence classification precedes incidents/findings/scoring and prevents repeated bodies, including security evidence, from re-alerting.
- Reprocess replacement uses surviving provenance only, preserves its logical run ID, removes all stale run-owned evidence, preserves explicit registrations/shared occurrences, and rolls back exactly on failure.
- Valid v3 databases migrate atomically to v4 with stable IDs/references; invalid/unsupported schemas fail closed; all normal connections enforce foreign keys.
- SQLite contains privacy-reduced structured occurrence evidence and no complete raw log lines.
- Baseline export remains portable and excludes router-instance history.
- The complete test suite, launcher drift guard, help/version checks, synthetic E2E, migration E2E, public-repository sensitive-data inspection, and private in-place smoke check all pass.

## Executor Stop Conditions

- If the private format contradicts a binding parser/identity/clock assumption above, stop and discuss the contradiction before broadening the adapter.
- If v3 migration cannot preserve IDs/references atomically, stop before writing schema version 4 and present the exact failing invariant.
- If an existing NETGEAR characterization changes, treat it as a regression and fix it; do not update the golden expectation unless the user explicitly approves a behavior change.
- If any test fails, do not commit, advance tasks, deploy, or declare completion. Diagnose and fix every failure or provide the full blocker report required by `AGENTS.md`.
