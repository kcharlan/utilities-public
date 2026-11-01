#!/usr/bin/env zsh
set -euo pipefail
script="${0:A:h:h}/design_orch/scripts/codex_packet_loop.zsh"
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
export HOME="$d/home" ROOT_DIR="$d/repo" AUTO_COMMIT_VALIDATED=true
mkdir -p "$HOME" "$ROOT_DIR/plans"
git -C "$ROOT_DIR" init -q
git -C "$ROOT_DIR" config user.email synthetic@example.invalid
git -C "$ROOT_DIR" config user.name Synthetic
print initial > "$ROOT_DIR/base"
git -C "$ROOT_DIR" add base
git -C "$ROOT_DIR" commit -qm initial
print allowed > "$ROOT_DIR/allowed"
print unrelated > "$ROOT_DIR/unrelated"
print staged > "$ROOT_DIR/staged"
git -C "$ROOT_DIR" add staged
printf '%s\n' '## Allowed Files' '- `allowed`' > "$ROOT_DIR/plans/packet.md"
sed '$d' "$script" > "$d/functions.zsh"
source "$d/functions.zsh"
auto_commit_validated_packet 1 "$ROOT_DIR/plans/packet.md" example
[[ $(git -C "$ROOT_DIR" show --format= --name-only HEAD) == allowed ]] || { print -u2 'commit included unrelated paths'; exit 1; }
[[ -f "$ROOT_DIR/unrelated" && -z $(git -C "$ROOT_DIR" ls-files unrelated) ]] || exit 1
[[ $(git -C "$ROOT_DIR" diff --cached --name-only) == staged ]] || exit 1
mkdir -p "$d/bin"
cat > "$d/bin/agent-stub" <<'EOF'
#!/bin/sh
printf '%s\n' "$@" > "$ARG_LOG"
EOF
chmod +x "$d/bin/agent-stub"
export ARG_LOG="$d/args"
CODEX_COMMAND="$d/bin/agent-stub"
CLAUDE_SONNET_COMMAND="$d/bin/agent-stub"
JSON_PROGRESS_PARSER="${0:A:h:h}/design_orch/scripts/codex_json_progress.py"
monitor_stage_heartbeat() { :; }
print prompt > "$d/prompt"
for AGENT_CLI in codex claude; do
  run_agent_exec stub medium "$d/prompt" "$d/output"
  if grep -E -- '--dangerously|bypassPermissions|--permission-mode|--allowedTools|--ignore-user-config|--ignore-rules' "$ARG_LOG"; then
    print -u2 'agent launch bypassed user permissions'; exit 1
  fi
done
print 'auto-commit safety passed'
