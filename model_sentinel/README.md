# Model Sentinel

Model Sentinel is a local CLI utility for tracking model-list availability changes across LLM providers over time.

It fetches each configured provider's authenticated model-list endpoint, compares the current result to a saved baseline, reports additions/removals/metadata drift, and can persist snapshots for later history queries.

Provider identity is first-class. OpenRouter and Abacus.AI are tracked independently even when they expose similarly named upstream models.

## Status

The initial CLI implementation is in place.

Current scope:

- `scan` command with compare-only default behavior
- explicit `--save` baseline persistence
- SQLite-backed saved snapshots and change history
- `history` queries for a provider/model pair
- `changes` cross-provider/cross-model change log with date range filtering
- `providers` config inspection
- `healthcheck` runtime/config validation
- text, JSON, and Markdown output
- smart report formatting: field-type-aware rendering, pricing normalization to per-1M tokens, list diffing
- auto-generated HTML companion report when changes are detected (dark-themed, self-contained)
- configurable report retention with automatic cleanup of old files
- macOS notifications on changes or actionable errors
- bounded gzip log rotation

## Runtime Model

This implementation is stdlib-only at runtime. There is no third-party bootstrap dependency layer to install before the tool can run.

Repo-local usage:

```bash
cd model_sentinel
./model-sentinel --help
```

The shebang launcher is the simplest local entry point.

You can also run the module directly:

```bash
python3 -m model_sentinel --help
```

Why not `./model_sentinel`?

- the project directory itself is already named `model_sentinel`
- a filesystem path cannot be both that directory and an executable file
- `./model-sentinel` is the closest clean shebang-based form without renaming the project folder

## Standalone Install

If you want a single command in `~/Library/Scripts/` without keeping the repo checkout present at runtime:

```bash
cd model_sentinel
./install_standalone.sh
```

That builds a single-file executable zipapp at:

```text
~/Library/Scripts/model-sentinel
```

and seeds the runtime-home config files if they do not already exist:

```text
~/.model_sentinel/providers.env
~/.model_sentinel/settings.env
~/.model_sentinel/launchd.env
```

After installation you can run:

```bash
~/Library/Scripts/model-sentinel --help
~/Library/Scripts/model-sentinel healthcheck
```

This removes the repo dependency for normal execution. It does not remove the requirement that provider credentials exist in the process environment. If your credentials come from a sourced secrets script, you still need either:

- a shell session that already sourced that file
- a small wrapper script that sources it and then execs the standalone command
- or `~/.model_sentinel/launchd.env` for LaunchAgent runs

## Configuration

Initialize the local config files with:

```bash
./setup.sh
```

Optional launchd automation files can be seeded with:

```bash
./setup_launchd.sh
```

The live config files are stored in the runtime home:

```text
~/.model_sentinel/providers.env
~/.model_sentinel/settings.env
```

`providers.env` defines which providers exist, whether they are enabled, which environment variable each provider uses for credentials, and how provider-returned pricing is converted into Model Sentinel's canonical unit of price per 1M tokens.

`settings.env` defines runtime behavior such as:

- log rotation size
- retained log generations
- notification defaults
- default report directory
- report retention days (automatic cleanup of old report files)
- default report detail mode and field-pattern display policy

Secrets do not belong in either file.

`setup.sh` is idempotent:

- it creates `~/.model_sentinel/providers.env` and `~/.model_sentinel/settings.env` from the templates if they do not exist
- it does not overwrite existing config files
- it prints the full paths you need to review and edit

After running setup:

1. review and edit `~/.model_sentinel/providers.env`
2. review and edit `~/.model_sentinel/settings.env`
3. start the secrets shell so the required credential env vars are present
4. run `./model-sentinel healthcheck`
5. create the first baseline with `./model-sentinel scan --save`

Each provider entry in `providers.env` must now include:

- `MODEL_SENTINEL_PROVIDER_<ID>_PRICE_MULTIPLIER`
- `MODEL_SENTINEL_PROVIDER_<ID>_PRICE_DIVISOR`

The conversion rule is:

```text
canonical_price = raw_provider_price * PRICE_MULTIPLIER / PRICE_DIVISOR
```

Example:

- OpenRouter raw per-token pricing: `1000000 / 1`
- Abacus raw per-1M-token pricing: `1 / 1`

## Required Credential Environment Variables

The initial providers expect:

- `OPENROUTER_AI_CREDS`
- `ABACUS_AI_CREDS`

If an enabled provider's credential environment variable is missing, the tool halts immediately and lists the missing variable names.

In your workflow that means the secrets shell alias must already have been invoked before running the utility or any automation around it.

## Commands

### Default Compare Run

With no subcommand, Model Sentinel behaves like `scan` in compare-only mode:

```bash
./model-sentinel
```

That will:

- fetch enabled providers
- compare against the previous saved baseline
- print a report to stdout
- not save a new snapshot

If no baseline exists yet, it prints a descriptive message telling you to create one explicitly.

### Save a Baseline

```bash
./model-sentinel scan --save
./model-sentinel scan --detail all
./model-sentinel scan --detail squelched
```

On the first save, the current results become the initial baseline. Later save runs persist new snapshots and record field-level changes relative to the selected baseline.

Human-readable scan reports use `--detail default` unless overridden by `MODEL_SENTINEL_REPORT_DETAIL` in `settings.env`. Default detail mode renders configured important fields and unclassified new fields, while summarizing configured noisy fields such as benchmarks. Use `--detail all` to render every field-level change, or `--detail squelched` to inspect only fields matched by the squelch patterns. JSON output remains full fidelity.

When a scan run auto-generates an HTML report because changes were detected, it also writes a full-detail companion report named like `scan_<timestamp>_full.html`. Notifications continue to target the concise report.

### Query History

```bash
./model-sentinel history --provider openrouter --model chatgpt-5.2
./model-sentinel history --provider openrouter --model chatgpt-5.2 --since 2025-01-01 --until 2025-12-31
./model-sentinel history --provider openrouter --model chatgpt-5.2 --detail all
```

`--since` and `--until` are inclusive and can be used together to bracket a date range.

### Query Changes Across Providers

```bash
./model-sentinel changes --since 2026-03-01
./model-sentinel changes --provider openrouter --since 2026-03-01 --until 2026-03-14
./model-sentinel changes --since 2026-03-01 --format json --output changes.json
./model-sentinel changes --since 2026-03-01 --detail squelched
```

`changes` queries all recorded field-level changes across all providers and models in a date range. Use `--provider` to limit to one provider. `--since` and `--until` are inclusive and can be used independently or together.

Unlike `history` (which targets a single provider/model pair), `changes` gives a cross-cutting view of everything that changed — useful for catching up after missed alerts or reviewing a period of drift.

Human-readable `changes` output honors the same report detail policy as `scan`. Use `--detail all` for full field payloads.

### Inspect Configured Providers

```bash
./model-sentinel providers
```

This lists configured providers and useful status fields, including whether each credential env var is currently present.

### Validate Runtime Readiness

```bash
./model-sentinel healthcheck
```

This validates:

- `~/.model_sentinel/providers.env`
- `~/.model_sentinel/settings.env`
- enabled provider definitions
- required credential env vars
- runtime directories
- SQLite readiness

## Help

Built-in help is intended to be complete:

```bash
./model-sentinel --help
./model-sentinel scan --help
./model-sentinel history --help
./model-sentinel changes --help
./model-sentinel providers --help
./model-sentinel healthcheck --help
```

## Report Formatting

Scan reports use smart, field-type-aware formatting:

- **Pricing fields** show normalized `$X.XX / 1M` alongside raw values, including newly added or removed prices
- **New structured fields** expand nested objects and object lists into readable leaf-level changes in human reports
- **List fields** (e.g., supported parameters) show added/removed items instead of dumping full arrays
- **Context and limit fields** use human-readable number formatting
- **All field changes** are grouped by category: Pricing, Context & Limits, Parameters, Capabilities, Other
- **Repetitive list changes** affecting at least three models are consolidated into one bulk-change entry in default reports. List-size differences are ignored when the actual additions/removals match.
- **Scalar and mixed changes remain model-specific**, so pricing, limits, cutoffs, and models with any additional visible change retain individual entries.
- **HTML scan reports include a compact Price Movement summary** that classifies each affected provider/model identity exactly once as higher-only, lower-only, mixed-direction, or price-fields-added/removed-only. Separate field totals show higher, lower, added, and removed price fields.
- Bulk entries aggregate their squelched changes and expose expandable model lists in HTML. The HTML Change Summary uses the same bulk entries plus one provider-level squelched rollup.

Bulk consolidation applies only to the default human-readable report. `--detail all`, the automatically generated full-detail HTML companion, and JSON output remain ungrouped and full fidelity.

### HTML Auto-Reports

When a scan detects changes and is writing a report to the configured report directory (notification flow), Model Sentinel automatically generates a self-contained HTML companion report alongside the text file.

The HTML report uses a dark industrial theme with color-coded change badges, model cards, expandable bulk model lists, a collapsed Price Movement model list, and a selectively consolidated summary table. Price increases use higher-cost red/salmon semantics, price decreases use lower-cost green semantics, and price fields appearing or disappearing use a neutral coverage color. It has no external dependencies — everything is inlined CSS.

When no changes are detected, only the text report is generated. This gives a quick visual cue in the reports folder: if an `.html` file exists for a run, something changed.

Notification clicks point to the HTML file when it exists, falling back to the text report otherwise.

Clickable-open support on macOS requires `terminal-notifier`. When it is unavailable, Model Sentinel falls back to an informational AppleScript notification that cannot open the report file on click.

If `terminal-notifier` is installed outside the default `PATH`, set its absolute path in:

```text
~/.model_sentinel/settings.env
```

Example:

```text
MODEL_SENTINEL_TERMINAL_NOTIFIER_PATH=/opt/homebrew/bin/terminal-notifier
```

## Report Retention

Report files are automatically cleaned up based on file age. The retention period is configurable in `settings.env`:

```text
MODEL_SENTINEL_REPORT_RETENTION_DAYS=30
```

Files older than the configured number of days are deleted during each scan run. Set to `0` to disable automatic cleanup.

## launchd Automation

Model Sentinel includes a user-level `launchd` setup path for macOS.

Seed the runtime-home launchd files with:

```bash
./setup_launchd.sh
```

That creates or preserves:

```text
~/.model_sentinel/launchd.env
~/.model_sentinel/install_launchd.sh
```

Then:

1. edit `~/.model_sentinel/launchd.env` to source your secrets bootstrap or export the required credential env vars
2. edit `~/.model_sentinel/install_launchd.sh` if you want to change the schedule or command
3. run `~/.model_sentinel/install_launchd.sh install`

From then on, rerun the runtime-home installer after edits to reload the LaunchAgent.

If your secrets bootstrap changes `PATH`, make sure `python3` still resolves to the interpreter you use for manual runs. In this environment that meant exporting `/opt/homebrew/bin` before sourcing the secrets file.

See [`docs/LAUNCHD.md`](./docs/LAUNCHD.md) for the full flow.

## Logging

Logs are stored under:

```text
~/.model_sentinel/logs/
```

Rotation is controlled by `settings.env`:

- `MODEL_SENTINEL_LOG_MAX_BYTES`
- `MODEL_SENTINEL_LOG_KEEP_FILES`

The active log stays uncompressed. Rotated archives are kept as `.gz`.

## Notifications

Notifications are intentionally simple:

- no notification on clean no-change runs
- notify on detected changes or actionable errors
- include the report path in the notification message
- do not auto-open Finder or the report as a side effect of sending the notification
- if `terminal-notifier` is installed, notification clicks can open the configured file or folder target
- otherwise macOS falls back to a passive notification path without a reliable click-through action

When notifications fire and you did not explicitly supply `--output`, Model Sentinel writes a report into the configured report directory so the alert has a concrete artifact to point at.

## Testing

Run the project test suite from this directory:

```bash
pytest
```

## Documents

- [`docs/DESIGN.md`](./docs/DESIGN.md)
- [`docs/LAUNCHD.md`](./docs/LAUNCHD.md)
