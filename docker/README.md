# Docker Projects

This directory groups the repository's Docker-focused projects. Each child
directory is an independent project; run its helper scripts from that project
directory and read its README before starting it.

## Current Contents

- `actual-data/` - Helper scripts for a local Actual Budget server. The scripts
  currently mount this directory as Actual's `/data`; read its privacy warning
  before first use.
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
  the webserver Nginx routing test and the `llm_proxy` pytest suite. The
  routing test never pulls images, and a check build does not leave its base
  images as named local images, so `refresh` first pulls the test's
  `nginx:stable-alpine` and `node:24-alpine` (or the images named by
  `NGINX_TEST_IMAGE` and `NGINX_TEST_NODE_IMAGE`).
  `package.json`, `pyproject.toml` and exact pins are never edited. Review the
  printed diff and commit it.
- `deploy` refuses to run while tracked `docker/` files have uncommitted
  changes. It copies changed tracked files into `~/docker`, backing up each
  replaced file under `~/.utilities-deploy-backups/docker-<timestamp>/`, and
  never deletes or touches local-only files such as `.env`. It then runs the
  deployed `update.sh` for each selected stack that was running, confirms the
  stack is running again from `~/docker`, and leaves stopped stacks stopped.
  A running stack without an `update.sh` (currently `n8n-poc`), or one running
  from a Compose file outside `~/docker`, is reported as needing manual action.
  `llm_collector` is synchronized only by its own `migrate.sh`; when its
  deployed copy differs from source, deploy reports that and skips it.

Both phases accept `--stack NAME` (repeatable) and `--dry-run`. The run exits
non-zero when any stack failed or needs manual action, and prints a summary
with problems first. `PROPAGATE_DEPLOY_ROOT` and `PROPAGATE_BACKUP_ROOT`
override the deployed copy and backup locations. A new top-level project must
be registered in the script's `STACKS` table before deploy will copy it.

The stubbed test suite runs without Docker, the network or real deployments:

```bash
zsh docker/tests/test_propagate_updates.zsh
```

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
- `actual-data/` is the exception: its current scripts mount the project
  directory itself. Do not run them from a public working copy that could make
  generated financial data eligible for accidental staging; use a private
  operational copy and verify `git status` before committing.
