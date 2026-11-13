# Docker Projects

This directory groups the repository's Docker-focused projects. Each child
directory is an independent project; run its helper scripts from that project
directory and read its README before starting it.

## Current Contents

- `actual-data/` - Helper scripts for a local Actual Budget server. Use a
  private operational copy outside a Git worktree for its `/data` directory.
- `docker-disk-compact/` - Zsh utility for reclaiming Docker Desktop disk space on macOS and reporting the true on-disk size of `Docker.raw`.
- `excalidraw/` - Docker Compose setup for a local Excalidraw instance.
- `llm_collector/` - Request-counting browser extension, collector service,
  external-state setup, and container runtime files.
- `llm_proxy/` - Modular, credential-stateless proxy that makes non-standard
  LLM provider APIs speak the OpenAI `/v1/chat/completions` protocol. Bridges
  T3 Chat and ChatJimmy with streaming translation, dynamic model discovery,
  T3 tool-call conversion, and T3 BYOK retry behavior.
- `mermaid/` - Shell scripts for running the Mermaid Live Editor container.
- `n8n-poc/` - Local n8n proof of concept with its encryption key and mutable
  state kept outside the public source tree.
- `webserver/` - Multi-service local web stack (Nginx + FastAPI + Express + index/config UI).

## Propagating Dependency Updates

Stacks deliberately follow moving image tags, and their update scripts just repull
or rebuild. Images are not pinned to digests, so updates arrive without version
tracking.

`propagate-updates.zsh` carries dependency updates from this source tree to the
deployed copy (`~/docker`) and the stacks running from it, in two phases with a
commit in between. Run it from anywhere in the repository:

```bash
docker/propagate-updates.zsh refresh
docker/propagate-updates.zsh deploy
```

- `refresh` changes only repository files. It updates the lockfiles within
  their declared ranges (`npm update --package-lock-only` for
  `webserver/index` and `webserver/app_node`, `uv pip compile --upgrade` for
  `webserver/app_py`, `uv lock --upgrade` for `llm_proxy`) and audits them
  (`npm audit`, `pip-audit`). It then test-builds the images under throwaway
  `propagate-check-*` Compose project names, removes those images, and runs
  both webserver test files and the `llm_proxy` pytest suite. Before the
  webserver tests, it reinstalls `webserver/index/node_modules` from the
  refreshed lock with `npm ci`. The
  routing test never pulls images, and a check build does not leave its base
  images as named local images, so `refresh` first pulls the test's
  `nginx:stable-alpine` and `node:24-alpine` (or the images named by
  `NGINX_TEST_IMAGE` and `NGINX_TEST_NODE_IMAGE`).
  `package.json`, `pyproject.toml` and exact pins are never edited. Review the
  printed diff and commit it.
- `deploy` requires the `main` branch and refuses to run while tracked `docker/` files have uncommitted
  changes. It copies changed tracked files into `~/docker`, backing up each
  replaced file under `~/.utilities-deploy-backups/docker-<timestamp>/`, and
  never deletes or touches local-only files such as `.env`. It then runs the
  committed bundle's `update.sh` for each selected stack that was running,
  confirms the stack is running again, and leaves stopped stacks stopped.
  A running stack without an `update.sh`, or one running
  from a Compose file outside `~/docker`, is reported as needing manual action.
  `llm_collector` is synchronized only by its own `migrate.sh`; when its
  deployed copy differs from source, deploy reports that and skips it.
  Each real deploy creates a private, verified snapshot of the committed
  Docker files under `~/.utilities-deploy-bundles/`. Updaters, Compose files
  and build inputs come from that snapshot; private configuration and mutable
  data continue to come from the deployed directories. Some running containers
  bind snapshot files read-only, so do not remove these snapshots while they
  are in use. After successful deploys, pruning keeps the current snapshot,
  all snapshots referenced by running or stopped containers or Compose
  projects, and the five newest other verified completed snapshots. Failed,
  in-progress, altered and unrecognized snapshots are retained. If reference inspection fails,
  pruning is skipped and a warning is printed.
  Snapshot paths are internal to managed propagation and are not stable paths
  for independently created containers. If independent Docker operations need
  to reference them, pass `--keep-source-bundles` on every deploy to disable
  bundle pruning; reference discovery and deletion are not atomic with those
  independent operations.
  After a successful deploy that made backups, it retains the newest two
  timestamped Docker backup directories by modification time, breaking ties
  by descending name. Failed, unchanged and dry runs do not prune backups.

Both phases accept `--stack NAME` (repeatable) and `--dry-run`. The run exits
non-zero when any stack failed or needs manual action, and prints a summary
with problems first. `PROPAGATE_DEPLOY_ROOT`, `PROPAGATE_BACKUP_ROOT` and
`PROPAGATE_BUNDLE_ROOT` override the deployed copy, backup and source-bundle
snapshot locations. A new top-level project must
be registered in the script's `STACKS` table before deploy will copy it.

## Tests

Run these from the repository root. The Compose contract needs the
`docker-compose` CLI and `jq`; it renders synthetic configuration without
starting containers. The propagation, trusted-updater and n8n tests also
require `jq`, and the propagation and Actual tests use Git. The other scripts
use zsh or Node as indicated and standard system tools; they use stubs instead
of real deployments or network access.

- `zsh docker/tests/test_compose_contract.zsh` — rendered Compose contracts.
- `zsh docker/tests/test_propagate_updates.zsh` — update propagation.
- `zsh docker/tests/test_trusted_updaters.zsh` — trusted updater scripts.
- `zsh docker/tests/test_actual_start.zsh` — Actual start script.
- `zsh docker/tests/test_mermaid_update.zsh` — Mermaid updater.
- `zsh docker/tests/test_n8n_up.zsh` — n8n start script.
- `node --test docker/tests/image-cleanup.test.mjs` — image cleanup commands.

## Local Data and Secrets

This is a public repository. Keep credentials, personal data, and mutable
application state outside the checkout. The projects that need private
configuration provide synthetic templates and document their external runtime
directories. In particular:

- `llm_collector/` stores secrets under `~/.config/llm_collector/` and runtime
  data under `~/.local/state/llm_collector/` by default.
- `n8n-poc/` requires an ignored `.env` whose data directory is outside the
  checkout.
- `webserver/` requires an ignored `.env` pointing at an external webroot.
- `actual-data/` mounts its script directory and refuses Git worktrees; use a
  private operational copy and back up its data.
