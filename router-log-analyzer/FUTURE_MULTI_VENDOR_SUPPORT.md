# Future Multi-Vendor Support

This document captures a practical shape for evolving `router_log_analyze.py` from a NETGEAR-specific ingestion tool into a router-agnostic analyzer without rewriting the learning and anomaly engine.

## Current State

The analyzer has two distinct layers:

1. Ingestion and normalization
   - Reads PDF or text exports
   - Parses router log lines
   - Imports router access-control config
   - Converts raw vendor-specific data into normalized `Event` objects and normalized device/config records

2. Analysis
   - Aggregates normalized events
   - Learns device and event behavior over time
   - Detects anomalies
   - Persists learned history in SQLite
   - Renders reports

The second layer is already mostly reusable. The first layer is where most of the current NETGEAR coupling lives.

## Where The Current NETGEAR Coupling Lives

The current implementation is NETGEAR-shaped in these areas:

- CLI wording refers to NETGEAR logs and exports.
- Log timestamp parsing expects the current NETGEAR timestamp format.
- Event label extraction assumes square-bracketed labels in the raw log line.
- Event normalization maps NETGEAR labels into internal event keys such as `DHCP_IP` and `WLAN_ACCESS_ALLOWED`.
- Event-family classification is based on those normalized keys.
- IP extraction includes a NETGEAR-specific DHCP pattern.
- Config import expects the current NETGEAR markdown export layout and column names.

That means the analyzer is not NETGEAR-only in principle, but it is NETGEAR-only at the parser boundary.

## Recommended Direction

Do not rewrite the anomaly engine.

Instead, introduce a vendor adapter boundary and keep a stable internal vocabulary. The adapter layer should translate raw vendor-specific input into the same normalized events and config structures the analyzer already uses.

The key design rule is:

- Vendor-specific labels vary.
- Internal canonical event keys should remain stable.

Examples:

- A Linksys DHCP lease event should still normalize to `DHCP_IP`.
- A Linksys "Wi-Fi client allowed" event should still normalize to `WLAN_ACCESS_ALLOWED`.
- A vendor-specific deny/block message should normalize to `WLAN_ACCESS_REJECTED`.

If that contract holds, most of the learning database and anomaly logic can stay intact.

## Recommended Architecture

Use a hybrid adapter model.

### 1. Adapter Boundary

Introduce a `RouterFormat` abstraction with responsibilities such as:

- Parse raw log text into normalized `Event` objects
- Parse vendor config exports into normalized device/config records
- Detect whether a given input likely matches the format

This can be done with Python classes, a small protocol, or simple functions grouped per format.

### 2. Stable Canonical Event Vocabulary

Keep internal event keys and families stable across vendors.

Examples of canonical event keys:

- `DHCP_IP`
- `WLAN_ACCESS_ALLOWED`
- `WLAN_ACCESS_REJECTED`
- `INTERNET_DISCONNECTED`
- `INTERNET_CONNECTED`
- `EMAIL_SENT`
- `LOG_CLEARED`

Examples of canonical event families:

- `DHCP`
- `WLAN_ALLOWED`
- `WLAN_REJECTED`
- `OTHER`

This is the compatibility layer that protects the rest of the system from vendor churn.

### 3. Hybrid Parsing Strategy

Support two kinds of adapters:

- Declarative profiles for simple formats
  - Timestamp regex and timestamp format
  - Noise-line patterns
  - Label extraction rules
  - Event-key mapping
  - Event-family mapping
  - IP extraction regex

- Python adapters for formats that need custom parsing
  - Multiline records
  - Irregular PDF extraction cleanup
  - Vendor-specific edge cases

This avoids forcing every future format into a purely regex-driven design.

## Phased Implementation Plan

### Phase 1. Isolate NETGEAR Parsing Behind An Adapter

Goal:

- No behavior change
- Move current NETGEAR-specific parsing into a dedicated adapter layer

Work:

- Extract current log parsing rules into a `netgear` adapter
- Extract current config-import parsing into a `netgear` adapter
- Keep the same normalized `Event` output
- Keep the same SQLite schema
- Keep the same anomaly logic

Result:

- The current system still only supports NETGEAR, but the boundary exists

### Phase 2. Add Format Selection

Goal:

- Make the input format explicit and future-ready

Work:

- Add `--format netgear|auto|...`
- Default to `netgear` or `auto`
- Update help text and docs to say "router log" rather than "NETGEAR log" where appropriate

For `auto`, start simple:

- Try known format detectors in order
- Pick the first one that produces a plausible parse

Result:

- The CLI is ready for multiple router vendors without changing analysis behavior

### Phase 3. Add Declarative Profile Support

Goal:

- Reduce code required for closely related vendor formats

Work:

- Define a profile schema for timestamp parsing, label extraction, noise filtering, event mapping, and IP extraction
- Let an adapter load that profile and perform generic line-by-line parsing

Result:

- New vendor support may be mostly configuration when the export format is simple

### Phase 4. Add A Second Vendor

Goal:

- Validate the architecture against a real second router format

Work:

- Collect real sample exports
- Add a `linksys` adapter or profile
- Map vendor-specific raw events into the canonical event vocabulary
- Add sample fixtures and regression tests

Result:

- Confidence that the design generalizes beyond NETGEAR

### Phase 5. Generalize Config Import

Goal:

- Avoid the current assumption that all router access-control exports are the same markdown table

Work:

- Move config import behind the adapter boundary
- Normalize all imported device/config data into the existing internal structure

Result:

- Router replacement does not imply rewriting allow/block import logic

## What Should Not Change

These parts should remain stable unless a real vendor requirement forces a change:

- SQLite schema for learned history
- Normalized `Event` structure
- Most anomaly logic
- Risk scoring
- Reporting formats

The entire point is to isolate parser volatility from analysis stability.

## Known Areas That Depend On Canonical Events

Some analysis behavior is intentionally keyed to canonical event names and families. In particular:

- DHCP counting
- DHCP burst suppression
- Cluster analysis, which currently uses DHCP activity as the cluster signal
- Internet-reset correlation, which uses WAN transitions plus synchronized DHCP/WLAN recovery activity

That is acceptable as long as new router formats map equivalent raw events into the same canonical event vocabulary.

## Testing Expectations For A Future Refactor

Any future parser-generalization work should include:

- Fixture-based tests for each supported vendor format
- Tests that different vendor exports normalize to equivalent canonical events when the behavior is equivalent
- Regression tests that existing NETGEAR parsing remains stable
- End-to-end tests that prove anomaly outputs remain unchanged for existing NETGEAR samples

The architecture should be considered successful only if the parser layer changes without destabilizing the learned behavior model.

## Suggested Initial File Shape

One possible shape:

- `router_log_analyze.py`
  - CLI, orchestration, analysis, persistence, reports
- `formats/netgear.py`
  - NETGEAR log parser
  - NETGEAR config parser
- `formats/linksys.py`
  - Linksys parser when needed
- `formats/profile_runtime.py`
  - Generic profile-driven parser helper
- `formats/profiles/*.json`
  - Declarative profiles for simple formats

This is only a reference shape, not a required design.

## Practical Recommendation

When this work becomes necessary, start with Phase 1 only.

Do not jump straight to a full multi-vendor framework before there is a second real router format in hand. The first step should be isolating the current NETGEAR parser cleanly. Once real Linksys or other sample exports are available, validate the architecture against those samples before adding more abstraction.
