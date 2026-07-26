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
