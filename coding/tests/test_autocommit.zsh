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
mkdir -p "$ROOT_DIR/audits"
print owned > "$ROOT_DIR/audits/owned.md"
print staged > "$ROOT_DIR/audits/unrelated-staged.md"
print untracked > "$ROOT_DIR/audits/unrelated.md"
print untracked > "$ROOT_DIR/plans/packet_unrelated.md"
git -C "$ROOT_DIR" add audits/unrelated-staged.md
auto_commit_durable_artifacts 'Record stage' audits/owned.md
[[ $(git -C "$ROOT_DIR" show --format= --name-only HEAD) == audits/owned.md ]] || { print -u2 'stage commit included unrelated artifacts'; exit 1; }
[[ -z $(git -C "$ROOT_DIR" ls-files audits/unrelated.md plans/packet_unrelated.md) ]] || exit 1
[[ $(git -C "$ROOT_DIR" diff --cached --name-only) == $'audits/unrelated-staged.md\nstaged' ]] || exit 1
(
  mkdir -p "$ROOT_DIR/docs"
  DESIGN_DOC="$ROOT_DIR/docs/design.md"
  DESIGN_PACKETIZATION_PLAYBOOK="$ROOT_DIR/docs/packetization.md"
  IMPLEMENTATION_PLAYBOOK="$ROOT_DIR/docs/implementation_packet_playbook.md"
  print design > "$DESIGN_DOC"
  print playbook > "$DESIGN_PACKETIZATION_PLAYBOOK"
  honor_stop_request() { return 0; }
  run_agent_exec() {
    if [[ "$1" == bootstrap ]]; then
      print guide > "$IMPLEMENTATION_PLAYBOOK"
      print packet > "$PLANS_DIR/packet_1.md"
      print status > "$STATUS_MD"
      print -r -- '{"packets":[{"id":"1","doc":"plans/packet_1.md"}]}' > "$STATUS_JSON"
    else
      print packet > "$PLANS_DIR/packet_2.md"
      print planned > "$STATUS_MD"
      print -r -- '{"packets":[{"id":"1","doc":"plans/packet_1.md"},{"id":"2","doc":"plans/packet_2.md"}]}' > "$STATUS_JSON"
    fi
  }
  run_bootstrap
  [[ $(git -C "$ROOT_DIR" show --format= --name-only HEAD) == $'docs/implementation_packet_playbook.md\nplans/packet_1.md\nplans/packet_status.json\nplans/packet_status.md' ]] || exit 1
  run_planner
  [[ $(git -C "$ROOT_DIR" show --format= --name-only HEAD) == $'plans/packet_2.md\nplans/packet_status.json\nplans/packet_status.md' ]] || exit 1
  FULL_TEST_COMMAND=true
  write_full_suite_report() { print report > "$2"; print json > "$3"; }
  update_full_suite_state() { print state > "$FULL_TEST_STATE_JSON"; }
  run_full_suite_verification 'example suite' false
  [[ $(git -C "$ROOT_DIR" show --format= --name-only HEAD) == $'audits/example_suite.json\naudits/example_suite.md\naudits/full_suite_state.json' ]] || exit 1
  highest_validated_packet_id() { print 1; }
  validated_packet_count() { print 1; }
  write_git_change_snapshot() { :; }
  clear_stage_timeout_count() { :; }
  update_drift_audit_state() { print state > "$DRIFT_AUDIT_STATE_JSON"; }
  drift_audit_result_field() {
    case "$2" in
      status) print repair_packet ;;
      repair_packet_id) print 3 ;;
      repair_packet_doc) print plans/packet_3.md ;;
      *) print synthetic ;;
    esac
  }
  run_agent_exec() {
    print report > "$AUDITS_DIR/stage_repair.md"
    print result > "$AUDITS_DIR/stage_repair.json"
    print repair > "$PLANS_DIR/packet_3.md"
    print repaired > "$STATUS_MD"
    print -r -- '{"packets":[{"id":"3","doc":"plans/packet_3.md"}]}' > "$STATUS_JSON"
  }
  run_drift_audit 'stage repair' false
  [[ $(git -C "$ROOT_DIR" show --format= --name-only HEAD) == $'audits/drift_audit_state.json\naudits/stage_repair.json\naudits/stage_repair.md\nplans/packet_3.md\nplans/packet_status.json\nplans/packet_status.md' ]] || exit 1
  [[ -z $(git -C "$ROOT_DIR" ls-files audits/unrelated.md plans/packet_unrelated.md) ]] || exit 1
  [[ $(git -C "$ROOT_DIR" diff --cached --name-only) == $'audits/unrelated-staged.md\nstaged' ]] || exit 1
)
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
