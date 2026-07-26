# design_orch

Reusable design-to-implementation orchestration kit extracted from
`utilities/git-multirepo-dashboard`.

## What it does

The loop:

1. bootstraps a project-specific implementation playbook and packet trackers
   from a design document and `docs/design_doc_packetization_playbook.md`;
2. maintains a planning horizon of narrowly scoped packet documents;
3. implements and validates one packet at a time;
4. periodically runs the configured full test command and cumulative drift
   audit; and
5. writes run events, diagnostics, audit state, and optional stage profiles.

The script supports `bootstrap`, `plan`, `run`, `status`, `stop`, and
`clear-stop` commands. Run `scripts/codex_packet_loop.zsh help` for the full
environment-variable list.

## Included files

- `orch_launch.sh` as a sample launcher for the packet loop
- `scripts/codex_packet_loop.zsh` for the packet orchestration loop
- `scripts/codex_json_progress.py` for progress/event normalization
- `docs/design_doc_packetization_playbook.md` as the packetization prompt and output contract

The loop creates `plans/`, `audits/`, and `automation_logs/` on demand. Those
generated directories are not part of this snapshot.

## Requirements

- zsh
- Python 3
- either the `codex` CLI (the default) or Claude command wrappers configured
  through `CLAUDE_SONNET_COMMAND` and `CLAUDE_OPUS_COMMAND`
- a design document
- a test environment matching `FULL_TEST_COMMAND` (default:
  `.venv/bin/python -m pytest tests -v`)

The loop invokes agents with approval/sandbox bypass flags. Review the script
and run it only in a repository and environment where that access is
appropriate.

## Use in another project

Copy this directory structure into the target repository, then set at least
the design path and test command:

```bash
DESIGN_DOC=docs/my_design.md \
FULL_TEST_COMMAND='my-project-test-command' \
./scripts/codex_packet_loop.zsh bootstrap

DESIGN_DOC=docs/my_design.md \
FULL_TEST_COMMAND='my-project-test-command' \
./scripts/codex_packet_loop.zsh run
```

By default, `ROOT_DIR` is the parent of `scripts/`, so this snapshot's
`scripts/codex_packet_loop.zsh` treats `coding/design_orch/` as its project
root. Override `ROOT_DIR` when the script remains elsewhere.

`orch_launch.sh` is deliberately sample-project-specific: it selects Claude,
enables automatic commits and profiling, and points to
`docs/git_dashboard_final_spec.md`. That design document is not included.
Supply it or replace `DESIGN_DOC` before using the launcher. The packet loop's
own default design path (`docs/cognitive_switchyard_design.md`) is also only a
placeholder in this stripped snapshot.
