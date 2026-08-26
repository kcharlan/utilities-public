# TP-Link Router-Instance Support Design

**Date:** 2026-08-25

**Status:** Implemented and validated in router-log-analyzer 0.5.0 after adversarial review. This document preserves the binding design rationale; the README is the current user-facing CLI contract.

**Scope:** Add TP-Link Archer system-log ingestion, router-instance-scoped system learning, portable device identity, snapshot client-count learning, and semantic deduplication while preserving existing NETGEAR behavior.

## Context

Before this work, the analyzer expected NETGEAR timestamps and square-bracketed event labels. A TP-Link Archer system-log export has a different structure:

- A header identifies the model, export time, firmware, router interfaces, and connected-client counts.
- Body records use ISO-like timestamps, component and process identifiers, syslog severity, numeric vendor event codes, and messages.
- Records are newest first.
- Startup records can begin with an untrusted clock value related to the firmware build date and then jump to the correct time after synchronization.
- Nightly exports are snapshots of a persistent event buffer. Successive files can repeat the entire body while changing only the export timestamp and connected-client counters.
- The observed format reports WAN DHCP startup negotiation, not LAN-client DHCP renewals.
- The header reports aggregate client counts but does not identify those clients.

The prior parser rejected these body records and produced no normalized events. Whole-file hashing also could not prevent repeated body events from being learned again when changing header values made each nightly export bytewise unique.

## Goals

1. Parse the observed TP-Link Archer system-log format without changing existing NETGEAR results.
2. Tie router/system health and security history to a stable physical router instance.
3. Keep device identity portable across router replacements.
4. Learn total, Wi-Fi, and wired connected-client counts as weak router-instance metrics.
5. Default a newly identified client to MEDIUM before explicit policy overrides while avoiding strong conclusions from anonymous count changes.
6. Prevent repeated snapshot body events from contaminating learned history.
7. Preserve the standalone, single-launcher installation model.
8. State unavailable checks explicitly instead of treating missing telemetry as normal behavior.
9. Make every run-derived observation safely replaceable through `--reprocess`.
10. Preserve existing NETGEAR finding severities, scores, and policy behavior.

## Non-Goals

- Inferring individual client identities from aggregate counts.
- Treating WAN DHCP negotiation as LAN-client DHCP activity.
- Adding a generic external profile language before a third real format requires it.
- Importing a TP-Link client or access-control configuration without a representative export.
- Copying private router logs, addresses, device names, or baseline contents into this public repository.
- Splitting runtime code into required sidecar modules that would break copy-based installation of the launcher.
- Turning baseline export into a database backup or round-tripping router-instance history.
- Persisting complete raw router log lines indefinitely.

## Considered Approaches

### 1. Adapter boundary with separate baseline scopes — selected

Add NETGEAR and TP-Link adapters, preserve a global device registry, and scope system behavior and snapshot metrics to a router instance.

This matches the portability requirement, isolates vendor behavior, and leaves room for another adapter without prematurely building a general framework.

### 2. New baseline epoch for every router replacement

Clone selected device data into a fresh epoch whenever the router changes.

This is simpler conceptually, but it duplicates portable identity, weakens continuity, and makes future replacements operationally cumbersome.

### 3. Fully declarative multi-vendor profile runtime

Define all parsing, identity, event mapping, and capability rules in external profiles.

This is flexible but excessive for two formats, complicates standalone distribution, and cannot express clock repair and snapshot-session logic cleanly without custom code.

## Architecture

The runtime remains in `router_log_analyze.py`. Adapter classes create a logical boundary inside the standalone script. No new runtime dependency is required.

### Adapter contract

Each adapter implements two responsibilities:

- `detect(text)`: return a confidence score based on format-specific evidence.
- `parse(text, source)`: return a normalized `ParsedRouterLog`.

`auto` format selection chooses one unambiguous high-confidence adapter. An explicit format option can resolve ambiguity or force diagnostic parsing. The initial supported format identifiers are stable internal values for NETGEAR and TP-Link Archer system logs; model names are metadata, not separate parser identifiers.

The normalized result contains:

- format identifier and capabilities;
- router identity candidate and interface identifiers;
- firmware metadata;
- export timestamp;
- snapshot metrics;
- normalized events;
- parsing, ordering, clock-quality, and coverage statistics;
- warnings that affect learning eligibility.

### Capability model

Adapters declare observed capabilities rather than allowing the analyzer to infer absence from missing events. Capabilities distinguish stable client identity, client DHCP equivalence, client allow/reject equivalence, comparable device-event coverage, supported canonical event keys and families, router/system events, WAN transitions, snapshot client counts, and trustworthy router-local event time.

Detector eligibility is explicit:

| Detector or profile | Required adapter evidence |
| --- | --- |
| New stable identity | Stable client identity |
| Blocked/rejected client | Stable client identity plus client access allow/reject equivalence |
| Per-device DHCP volume | Client DHCP equivalence |
| Per-device total event volume | Comparable device-event coverage; identity alone is insufficient |
| Per-device timing, new/rare type, and behavior | Trustworthy local time plus the relevant supported canonical event key/family |
| DHCP cluster visibility | Stable client identity plus client DHCP equivalence |
| Confirmed reset correlation | WAN transitions plus supported recovery keys |
| Inferred reset correlation | Stable client identity plus client DHCP/recovery equivalence |
| Snapshot client-count profile | Valid snapshot client counts |
| Router system/security profile | Router/system events and stable router identity |

An adapter supplies a set of supported canonical keys/families rather than one coarse device-events boolean. Cross-vendor `total_events` history is disabled unless the adapter explicitly declares comparable event coverage. A TP-Link snapshot without client identities therefore cannot generate missing-device, per-device DHCP, device-timing, or cluster-visibility conclusions. Capability loss is reported as unavailable and never contributes a synthetic zero.

### Router identity

For the observed TP-Link format, the stable instance key is a digest of the adapter's canonical vendor namespace and the normalized LAN interface MAC address. Model is validated and stored as mutable metadata, not included in physical identity. A changed model string for the same canonical LAN MAC creates a warning and metadata observation rather than silently splitting history.

The LAN MAC and WAN MAC values are registered as router-owned interfaces. They are excluded from client discovery for that active parsed router even when they appear in WAN DHCP messages. Historical ownership is retained as router metadata, not as a permanent global client blacklist: a former router interface may later be observed as a client behind a different router instance. A simultaneous cross-instance ownership/client conflict is reported as an identity warning.

Malformed, all-zero, broadcast, or group/multicast LAN MAC values cannot derive persistent identity. Firmware version is mutable instance metadata. A firmware update does not create a new router instance. Reports use a friendly label rather than exposing the internal digest. The default label combines vendor and model with a generated short digest that is not a visible substring of a hardware address.

`--router-label` changes presentation only. It never establishes identity, splits history, or merges two routers with the same label. If an adapter can parse events but cannot derive stable identity, it may render a non-persistent report; persistent learning requires a separate `--router-instance` stable user-assigned identity override.

### Portable device identity

The existing device registry remains network-wide. MAC address, friendly name, allow/block status, connection type, and cluster membership survive router replacement. Baseline/config registration is recorded separately from run-derived observation provenance.

Durable registrations retain import sequence and source. For each non-null registered field, the latest explicit import wins, preserving the current upsert behavior; omission from a later import does not revoke an older registration. Re-importing the same config digest confirms rather than duplicates its row. Each baseline import intentionally creates a new epoch and therefore a new registration source.

Existing learned device behavior is retained. It is evaluated only when the active adapter declares semantically compatible device-level capabilities. Missing telemetry never contributes a zero observation.

Router-owned interfaces never enter the portable device registry as clients.

Router replacement does not itself create a new global baseline epoch. Existing baseline export remains a portable bootstrap document, not a database backup: it carries device/cluster configuration, learned numeric ranges, and the existing descriptive event-profile fields, but does not export router instances, firmware, occurrence history, snapshot metrics, or router behavior. Descriptive event profiles remain non-round-trippable in this scope and are documented as such rather than silently presented as restorable history.

## TP-Link Parsing and Normalization

### Header

The adapter parses:

- model;
- export timestamp;
- hardware and firmware versions;
- LAN and WAN interface metadata;
- total connected clients;
- Wi-Fi connected clients.

Wired clients are derived as `total_clients - wifi_clients`. The three values form one correlated observation set. If either reported count is invalid or Wi-Fi exceeds total, the raw values remain available in the current report, but the entire set is ineligible for learning and no wired value is derived.

IP addresses may be retained in local diagnostic metadata when needed, but they do not participate in router identity and should not be elevated into public fixtures or documentation.

### Body records

A body record is parsed into:

- raw timestamp;
- timestamp trust classification;
- component;
- process identifier;
- syslog severity;
- numeric vendor event code;
- normalized message;
- canonical event key and family when a stable equivalent exists;
- actor scope (`router` or `device`);
- optional referenced client identity;
- source sequence number and an in-memory original source line for the current local report.

Records are normalized into chronological order after parsing.

WAN DHCP messages are router-scoped events such as WAN discover, offer, request, acknowledgement, and release. They must never normalize to the client-level `DHCP_IP` key.

Recognized internet-up and internet-down signals may map to the existing canonical internet transition vocabulary. Boot context remains attached so startup recovery is not automatically treated as an independent outage.

Unknown vendor codes remain reviewable under deterministic keys derived from component, code, and one adapter-approved action token from a small closed vocabulary with an `other` fallback. Volatile message text is evidence, not unbounded behavior vocabulary. Numeric codes and privacy-reduced structured evidence are retained. Complete raw lines are not written to SQLite by default and do not participate directly in occurrence identity. Persisted normalized messages remove address-like tokens and client names already represented through structured identity references. The original source export remains the audit source for future remapping.

### Client identities in future records

The current header contains counts only. If a body record supplies a MAC address or another adapter-approved stable client identity:

- router-owned interface identities remain router-scoped;
- a registered device is treated as known and its last-seen information is updated;
- an unregistered client becomes a new-device finding;
- ambiguous identifiers stay attached to the router event and do not create a device record.

## Clock Trust and Boot Sessions

Clock trust and boot-session grouping are independent classifications. A trusted TP-Link timestamp means trustworthy ordering and calendar position in router-local time; it is not treated as a UTC instant because the export contains no offset. Timezone or daylight-saving changes are metadata/timing concerns, not firmware-date pre-synchronization corrections.

The adapter reconstructs TP-Link emission order from the newest-first body. A correction is considered large when adjacent emission-order timestamps differ by at least 24 hours. A post-correction timestamp is near the export time when it is no more than 48 hours before or five minutes after the header timestamp. When a startup cluster uses the firmware build date and a large forward correction reaches that near-export window, the earlier cluster is pre-synchronization. Those records remain visible, but they:

- do not create artificial historical observation dates;
- do not participate in weekday or time-of-day learning;
- do not expand the observed run duration;
- may contribute startup-sequence evidence within a resolved boot session.

Backward corrections larger than five minutes or multiple corrections divide the body into clock segments, classified independently per boot/clock epoch. A later boot-time correction does not retroactively invalidate a prior boot's already-synchronized segment. A backward correction at an explicit boot boundary starts a new untrusted epoch; a backward jump without boot evidence is clock-ambiguous rather than automatically treated as firmware-date pre-synchronization. The ambiguous interval is excluded from timing/duration learning without discarding surrounding valid calendar evidence. These thresholds are adapter constants covered by fixtures rather than general anomaly-policy settings.

Boot sessions are detected from adapter-defined startup markers and transition sequences whether or not the clock was already correct. Before session assignment, each trusted record receives a timestamp-bearing session-independent match digest over router instance, router-local timestamp, component, process identifier, vendor code, severity, normalized message, and actor. A persisted boot session has a database identifier, router instance, trusted anchor or adapter-supplied unique boot identifier, canonical startup signature, and the trusted match digests assigned to it. The signature uses stable component/code/action tokens and excludes timestamps, process identifiers, full messages, and dependence on the complete visible buffer, but it is corroboration rather than unique identity.

Session resolution follows this order:

1. If a snapshot shares one unambiguous timestamp-bearing trusted match digest with a persisted boot session, reuse that session.
2. Otherwise, match a canonical startup signature whose candidate trusted anchor exactly matches a persisted session anchor.
3. Otherwise, an explicit boot marker with a trusted anchor or adapter-supplied unique boot identifier creates a persistent session.
4. An anchorless boot or truncated pre-synchronization fragment receives run-local report context but is not assigned to cross-run occurrence or behavior history. Exact whole-file duplicate handling still applies.

This lets rolling snapshots reuse a previously persisted anchor instead of deriving identity from whichever event now happens to be first in the buffer. A later reboot with already-correct time still receives boot context from its startup markers and distinct trusted occurrences.

Trusted non-boot events use their router-local timestamp in occurrence identity. Boot events additionally use the resolved persisted session identifier. Untrusted events require a persistently resolved anchored boot session to enter cross-run occurrence evidence; otherwise they remain report-only. If session resolution fails, the report explains that reliable cross-snapshot deduplication was unavailable for that segment. Stable client identity and explicit non-temporal security evidence may still be actionable in the current report even when their timestamps are untrusted; they remain excluded from calendar, duration, and time-of-day learning.

TP-Link snapshot imports do not use the current duration-based partial-run rule. Snapshot metrics are point observations at export time, and novel trusted body events are occurrences rather than evidence of continuous coverage.

## Cross-Snapshot Deduplication

Whole-file hashes continue to identify byte-for-byte duplicate inputs, but uniqueness is scoped to `(router_instance_id, file_hash)`. Router detection and identity resolution therefore occur before duplicate-run lookup. Identical bytes may be imported for two explicitly different router instances without merging their state. A second semantic layer handles snapshots whose headers change while their event bodies overlap.

Each normalized body occurrence receives a versioned `occurrence-v1` digest over the following ordered fields with an explicit separator and null token:

- router instance;
- trusted router-local timestamp and, for boot events, the resolved boot-session identifier;
- component;
- process identifier;
- vendor code;
- syslog severity;
- normalized message;
- resolved actor scope and identity.

The process identifier remains in the occurrence digest because two otherwise identical lines from distinct processes can represent separate emitted events. It does not participate in the learned event key because process identifiers are volatile behavior metadata. Exact repetitions of the full semantic tuple at the log's one-second resolution collapse to one occurrence, matching existing NETGEAR exact-duplicate behavior; source sequence is diagnostic and does not create multiplicity.

All durable opaque identities (router instance/override, firmware profile, router subject, trusted overlap, startup signature, normalized message, and occurrence digest) carry an explicit versioned prefix and fixed field order/normalization contract. A future normalization change requires a migration or compatibility lookup rather than silently creating a second identity universe.

Persistence separates canonical evidence from run provenance:

- `router_event_occurrences` stores the canonical digest and privacy-reduced normalized evidence.
- `run_event_occurrences` links every containing run to the canonical digest and records whether that run classified it as novel or repeated at ingest.

Occurrence classification happens before incident detection, anomaly detection, and scoring:

`parse -> identify router -> classify clock/boot -> compute occurrence IDs -> classify novel/repeated against surviving run links -> analyze novelty/trust-aware eligible evidence -> persist atomically`

The complete within-run deduplicated occurrence set remains available for coverage, boot reconstruction, stable-client observation, detector context, and repeated counts. Context-sensitive detectors receive novelty/trust flags: repeated occurrences may supply sequence context, but a fresh body-event incident/finding/score requires at least one novel qualifying constituent. A fully repeated completed incident, rejection, or security event cannot alert again merely because the header changed. Learned router history represents each distinct eligible canonical occurrence with surviving provenance exactly once, independent of which ingest first owned it. New snapshot metrics are still analyzed and stored at their export timestamp.

Reprocessing transactionally removes the replaced run's links before classifying its replacement. Canonical occurrences remain while any surviving run references them and are deleted only when no links remain. If the replacement no longer produces a digest, later snapshots that contained it still preserve its canonical evidence. A failed replacement restores the original run and all links.

If the first run that contributed a learned occurrence is removed while another eligible run link survives, the occurrence remains represented once in learned history. An implementation may query distinct surviving occurrences directly or transactionally promote the earliest eligible surviving link as the materialized learning owner. Every run containing stable client identity evidence owns its own device observation even when its related router occurrence was repeated.

The replacement transaction also removes the target run's device/router observations and daily behavior rows before any state-dependent finding is computed. The replacement analyzes against an effective state rebuilt from explicit registrations and all other surviving runs, so a device observed only by the old version of the target run cannot make its own replacement treat that device as previously known. Findings, scoring, new observations, and summary refreshes then complete inside the same transaction; any failure restores the original effective state.

## Persistence Model

The next schema version separates durable identity, run-owned observations, canonical occurrences, and run-to-occurrence provenance. Cached first/last-seen fields are summaries, never the sole evidence for whether an identity is known.

### `router_instances`

Stores the stable instance key, canonical vendor, friendly label, and cached first/last seen. Model and firmware are observations rather than identity. Cached timestamps are refreshed from surviving run-owned and explicit registration evidence using chronological minimum/maximum, not ingestion order.

### Explicit identity registrations

Baseline/config imports remain distinguishable from observed presence. Deleting or reprocessing a run cannot remove an intentionally registered device, while a device known only because of a replaced run ceases to be known if the replacement and all other surviving evidence omit it.

### `runs`

Adds router instance, format, export timestamp, capabilities, body digest, and novel/repeated event counts. Whole-file uniqueness becomes `UNIQUE(router_instance_id, file_hash)`, and run lookup/reprocess APIs require both values. Legacy runs are assigned to one legacy NETGEAR instance because the old schema cannot recover distinctions between historical NETGEAR devices that were already combined.

### Run-owned observations

- `device_observations` records `(run_id, mac, seen_at, evidence_kind, evidence_digest, attributes)` for client evidence, unique on those first five fields.
- `router_metadata_observations` records exactly one run-owned model, hardware, and firmware observation per run.
- `router_snapshot_metrics` records exactly one row per run with router instance, baseline epoch, export timestamp, the correlated count set, and learning inclusion/exclusion reason.
- Existing daily behavior rows remain run-owned through `run_id`.

Firmware profiles are durable versioned opaque identities over canonical vendor plus normalized firmware value/sentinel. They exclude model, hardware, router instance, and labels. A metadata observation references its effective profile when attribution is known; router behavior combines the profile with its router instance, so a shared firmware string never merges behavior across routers.

Reprocessing replaces these rows transactionally. After replacement, device, router, and behavior-subject summary timestamps are recomputed from surviving observations plus explicit registrations. The same refresh removes orphan summary-only identities that have neither registration nor surviving observation.

### Router snapshot metrics

Stores total, Wi-Fi, and wired client counts by router instance, active baseline epoch, export timestamp, and owning run. Rows carry one correlated-set learning inclusion flag and exclusion reason.

### Router event occurrences

`router_event_occurrences` stores canonical occurrence digests and privacy-reduced normalized router-event evidence. `run_event_occurrences` records every run that contained each digest plus its ingest-time novel/repeated classification. Canonical occurrences are deleted only after their last run link disappears.

`router_boot_sessions` stores canonical per-router boot sessions; run/session links and occurrence evidence provide provenance. A session is removed only when no surviving run or occurrence references it.

### Router behavior history

Uses the existing subject-behavior model with a router-instance-and-firmware-profile subject key. New router events are no longer learned through the global `__SYSTEM__` device identity. Existing legacy system subject history is associated with the migrated legacy NETGEAR instance and an `unknown-legacy-firmware` profile.

Device history remains keyed to portable device identity and baseline epoch.

### Schema v3 migration contract

Only schema v3 is supported for in-place upgrade. Older or structurally unexpected databases fail closed with recovery guidance instead of being stamped as current. New databases are created directly at the new schema version.

The v3 migration algorithm is:

1. Read `metadata.schema_version` and validate the required v3 tables, columns, indexes, and reference counts without changing journal mode, creating WAL/SHM files, or performing any other write.
2. After accepting valid v3, record relevant pragmas and reference counts; outside a transaction, disable foreign-key enforcement for the SQLite table-rebuild procedure.
3. Begin one `IMMEDIATE` migration transaction.
4. Create the new non-run-dependent router, firmware, and registration structures and insert one deterministic legacy NETGEAR router instance.
5. Rebuild `runs` with the same primary-key values, the legacy router foreign key, new nullable/default metadata, and `UNIQUE(router_instance_id, file_hash)` instead of global file-hash uniqueness. Dependent run IDs remain unchanged.
6. Only after the final `runs` table name exists, create the new run-owned observation, boot-session, occurrence, and link tables.
7. Backfill explicit device registrations from all legacy baseline-seed rows and baseline/config-sourced device rows. Use migration-only legacy source keys: exact epoch keys for baseline seeds, a deterministic sentinel for config-sourced catalog rows because v3 did not retain the source file digest, and a catalog-preservation source for otherwise-unrepresented real-MAC device rows. Do not invent historical file provenance. Backfill run-owned device observations from real-MAC legacy daily rows, representing distinct first/last extrema separately. Preserve legacy global `__SYSTEM__` device rows for audit but exclude them from new router-history queries.
8. Re-key legacy system subject-behavior rows and catalog entries to the legacy router and legacy firmware profile without changing their primary data or run references.
9. Recompute identity/subject summaries from registrations and observations, recreate indexes, and validate source/destination row counts, composite uniqueness, non-null router assignments, every final child foreign-key declaration, `sqlite_master` references, and `PRAGMA foreign_key_check`.
10. Write the new schema version last, commit, restore and enable `PRAGMA foreign_keys = ON`, apply/retain WAL only for the accepted database, then run the integrity checks again.

Any failure rolls back the transaction and restores the connection pragma before returning an error. Running the migration again after success is a no-op. Every normal database connection enables foreign-key enforcement; the temporary disabled state exists only around the documented table rebuild.

## Analysis and Severity

### Snapshot client counts

- Use the existing numeric-profile and tolerance machinery over the seven most recent eligible snapshots, not seven calendar days.
- Require at least three earlier eligible snapshots before emitting a deviation finding.
- Store and display earlier observations without scoring them.
- Apply the existing learned range (`mean +/- 2 * max(stddev, floor)`) and tolerance classification, then enforce a hard post-policy LOW ceiling for count-only evidence.
- Never infer a new device from counts alone.
- Treat total, Wi-Fi, and wired as one correlated observation and produce at most one count finding/risk contribution per snapshot.
- Retain an impossible correlated count set for report diagnostics but exclude all three metrics from learning.

### Device discovery

- A client already present in the portable device registry does not produce a new-device finding.
- A previously unseen stable client identity discovered through the new adapter-independent discovery path is MEDIUM before policy.
- Explicit policy overrides may suppress, cap, or escalate that MEDIUM default.
- A new identity accompanied by a rejected or blocked event defaults to one consolidated HIGH finding before policy rather than separate discovery and rejection score contributions.
- Explicit repeated hostile activity may reach CRITICAL through policy.
- Known-device presence details remain informational unless another established behavioral rule is violated.
- Existing NETGEAR `unknown_device` and `blocked_device_activity` paths retain their current CRITICAL defaults and current policy behavior; this feature does not reinterpret their findings.

### Router and security behavior

The first three eligible observations establish a router-specific, firmware-specific warm-up inventory. Learned router behavior compares only with the same router instance, firmware profile, and active baseline epoch.

- A later new router event type is MEDIUM by default after the three-observation warm-up.
- Firmware change between two known, distinct normalized profiles is a LOW router-instance observation and selects a new firmware behavior profile with its own warm-up. Missing/unknown firmware does not overwrite last-known transition state or emit a change; when a prior known profile exists it remains the effective profile for attribution. It does not reset snapshot-count history, portable device identity, or device behavior.
- An unexpected transition from the learned running/enabled state to stopped/disabled defaults to MEDIUM before policy.
- Firewall, access-control, rejection, and repeated security failures may escalate through explicit canonical mappings and policy.
- Vendor syslog severity informs, but does not solely determine, analyzer severity.
- Expected startup service churn is learned within boot context instead of generating recurring alerts.
- Direct high-confidence security evidence such as an explicit client rejection or firewall failure remains eligible during firmware warm-up; only history-dependent router-behavior conclusions wait for the new profile.

Rolling-buffer occurrences use chronological prior metadata to determine effective firmware. Records provably earlier than the prior known firmware observation remain with the earlier profile. Evidence in an unresolved upgrade interval remains reportable and deduplicable but is excluded from firmware-scoped behavior learning until an explicit upgrade/post-upgrade boot marker or equivalent adapter evidence resolves it.

NETGEAR system events retain their current legacy finding kinds, history/warm-up semantics, score grouping, and report placement. Router-scoped storage may change internally, but it does not route legacy NETGEAR SYSTEM_ACTOR analysis through the new three-observation TP-Link/router warm-up path.

The previously established metric-learning rule remains: stable metric-only anomalies may enter future numeric baselines, while partial, blocked-device, unknown/security, timing, and behavior anomalies remain quarantined as appropriate.

## Reporting

Text, Markdown, HTML, and JSON reports add:

- router label, vendor, model, firmware, format, and export timestamp;
- parser capabilities and unavailable checks;
- current total, Wi-Fi, and wired counts with learned ranges and changes when available;
- novel and repeated body-event counts;
- system and security state changes;
- newly identified devices;
- clock-trust and boot-session warnings;
- parser coverage and ignored/malformed counts.

A snapshot with no novel body events is still a valid observation. The report should say that the body repeated prior events while presenting the new header metrics.

Reports must distinguish `unavailable` from `zero` and `normal`. For example, lack of client DHCP capability is not reported as zero DHCP activity.

## CLI Behavior

- Default format selection is automatic.
- An explicit format option is available for diagnosis and ambiguity.
- `--router-label` changes presentation only; `--router-instance` supplies stable identity when derivation is unavailable.
- Existing management, report, policy, baseline, database, and reprocessing commands retain their behavior.
- Help and README wording change from NETGEAR-only to supported router formats while documenting format-specific capabilities.

The router security-config importer remains NETGEAR-specific until a real TP-Link client/config export defines another contract.

Management-only invocations retain their existing ordering and behavior. When a management option is combined with a logfile, input loading, format validation, and persistent router-identity validation occur before any management mutation. A combined invocation with ambiguous/mismatched format or no persistent identity fails without applying the management change; this is the safety-first interpretation of the no-mutation-before-validation rule.

## Error Handling and Transactionality

- Unknown or ambiguous formats fail before database mutation and show detection evidence.
- A recognized header with incomplete optional metadata continues with valid sections and warnings.
- Invalid or inconsistent correlated snapshot counts are retained for report diagnostics but all three metrics are omitted from learning.
- Parsed events without stable router identity can be reported but cannot alter persistent router history without an explicit override.
- A fully repeated body is a successful import, not an error.
- Byte-identical NETGEAR input preserves current behavior: produce a fresh report under current policy/history but add no duplicate run or learning rows. For rolling-snapshot adapters, a byte-identical scoped input produces a deduplicated report without rescoring body or identical header evidence.
- Run links, device/router observations, firmware evidence, snapshot metrics, occurrences, boot sessions, behavior rows, and derived summary refreshes commit or roll back atomically.
- Schema migration follows the explicit v3 contract above and preserves all v3 device, run, finding, incident, and baseline records and identifiers.

## Testing Strategy

All fixtures use unmistakably synthetic addresses, names, timestamps, firmware strings, and device data.

### Adapter and normalization tests

- NETGEAR detection and parsing regression coverage, including unchanged findings, severities, scores, report JSON, and CLI behavior.
- TP-Link detection confidence and explicit format selection.
- Header metadata and total/Wi-Fi/wired parsing.
- Impossible Wi-Fi-greater-than-total input retains diagnostics but makes the entire correlated metric set ineligible.
- Reverse-order normalization.
- WAN DHCP classification distinct from LAN-client DHCP.
- Canonical internet-transition mapping with boot context.
- Unknown code preservation.
- Router-owned MAC exclusion.
- Future client-identity extraction behavior.
- Router-local timestamp semantics without an invented UTC offset.
- Persisted occurrence evidence contains no complete raw source line or unstructured address/name tokens.

### Clock and deduplication tests

- Firmware-date pre-synchronization detection.
- Exclusion of untrusted dates from timing and run-span calculations.
- Stable boot-session identity across repeated snapshots.
- Distinct identity for a genuine later reboot.
- A boot with already-correct time still receives boot context.
- A truncated rolling snapshot reuses a persisted session through overlap without recomputing a new anchor.
- Backward and multiple clock corrections follow independent per-boot/clock-epoch trust classification.
- Two boots in one rolling buffer retain independent trusted synchronized segments; a non-boot backward local-time adjustment is clock-ambiguous rather than pre-synchronization.
- Repeated body plus changed header metrics.
- Mixed overlapping and novel body events.
- Safe behavior when no trusted boot anchor exists.
- Fully repeated security evidence cannot create a new finding or score contribution.
- Reprocessing one run cannot invalidate an occurrence still referenced by another run.
- Reprocessing the first learning owner promotes or otherwise preserves one learned contribution through a surviving eligible repeated link.
- Exact semantic tuples collapse while distinct process identifiers remain distinct.

### Persistence and migration tests

- Router-instance creation and lookup.
- Separation of two routers with the same model but different synthetic LAN MACs.
- Two router instances can ingest identical bytes because whole-file uniqueness is instance-scoped.
- Model-string and router-label changes do not split identity for one canonical LAN MAC.
- Invalid identity MACs require explicit stable override for persistence.
- Firmware updates without instance replacement.
- Firmware-specific router behavior profiles without resetting counts or device history.
- Clean v3-to-next-version legacy NETGEAR migration with preserved run IDs and references.
- Legacy baseline/config device rows become explicit registrations and survive run replacement.
- Migration executed twice is a no-op.
- Injected mid-migration failure rolls back all logical state and leaves schema version unchanged.
- Foreign-key and row-count invariants pass after migration.
- Every run-owned child declaration references the final `runs` table; unsupported schemas fail without journal-mode/WAL mutation.
- Portable device history retained across router instances.
- Router behavior isolated by instance and epoch.
- Snapshot metric inclusion, exclusion, and uniqueness.
- Reprocessing the sole observing run removes stale device, router, subject, firmware, metric, and first/last-seen evidence while preserving explicit registrations.
- A replacement does not treat a device known only from the removed version of that same run as previously known.
- First/last seen uses chronological minimum/maximum when older input is ingested later.

### Analysis and reporting tests

- No count anomaly before three historical snapshots.
- Count-only anomaly capped at LOW.
- Count-only LOW remains a hard ceiling after policy evaluation.
- Correlated client-count scoring.
- Known device does not produce a new-device finding.
- New stable client defaults to MEDIUM and explicit policy may suppress, cap, or escalate it.
- Rejected or blocked new client defaults to one correlated HIGH finding.
- Capability-gated device, total-event-volume, reset, and cluster checks.
- Loss of capability reports unavailable and never persists a synthetic zero.
- Cross-vendor total-event history stays disabled without explicit comparable-coverage capability.
- Warm-up behavior for a new router instance.
- Firmware change starts a new router behavior profile while direct security evidence remains active.
- Unexpected security-service state change.
- Reports show unavailable checks and novel/repeated counts.
- JSON schema additions match text, Markdown, and HTML output.

### Validation

Run the complete project test suite and the repository uv-header drift guard because the standalone launcher changes. After tests pass, exercise help/version and a safe end-to-end analysis against a disposable database using a synthetic TP-Link fixture. No downloaded private log is copied into the repository or committed.

## Acceptance Criteria

1. The supplied local TP-Link snapshot parses without modifying or committing it.
2. Successive snapshots with identical bodies store the body occurrences once while retaining each unique export-time client-count observation.
3. The startup clock jump cannot create a false historical observation day or continuous multi-month run.
4. WAN DHCP events never change per-device DHCP baselines.
5. Router system and security behavior is isolated by physical router instance.
6. Existing known devices remain known after router replacement.
7. Anonymous count movement is at most LOW; a newly identified client defaults to MEDIUM before explicit policy overrides.
8. Reports disclose unavailable device checks.
9. Existing NETGEAR parsing, learning, incident analysis, reports, and CLI behavior remain covered and passing.
10. The complete repository-required test suite passes with only synthetic committed artifacts.
11. Reprocessing cannot leave run-derived identity, firmware, subject, metric, occurrence, or timestamp evidence behind.
12. Semantic occurrence classification precedes findings and scoring, so repeated body evidence cannot re-alert.
13. Schema v3 upgrades atomically with stable IDs and fails closed for unsupported or malformed schemas.
14. Complete raw source lines are not retained in SQLite by default.
