#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

AGENT_CLI=claude \
DESIGN_DOC=docs/git_dashboard_final_spec.md \
AUTO_COMMIT_VALIDATED=true \
PROFILE_STAGES=true \
./scripts/codex_packet_loop.zsh run
