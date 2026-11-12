# Model Ladder

Model Ladder compares the effort levels of AI models by their Artificial Analysis
available index scores and by what one task costs. One command fetches the
current data and builds a single offline page with:

- an index selector for the Intelligence Index and available domain indexes;
  Coding and Agentic appear when the API supplies scores for them;
- an all-models view: every model scored in the selected index, the overall frontier, and a sortable
  table filterable by creator and by text (matching creator, family or the full
  model name, so tags are searchable);
- a compare view for the model families you pick: an effort ladder per family
  (in fixed effort order from the highest level to the lowest; this table is not
  header-sortable, the other tables sort by header), a whole-point Pareto ladder, what one step
  up or down costs, and plain sentences stating what the numbers show;
- a status strip with the age of the data, the index version, the request quota
  left, and a panel listing what changed. It compares the newest snapshot with the
  most recent older one that differs in what the page shows (index version, an
  added or removed model, any index score or cost), so a refetch that changes only fields
  the page does not use leaves the last real change visible.

The page states facts. It makes no recommendation. Same data in, same page out.

## Indexes and cost

The API supplies cost per task for the Intelligence Index run only. Other indexes
pair their scores with that borrowed cost; the page marks costs and frontiers accordingly.
Models without a score in the selected index remain selected with an unscored chip.
Individual unscored effort levels show `No score`, and a note lists the omitted levels.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (`brew install uv`). The launcher is
   a single uv script with no other dependencies; the first run resolves its
   interpreter.
2. Create a free Artificial Analysis API key on their site.
3. Give the tool the key in one of two ways:
   - set the environment variable `MODEL_LADDER_AA_KEY`; or
   - store the key in a 1Password Login item and put that item's name in
     `~/.model_ladder/config.json` as `op_item`. This needs the
     [1Password CLI](https://developer.1password.com/docs/cli/get-started/)
     (`op`) at `/opt/homebrew/bin/op` or `/usr/local/bin/op`, with 1Password open
     and unlocked and **Settings, Developer, Integrate with 1Password CLI**
     enabled. Optional `op_vault` selects a vault and `op_field` names the field
     (default `credential`).

The key is read at fetch time and held in memory only. It is never logged,
written to disk, placed on a command line or embedded in the page.

## Commands

```
model_ladder [refresh|build] [--no-refresh] [--no-open] [--output PATH] [--version]
```

| Command | What it does |
| --- | --- |
| `model_ladder` | Fetches if the newest snapshot is older than `max_age_hours` (or missing), builds the page, opens it. |
| `model_ladder refresh` | Always fetches, then builds and opens. |
| `model_ladder build` | Builds from the newest snapshot; never fetches. |
| `--no-refresh` | Never fetch, even if the data is old. |
| `--no-open` | Do not open the page in a browser. |
| `--output PATH` | Write the page there instead of the runtime home. |
| `--version` | Print the version. |

Each slow step announces itself on stdout before it starts. Stderr carries only
problems.

If a fetch fails (no key, network error, HTTP error, quota used up) and a
snapshot exists, the command says why and builds from the snapshot; the page
shows the age of the data it actually holds. It exits non-zero only when there
is no snapshot to build from.

## Quota

The free tier allows 100 requests per fixed 24-hour window. A full fetch costs 4
requests (four pages). The command prints the requests remaining and the reset
time from the response headers after each fetch. Automatic refresh happens only
when the newest data is older than `max_age_hours` (default 12). The API serves
current data only; Model Ladder keeps its own snapshots.

## Whole points

The analysis works in whole index points: every comparison uses the index rounded
to the nearest whole point, halves rounding up, computed in integer tenths. For
example, two invented settings of "Example Model" that score 61.8 and 62.2 are both 62, so they
are not separate steps. On the Pareto ladder the cheaper of the two is on the
frontier and the other is marked as dominated, with the reason that the cheaper one
scores the same for less. The decimal is shown small and muted beside each whole
number, and a "Whole points / Decimals" switch reruns the same logic on raw
values. Costs are not rounded for arithmetic.

Rows with no cost per task (missing, `null` or 0) stay on effort ladders with the
cost blank but are left out of the Pareto and step-cost calculations.

## Names, effort levels and "Needs attention"

The data has no structured field for effort or family, so both come from the
model name, once, in Python. A name ending in one parenthesised group has its
family before the group; the group is split on commas into words. A word equal
to one of `max, xhigh, high, medium, low, minimal` (any case) is the row's effort;
the word `Non-reasoning` places the row below every effort level; other words are
kept as tags and shown beside the name.

"Needs attention" lists scored models the rule cannot place: a name with more
than one parenthesised group, a name with two effort words, or two models of the
same maker and family that share one effort level. They are never guessed or
dropped: they stay in the all-models table under their full name and are left out
of effort ladders. The fix is a visible row, or one word added to the vocabulary
in the launcher.

## Runtime home

`~/.model_ladder/` (override with `MODEL_LADDER_HOME`), directory mode 0700,
files 0600:

- `config.json`: written on first run. Keys `op_item`, `op_vault`, `op_field`,
  `max_age_hours` (a positive number of hours, at most 87600, ten years).
- `snapshots/<UTC timestamp>.json.gz` (directory mode 0700): each fetch as
  delivered, newest 60 kept.
- `model_ladder.html`: the built page, replaced atomically.

Nothing is written inside the repository.

## Tests

No test contacts Artificial Analysis or runs `op`. From the repository root:

```
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py model_ladder
node --test "model_ladder/tests/js/*.test.mjs"
node tools/sync_frontend_vendor.mjs --check model_ladder/model_ladder
UV_PYTHON_DOWNLOADS=never ./model_ladder/model_ladder --help
```

The first covers the unit, launcher and Chromium browser tests, all on invented
data. A real `refresh` contacts Artificial Analysis and uses the API key; run it
yourself when you want live data.

## Deploy

Commit on `main`, then:

```
node tools/deploy_copies.mjs --only model_ladder --dry-run
node tools/deploy_copies.mjs --only model_ladder
```

The installed command is `~/Library/Scripts/model_ladder`. Repository updates do
not update it; deploy again after changes.

## Attribution and data

Data is provided by [Artificial Analysis](https://artificialanalysis.ai/) and is
shown with attribution. Redistribution needs their permission, so fetched data
stays in the runtime home and must never be committed to this repository.
