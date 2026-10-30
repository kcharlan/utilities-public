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
- `browse` read-only, fully offline history browser with Activity, Models,
  Catalog, and Hosts views
- `providers` config inspection
- `healthcheck` runtime/config validation
- explicit `credentials refresh` acquisition into a private persistent cache
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

You can also run the module directly from an activated project virtual
environment:

```bash
source .venv/bin/activate
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

Building requires [uv](https://docs.astral.sh/uv/) (`brew install uv`). The
installer packages the staged source with `build_standalone.py`, a PEP 723
script it runs through `uv run --no-python-downloads --script`, so uv selects
the build interpreter from that header and never downloads one; the build
never runs on whatever `python3` is first on `PATH`. The installed zipapp
still runs on `/usr/bin/env python3` and stays stdlib-only. `--check` does not
need uv.

That builds a single-file executable zipapp at:

```text
~/Library/Scripts/model-sentinel
```

(pass a target path, such as `./install_standalone.sh "$HOME/bin/model-sentinel"`,
to install elsewhere; `--check` accepts the same optional path) and seeds the runtime-home config files if they do not already exist:

```text
~/.model_sentinel/providers.env
~/.model_sentinel/settings.env
~/.model_sentinel/launchd.env
```

After installation you can run:

```bash
~/Library/Scripts/model-sentinel --version
~/Library/Scripts/model-sentinel --help
~/Library/Scripts/model-sentinel healthcheck
```

The zipapp is a point-in-time copy: pulling or editing the repository does not
update it. After repository updates, rebuild the standalone or run the
read-only freshness check from the checkout:

```bash
./install_standalone.sh
./install_standalone.sh --check
```

`--check` compares the exact Python contents that would be packaged with the
source hash embedded in the installed target. It does not replace the target,
seed runtime files, load provider configuration, or contact a provider.
`--version` is also configuration-free and reports the product version,
artifact kind, Git revision context, packaged source hash, and UTC build time.

The standalone removes the repo dependency for normal execution. The
repo-provided `launchd` installer is separate and embeds the checkout path when
it is seeded; see [`docs/LAUNCHD.md`](./docs/LAUNCHD.md).

The standalone supports both environment credentials and a private persistent
credential file. In the default environment mode, credentials from a sourced
secrets script still need either:

- a shell session that already sourced that file
- a small wrapper script that sources it and then execs the standalone command
- or `~/.model_sentinel/launchd.env` for LaunchAgent runs

In file mode, explicitly refresh the cache first; subsequent scans need neither
the secrets shell nor the refresh mount. Installation preserves existing config
and bootstrap files. It does not migrate settings or remove old bootstrap lines;
review those files manually when changing credential modes.

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

Set `MODEL_SENTINEL_HOME` to use a different runtime home; the setup scripts,
installers, and CLI all honor it.

`providers.env` defines which providers exist, whether they are enabled, which
environment variable each provider uses for credentials, and the default
multiplier/divisor used as fallback conversion factors for provider-returned
monetary price fields.

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
- endpoint capture (`MODEL_SENTINEL_ENDPOINT_CAPTURE`)

Secrets do not belong in either file.

`setup.sh` is idempotent:

- it creates `~/.model_sentinel/providers.env` and `~/.model_sentinel/settings.env` from the templates if they do not exist
- it does not overwrite existing config files
- it prints the full paths you need to review and edit

After running setup:

1. review and edit `~/.model_sentinel/providers.env`
2. review and edit `~/.model_sentinel/settings.env`
3. export the required credential env vars, or configure and refresh file credentials below
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

For generic providers and registered rules that inherit the configured
factors, the conversion rule is:

```text
canonical_price = raw_provider_price * PRICE_MULTIPLIER / PRICE_DIVISOR
```

Registered provider profiles may instead declare an explicit scale, display
unit, comparison group, and canonical-storage target for each field. The
OpenRouter profile displays token fields as `/1M tokens`, `web_search` as
`/1K searches`, `request` as `/request`, and `image` as `/image`. An unknown
OpenRouter monetary leaf remains visible as `/unit unknown`; it does not enter
the token-price snapshot columns or absolute token-rate headlines.

OpenRouter's configured `1000000 / 1` factors remain required and provide the
inherited fallback contract, but its registered field rules cannot be changed
accidentally by stale provider-wide factors. The Abacus template intentionally
retains `1 / 1`, but that is not a complete normalization rule: its public
schema mixes per-token token rates with media prices in other units. Abacus
therefore uses the generic fallback profile until its authenticated payload is
validated and a dedicated field-rule registry is added.

### Endpoint capture

`MODEL_SENTINEL_ENDPOINT_CAPTURE` controls whether a saved scan also records
each model's per-provider endpoint list for providers whose profile supports it
(currently OpenRouter). Capture is on by default; when the key is absent the
setting is `true`. Accepted values are `1`/`true`/`yes`/`on` and
`0`/`false`/`no`/`off`.

Capture adds network traffic to every saved scan: one extra request per
distinct endpoint-list path found in the catalog, not one per model, because
several catalog models can share a path. At most 4 requests are in flight at a
time, and new requests are admitted for at most 180 seconds per scan. Paths not
started by then are recorded as failed rather than treated as empty. Requests
are anonymous: they send no authorization header or cookie, do not follow
redirects, and never retry with credentials. This is a local policy choice;
Model Sentinel does not assume the provider guarantees anonymous access, and an
authentication failure appears as a failed path.

Each capture is saved in the runtime database with the catalog scrape it belongs
to: one row per catalog model mapping, one per endpoint-list path with its
outcome and sanitized error, each endpoint's stable state (stored once and
shared by identical endpoints), and a gzip archive of the decoded response
bodies. A capture is compared only with the capture of the scan's selected
catalog baseline, never with a newer or last-good capture. Lists that cannot be
compared (a failed fetch on either side, a newly appearing or disappearing
path, or a split, merge or partial move of models between paths) are recorded
as comparison gaps rather than treated as empty lists.

OpenRouter uptime is sampled from the response's rolling 5-minute, 30-minute
and 1-day windows. These are provider-reported percentages at capture time,
not measurements made by Model Sentinel. Finite numeric values from 0 through
100 are stored in `endpoint_telemetry`; missing values, booleans, strings and
out-of-range values become NULL. Present raw telemetry fields, including nulls
and rejected uptime values, remain in canonical JSON. Telemetry does not
participate in stable-state comparisons or endpoint change counts.

Each processed capture has an `endpoint_telemetry_captures` marker, including
captures with no telemetry rows. On saved scans, capture-capable providers
first backfill older unprocessed gzip archives locally, even when new endpoint
capture is switched off. Backfill uses the same response-order endpoint keys
as new captures, saves only samples matching recorded observations, and counts
unmatched archive endpoints. Each archive commits independently; a failure
rolls back that archive and leaves it pending for a later saved scan. Minimal
error captures with no archive are ineligible. Backfill needs no network
request, and its failures are logged as redacted warnings without changing the
catalog scan outcome. Progress logs give captures, rows and unmatched counts.
`healthcheck` reports pending archived captures and the cumulative unmatched
count as advisory detail without changing the capture status or exit code.

Endpoint failures never change the catalog result, the notification decision,
or the scan exit status. A capture that fails as a whole is saved as a minimal
`error` capture with a sanitized message; the log records each capture's status
and its request, failure, mapping, comparison-gap and change counts. A report or
artifact whose Alias check or Provider endpoints sections cannot be built or
rendered omits them and the log records a redacted warning; its catalog content
is unchanged. To turn capture off, set
`MODEL_SENTINEL_ENDPOINT_CAPTURE=false` in `~/.model_sentinel/settings.env`.

## Provider Credentials

The initial providers expect:

- `OPENROUTER_AI_CREDS`
- `ABACUS_AI_CREDS`

Each provider's `API_KEY_ENV` names its credential in either source mode.
Before a scan, Model Sentinel validates the selected providers' credentials
and halts before any network request if one is missing or invalid.
`healthcheck` reports missing credentials for enabled providers. The local
`providers`, `history`, and `changes` queries do not require provider
credentials.

The default `environment` mode reads the calling process environment, so load
your secrets shell before manual runs or supply credentials in the scheduled
runner's environment. It remains supported without a cache.

### Persistent File Credentials

Configure these four settings in the runtime home's `settings.env`:

| Setting | Default / meaning |
| --- | --- |
| `MODEL_SENTINEL_CREDENTIAL_SOURCE` | `environment`; choose `environment` or `file` |
| `MODEL_SENTINEL_CREDENTIAL_FILE` | `credentials.env`; persistent cache destination, must not be blank |
| `MODEL_SENTINEL_CREDENTIAL_REFRESH_FILE` | blank; static input file or 1Password mounted pipe used only by explicit refresh |
| `MODEL_SENTINEL_CREDENTIAL_REFRESH_TIMEOUT_SECONDS` | `5`; positive finite seconds bounding reader communication, not the entire refresh operation |

Paths expand `~`; relative paths resolve under the runtime home. Keep the cache
outside every Git checkout. Its immediate parent must be private (`0700`) and
the regular, nonsymlink cache file must be `0600`. Refresh creates or secures
the runtime home to `0700` and publishes the cache with mode `0600`. An alternate
cache parent must already exist with mode `0700`; unsafe caches are rejected.
The refresh input and
cache destination must be different files, including when hardlinked.

The cache is **plaintext at rest**. File permissions limit access but do not
encrypt it. Use file mode only if that tradeoff fits your local security needs.

The refresh input must be owned by the current user, have exactly mode `0600`,
and be a regular file or FIFO. Final symlinks are rejected. These source rules
are separate from the cache's private-parent and regular-file requirements.

The refresh input is UTF-8 assignment text, bounded to 65,536 bytes, using one
`KEY=VALUE` per line. Blank lines and full-line `#` comments are allowed. Names
must be identifiers (`[A-Za-z_][A-Za-z0-9_]*`), with no duplicate names. Values
may be unquoted or single/double quoted strings with Python-style escapes.
Whitespace around assignments is ignored; quoted value whitespace is retained.
No `export`, `source`, multiline strings, continuations, shell expansion, or
command execution occurs. Shell-looking text is literal. Required values must
be nonempty printable ASCII, not whitespace-only or unresolved
`op://` references. A malformed input or failed refresh preserves the old cache.

For a mounted refresh source, set its path and run manually:

```bash
./model-sentinel credentials refresh
./model-sentinel credentials refresh --provider synthetic_disabled
```

Replace the synthetic provider ID with one configured in `providers.env`.
Default refresh selects enabled providers; explicit selection can include a
disabled provider. Only configured credential names are stored. A selected
refresh replaces selected values, retains unselected configured cached values,
and drops names no longer referenced by any configured provider. Rename an
`API_KEY_ENV` only with a matching provider config edit and refresh. Renaming a
mount changes the refresh setting, not the stable cache destination.

Alternatively, after your existing secrets shell has loaded credentials, run
this optional human step:

```bash
./model-sentinel credentials refresh --from-environment
```

This needs no refresh path and launches no shell. Refresh works while source
mode is still `environment`, so populate and check the cache before switching
to `file`. Then run `healthcheck` and `scan --save`. File mode uses the cache
exclusively and does not merge inherited environment credentials. Scans never
read the mount or initiate a refresh. A mounted refresh may prompt through
1Password itself; there is no automatic desktop launch or login retry.

Refresh manually after rotating credentials. There is no automatic expiry or
refresh hook/job. `providers` reports credential source/status, presence/errors,
and last successful scan. `healthcheck` reports **cache last updated** and age
from the file modification time, not provider validity or proof that every
retained key was re-extracted. A future timestamp warns instead of showing a
negative age; missing disabled-provider keys do not fail healthcheck. Refresh
returns `0` on success and `2` on safe errors; healthcheck retains `0`/`1`.

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

Conditional-pricing policies follow the same detail modes. In `default`, a
grouped schedule stays compact, ordered rules already retain their source order,
and HTML keeps their canonical audit evidence in a collapsed disclosure. For
grouped and ordered states, `all` adds source rules to grouped schedules and
opens or expands available canonical audit evidence without changing the
interpretation. Raw fallback is self-contained and identical in `default` and
`all`, including its canonical evidence and disclosure state. `squelched`
omits the conditional-pricing and Price Movement panels. This is
presentation-only: stored field paths and values, override-list order, SQLite
schema, and JSON reports are unchanged.

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

The history query now uses one windowed latest-model join and pushes bounded
date prefilters into SQLite, so even a short `--since` range stays fast as the
database grows.

Human-readable `changes` output honors the same report detail policy as `scan`. Use `--detail all` for full field payloads.

When records exist and `--output` is omitted, `changes` also saves its primary
output in a timestamped `.txt` artifact plus an HTML report in the configured
report directory. The primary artifact contains text by default; with
`--format json`, its contents are JSON even though the managed filename still
uses `.txt`. Supplying `--output` writes only the requested text or JSON
artifact.

### Browse History

```bash
./model-sentinel browse
./model-sentinel browse --provider openrouter
./model-sentinel browse --view catalog
./model-sentinel browse --view hosts
./model-sentinel browse --model example-provider/fake-org/test-model-a
./model-sentinel browse --no-open --port 8110
```

`browse` starts a local history browser over the existing SQLite database. It
binds to `127.0.0.1`, prefers port `8110`, and tries the next 19 ports if that
one is busy; `--port 0` lets the OS choose. `--no-open` skips opening the
browser, and `Ctrl-C` stops the server.

- **Activity** is an event-first feed with a 180-day heatmap, provider and
  change facets, range presets, bulk-change groups, and raw-value detail.
  Default detail folds models whose only changes are squelched into one line
  per day; selecting a category or switching to All shows those model cards.
- **Models** pins up to eight provider/model pairs and compares their saved
  aspects on synchronized timelines and an event rail.
- **Catalog** compares saved provider snapshots in a sortable table, with
  date-snapping snapshot controls, column presets, per-cell history
  sparklines, and links back to the timeline or feed. Compare mode initially
  shows changed models only; turn off **Changed only** to inspect the full
  snapshot.
- **Hosts** compares serving companies in an exact saved endpoint capture.
  Select no hosts for best-across-host comparisons, one for its summary and
  history, or several for side-by-side columns. Each compact row represents one
  model from an endpoint list, with a variants count for additional mapped
  models. Rank by exact price, sampled uptime, context length, or max output;
  equal values share a rank. When present, output price is the default ranking.
  Missing values remain visible without a best marker. The Best column
  identifies the winner and ties, while the spread strip shows every ranked
  host. Compared hosts use selection-order colors. Positive prices use a
  logarithmic spread; signed/zero prices and other dimensions use a linear
  spread. Host cells show exact best markers and signed gaps: percentage points
  for uptime, percentage differences for other rankings. A nonzero difference
  below displayed precision retains its sign and a less-than label; tooltips
  give an approximate magnitude. Percentage gaps from zero remain undefined.
  Gaps use a true minus sign and `pt` for uptime. Numeric columns align right;
  one-host rows put the host value and rank before Best and Spread. Compact
  precision shows the quantization, token capacities use K/M labels with full
  integers in titles, and full endpoint details retain the published bit width.
  Spread strips emphasize compared hosts and show text alone for a sole host
  or equal values. The wrapping one-host summary includes models, endpoints,
  tags, median uptime, non-normal endpoints and a precision mix.

  Click any results row or its model name, including an unmapped model, to open
  its endpoint drawer; activating the open row again closes it.
  The nonmodal drawer leaves the background interactive and opens with focus
  on its heading. Hosts menus and model suggestions appear above the drawer
  and remain clickable where they overlap it. Escape closes a Hosts menu or
  model suggestion list first;
  with no such overlay open, it closes the drawer. The drawer shows every
  observed endpoint in compact rows, passing rows before failing rows, the
  first failing condition, price columns with values for that model, precision,
  capacities, uptime and status. **Details** expands complete endpoint facts
  across the table below its endpoint. Its mapped-model links open
  individual dossiers; aliases remain visible. The "Also served as" line
  shows only names other than the heading and is omitted when none remain.
  Open dossier uses the first
  mapped model, and is disabled for unmapped lists. The drawer's `hlist` URL
  state supports copied URLs and Back/Forward; closing restores focus to its row
  or the results heading. The results initially show 50 models; **Show 50 more**
  adds 50. Changes to comparison or filters reset this limit. The summary counts
  qualifying/captured endpoints separately from admitted models.

  Click a column heading to sort ascending, click again for descending, and
  click once more to remove it. Additional columns join the sort in priority
  order; arrows and numbers mark the active stack. The toolbar summary names
  displayed keys and **Clear sort** removes the saved stack, even when no models
  qualify. Missing values stay last in either direction, prices compare exactly,
  and ties retain the default order.
  Drawer sorting stays within the passing and failing groups. The `hsort` and
  `dsort` URL lists store `a:<key>` or `d:<key>` entries for results and drawer
  sorting. Hidden result columns retain their keys and resume sorting when
  displayed again; empty drawer price columns likewise keep their saved keys
  without active sorting until a model with values is opened. Price paths
  absent from a capture are removed. Changing ranking keeps sorting. Sort
  clicks and clearing support reload and Back/Forward. Invalid keys and duplicate columns are
  removed without adding history entries.
  Result keys are `model`, `best`, `spread`, `host:<name>`, `rank`, `precision`,
  `context`, `uptime`, `status`, and `hosts`. Drawer keys are `host`, `endpoint`,
  `price:<path>`, `precision`, `context`, `output`, `uptime`, and `status`.
  Host names and price paths must belong to the selected capture.

  The first displayed sort column is tinted. Adjacent comparator-equal values
  form groups within the current page, separately for qualifying and failing
  drawer endpoints. Groups averaging three or more rows use full-width headings
  with their value and model/endpoint count; smaller groups use alternating
  bands and rules. All-singleton groups show only the column tint. Missing
  values group together. Status headings describe the absolute status code
  shared by signed values. Failing drawer endpoints always start with a
  **Not qualifying** heading. Group headings do not open drawers or count
  toward the 50-model pagination limit.

  **Add host** opens a searchable checkbox list ordered by models served; remove
  a compared host with its pill. Picker counts describe observed coverage, and
  incomplete history captures break uptime trends. **Snapshot** selects an
  exact saved capture, newest first. **Provider** appears alongside ranking and
  snapshot when multiple providers have captures; changing it clears the old
  provider's snapshot. Capture, host selection, ranking, and row match survive
  reloads. The compact Hosts strip retains view tabs and Appearance, with its
  page heading available to assistive technology. The toolbar, results and
  pagination share a panel. On desktop the page scrolls beneath the sticky
  toolbar and table headings. Wide comparisons scroll horizontally with a
  pinned model column and ordinary table headings. On narrow screens toolbar
  and headings scroll with the page; menus become bottom sheets and the drawer
  fills the width.

  The toolbar opens keyboard-accessible condition menus for host
  scope, normal status (code 0), precision, minimum uptime, context and
  output capacity, supported parameters/native tools and implicit caching,
  service tiers and exact price limits. Opening a menu leaves conditions
  unchanged. Checkbox lists support local substring filtering with highlighted
  matches; their counts include endpoints passing all other conditions. The
  inline **Search models** field suggests capture names and mapped model IDs;
  its clear button cancels pending typing and returns focus to the field.
  Conditions combine
  with AND; each removal count measures that condition alone across the capture.
  Precision's 16-bit and 8-bit shortcuts preserve unknown/unrecognized chips.
  An empty active precision or tier selection matches nothing; remove its
  condition to restore unrestricted matching. Null service tiers display as
  `standard`, while string tiers retain JSON quotes, including `"standard"` and
  `"null"`. Price limits preserve decimal text and compare exact values.
  **Hosts** switches between **Exclude these** and **Only these**; either mode
  is inactive when its selection is empty. Supports uses one search across
  Request parameters, Native tools and Caching. Menus keep their header,
  search, shortcuts and effect footer visible while options scroll. Threshold
  forms scroll between their fixed header and footer when space is limited.
  Menus become bottom sheets on narrow screens. Clear appears only for a
  configured condition. Add host opens **Compare hosts**, ordered by models served.
  Uptime presets toggle off when pressed again. Token-price columns offer
  exact maximum presets of $0.5, $1, $5 and $15 per million tokens.

  **Rows: any** admits a model if one selected host qualifies; **Rows: all**
  requires each host. **Show excluded** uses endpoint presence
  for the same row rule and shows failing endpoints dimmed with their first
  failing condition, without awarding them ranks. With no selection, any host
  can admit a list. Missing uptime can be included explicitly, and the uptime
  condition pauses for snapshots without stored telemetry; see [Endpoint
  capture](#endpoint-capture) for the saved telemetry facts. A paused uptime
  condition keeps its chip and can be cleared, with its other controls disabled.
  **Clear all** removes conditions while keeping ranking, row rule, Show
  excluded, provider, selected hosts, and capture. Configured chips show
  summaries and individual removal counts, and remove individual conditions.
  Clear all appears only while a condition is configured. Paused uptime retains
  its configured chip without an evaluated removal count.
  Conditions and empty chip selections survive
  copied URLs/reloads. Numeric typing replaces the current history entry;
  deliberate selections retain Back/Forward navigation. Editors close with
  `Esc` and return focus to their trigger. Menus focus search or their custom
  field (the checkbox for Status); paused Uptime focuses Clear, or its heading
  without a configured threshold. Price focuses its heading when the capture
  has no price columns. Menus have no Close button.
  Tab stays within an open menu;
  clicking another trigger switches directly. Arrow keys navigate checkbox
  options, and Space or Enter selects them. Search suggestions keep focus in
  the input: use arrows then Enter, or select with a pointer. Host history owns
  the date range and range presets; these controls and Detail are omitted from
  the global bar on Hosts.

Every model name opens a dossier containing identity and presence evidence,
current facts, field-history sparklines, and the complete stored changelog.
Use the **Timeline** action to graph that model or **That day in Activity** to
inspect the provider-wide context. The **Find model** box searches every saved
provider regardless of the current provider filter.

A dossier's **Serving endpoints** section shows the endpoint list saved with
the exact snapshot the dossier displays (see Endpoint capture), never a newer
capture or another snapshot's. For a captured list it shows each endpoint's
prices (hover a cell for the raw value), quantization, context length, status
(`normal` for code 0, `status <code>` otherwise), and Uptime 1d/30m/5m samples.
Missing or malformed facts and absent samples show dashes; real zero uptime
stays visible. When uptime isn't stored, the section explains its absence and
mentions archive backfill only when eligible. These facts use only that exact
capture and list, with no live requests or archive decoding. New columns scroll
inside the table on narrow screens. The section also shows the list's changes
in saved order up to that snapshot (at most 200, newest first, with a note when older changes
are left out), and the capture's status and baseline comparison. When several
catalog models share one list, a note names the list and its other models and
warns that the catalog row's own price can differ. For an alias, it shows each
price that differs from the target, which endpoints carry the alias's prices
(claims about the named prices only), and a price ladder per differing price
with neutral endpoint dots and target/alias marks. Otherwise the section says
why there is no list: the snapshot was not captured (with the provider's first
usable capture date, or a pointer to the capture setting), the database
predates endpoint capture, the catalog row has no or a malformed endpoint
link, the alias target is missing or its chain is a cycle, the list failed to
fetch or was not sent before the endpoint fetch budget ran out, or the whole
capture failed. Failures show the saved error evidence;
**Re-read saved capture** only asks the local browse server again and never
contacts the provider.

The read-only JSON API also exposes `GET /api/hosts?provider=<id>` and
`GET /api/host_history?provider=<id>&host=<name>`. Hosts selects the newest
usable saved endpoint capture unless `scrape_id` selects an exact saved
successful catalog scrape. It returns list/model/alias identities, serving
hosts, endpoint capabilities, normalized precision, exact hexadecimal rational
prices, both capture-wide `display` and independently formatted `display_own`
price text, and sampled uptime. Host history accepts local-date `from`/`to` bounds
and returns observed coverage and up to 200 changes, newest first. Missing
telemetry remains null; absence from an incomplete capture is unknown rather
than zero. These routes never backfill or fetch provider data.

The browser is read-only: it opens SQLite in read-only/query-only mode and does
not create or update database, config, log, report, or cache files. It is also
fully offline; Preact, htm, uPlot, CSS, and every other page asset are packaged
with Model Sentinel, so viewing history makes no network request.

The URL hash contains the selected view and filters, making browser
back/forward and copied local URLs reproducible. Press `/` to focus **Search
models** on Hosts or **Find model** on other views, `1`, `2`, `3`, or `4` to switch
among Activity, Models, Catalog, and Hosts, and
`Esc` to close search results, drawers, or popovers. The Appearance disclosure
offers System, Light, and Dark themes; the choice is stored only in browser
`localStorage`, not in Model Sentinel's runtime home.

`browse` requires readable `providers.env` and `settings.env` files plus an
existing database containing at least the Model Sentinel schema; a database
created before endpoint capture, without its tables, is accepted. Run
`./setup.sh` if the config files are absent and `./model-sentinel scan --save`
to create the first saved snapshot. Provider credentials and network access
are not required to browse saved history.

### Inspect Configured Providers

```bash
./model-sentinel providers
```

This lists configured providers, credential source/status, presence/errors,
and last successful scan; credential values are never reported. Use `healthcheck`
for cache last updated and age when file mode is selected.

### Validate Runtime Readiness

```bash
./model-sentinel healthcheck
```

This validates:

- the running build identity and resolved command entrypoint
- `~/.model_sentinel/providers.env`
- `~/.model_sentinel/settings.env`
- all provider definitions
- credentials for enabled providers from the selected source
- runtime directories
- SQLite readiness

It also emits non-fatal warnings for duplicate display labels and provider
kinds that are using the generic fallback profile.

For each enabled provider whose profile supports endpoint capture, an
`endpoint_capture` item shows whether the setting is enabled and the latest
capture's date, status and counts, or `no capture yet`. It is `warn` when the
latest capture is `partial` or `error` while capture is enabled, or when the
capture history cannot be read; it never changes the healthcheck exit status.

## Help

Built-in help is intended to be complete:

```bash
./model-sentinel --version
./model-sentinel --help
./model-sentinel scan --help
./model-sentinel history --help
./model-sentinel changes --help
./model-sentinel browse --help
./model-sentinel providers --help
./model-sentinel healthcheck --help
./model-sentinel credentials --help
./model-sentinel credentials refresh --help
```

## Report Formatting

Format support is command-specific. HTML is an internally generated companion,
not a `--format` value:

| Command | Text | JSON | Markdown | Internal HTML |
|---|---:|---:|---:|---:|
| `scan` | yes | yes | yes | yes |
| `history` / model list | yes | yes | yes | no |
| `changes` | yes | yes | no | yes |
| `providers` | yes | yes | yes | no |
| `healthcheck` | yes | yes | yes | no |

Scan reports use smart, field-type-aware formatting:

- **Fields classified as monetary prices** are presented as a normalized
  `$X.XX` figure in the unit declared by the active provider profile alongside
  the provider's raw value. OpenRouter token prices use `/1M tokens`, searches
  use `/1K searches`, and request/image prices retain their respective units.
  Unknown OpenRouter monetary leaves use `/unit unknown`. Newly added and
  removed prices are included. For an unregistered, mixed-unit provider this
  classification and unit are best-effort; see the Abacus caveat under
  Configuration.
  - **In HTML only,** the normalized figure *leads*: it is the value in the cell, the unit moves to its own column, and the raw provider value is available on demand — in the cell's tooltip, and inline via the page's "Show raw values" toggle (see below), which is on by default in the full-detail companion. The HTML Change Summary follows the same order.
  - **Text and markdown still lead with the raw value**, in the form `2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)`, and have no toggle. They are the audit formats; the literal value a provider published is what they exist to record.
- **New structured fields** expand nested objects and object lists into readable leaf-level changes in human reports
- **Parameter-name lists** recognized by the provider profile show sorted added/removed names and unique size transitions in scan reports, history, changes, Activity, endpoint histories, and raw-evidence summaries. Ordering and duplicate-only differences produce no primary human row; stored records and JSON retain the original evidence. Missing, null, and malformed operands remain neutral, while a valid empty list is a known set. Name lists establish membership only; supplied parameter-attribute objects retain their named leaf changes.
- **Other list fields** retain their existing member comparison; parameter-set semantics do not apply to arbitrary arrays or ordered pricing policies.
- **Context and limit fields** use human-readable number formatting
- **All field changes** are grouped by category: Pricing, Context & Limits, Parameters, Capabilities, Other
- **A column too narrow for a real value prints a bounded sentinel, never a false zero.** A movement smaller than the price column can show reads `<$0.0001` or `+<$0.0001`, and a percentage below the row's precision reads `↑ <0.1%`. The consequence is deliberate: a displayed row need not visibly add up (`$2.00 → $2.00 +<$0.0001`), because each cell states something true even where the arithmetic is not legible at the printed width. The alternative — rounding to `$0.0000` and `0.0%` — states something false.
- **Repetitive list changes** affecting at least three models are consolidated into one bulk-change entry in default reports. List-size differences are ignored when the actual additions/removals match.
- **Scalar and mixed changes remain model-specific**, so pricing, limits, cutoffs, and models with any additional visible change retain individual entries.
- Bulk entries aggregate their squelched changes and expose expandable model lists in HTML. The HTML Change Summary uses the same bulk entries plus one provider-level squelched rollup.

Endpoint histories distinguish displayed changes from loaded recorded rows when
parameter no-ops are hidden. A truncated page still states that older records
are not shown, including when every loaded record is a human no-op.

### Alias Check and Provider Endpoints

For a provider whose profile supports endpoint capture (currently
OpenRouter), every successful scan, saved or compare-only, also compares each
catalog alias (a model whose `alias_target` names another catalog model) with
the model its alias chain resolves to, on the price leaves both resolve to the
same unit. The comparison runs on the scan's selected baseline snapshot and the
current catalog, so an alias divergence is `new`, `changed`, `persisting`, or
`resolved` (a retargeted alias names both targets), and is `unavailable` when
the alias, its target, or the previously divergent prices can no longer be
compared. On a first save every current divergence is `new`. A saved scan
also checks which endpoints of the target's captured list carry the alias's
prices; such a match is a claim about the named prices only, and the report
never says that no endpoint matches while any endpoint could not be checked.

Text and Markdown append two sections after the catalog report:

- **Alias check** lists `new`, `changed`, and `resolved` divergences with one
  labelled alias-versus-target sentence per differing price, raw value first.
  `--detail all` adds `unavailable` events, prices that could not be compared,
  and why endpoint matching was unavailable.
- **Provider endpoints** leads with the capture's status and counts, how the
  selected baseline's capture was used (a genuine first capture is stated
  separately from a missing or unusable baseline capture), and summary
  clauses counted over every list: lists with price or capability changes, endpoint
  additions and removals, conditional pricing and status changes, persisting
  alias divergences, lists that failed to fetch, lists never requested
  because the endpoint fetch budget ran out, mapping failures, and
  comparison gaps.
  "No endpoint changes" is stated only for lists that were actually compared.
  Persisting alias divergences come next, then changed lists: lists are
  grouped by the comparison unit of their first moved price in profile order
  and ranked within a unit by their largest move, and lists with no comparable
  price move follow in path order. Default detail shows price, endpoint
  presence, conditional pricing, and provider-selected capability changes for at most 25 lists and states
  how many were omitted; `--detail all` shows every list with its metadata
  and status changes, the raw conditional-pricing JSON, comparison gaps, and
  failed lists. Endpoint fields are classified strictly: a monetary-looking
  field the profile has no price rule for is shown as a neutral value, not a
  price. Endpoint field labels describe the endpoint, so an endpoint's own
  `context_length` reads `Context length`, without the catalog's `(model)`
  qualifier.

Capability selection belongs to the provider profile: parameter membership,
Parameters and Capabilities categories, supplied defaults, architecture, and
implicit caching are included by default. Pricing, conditional selectors,
status, and Context & Limits retain their existing routing. Supplied objects
expand into named leaf transitions; descendant capability patterns apply even
when their parent first appears or disappears. Expansion stops at recognized
parameter-name fields at every nesting depth, keeping malformed operands
neutral. Parameter reorder/duplicate-only changes
leave no empty list heading in either report. The capability summary counts
each changed list once before the display cap, even when multiple endpoints,
fields, or catalog models share that list. Raw JSON and saved evidence remain
unchanged.

The HTML report follows the same sections and policy (see HTML
Auto-Reports): `new`, `changed`, and `resolved` alias events follow the Price
Movement card, and everything else sits in a closed `Provider endpoints`
disclosure.
`--detail squelched` omits both sections. JSON output adds optional top-level
`alias_checks` and `endpoint_captures` maps, keyed by provider ID and present
only when that data exists; `endpoint_captures` carries the capture summary
without its lists, with every change and comparison gap, and each change's
`price_evidence` (normalized display, unit, and comparison group). Neither
map changes the `providers` payload.

Endpoint changes and alias events never count as catalog changes: they do not
create managed report artifacts, trigger notifications, or enter model counts
or Price Movement. They still appear on stdout and in an explicit `--output`
file, and in a managed report that catalog changes created.

### Conditional Pricing Policies

When a provider publishes `pricing.overrides`, human reports interpret the
parent list as one pricing policy instead of flattening selectors into apparent
money fields. The report chooses one conservative presentation:

- **Grouped schedule:** proven, non-overlapping UTC regions with complete
  effective rate vectors are collapsed into base/default, scheduled, and peak
  bands.
- **Ordered rules:** understood conditions remain in provider source order.
  Every cell distinguishes an explicit price from `not set by this rule`, and
  the report notes that later matching rules win per price key.
- **Raw fallback:** an unsupported or ambiguous selector, price, unit, or
  precedence relationship keeps the canonical stored parent evidence visible
  and makes no schedule-direction claim.

OpenRouter time predicates are evaluated against the request instant's UTC
civil weekday and clock. Windows are half-open (start inclusive, end
exclusive); a window whose start is later than its end covers the two portions
of each selected UTC day, not a locally converted schedule. A threshold such
as `Prompt > 200,000 tokens` is strictly greater than the stated count.

The displayed base, scheduled, and peak figures are provider-advertised catalog
rates. They do not predict which endpoint OpenRouter will route an actual
request to or the amount that will ultimately be billed; actual routing and
billing can vary.

Every model with bucketed directional, coverage, or conditional movement gets
exactly one of five fixed Price Movement buckets: Higher only, Lower only,
Both directions, Added/removed only, or `Conditional / variable`. A model with
a conditional policy stays in that exclusive bucket even when the event also
contains an ordinary price fact. Reports with ordinary directional models keep
the ordinary higher/lower/mixed verdict and append
`conditional pricing also changed`; a conditional-only population instead
leads with `conditional pricing changed`.

The panel's accounting comes from the same event record as the policy block.
It distinguishes changed conditional policies (or schedule events in a range),
source rules, price dimensions, and effective rate bands from direct price
fields. A matched top-level base-price change absorbed into the policy is still
counted once as a direct/base price fact, not repeated as a scalar row.
Semantically unchanged or unresolved direct prices appear only in the neutral
`unchanged/unknown` field tally: they do not create a sixth model bucket.

### Color Semantics

**Wherever an HTML report states a field change, color carries one meaning and only one: cost.** Red/salmon marks a price going up, green a price going down. Nothing that reports a change is allowed to borrow those two colors, so a red change cell always means "this got more expensive" and a green one always means "this got cheaper" — a reader never has to check which axis a color is on. This holds in all three HTML documents: the scan report's model cards, its automatically generated `_full.html` companion, and the standalone `changes` report's change table — plus the Price Movement card and the Change Summary in each.

Everything else takes a non-cost color: capacity changes (context windows, output limits) are amber, capability changes are blue, a disabled capability and purely informational changes are dim, list membership is blue for a member arriving and dim for one leaving (in every card type and in the `changes` report alike), and a price field appearing or disappearing is the neutral coverage blue — coverage is not a direction, and painting an added price red would claim a price rise that was never measured. Violet marks a **reference price** and nothing else: an alias's and its target's catalog prices in the Alias check and on its price strips and ladders, and the endpoint prices that equal them. A reference price is a point of comparison, not a change, so violet never appears on a change row or in the Change Summary.

Two things outside that vocabulary still use red and green, and neither reports a field change: **run status** — a provider card and its badge are green when clean and red when the fetch failed, and an error message is red — and the **added/removed model lists**, where a whole model arriving is green and one departing is red. Both are presence-or-health signals about the scan itself rather than statements about a value moving, and neither appears in a change table, a model card row, or the Change Summary.

Bulk consolidation applies only to the default human-readable report. `--detail all`, the automatically generated full-detail HTML companion, and JSON output remain ungrouped and full fidelity.

### HTML Auto-Reports

When a scan detects changes and is writing a report to the configured report
directory (the notification flow), Model Sentinel automatically generates a
self-contained HTML companion report alongside the primary text, JSON, or
Markdown report. An explicit `--output` writes only that requested format.

The HTML report uses a dark industrial theme and has no external dependencies and no JavaScript — all CSS is inlined, and every interactive affordance is built from native `<details>`, `:target` and `:has()`.

**The Price Movement card comes first.** Its ordinary directional verdict is
derived from affected models, with conditional movement reported alone or as a
suffix when present. Eligible absolute headlines name the largest comparable
increase and decrease. Separate tallies reconcile model-bucket totals,
direct/base price fields, and conditional structure (policy or event, rules,
dimensions, and effective bands). Bucketed affected models are grouped by the
five fixed movement buckets—higher, lower, both, coverage, and
conditional/variable—and zero-count groups are omitted. Neutral-only
unchanged or unresolved direct-price models contribute field tallies without
model-bucket membership.

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

**The two companions link to each other.** The concise report's header carries a `Full-detail report →` link and the full-detail report's header carries `← Concise report`, placed after the `Show raw values` checkbox. Each link is a relative filename in the same report directory, so the pair can be moved or opened together and still navigate. The links use the same dim navigation styling as the card `↑` back-link rather than a change color, and they appear only in the auto-generated pair: a report written with `--output` has no companion and no link.

**Alias events follow the Price Movement card.** For a provider with alias
checks (see Alias Check and Provider Endpoints), an `Alias check` card lists
`new`, `changed`, and `resolved` divergences; the full-detail companion adds
`unavailable` events and prices that could not be compared. A divergence
(new, changed, or persisting) is a **rate card**: one row per differing price
with the alias's and the target's normalized figures (the raw provider values
on the `Show raw values` sub-line) and, when the target's endpoint list was
captured in this scan, a compact **price strip** of that list on a log scale:
a dot per endpoint price, the alias's solid triangle above the track, the
target's hollow diamond below it, and the low and high prices at its ends.
Other events keep one labelled sentence per price. Divergences are not price
moves, so the card never uses red or green; the alias and target are
reference prices and take the reference violet (see Color Semantics).

The full **price ladders** sit in a closed `Endpoint prices for …` disclosure
under each rate card, open by default in the full-detail companion. Each
ladder is a static SVG under a heading naming its price and unit, with a dot
per endpoint price and the two labelled reference marks; an endpoint dot that
shares the alias's or target's price is violet too. Coincident or crowded
labels move to separate rows instead of overlapping, the ladder keeps a
legible size and scrolls inside its frame on a narrow screen, and each ladder
is an accessible image whose title names it and whose caption lists every
placed price low to high, plus any endpoint that could not be placed (free,
missing, or in another unit). The caption rows carrying the alias or target
price lead with it and are banded so they stand out of the list. A leaf no
endpoint carries gets no ladder, and its strip cell says so.

**Endpoint detail is one closed disclosure.** `Provider endpoints` sits after
`Other changes`, closed in both companions, and its summary line carries the
same uncapped clauses as the text report. Inside are the capture and baseline
facts, persisting alias divergences, then each changed list: an
endpoint-price table (endpoint, one column per resolved price with its unit in
the header, and the change), with each cell's raw provider value in its
tooltip and on the `Show raw values` sub-line, and a separate table of selected
capability changes in the model cards' column layout. Full detail adds remaining
metadata and status changes to that table. Price
cells use the cost colors; an endpoint added or removed, or a price appearing,
is coverage blue. The concise report shows at most 25 lists; when lists are
omitted, or only the full report can show them, its note links to the
full-detail companion's `#provider-endpoints`, and the full-detail disclosure
links back to the concise one. `--detail squelched` omits both additions, and
a report without endpoint or alias data is unchanged.

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

1. choose environment credentials in `~/.model_sentinel/launchd.env`, or configure file mode in `settings.env` and explicitly refresh the private cache; keep unrelated exports in `launchd.env`
2. edit `~/.model_sentinel/install_launchd.sh` if you want to change the schedule or command
3. run `~/.model_sentinel/install_launchd.sh install`

Rerun the runtime-home installer after schedule or command edits to reload the
LaunchAgent. Edits to `launchd.env` take effect on the next run without reload.

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

`settings.env` controls the policy: `MODEL_SENTINEL_NOTIFY_DEFAULT` turns
notifications on or off, `MODEL_SENTINEL_NOTIFY_ON` selects `changes`,
`errors`, `both`, or `never`, `MODEL_SENTINEL_NOTIFY_OPEN_TARGET` makes a click
open the report `file` or its `folder`, and `MODEL_SENTINEL_NOTIFY_SOUND` names
the sound. `scan --notify` or `scan --no-notify` overrides
`MODEL_SENTINEL_NOTIFY_DEFAULT` for one run; neither overrides
`MODEL_SENTINEL_NOTIFY_ON=never`.

When notifications fire and you did not explicitly supply `--output`, Model Sentinel writes a report into the configured report directory so the alert has a concrete artifact to point at.

## Testing

Create or activate a project virtual environment, install the development
dependencies, install Chromium once per machine, and run the complete project
test suite from this directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest
```

The Playwright browser smoke suite is part of the ordinary test run. It is not
silently skipped when Chromium is unavailable; install the browser dependency
before running the suite.

For isolated Hosts visual acceptance, create a new or empty directory outside
all repository checkouts, then run `.venv/bin/python -m
tests.hosts_validation_fixture /private/tmp/synthetic-hosts-runtime`. The builder
rejects occupied and repository-contained paths, including filesystem aliases,
and prints the resolved runtime path. Use it as `MODEL_SENTINEL_HOME` for
`browse --no-open --view hosts --port 0`. Its newest capture is intentionally
empty; select the first capture (2026-09-01) to inspect the synthetic comparison
cases. Stop the server before removing that exact temporary runtime directory.

## Documents

- [`docs/hosts_and_endpoints.md`](./docs/hosts_and_endpoints.md) — developer contracts for endpoint capture, storage, APIs, and Hosts state.

- [`docs/LAUNCHD.md`](./docs/LAUNCHD.md)
