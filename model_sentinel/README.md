# Model Sentinel

Model Sentinel is a local CLI utility for tracking model-list availability changes across LLM providers over time.

It fetches each configured provider's authenticated model-list endpoint, compares the current result to a saved baseline, reports additions/removals/metadata drift, and can persist snapshots for later history queries.

Provider identity is first-class. OpenRouter and Abacus.AI are tracked independently even when they expose similarly named upstream models.

## Status

The CLI is implemented and includes:

- `scan` command with compare-only default behavior
- explicit `--save` baseline persistence
- SQLite-backed saved snapshots and change history
- `history` queries for a provider/model pair
- `changes` cross-provider/cross-model change log with date range filtering
- `providers` config inspection
- `healthcheck` runtime/config validation
- text, JSON, and Markdown output for scan, history, provider, and healthcheck
  reports; the cross-provider `changes` command supports text and JSON
- smart report formatting: field-type-aware rendering, profile-aware price
  presentation, and list diffing
- auto-generated, self-contained HTML reports for detected changes when the
  command is using the managed report directory
- configurable report retention with automatic cleanup of old files
- macOS notifications on changes or actionable errors
- bounded gzip log rotation

## Runtime Model

This implementation requires Python 3.11 or newer and is stdlib-only at
runtime. There is no third-party bootstrap dependency layer to install before
the tool can run.

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

This removes the repo dependency for normal execution. The repo-provided
`launchd` installer is separate and embeds the checkout path when it is seeded;
see [`docs/LAUNCHD.md`](./docs/LAUNCHD.md).

The standalone install does not remove the requirement that provider
credentials exist in the process environment. If your credentials come from a
sourced secrets script, you still need either:

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

`providers.env` defines which providers exist, whether they are enabled, which
environment variable each provider uses for credentials, and the default
multiplier/divisor used to present provider-returned monetary price fields.

Each provider's `KIND` selects a provider profile for its payload envelope,
field mapping, labels, classification rules, and report behavior. Unregistered
kinds remain usable through a flexible generic profile; `healthcheck` emits a
non-fatal warning that their labels and price-field detection are best-effort.

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

`MODEL_SENTINEL_PROVIDER_<ID>_LABEL` is display text only; `<ID>` is the
provider's identity and is what reports group by. Labels should be unique
across all providers, enabled or not. A duplicate remains safe because reports
disambiguate by provider ID; `healthcheck` emits a non-fatal warning naming
both providers so the display text can be cleaned up.

Each provider entry in `providers.env` must include:

- `MODEL_SENTINEL_PROVIDER_<ID>_PRICE_MULTIPLIER`
- `MODEL_SENTINEL_PROVIDER_<ID>_PRICE_DIVISOR`

The conversion rule is:

```text
canonical_price = raw_provider_price * PRICE_MULTIPLIER / PRICE_DIVISOR
```

OpenRouter's registered profile uses `1000000 / 1` because its common token
prices are returned per token. The Abacus template intentionally retains
`1 / 1`, but that is not a complete normalization rule: its public schema
mixes per-token token rates with media prices in other units. Abacus therefore
uses the generic fallback profile until per-field price rules and the
authenticated payload are validated. See
[`docs/provider_schema_notes.md`](./docs/provider_schema_notes.md).

## Required Credential Environment Variables

The initial providers expect:

- `OPENROUTER_AI_CREDS`
- `ABACUS_AI_CREDS`

Before a scan, Model Sentinel validates the selected providers' credential
environment variables and halts before any network request if one is missing.
`healthcheck` reports missing credentials for enabled providers. The local
`providers`, `history`, and `changes` queries do not require provider
credentials.

In your workflow that means the secrets shell alias must already have been invoked before running the utility or any automation around it.

## Commands

### Default Compare Run

With no subcommand, Model Sentinel behaves like `scan` in compare-only mode:

```bash
./model-sentinel
```

For each selected provider with a saved baseline, that will:

- fetch enabled providers
- compare against the previous saved baseline
- print a report to stdout
- not save a new snapshot

If a provider has no baseline, compare-only mode reports that condition and
does not fetch that provider. Create the baseline explicitly with
`scan --save`.

### Scan and Save Options

```bash
./model-sentinel scan --save
./model-sentinel scan --detail all
./model-sentinel scan --detail squelched
./model-sentinel scan --baseline previous-day
./model-sentinel scan --baseline-date 2026-07-01
./model-sentinel scan --provider openrouter
```

On the first save, the current results become the initial baseline. Later save runs persist new snapshots and record field-level changes relative to the selected baseline.

The default baseline is the latest saved snapshot for each provider.
`--baseline previous-day` selects the latest saved snapshot from an earlier
local calendar day. `--baseline-date YYYY-MM-DD` selects a saved snapshot on
that local date and, in compare-only mode, reports the nearest surrounding
saved dates when no exact match exists.

Human-readable scan reports use `--detail default` unless overridden by `MODEL_SENTINEL_REPORT_DETAIL` in `settings.env`. Default detail mode renders configured important fields and unclassified new fields, while summarizing configured noisy fields such as benchmarks. Use `--detail all` to render every field-level change, or `--detail squelched` to inspect only fields matched by the squelch patterns. JSON output remains full fidelity.

When a scan run auto-generates an HTML report because changes were detected, it also writes a full-detail companion report named like `scan_<timestamp>_full.html`. Notifications continue to target the concise report.

### Query History

```bash
./model-sentinel history --provider openrouter --model chatgpt-5.2
./model-sentinel history --provider openrouter --model chatgpt-5.2 --since 2025-01-01 --until 2025-12-31
./model-sentinel history --provider openrouter --model chatgpt-5.2 --detail all
./model-sentinel history --provider openrouter --model list
./model-sentinel history --provider openrouter --model list chatgpt
```

`--since` and `--until` are inclusive and can be used together to bracket a date range.

Use the special model value `list` to show known saved model IDs for a
provider. An optional positional pattern filters that list by partial,
case-insensitive match against model ID or display name.

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

When records exist and `--output` is omitted, `changes` also saves its primary
output in a timestamped `.txt` artifact plus an HTML report in the configured
report directory. The primary artifact contains text by default; with
`--format json`, its contents are JSON even though the managed filename still
uses `.txt`. Supplying `--output` writes only the requested text or JSON
artifact.

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
- all provider definitions
- credential env vars for enabled providers
- runtime directories
- SQLite readiness

It also emits non-fatal warnings for duplicate display labels and provider
kinds that are using the generic fallback profile.

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

- **Fields classified as monetary prices** are presented as a normalized
  `$X.XX` per-1M figure alongside the provider's raw value. Newly added and
  removed prices are included. For an unregistered, mixed-unit provider this
  classification and unit are best-effort; see the Abacus caveat under
  Configuration.
  - **In HTML only,** the normalized figure *leads*: it is the value in the cell, the unit moves to its own column, and the raw provider value is available on demand — in the cell's tooltip, and inline via the page's "Show raw values" toggle (see below), which is on by default in the full-detail companion. The HTML Change Summary follows the same order.
  - **Text and markdown still lead with the raw value**, in the form `2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)`, and have no toggle. They are the audit formats; the literal value a provider published is what they exist to record.
- **New structured fields** expand nested objects and object lists into readable leaf-level changes in human reports
- **List fields** (e.g., supported parameters) show added/removed items instead of dumping full arrays
- **Context and limit fields** use human-readable number formatting
- **All field changes** are grouped by category: Pricing, Context & Limits, Parameters, Capabilities, Other
- **A column too narrow for a real value prints a bounded sentinel, never a false zero.** A movement smaller than the price column can show reads `<$0.0001` or `+<$0.0001`, and a percentage below the row's precision reads `↑ <0.1%`. The consequence is deliberate: a displayed row need not visibly add up (`$2.00 → $2.00 +<$0.0001`), because each cell states something true even where the arithmetic is not legible at the printed width. The alternative — rounding to `$0.0000` and `0.0%` — states something false.
- **Repetitive list changes** affecting at least three models are consolidated into one bulk-change entry in default reports. List-size differences are ignored when the actual additions/removals match.
- **Scalar and mixed changes remain model-specific**, so pricing, limits, cutoffs, and models with any additional visible change retain individual entries.
- Bulk entries aggregate their squelched changes and expose expandable model lists in HTML. The HTML Change Summary uses the same bulk entries plus one provider-level squelched rollup.

### Color Semantics

**Wherever an HTML report states a field change, color carries one meaning and only one: cost.** Red/salmon marks a price going up, green a price going down. Nothing that reports a change is allowed to borrow those two colors, so a red change cell always means "this got more expensive" and a green one always means "this got cheaper" — a reader never has to check which axis a color is on. This holds in all three HTML documents: the scan report's model cards, its automatically generated `_full.html` companion, and the standalone `changes` report's change table — plus the Price Movement card and the Change Summary in each.

Everything else takes a non-cost color: capacity changes (context windows, output limits) are amber, capability changes are blue, a disabled capability and purely informational changes are dim, list membership is blue for a member arriving and dim for one leaving (in every card type and in the `changes` report alike), and a price field appearing or disappearing is the neutral coverage blue — coverage is not a direction, and painting an added price red would claim a price rise that was never measured.

Two things outside that vocabulary still use red and green, and neither reports a field change: **run status** — a provider card and its badge are green when clean and red when the fetch failed, and an error message is red — and the **added/removed model lists**, where a whole model arriving is green and one departing is red. Both are presence-or-health signals about the scan itself rather than statements about a value moving, and neither appears in a change table, a model card row, or the Change Summary.

Bulk consolidation applies only to the default human-readable report. `--detail all`, the automatically generated full-detail HTML companion, and JSON output remain ungrouped and full fidelity.

### HTML Auto-Reports

When a scan detects changes and is writing a report to the configured report
directory (the notification flow), Model Sentinel automatically generates a
self-contained HTML companion report alongside the primary text, JSON, or
Markdown report. An explicit `--output` writes only that requested format.

The HTML report uses a dark industrial theme and has no external dependencies and no JavaScript — all CSS is inlined, and every interactive affordance is built from native `<details>`, `:target` and `:has()`.

**The Price Movement card comes first and is denominated in dollars.** It opens with a verdict over the affected *models* — `higher — 5 up` when every model that moved moved up, `mostly higher — 4 up, 1 down` when the population is merely lopsided, and `mixed` when no direction leads. The qualifier is dropped on a unanimous result rather than hedging it. Beneath the verdict sit the biggest increase and the biggest decrease, each naming its model, field, old and new price, dollar delta and percentage; then two tallies that keep affected-model counts and changed-price-field counts visibly separate; then a collapsed list of every affected model, grouped by direction. Zero-count categories are omitted so only observed movements compete for attention.

**Each model card is a single aligned table.** One row per field, with fixed columns for category, field name, old value, new value, unit, delta and percentage, so values line up down the card and can be compared by eye instead of read as prose. The category name appears as a dim chip on the first row of each group.

**Pricing fields use one stable semantic order.** The active provider profile
defines the preferred sequence within each human-readable Pricing group.
OpenRouter presents Input first, then cache variants, then Output; any other
Pricing fields follow alphabetically. Scan text, Markdown, concise and
full-detail HTML, `changes` text and HTML, and the HTML Change Summary all use
that same sequence. This is presentation-only: JSON output, chronological
history, and stored source field order are unchanged. Across the HTML page,
price-changed model cards are still ranked by impact, and the Price Movement
headline still elevates the largest dollar movements.

**The page has two tiers.** Models whose prices moved are presented directly. Everything else — models with no price change, bulk-change groups, and the report-detail rollups — is folded into one collapsed `Other changes` disclosure, which states in its summary exactly what it contains. A card that is hiding squelched fields carries a `+N hidden` chip in its header, with a breakdown in the chip's tooltip, so suppression is always visible even when the detail is not.

**Navigation is by anchor.** Every model card has a stable id; the Price Movement panel and the tier-1 Change Summary rows link into them, and each card header carries a dim `↑` back-link to the Price Movement card. The landed-on card is highlighted, with the highlight animation suppressed under `prefers-reduced-motion`.

**Raw values are available without leaving the page.** Hovering a price cell shows the full derivation — the provider's literal value, its magnitude in scientific notation as a parenthetical, the conversion factor and the resulting figure, e.g. `0.000002 (2.0e-6) × 1,000,000 = $2.00`. Because a tooltip cannot be selected or copied, a `Show raw values` checkbox in the header also reveals a selectable `old → new` sub-line under every price row. That checkbox is **ticked by default in the full-detail companion report**, whose whole purpose is the raw numbers, and unticked in the concise one.

When no changes are detected, no HTML companion is generated. The requested
primary format is still emitted to stdout or an explicit `--output`; the
managed report directory receives no scan artifact unless notification policy
creates a report path.

Notification clicks point to the HTML file when it exists, falling back to the
primary report otherwise.

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

Create or activate a project virtual environment, install pytest there, and run
the complete project test suite from this directory:

```bash
pytest
```

## Documents

- [`docs/DESIGN.md`](./docs/DESIGN.md)
- [`docs/LAUNCHD.md`](./docs/LAUNCHD.md)
- [`docs/provider_schema_notes.md`](./docs/provider_schema_notes.md)
- [`docs/report_readability_redesign_design.md`](./docs/report_readability_redesign_design.md)
