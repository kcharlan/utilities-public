# cron-eval repo-task example

This benchmark asks a model to implement `cron_eval.py`, a standard-library cron expression evaluator. Set `BENCH_CRON_EVAL_SOURCE_REPO=/Users/example/source/cron-eval-beta` before running real models.

Runs land on `bench/cron-eval/<model-slug>/<timestamp>__aNN` branches in the source repo and write artifacts to `${BENCH_CRON_EVAL_OUTPUT_DIR:-~/Documents/benchmark-llm/cron-eval}`.
