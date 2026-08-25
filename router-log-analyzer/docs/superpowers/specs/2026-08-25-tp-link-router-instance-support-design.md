# TP-Link Router-Instance Support Design

**Date:** 2026-08-25

**Status:** Approved design

**Scope:** Add TP-Link Archer system-log ingestion, router-instance-scoped system learning, portable device identity, snapshot client-count learning, and semantic deduplication while preserving existing NETGEAR behavior.

## Context

The analyzer currently expects NETGEAR timestamps and square-bracketed event labels. A TP-Link Archer system-log export has a different structure:

- A header identifies the model, export time, firmware, router interfaces, and connected-client counts.
- Body records use ISO-like timestamps, component and process identifiers, syslog severity, numeric vendor event codes, and messages.
- Records are newest first.
- Startup records can begin with an untrusted clock value related to the firmware build date and then jump to the correct time after synchronization.
- Nightly exports are snapshots of a persistent event buffer. Successive files can repeat the entire body while changing only the export timestamp and connected-client counters.
- The observed format reports WAN DHCP startup negotiation, not LAN-client DHCP renewals.
- The header reports aggregate client counts but does not identify those clients.

The current parser rejects these body records and produces no normalized events. Whole-file hashing also cannot prevent repeated body events from being learned again when changing header values make each nightly export bytewise unique.

## Goals

1. Parse the observed TP-Link Archer system-log format without changing existing NETGEAR results.
2. Tie router/system health and security history to a stable physical router instance.
3. Keep device identity portable across router replacements.
4. Learn total, Wi-Fi, and wired connected-client counts as weak router-instance metrics.
5. Surface a newly identified client at MEDIUM or higher while avoiding strong conclusions from anonymous count changes.
6. Prevent repeated snapshot body events from contaminating learned history.
7. Preserve the standalone, single-launcher installation model.
8. State unavailable checks explicitly instead of treating missing telemetry as normal behavior.

## Non-Goals

- Inferring individual client identities from aggregate counts.
- Treating WAN DHCP negotiation as LAN-client DHCP activity.
- Adding a generic external profile language before a third real format requires it.
- Importing a TP-Link client or access-control configuration without a representative export.
- Copying private router logs, addresses, device names, or baseline contents into this public repository.
- Splitting runtime code into required sidecar modules that would break copy-based installation of the launcher.

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

Adapters declare observed capabilities rather than allowing the analyzer to infer absence from missing events. Capabilities cover at least:

- client identities;
- client DHCP activity;
- client allow/reject activity;
- router/system events;
- WAN transition events;
- snapshot client counts;
- trustworthy event timestamps.

Analysis routines run only when their required capability is present. A TP-Link snapshot without client identities cannot generate missing-device, per-device DHCP, device-timing, or cluster-visibility conclusions.

### Router identity

For the observed TP-Link format, the stable instance key is a digest of:

1. normalized vendor;
2. normalized model;
3. normalized LAN interface MAC address.

The LAN MAC and WAN MAC values are registered as router-owned interfaces. They are excluded from client discovery even when they appear in WAN DHCP messages.

Firmware version is mutable instance metadata. A firmware update does not create a new router instance. Reports use a friendly label rather than exposing the internal digest. The default label combines vendor and model with a non-sensitive local disambiguator; a user-supplied label may replace it.

If an adapter can parse events but cannot derive stable identity, it may render a non-persistent report. Persistent learning requires an explicit router-instance override so unrelated hardware is never silently merged.

### Portable device identity

The existing device registry remains network-wide. MAC address, friendly name, allow/block status, connection type, first/last seen, and cluster membership survive router replacement.

Existing learned device behavior is retained. It is evaluated only when the active adapter declares semantically compatible device-level capabilities. Missing telemetry never contributes a zero observation.

Router-owned interfaces never enter the portable device registry as clients.

## TP-Link Parsing and Normalization

### Header

The adapter parses:

- model;
- export timestamp;
- hardware and firmware versions;
- LAN and WAN interface metadata;
- total connected clients;
- Wi-Fi connected clients.

Wired clients are derived as `total_clients - wifi_clients`. If Wi-Fi exceeds total or a count is invalid, the adapter records a warning and omits the inconsistent derived metric rather than coercing it.

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
- original source line for local reporting and audit.

Records are normalized into chronological order after parsing.

WAN DHCP messages are router-scoped events such as WAN discover, offer, request, acknowledgement, and release. They must never normalize to the client-level `DHCP_IP` key.

Recognized internet-up and internet-down signals may map to the existing canonical internet transition vocabulary. Boot context remains attached so startup recovery is not automatically treated as an independent outage.

Unknown vendor codes remain reviewable under deterministic keys derived from component, code, and normalized action. Numeric codes and original messages are retained so later mappings do not require reparsing private source files.

### Client identities in future records

The current header contains counts only. If a body record supplies a MAC address or another adapter-approved stable client identity:

- router-owned interface identities remain router-scoped;
- a registered device is treated as known and its last-seen information is updated;
- an unregistered client becomes a new-device finding;
- ambiguous identifiers stay attached to the router event and do not create a device record.

## Clock Trust and Boot Sessions

The adapter preserves raw timestamps and separately classifies their trust.

When a startup cluster uses the firmware build date and is followed by a large forward jump to a timestamp near the export date, the earlier cluster is classified as pre-synchronization. Those records remain visible, but they:

- do not create artificial historical observation dates;
- do not participate in weekday or time-of-day learning;
- do not expand the observed run duration;
- may contribute event presence and startup-sequence evidence within their boot session.

The boot-session key is derived from the router instance, the first trusted timestamp following the clock jump, and a normalized startup-sequence signature. This makes the key stable across repeated exports of the same boot while distinguishing a later reboot with a new trusted anchor.

Trusted events use their original timestamp in occurrence identity. Untrusted events additionally use the derived boot-session key. If no trusted session anchor can be resolved, untrusted events are shown but excluded from learned occurrence history, and the report explains that reliable cross-snapshot deduplication was unavailable for that segment.

TP-Link snapshot imports do not use the current duration-based partial-run rule. Snapshot metrics are point observations at export time, and novel trusted body events are occurrences rather than evidence of continuous coverage.

## Cross-Snapshot Deduplication

Whole-file hashes continue to identify byte-for-byte duplicate inputs. A second semantic layer handles snapshots whose headers change while their event bodies overlap.

Each normalized body occurrence receives a digest over:

- router instance;
- trusted raw timestamp or untrusted boot-session key plus raw timestamp;
- component;
- process identifier;
- vendor code;
- syslog severity;
- normalized message;
- resolved actor scope and identity.

The process identifier remains in the occurrence digest because two otherwise identical lines from distinct processes can represent separate emitted events. It does not participate in the learned event key because process identifiers are volatile behavior metadata.

An occurrence already owned by a prior run for the same router is counted as repeated and is not inserted into daily behavior history again. New snapshot metrics are still stored at their export timestamp. Reports show novel and repeated event counts separately.

Occurrence ownership participates in the same transaction as run persistence. `--reprocess` removes occurrence records owned by the replaced run before rebuilding it, so a failed replacement can roll back without losing the prior state.

## Persistence Model

The next schema version adds or extends these concepts:

### `router_instances`

Stores the stable instance key, vendor, model, friendly label, identity metadata, first seen, and last seen.

### Router firmware observations

Stores firmware and hardware metadata per router instance and observation time so changes can be reported without changing identity.

### `runs`

Adds router instance, format, export timestamp, capabilities, body digest, and novel/repeated event counts. Legacy runs are assigned to one legacy NETGEAR instance because the old schema cannot recover distinctions between any historical NETGEAR devices that were already combined.

### Router snapshot metrics

Stores total, Wi-Fi, and wired client counts by router instance, active baseline epoch, and export timestamp. Rows carry learning inclusion and exclusion reasons.

### Router event occurrences

Stores occurrence digests and normalized router-event evidence for cross-snapshot deduplication and audit.

### Router behavior history

Uses the existing subject-behavior model with a router-instance subject key. New router events are no longer learned through the global `__SYSTEM__` device identity. Existing legacy system subject history is associated with the migrated legacy NETGEAR instance.

Device history remains keyed to portable device identity and baseline epoch.

## Analysis and Severity

### Snapshot client counts

- Use the frequent seven-day rolling window.
- Require at least three earlier eligible snapshots before emitting a deviation finding.
- Store and display earlier observations without scoring them.
- Cap count-only deviation findings at LOW.
- Never infer a new device from counts alone.
- Treat total, Wi-Fi, and wired as correlated metrics for scoring so one snapshot shift does not triple-count risk.

### Device discovery

- A client already present in the portable device registry does not produce a new-device finding.
- A previously unseen stable client identity is MEDIUM by default.
- A new identity accompanied by a rejected or blocked event is HIGH.
- Explicit repeated hostile activity may reach CRITICAL through policy.
- Known-device presence details remain informational unless another established behavioral rule is violated.

### Router and security behavior

The first eligible observations establish a router-specific warm-up inventory. Later behavior compares only with the same router instance and active baseline epoch.

- A later new router event type is MEDIUM by default after sufficient router history exists.
- Firmware change is reported as a router-instance observation and begins a learning grace boundary for behavior whose semantics may have changed.
- An unexpected transition from the learned running/enabled state to stopped/disabled is at least MEDIUM.
- Firewall, access-control, rejection, and repeated security failures may escalate through explicit canonical mappings and policy.
- Vendor syslog severity informs, but does not solely determine, analyzer severity.
- Expected startup service churn is learned within boot context instead of generating recurring alerts.

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
- An optional router label or explicit instance override resolves inputs without a derivable stable identity.
- Existing management, report, policy, baseline, database, and reprocessing commands retain their behavior.
- Help and README wording change from NETGEAR-only to supported router formats while documenting format-specific capabilities.

The router security-config importer remains NETGEAR-specific until a real TP-Link client/config export defines another contract.

## Error Handling and Transactionality

- Unknown or ambiguous formats fail before database mutation and show detection evidence.
- A recognized header with incomplete optional metadata continues with valid sections and warnings.
- Invalid or inconsistent snapshot counts are omitted from learning rather than coerced.
- Parsed events without stable router identity can be reported but cannot alter persistent router history without an explicit override.
- A fully repeated body is a successful import, not an error.
- Run, metric, occurrence, behavior, and reprocess mutations commit or roll back atomically.
- Schema migration is idempotent and preserves all prior device, run, finding, incident, and baseline records.

## Testing Strategy

All fixtures use unmistakably synthetic addresses, names, timestamps, firmware strings, and device data.

### Adapter and normalization tests

- NETGEAR detection and parsing regression coverage.
- TP-Link detection confidence and explicit format selection.
- Header metadata and total/Wi-Fi/wired parsing.
- Reverse-order normalization.
- WAN DHCP classification distinct from LAN-client DHCP.
- Canonical internet-transition mapping with boot context.
- Unknown code preservation.
- Router-owned MAC exclusion.
- Future client-identity extraction behavior.

### Clock and deduplication tests

- Firmware-date pre-synchronization detection.
- Exclusion of untrusted dates from timing and run-span calculations.
- Stable boot-session identity across repeated snapshots.
- Distinct identity for a genuine later reboot.
- Repeated body plus changed header metrics.
- Mixed overlapping and novel body events.
- Safe behavior when no trusted boot anchor exists.
- Transactional reprocessing of occurrence ownership.

### Persistence and migration tests

- Router-instance creation and lookup.
- Separation of two routers with the same model but different synthetic LAN MACs.
- Firmware updates without instance replacement.
- Legacy NETGEAR instance migration.
- Portable device history retained across router instances.
- Router behavior isolated by instance and epoch.
- Snapshot metric inclusion, exclusion, and uniqueness.

### Analysis and reporting tests

- No count anomaly before three historical snapshots.
- Count-only anomaly capped at LOW.
- Correlated client-count scoring.
- Known device does not produce a new-device finding.
- New stable client defaults to MEDIUM.
- Rejected or blocked new client escalates to HIGH.
- Capability-gated device and cluster checks.
- Warm-up behavior for a new router instance.
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
7. Anonymous count movement is at most LOW; a newly identified client is at least MEDIUM.
8. Reports disclose unavailable device checks.
9. Existing NETGEAR parsing, learning, incident analysis, reports, and CLI behavior remain covered and passing.
10. The complete repository-required test suite passes with only synthetic committed artifacts.
