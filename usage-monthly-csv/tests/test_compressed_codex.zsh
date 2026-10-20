#!/usr/bin/env zsh
set -euo pipefail

# A system command that cannot read .jsonl.zst must fail on missing days/totals.
# Run the actual installed command against invented usage only.
SCRIPT=${SCRIPT:-${0:A:h:h}/usage-monthly-csv}
export npm_config_cache=${npm_config_cache:-$HOME/.npm}
export npm_config_offline=true
test_home=$(mktemp -d)
trap 'rm -rf -- "$test_home"' EXIT

# Capture only the named command, never the user's complete shell configuration.
export TEST_CCUSAGE_DEFINITION="$test_home/system-ccusage.zsh"
if system_ccusage=$(command -v ccusage); then
  printf 'ccusage() { %s "$@"; }\n' "${(q)system_ccusage}" > "$TEST_CCUSAGE_DEFINITION"
else
  zsh -ic 'if (( ${+functions[ccusage]} )); then functions ccusage; elif (( ${+aliases[ccusage]} )); then alias -L ccusage; else exit 1; fi' > "$TEST_CCUSAGE_DEFINITION"
fi
export HOME="$test_home/home"
export CODEX_HOME="$HOME/.codex"
export CLAUDE_CONFIG_DIR="$HOME/.claude"
mkdir -p "$test_home/bin" "$CODEX_HOME/sessions" "$CODEX_HOME/archived_sessions" "$CLAUDE_CONFIG_DIR/projects"

# Keep package resolution and pricing offline, and date grouping deterministic.
cat > "$test_home/bin/ccusage" <<'STUB'
#!/usr/bin/env zsh
source "$TEST_CCUSAGE_DEFINITION"
command_line=ccusage
for arg in "$@" --offline --timezone UTC; do
  command_line+=" ${(q)arg}"
done
eval "$command_line"
STUB
chmod +x "$test_home/bin/ccusage"

write_usage() {
  jq -nc --arg timestamp "$1" '{timestamp: $timestamp, type: "event_msg", payload: {
    type: "token_count", info: {model: "gpt-5", last_token_usage: {
      input_tokens: 100, cached_input_tokens: 20, output_tokens: 10,
      reasoning_output_tokens: 0, total_tokens: 110
    }}
  }}'
}

# Mix a live plain session, a compressed session, and a compressed archive.
# The final day has no usage and must not be fabricated as a zero-filled row.
write_usage '2030-04-01T12:00:00Z' > "$CODEX_HOME/sessions/synthetic-plain.jsonl"
for day in 02 03 04 05; do
  write_usage "2030-04-${day}T12:00:00Z"
done | zstd -q -c > "$CODEX_HOME/sessions/synthetic-compressed.jsonl.zst"
for day in 06 07 08 09; do
  write_usage "2030-04-${day}T12:00:00Z"
done | zstd -q -c > "$CODEX_HOME/archived_sessions/synthetic-archive.jsonl.zst"

PATH="$test_home/bin:$PATH" zsh "$SCRIPT" --date 2030-04-20 --output-dir "$test_home/out"
csv="$test_home/out/cusage-0430.csv"
expected_dates=$(printf '"2030-04-%02d"\n' {1..9})
actual_dates=$(tail -n +2 "$csv" | cut -d, -f1)
if [[ "$actual_dates" != "$expected_dates" ]]; then
  print -u2 -- "FAIL: compressed Codex usage dates missing or duplicated"
  print -u2 -- "Expected:\n$expected_dates\nActual:\n$actual_dates"
  exit 1
fi
awk -F, 'NR > 1 { if ($6 != 110) exit 1; total += $6 } END { if (total != 990) exit 1 }' "$csv" || {
  print -u2 -- 'FAIL: compressed Codex usage token totals differ from synthetic inputs'
  exit 1
}
print -- 'ok: compressed Codex usage survives monthly CSV export'
