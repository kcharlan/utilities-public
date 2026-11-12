# Decision Ladder

Decision Ladder builds an offline page from the JevBench feed published by
[Benchmark Heaven](https://benchmarkheaven.com/). It reports the published data
and its limits without making recommendations.

## What the page shows

The page shows data age, revision, method, official caps, measurement counts,
and a capability board and chart. The Changes panel compares the newest snapshot
with the last snapshot that differs in displayed data for the selected scoring
mode. When the scoring method changes, earlier and later scores are not
comparable. Not ranked lists excluded systems, their listing and reasons, with
a text filter.

## Setup

Install [uv](https://docs.astral.sh/uv/) (`brew install uv`), then run
`decision_ladder`. The first invocation may resolve its Python environment.

## Commands

| Command | Effect |
| --- | --- |
| `decision_ladder` | Fetch if no snapshot exists or the latest check exceeds `max_age_hours`, then build and open the page. |
| `decision_ladder refresh` | Fetch, then build and open the page. |
| `decision_ladder build` | Build from the latest snapshot without fetching. |
| `--no-refresh` | Build without fetching. |
| `--no-open` | Do not open the browser. |
| `--output PATH` | Write the page to the selected path. |
| `--version` | Print the version. |

A refresh makes one request to Benchmark Heaven. If fetching fails, the newest
snapshot is used when available.

## Tiers and caps

The board groups ranked systems into Capability tiers, rounding to whole points
by default; decimal mode uses the feed's scores. Within a tier, price, latency,
and name determine order. Tiers expand until at least 25 systems are shown;
later tiers start collapsed. Adjustable cost and median latency caps default to
the feed's official limits. Systems missing either value are outside the caps.
The frontier shows systems not dominated on Capability and the selected price
or latency axis; it is descriptive and does not create a weighted score.
Frontier-only filtering is off by default.

Chart circles represent open weights, squares hosted APIs, and diamonds
Reference and other boards. Filled markers indicate the frontier; dark outlines
indicate published prices or end-to-end measured latency. Zero and unavailable
values cannot be plotted on a logarithmic axis.

## Estimates and assumed latency

Prices other than published tariffs and listings are estimates. Latency may
include an assumed adjustment; the feed has no confidence intervals. Price
estimates are marked `est.` and assumed latency is marked `assumed`. The
official caps and methodology come from the feed.

## Compare

Compare shows up to eight selected systems and their axis scores, official
ranks, prices, latency, sources and measurement details. Best-value marks
identify the highest or lowest selected values in each row; they add no score.

## Runtime home

The runtime home is `~/.decision_ladder/` (override `DECISION_LADDER_HOME`),
with directories mode 0700 and files mode 0600. `config.json` sets
`max_age_hours` (default 24, maximum 87600); `snapshots/` retains the newest
60 distinct feeds and `decision_ladder.html` is replaced atomically. Fetched
data stays in this private runtime home.

## Tests

Tests use invented data and do not contact the provider. From the repository root:

```
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py decision_ladder
node --test "decision_ladder/tests/js/*.test.mjs"
node tools/sync_frontend_vendor.mjs --check decision_ladder/decision_ladder
UV_PYTHON_DOWNLOADS=never ./decision_ladder/decision_ladder --help
```

## Deploy

From merged `main`, preview and install the direct copy:

```
node tools/deploy_copies.mjs --only decision_ladder --dry-run
node tools/deploy_copies.mjs --only decision_ladder
```

The installed command is `~/Library/Scripts/decision_ladder`; repository updates
do not update that copy. Deployment requires separate authorization.

## Attribution and data limits

JevBench data is provided by Benchmark Heaven; the feed's terms and data licence
have not been verified. The page reports published data and its limits, not
recommendations.
