# cron-eval repo-task example

This benchmark asks a model to implement `cron_eval.py`, a standard-library cron expression evaluator. A deterministic hidden suite grades 100 cases across field parsing, steps, lists and ranges, DOM/DOW interaction, `L` and `W`, calendar edges, timezones and DST, and error handling. The adjudicator explains the fixed validator score; it does not rescore the result.

## Setup

Create or select a git repository that will receive the model changes, then set:

```bash
export BENCH_CRON_EVAL_SOURCE_REPO=/absolute/path/to/cron-eval-source
```

The source repository needs at least one commit because the runner creates git worktrees from `HEAD`.

Before running, also update `output_dir` in `bench.yaml`. The checked-in value documents the intended `BENCH_CRON_EVAL_OUTPUT_DIR` override and fallback, but it uses shell-style `${NAME:-default}` syntax; the current manifest expander supports only `$NAME` and `${NAME}`. Use either a direct path:

```yaml
output_dir: ~/Documents/benchmark-llm/cron-eval
```

or a plain environment reference:

```yaml
output_dir: ${BENCH_CRON_EVAL_OUTPUT_DIR}
```

and export `BENCH_CRON_EVAL_OUTPUT_DIR` before running.

The model invocation script uses `opencode`. The adjudication script defaults to `cx exec` through `zsh -lic`, so the `cx` wrapper must be available to a login shell. Override it with `BENCH_CRON_EVAL_ADJUDICATOR_BIN`; optionally set `BENCH_CRON_EVAL_ADJUDICATOR_MODEL` and `BENCH_CRON_EVAL_ADJUDICATOR_ARGS`.

## Run

From the `benchmark-llm` directory:

```bash
./bench run examples/cron-eval -m openrouter/example/model
```

For a model sweep:

```bash
./bench run examples/cron-eval -m @examples/cron-eval/models-openrouter.txt
```

`bench.yaml` runs every requested model three times in breadth order. Each attempt gets a `bench/cron-eval/<model-slug>/<timestamp>__aNN` branch in the source repository. Successful worktree checkouts are removed after their outputs are committed, while the branches remain for inspection.

Run artifacts are written beneath the configured `output_dir`. Each successful run contains deterministic score and validation artifacts plus `report.md`; after the batch, the same adjudication command creates `summary.md` in the output root.

## Benchmark contract

The model sees `prompt.txt` and the files under `visible/`. In particular, `visible/spec.md` is the authoritative cron dialect and `visible/starter_test.py` is only a small smoke suite. Hidden fixtures, the reference implementation, and the rubric are staged for validation and are not copied into the model workspace.
