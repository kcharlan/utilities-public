# Decision Ladder

Decision Ladder builds an offline status page from the JevBench feed published by
[Benchmark Heaven](https://benchmarkheaven.com/). It shows the data age,
revision, method, official caps and measurement counts. It states facts and
makes no recommendation.

Install [uv](https://docs.astral.sh/uv/) (`brew install uv`), then run
`decision_ladder`. The first invocation may resolve its Python environment.

```
decision_ladder [refresh|build] [--no-refresh] [--no-open] [--output PATH] [--version]
```

The default command fetches when there is no snapshot or the newest check is
older than `max_age_hours`, then builds and opens the page. `refresh` always
fetches; `build` and `--no-refresh` never fetch. `--no-open` suppresses the
browser; `--output` selects the output file. A failed fetch uses the newest
snapshot if one exists. A refresh makes one request to Benchmark Heaven.

The runtime home is `~/.decision_ladder/` (override `DECISION_LADDER_HOME`),
with directories mode 0700 and files mode 0600. `config.json` sets
`max_age_hours` (default 24, maximum 87600); `snapshots/` retains the newest
60 distinct feeds and `decision_ladder.html` is replaced atomically. Fetched
data stays in this private runtime home. Data licensing has not been checked.

Prices other than published tariffs and listings are estimates. Latency may
include an assumed adjustment; the feed has no confidence intervals. The
official caps and methodology come from the feed.

Tests use invented data and do not contact the provider:

```
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py decision_ladder
node tools/sync_frontend_vendor.mjs --check decision_ladder/decision_ladder
UV_PYTHON_DOWNLOADS=never ./decision_ladder/decision_ladder --help
```

## Board and comparisons

The board groups ranked systems into Capability tiers, rounding to whole points
by default; decimal mode uses the feed's scores. Within a tier, price, latency,
and name determine order. Adjustable cost and median latency caps default to the
feed's official limits. Systems missing either value are outside the caps. The
frontier shows systems not dominated on Capability and the selected price or
latency axis; it is descriptive and does not create a weighted score.

The Compare tab shows up to eight chosen systems and their axis scores, official
ranks, prices, latency, sources and measurement details. Not ranked lists the
feed's excluded systems and reasons. The Changes panel compares the newest
snapshot with the last snapshot that differs in displayed data. When the scoring
mode changes, the comparison uses the newest visible difference in that mode.
Reference and other boards appear in All with diamond chart markers; their board
labels retain their identity. When the scoring method changes, earlier and later
scores are not comparable. Price estimates
are marked `est.` and assumed latency is marked `assumed`; dashed chart markers
indicate modelled values.

## Deploy

From merged `main`, preview and install the direct copy:

```
node tools/deploy_copies.mjs --only decision_ladder --dry-run
node tools/deploy_copies.mjs --only decision_ladder
```

The installed command is `~/Library/Scripts/decision_ladder`; repository updates
do not update that copy. Deployment requires separate authorization.

The JavaScript math tests are also run with
`node --test "decision_ladder/tests/js/*.test.mjs"`. JevBench data is provided
by Benchmark Heaven; the feed's terms and data licence have not been verified.
The page reports the published data and its limits, not recommendations.
