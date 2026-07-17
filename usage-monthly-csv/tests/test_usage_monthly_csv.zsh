#!/usr/bin/env zsh
set -euo pipefail

SCRIPT=${SCRIPT:-${0:A:h:h}/usage-monthly-csv}
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
mkdir -p "$TMPDIR/bin" "$TMPDIR/out"

cat <<'STUB' >"$TMPDIR/bin/npx"
#!/usr/bin/env zsh
set -eu
if [[ "${1:-}" == "--yes" ]]; then
  shift
fi
package=$1
subcommand=$2
command=$3
format=$4
shift 4

[[ "$package" == "ccusage@latest" ]] || { print -u2 -- "unexpected package: $package"; exit 1; }
[[ "$subcommand" == "claude" || "$subcommand" == "codex" ]] || { print -u2 -- "unexpected subcommand: $subcommand"; exit 1; }
[[ "$command" == "daily" ]] || { print -u2 -- "unexpected command: $command"; exit 1; }
[[ "$format" == "--json" ]] || { print -u2 -- "unexpected format: $format"; exit 1; }

since=""
until=""
while (( $# > 0 )); do
  case "$1" in
    --since)
      since=$2
      shift 2
      ;;
    --until)
      until=$2
      shift 2
      ;;
    *)
      print -u2 -- "unexpected arg: $1"
      exit 1
      ;;
  esac
done

case "$subcommand:$since:$until" in
  claude:20260401:20260430)
    cat <<'EOF'
{"daily":[{"date":"2026-04-01","inputTokens":1,"outputTokens":2,"cacheCreationTokens":3,"cacheReadTokens":4,"totalTokens":5,"totalCost":6}],"totals":{}}
EOF
    ;;
  codex:20260401:20260430)
    cat <<'EOF'
{"daily":[{"date":"2026-04-01","inputTokens":10,"cachedInputTokens":20,"outputTokens":30,"reasoningOutputTokens":40,"totalTokens":50,"costUSD":60}],"totals":{}}
EOF
    ;;
  claude:20260501:20260531)
    print -- '[]'
    ;;
  codex:20260501:20260531)
    cat <<'EOF'
{"daily":[],"totals":{}}
EOF
    ;;
  claude:20251201:20251231)
    cat <<'EOF'
[{"date":"2025-12-01","inputTokens":101,"outputTokens":102,"cacheCreationTokens":103,"cacheReadTokens":104,"totalTokens":105,"totalCost":106}]
EOF
    ;;
  codex:20251201:20251231)
    cat <<'EOF'
[{"date":"2025-12-01","inputTokens":110,"cachedInputTokens":120,"outputTokens":130,"reasoningOutputTokens":140,"totalTokens":150,"costUSD":160}]
EOF
    ;;
  claude:20260601:20260630)
    cat <<'EOF'
{"daily":[{"period":"2026-06-01","inputTokens":201,"outputTokens":202,"cacheCreationTokens":203,"cacheReadTokens":204,"totalTokens":205,"totalCost":206}],"totals":{}}
EOF
    ;;
  codex:20260601:20260630)
    cat <<'EOF'
{"daily":[{"date":"2026-06-01","inputTokens":210,"cachedInputTokens":220,"outputTokens":230,"reasoningOutputTokens":240,"totalTokens":250,"costUSD":260}],"totals":{}}
EOF
    ;;
  *)
    print -u2 -- "unexpected subcommand/since/until: $subcommand $since $until"
    exit 1
    ;;
esac
STUB

chmod +x "$TMPDIR/bin/npx"

export PATH="$TMPDIR/bin:$PATH"

fail() {
  print -u2 -- "FAIL: $*"
  exit 1
}

expect_file_contains() {
  local file=$1
  local pattern=$2
  [[ -f "$file" ]] || fail "missing file $file"
  grep -F -- "$pattern" "$file" >/dev/null || fail "expected '$pattern' in $file"
}

expect_file_not_contains() {
  local file=$1
  local pattern=$2
  [[ -f "$file" ]] || fail "missing file $file"
  if grep -F -- "$pattern" "$file" >/dev/null; then
    fail "did not expect '$pattern' in $file"
  fi
}

expect_file_missing() {
  local file=$1
  [[ ! -e "$file" ]] || fail "unexpected file $file"
}

zsh "$SCRIPT" --date 2026-04-10 --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-0426.csv" '"date","inputTokens","outputTokens","cacheCreationTokens","cacheReadTokens","totalTokens","totalCost"'
expect_file_contains "$TMPDIR/out/ccusage-0426.csv" '"2026-04-01",1,2,3,4,5,6'
expect_file_contains "$TMPDIR/out/cusage-0426.csv" '"date","inputTokens","cachedInputTokens","outputTokens","reasoningOutputTokens","totalTokens","costUSD"'
expect_file_contains "$TMPDIR/out/cusage-0426.csv" '"2026-04-01",10,20,30,40,50,60'
expect_file_not_contains "$TMPDIR/out/ccusage-0426.csv" '"agents"'
expect_file_not_contains "$TMPDIR/out/cusage-0426.csv" '"agents"'
expect_file_missing "$TMPDIR/out/ccusage-0326.csv"
expect_file_missing "$TMPDIR/out/cusage-0326.csv"

rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-05-02 --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-0526.csv" '"date","inputTokens","outputTokens","cacheCreationTokens","cacheReadTokens","totalTokens","totalCost"'
expect_file_contains "$TMPDIR/out/cusage-0526.csv" '"date","inputTokens","cachedInputTokens","outputTokens","reasoningOutputTokens","totalTokens","costUSD"'
expect_file_contains "$TMPDIR/out/ccusage-0426.csv" '"2026-04-01",1,2,3,4,5,6'
expect_file_contains "$TMPDIR/out/cusage-0426.csv" '"2026-04-01",10,20,30,40,50,60'

rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-01-10 --prior-month --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-1225.csv" '"2025-12-01",101,102,103,104,105,106'
expect_file_contains "$TMPDIR/out/cusage-1225.csv" '"2025-12-01",110,120,130,140,150,160'
expect_file_missing "$TMPDIR/out/ccusage-0126.csv"
expect_file_missing "$TMPDIR/out/cusage-0126.csv"

rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-06-20 --output-dir "$TMPDIR/custom"
expect_file_contains "$TMPDIR/custom/ccusage-0626.csv" '"2026-06-01",201,202,203,204,205,206'
expect_file_contains "$TMPDIR/custom/cusage-0626.csv" '"2026-06-01",210,220,230,240,250,260'

cat <<'STUB' >"$TMPDIR/bin/npx"
#!/usr/bin/env zsh
set -eu
if [[ "${1:-}" == "--yes" ]]; then
  shift
fi
package=$1
subcommand=$2

[[ "$package" == "ccusage@latest" ]] || { print -u2 -- "unexpected package: $package"; exit 1; }

case "$subcommand" in
  claude)
    cat <<'EOF'
{"daily":[{"date":"2026-04-01","inputTokens":1,"outputTokens":2,"cacheCreationTokens":3,"cacheReadTokens":4,"totalTokens":5,"totalCost":6}],"totals":{}}
EOF
    ;;
  codex)
    cat <<'EOF'
{"daily":[{"date":"Apr 01, 2026","inputTokens":10,"cachedInputTokens":20,"outputTokens":30,"reasoningOutputTokens":40,"totalTokens":50,"costUSD":60}],"totals":{}}
EOF
    ;;
  *)
    print -u2 -- "unexpected subcommand: $subcommand"
    exit 1
    ;;
esac
STUB

chmod +x "$TMPDIR/bin/npx"
rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-04-10 --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-0426.csv" '"2026-04-01",1,2,3,4,5,6'
expect_file_contains "$TMPDIR/out/cusage-0426.csv" '"2026-04-01",10,20,30,40,50,60'
expect_file_not_contains "$TMPDIR/out/cusage-0426.csv" '"Apr 01, 2026",10,20,30,40,50,60'

HELP=$(zsh "$SCRIPT" --help)
print -- "$HELP" | grep -F -- '--output-dir DIR' >/dev/null || fail 'help missing output-dir'
print -- "$HELP" | grep -F -- '--prior-month' >/dev/null || fail 'help missing prior-month'
print -- "$HELP" | grep -F -- 'Defaults:' >/dev/null || fail 'help missing defaults section'
print -- "$HELP" | grep -F -- '2 days' >/dev/null || fail 'help missing boundary default'
print -- "$HELP" | grep -F -- 'Filename pattern: ccusage-MMYY.csv and cusage-MMYY.csv' >/dev/null || fail 'help missing split filename pattern'

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPDIR" "$TMPROOT"' EXIT
mkdir -p "$TMPROOT/home" "$TMPROOT/out"

cat <<'ZSHRC' >"$TMPROOT/home/.zshrc"
ccusage_csv() {
  print -- "ccusage:$*"
}

cusage_csv() {
  print -- "cusage:$*"
}
ZSHRC

HOME="$TMPROOT/home" PATH="/usr/bin:/bin:/usr/sbin:/sbin" zsh "$SCRIPT" --date 2026-04-10 --output-dir "$TMPROOT/out"
expect_file_contains "$TMPROOT/out/ccusage-0426.csv" "ccusage:--since 20260401"
expect_file_contains "$TMPROOT/out/cusage-0426.csv" "cusage:--since 20260401"

print -- 'ok'
