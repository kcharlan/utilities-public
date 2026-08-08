# Model Sentinel Design

Status: implemented. This document describes the current architecture and its
durable constraints. See the project [README](../README.md) for operator
commands and setup.

## Purpose and Boundaries

Model Sentinel is a local CLI that tracks changes in the authenticated model
lists exposed by LLM providers. It:

- fetches each selected provider's model-list endpoint
- compares the response with an explicitly saved baseline
- reports added and removed models and field-level metadata changes
- optionally saves the new snapshot and its change history in SQLite
- supports historical and cross-provider change queries

The authenticated model-list response is the source of truth for availability.
Presence means "advertised to this credential"; Model Sentinel does not invoke
each model to prove that inference succeeds.

The current design deliberately does not:

- merge equivalent models across providers
- make provider inference calls
- provide a web UI or long-running service
- store raw provider responses outside the normalized snapshot
- embed secrets in project or runtime configuration

## Runtime Layout

The application is Python 3.11+ and uses only the standard library at runtime.
The repository launcher imports the package directly:

```text
model-sentinel
  -> model_sentinel.cli.main()
```

`install_standalone.sh` packages the same code as an executable zipapp. Mutable
state is kept in the runtime home selected by `MODEL_SENTINEL_HOME`, whose
default `~/.model_sentinel/` is outside the repository:

```text
~/.model_sentinel/
  providers.env
  settings.env
  launchd.env
  model_sentinel.db
  logs/
  debug/
  reports/
```

The `debug/` directory is created for runtime diagnostics, but the current CLI
does not persist raw response payloads there.

## Identity

Provider identity is first-class. A tracked model is identified by:

```text
(provider_id, provider_model_id)
```

`provider_id` comes from the `<ID>` segment of
`MODEL_SENTINEL_PROVIDER_<ID>_*`; the configured label is display text only.
The same upstream model on two providers remains two independent records. A
provider-local ID rename is reported as one removal and one addition.

Duplicate labels are safe because reports group on provider ID and
disambiguate collisions as `Label (provider_id)`. `healthcheck` reports exact
label collisions as a non-fatal warning.

## Configuration

`providers.env` contains one complete set of keys per provider:

- enablement, display label, and provider kind
- base URL and model-list path
- the name of the credential environment variable
- positive price multiplier and divisor

Credentials are read from the process environment named by the provider
configuration. They never belong in `providers.env`, `settings.env`, docs, or
the SQLite database. A scan validates all selected credentials before starting
any fetch.

`settings.env` controls:

- log size and retained generations
- managed report directory and retention
- default report detail mode, show/squelch patterns, and unclassified limit
- notification enablement, event policy, open target, sound, and optional
  `terminal-notifier` path

`setup.sh` seeds both files without overwriting existing runtime configuration.
Relative report directories are resolved under the runtime home.

## Provider Profiles

`ProviderConfig.kind` selects an immutable `ProviderProfile`. A profile owns
provider-specific interpretation:

- accepted model-list envelope keys
- normalized-field candidate paths
- field labels and known boolean paths
- price/count classification predicates
- conditional-pricing identity fields
- preferred presentation order for Pricing field paths
- default report show/squelch patterns

Fetch, normalization, change classification, and human reporting all receive
the resolved profile explicitly. An unregistered kind uses
`GENERIC_PROFILE`; `healthcheck` warns that labels and price detection are then
best-effort.

Only OpenRouter currently has a registered provider profile. Abacus.AI remains
on the generic profile because its public payload mixes per-token rates with
media prices in several units; a single provider-wide multiplier cannot
normalize those fields correctly. The provider observations and deferred work
are recorded in [provider_schema_notes.md](./provider_schema_notes.md).

Profile behavior is presentational and interpretive. Stored
`field_changes.field_name` values remain the raw dotted paths, JSON reports do
not replace them with labels, and profile resolution never rewrites history.

## Fetch and Normalization

`providers.fetch_raw_models()` sends a bearer-authenticated `GET` request with
a 30-second timeout. A top-level list is accepted directly. Object payloads are
searched only through the envelope keys allowed by the selected profile, and
every model entry must be an object.

`normalize.normalize_models()` builds a stable common record while preserving
the canonicalized complete provider object in `metadata_json`. The normalized
columns are:

- identity and display fields
- description, family, and provider timestamp
- context and output limits
- input, output, cache-read, and cache-write prices
- reasoning, tool, modality, structured-output, deprecation, and status flags
- canonical provider metadata JSON

Common normalized price columns use:

```text
normalized_price = raw_price * price_multiplier / price_divisor
```

Human metadata-diff reports classify and present raw provider metadata using
the same profile conversion factors. This rule is valid only where the
configured factors represent the field's real unit; the current Abacus
limitation is why that provider is not registered.

## Snapshots and Baselines

Every successful fetch produces an in-memory normalized snapshot and records a
scrape attempt. Persistence of model rows and field changes is controlled by
`--save`.

Compare-only behavior:

- resolve a saved baseline independently for each provider
- if none matches, report an actionable `baseline_missing` result and skip the
  provider fetch
- otherwise fetch, normalize, compare, and report without saving a baseline

Save behavior:

- fetch and compare when a baseline exists
- treat all current models as additions when creating the first baseline
- save normalized model rows
- record additions, removals, and field changes

Supported baseline selectors are:

- `previous`: latest saved successful snapshot for the provider
- `previous-day`: latest saved successful snapshot before today's local date
- `--baseline-date YYYY-MM-DD`: the first saved successful snapshot on that
  local date

In compare-only mode, a missing exact date reports the nearest saved timestamp
before and after the requested date when available.

## Diff Semantics

The model-ID sets determine additions and removals. For IDs present in both
snapshots, Model Sentinel recursively compares the canonical provider metadata
objects:

- dictionary keys are traversed in sorted order
- a missing key is represented as `null` on the absent side
- non-dictionary values, including lists, are compared as values
- changed leaves retain their raw dotted paths

The full provider metadata, rather than only the common normalized columns, is
therefore the source for field-level change detection.

One-sided nested objects and object lists are flattened for human presentation.
Conditional pricing override lists receive identity-aware comparison when
their profile can match tiers safely. This expansion is presentation-only;
stored changes and JSON output preserve the source values.

## SQLite Model

SQLite is the system of record at `~/.model_sentinel/model_sentinel.db` (or the
configured runtime home). The schema is created idempotently and has four
tables:

### `providers`

One current configuration row per `provider_id`: label, kind, endpoint fields,
credential environment-variable name, enabled flag, and update timestamp.

### `scrapes`

One row per fetch attempt: provider, UTC start/completion timestamps, status,
baseline mode and scrape ID, whether the snapshot was saved, model count, and
error text.

### `snapshot_models`

One normalized model per saved scrape. The composite key is
`(scrape_id, provider_model_id)`. It contains the common normalized columns and
the canonical `metadata_json`.

### `field_changes`

One row for a model addition/removal or one changed field: provider and model
identity, source/target scrape IDs, kind, raw field path, JSON old/new values,
and detection timestamp.

Change-log queries exclude initial-baseline records whose `from_scrape_id` is
null. Timestamps are stored in UTC and converted to local time for display and
date filtering.

## Reporting

Public report entry points cover scans, history, known-model lists,
cross-provider changes, provider configuration, and healthcheck results.

Format support is intentionally command-specific:

| Command | Text | JSON | Markdown | Internal HTML |
|---|---:|---:|---:|---:|
| `scan` | yes | yes | yes | yes |
| `history` / model list | yes | yes | yes | no |
| `changes` | yes | yes | no | yes |
| `providers` | yes | yes | yes | no |
| `healthcheck` | yes | yes | yes | no |

HTML is an internally generated companion format rather than a CLI `--format`
choice. Scan companions are generated only when changes exist and the scan has
a managed report path (normally because notification policy fired).
`changes`, when records exist and no explicit output path was given, saves its
primary output in a timestamped `.txt` artifact plus an HTML report in the
managed report directory. With the default format, that primary artifact is
text; `--format json` changes its contents but not the managed `.txt` suffix.

### Detail policy

Human field-level reports use `fnmatch` patterns over raw dotted paths:

- shown fields render in default mode
- squelched fields are summarized in default mode
- unclassified fields render up to a provider-level cap
- `--detail all` renders every non-no-op human detail
- `--detail squelched` renders only squelch-matched details

The policy affects presentation only. JSON remains full fidelity, including
records human reports classify as no-ops.

Default scan reports may consolidate at least three models with the same
complete visible list-membership change. Any visible scalar change keeps a
model individual. Bulk grouping is disabled in all-detail and JSON output.

The shared change-classification and value-formatting layer lives in
`change_render.py`; report assembly lives in `reporting.py`. This separation
keeps type semantics, labels, price precision, and no-op handling consistent
across text, Markdown, scan HTML, changes HTML, and summary surfaces.

Within every human-readable Pricing group, report assembly applies the stable
semantic order owned by the active provider profile. OpenRouter orders Input,
cache variants, and Output first, then places unranked Pricing fields
alphabetically. The same order is used by scan text, Markdown, concise and
full-detail HTML, `changes` text and HTML, and the HTML Change Summary. This
ordering is presentation-only: JSON output, chronological history, stored raw
field paths, and source storage order are unchanged. It also does not replace
the HTML page-level impact ranking: model cards with price changes and the
Price Movement headline continue to prioritize the largest dollar movements.

The HTML triage layout, cost-only color vocabulary, price-movement model,
sorting, navigation, raw-value behavior, and implementation amendments are
specified in
[report_readability_redesign_design.md](./report_readability_redesign_design.md).

## Notifications and Managed Reports

Notifications are macOS-only and never make a scan fail. Policy can target
changes, errors, both, or neither, with per-run `--notify`/`--no-notify`
override of default enablement.

When available, `terminal-notifier` supplies click-to-open behavior for the
report file or its directory. Otherwise Model Sentinel uses a passive
AppleScript notification and includes a manual path when it fits.

For scan notifications without explicit `--output`, the CLI first writes a
timestamped primary report. If changes exist, it also writes concise and
all-detail HTML companions, and the notification targets the concise HTML
file. Clean scans do not create managed artifacts merely to prove that they
ran.

Report retention deletes managed `.txt`, `.html`, `.json`, and `.md` files
older than the configured age after each scan. A retention value of zero
disables cleanup.

## Logging and Failure Behavior

The CLI logs to stderr and
`~/.model_sentinel/logs/model_sentinel.log`. Size-based rotation gzip-compresses
older generations and honors the configured total-file count.

Configuration and credential errors fail before network work. During a
multi-provider scan, provider fetch or normalization errors are captured per
provider so remaining providers are still processed; the complete report is
emitted and the command returns nonzero if any provider failed.

`healthcheck` validates configuration files, parsed configuration, enabled
credentials, runtime directories, and SQLite initialization. Generic-profile
use and duplicate labels are warnings and do not change its exit status.

## Scheduling

The macOS LaunchAgent workflow seeds editable files into the runtime home and
generates a runner plus plist. The runner exports `MODEL_SENTINEL_HOME`, seeds
a Homebrew-friendly `PATH`, sources `launchd.env`, changes to the repository
path captured when the installer was seeded, and executes `scan --save` by
default.

The generated job therefore depends on that checkout remaining at the captured
path. Operational commands and customization points are documented in
[LAUNCHD.md](./LAUNCHD.md).

## Deferred Work

The following are deliberate future extensions rather than current behavior:

- authenticated schema validation for Abacus.AI and OpenCode Zen
- per-field pricing rules and unit labels for mixed-unit providers
- a registered Abacus provider profile after those rules exist
- explicit handling for per-request OpenRouter prices
- provider-specific auth schemes, headers, query parameters, and timeouts
- raw-response debug capture behind an explicit opt-in
