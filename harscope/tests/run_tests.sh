#!/usr/bin/env bash
#
# harscope API integration test suite
#
# Usage:
#   ./run_tests.sh <har_file> [port]
#
# Starts a harscope server, loads the HAR file, and runs all 8 tests.
# Exits with code 0 if all tests pass, 1 if any fail.
#
# Examples:
#   ./run_tests.sh ../t3.chat.GPT52Instant.har
#   ./run_tests.sh ../chatgpt.com.GPT52.Instant.har 8333

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HARSCOPE="$SCRIPT_DIR/../harscope"
HAR_FILE="${1:?Usage: $0 <har_file> [port]}"
PORT="${2:-8299}"
BASE="http://127.0.0.1:$PORT"
TMPDIR="$(mktemp -d)"
PASS=0
FAIL=0
SERVER_PID=""

# Resolve HAR_FILE to absolute path
HAR_FILE="$(cd "$(dirname "$HAR_FILE")" && pwd)/$(basename "$HAR_FILE")"

cleanup() {
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    rm -rf "$TMPDIR"
}
trap cleanup EXIT

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }
check() {
    # $1 = description, $2 = expected, $3 = actual
    if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected=$2, got=$3)"; fi
}

# --- Start server ---
echo "Starting harscope on port $PORT..."
"$HARSCOPE" --port "$PORT" > "$TMPDIR/server.log" 2>&1 &
SERVER_PID=$!

# Wait for server to be ready
for i in $(seq 1 20); do
    if curl -s "$BASE/api/status" > /dev/null 2>&1; then break; fi
    sleep 0.5
done

if ! curl -s "$BASE/api/status" > /dev/null 2>&1; then
    echo "ERROR: Server failed to start. Log:"
    cat "$TMPDIR/server.log"
    exit 1
fi

# --- Load HAR file ---
echo "Loading $HAR_FILE..."
LOAD_RESULT=$(curl -s -X POST "$BASE/api/open" \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"$HAR_FILE\"}")
ENTRY_COUNT=$(echo "$LOAD_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['entryCount'])")
echo "Loaded $ENTRY_COUNT entries"
echo ""

# --- Gather findings info ---
SECURITY_JSON="$TMPDIR/security.json"
curl -s "$BASE/api/security" > "$SECURITY_JSON"
FINDING_COUNT=$(python3 -c "import json; print(len(json.load(open('$SECURITY_JSON'))['findings']))")
echo "Security scan found $FINDING_COUNT findings"
echo ""

if [ "$FINDING_COUNT" -eq 0 ]; then
    echo "ERROR: No security findings detected. Cannot run tests. Check the HAR file."
    exit 1
fi

# ============================================================
# TEST 1: All auto-detected findings redacted in export
# ============================================================
echo "=== TEST 1: All auto-detected findings redacted in export ==="
curl -s -X POST "$BASE/api/export/har" -o "$TMPDIR/sanitized.har"

T1_RESULT=$(python3 "$SCRIPT_DIR/verify_redaction.py" \
    "$SECURITY_JSON" "$TMPDIR/sanitized.har" "all_redacted")
check "All findings redacted" "PASS" "$T1_RESULT"

# ============================================================
# TEST 2: EDL export + CLI validation
# ============================================================
echo "=== TEST 2: EDL export + CLI validation ==="
curl -s -X POST "$BASE/api/export/edl" -o "$TMPDIR/sanitized.edl.json"

EDL_COUNT=$(python3 -c "import json; print(len(json.load(open('$TMPDIR/sanitized.edl.json'))['decisions']))")
echo "  EDL has $EDL_COUNT decisions"

VALIDATE_OUTPUT=$("$HARSCOPE" --validate "$TMPDIR/sanitized.har" --edl "$TMPDIR/sanitized.edl.json" 2>&1)
if echo "$VALIDATE_OUTPUT" | grep -q "RESULT: VALID"; then
    pass "EDL validation"
else
    fail "EDL validation"
    echo "$VALIDATE_OUTPUT" | tail -5
fi

# ============================================================
# TEST 3: Toggle auto-redact finding to KEEP
# ============================================================
echo "=== TEST 3: Toggle finding to KEEP ==="

# Pick the first finding
FIRST_ID=$(python3 -c "import json; print(json.load(open('$SECURITY_JSON'))['findings'][0]['id'])")

curl -s -X POST "$BASE/api/security/toggle" \
    -H "Content-Type: application/json" -d "{\"id\": $FIRST_ID}" > /dev/null

# Verify it's toggled off
TOGGLED=$(curl -s "$BASE/api/security" | python3 -c "
import json, sys
data = json.load(sys.stdin)
f = [x for x in data['findings'] if x['id'] == $FIRST_ID][0]
print('off' if not f['redact'] else 'on')
")
check "Finding $FIRST_ID toggled to keep" "off" "$TOGGLED"

# Export and verify that value is NOT redacted
curl -s -X POST "$BASE/api/export/har" -o "$TMPDIR/kept.har"
T3_RESULT=$(python3 "$SCRIPT_DIR/verify_redaction.py" \
    "$SECURITY_JSON" "$TMPDIR/kept.har" "check_kept" "$FIRST_ID")
check "Kept finding value preserved in export" "PASS" "$T3_RESULT"

# Toggle back
curl -s -X POST "$BASE/api/security/toggle" \
    -H "Content-Type: application/json" -d "{\"id\": $FIRST_ID}" > /dev/null

# ============================================================
# TEST 4: Manual redact a non-flagged value
# ============================================================
echo "=== TEST 4: Manual redact non-flagged value ==="

# Find a non-flagged body key to manually redact
MANUAL_INFO=$(python3 "$SCRIPT_DIR/verify_redaction.py" \
    "$SECURITY_JSON" "$HAR_FILE" "find_manual_target")
MANUAL_ENTRY=$(echo "$MANUAL_INFO" | cut -d'|' -f1)
MANUAL_LOC=$(echo "$MANUAL_INFO" | cut -d'|' -f2)
MANUAL_VAL=$(echo "$MANUAL_INFO" | cut -d'|' -f3)
MANUAL_KEY=$(echo "$MANUAL_INFO" | cut -d'|' -f4)

if [ -z "$MANUAL_LOC" ] || [ "$MANUAL_LOC" = "NONE" ]; then
    echo "  SKIP: No suitable non-flagged body key found"
else
    echo "  Target: entry[$MANUAL_ENTRY] key=$MANUAL_KEY"

    # Add manual redaction
    curl -s -X POST "$BASE/api/redaction/manual" \
        -H "Content-Type: application/json" \
        -d "{\"entryIndex\": $MANUAL_ENTRY, \"location\": \"$MANUAL_LOC\", \"value\": \"$MANUAL_VAL\"}" > /dev/null

    # Export and verify redacted
    curl -s -X POST "$BASE/api/export/har" -o "$TMPDIR/manual.har"
    T4A_RESULT=$(python3 "$SCRIPT_DIR/verify_redaction.py" \
        "$SECURITY_JSON" "$TMPDIR/manual.har" "check_manual" "$MANUAL_ENTRY" "$MANUAL_KEY")
    check "Manual redaction applied" "PASS" "$T4A_RESULT"

    # Remove manual redaction
    curl -s -X POST "$BASE/api/redaction/remove-manual" \
        -H "Content-Type: application/json" \
        -d "{\"entryIndex\": $MANUAL_ENTRY, \"location\": \"$MANUAL_LOC\"}" > /dev/null

    # Export and verify NOT redacted
    curl -s -X POST "$BASE/api/export/har" -o "$TMPDIR/unmanual.har"
    T4B_RESULT=$(python3 "$SCRIPT_DIR/verify_redaction.py" \
        "$SECURITY_JSON" "$TMPDIR/unmanual.har" "check_manual_removed" "$MANUAL_ENTRY" "$MANUAL_KEY")
    check "Manual redaction removed" "PASS" "$T4B_RESULT"
fi

# ============================================================
# TEST 5: Bulk deselect by severity
# ============================================================
echo "=== TEST 5: Bulk deselect warnings ==="

HAS_BOTH=$(python3 -c "
import json
data = json.load(open('$SECURITY_JSON'))
sevs = set(f['severity'] for f in data['findings'])
print('yes' if 'warning' in sevs and 'critical' in sevs else 'no')
")

if [ "$HAS_BOTH" = "no" ]; then
    echo "  SKIP: HAR does not have both warning and critical findings"
else
    curl -s -X POST "$BASE/api/security/bulk" \
        -H "Content-Type: application/json" \
        -d '{"action": "deselect", "severity": "warning"}' > /dev/null

    BULK_CHECK=$(curl -s "$BASE/api/security" | python3 -c "
import json, sys
data = json.load(sys.stdin)
w_on = sum(1 for f in data['findings'] if f['severity'] == 'warning' and f['redact'])
c_off = sum(1 for f in data['findings'] if f['severity'] == 'critical' and not f['redact'])
print('PASS' if w_on == 0 and c_off == 0 else 'FAIL')
")
    check "Warnings deselected, criticals kept" "PASS" "$BULK_CHECK"

    # Export and spot-check
    curl -s -X POST "$BASE/api/export/har" -o "$TMPDIR/bulk.har"
    T5_RESULT=$(python3 "$SCRIPT_DIR/verify_redaction.py" \
        "$SECURITY_JSON" "$TMPDIR/bulk.har" "check_bulk")
    check "Export respects bulk toggle" "PASS" "$T5_RESULT"

    # Restore
    curl -s -X POST "$BASE/api/security/bulk" \
        -H "Content-Type: application/json" \
        -d '{"action": "select"}' > /dev/null
fi

# ============================================================
# TEST 6: Mixed EDL round-trip
# ============================================================
echo "=== TEST 6: Mixed EDL round-trip ==="

# Toggle first finding to KEEP
curl -s -X POST "$BASE/api/security/toggle" \
    -H "Content-Type: application/json" -d "{\"id\": $FIRST_ID}" > /dev/null

# Add a manual redaction (reuse from test 4 if available)
if [ -n "$MANUAL_LOC" ] && [ "$MANUAL_LOC" != "NONE" ]; then
    curl -s -X POST "$BASE/api/redaction/manual" \
        -H "Content-Type: application/json" \
        -d "{\"entryIndex\": $MANUAL_ENTRY, \"location\": \"$MANUAL_LOC\", \"value\": \"$MANUAL_VAL\"}" > /dev/null
fi

curl -s -X POST "$BASE/api/export/har" -o "$TMPDIR/mixed.har"
curl -s -X POST "$BASE/api/export/edl" -o "$TMPDIR/mixed.edl.json"

MIXED_VALIDATE=$("$HARSCOPE" --validate "$TMPDIR/mixed.har" --edl "$TMPDIR/mixed.edl.json" 2>&1)
if echo "$MIXED_VALIDATE" | grep -q "RESULT: VALID"; then
    pass "Mixed EDL validation"
else
    fail "Mixed EDL validation"
    echo "$MIXED_VALIDATE" | tail -5
fi

# Check EDL has keep and possibly manual decisions
MIXED_EDL_CHECK=$(python3 -c "
import json
edl = json.load(open('$TMPDIR/mixed.edl.json'))
keeps = sum(1 for d in edl['decisions'] if d['action'] == 'keep')
print('PASS' if keeps > 0 else 'FAIL')
")
check "EDL contains keep decisions" "PASS" "$MIXED_EDL_CHECK"

# Cleanup
curl -s -X POST "$BASE/api/security/toggle" \
    -H "Content-Type: application/json" -d "{\"id\": $FIRST_ID}" > /dev/null
if [ -n "$MANUAL_LOC" ] && [ "$MANUAL_LOC" != "NONE" ]; then
    curl -s -X POST "$BASE/api/redaction/remove-manual" \
        -H "Content-Type: application/json" \
        -d "{\"entryIndex\": $MANUAL_ENTRY, \"location\": \"$MANUAL_LOC\"}" > /dev/null
fi

# ============================================================
# TEST 7: Reset and reapply
# ============================================================
echo "=== TEST 7: Reset and reapply ==="

# Create mixed state
curl -s -X POST "$BASE/api/security/toggle" \
    -H "Content-Type: application/json" -d "{\"id\": $FIRST_ID}" > /dev/null
if [ -n "$MANUAL_LOC" ] && [ "$MANUAL_LOC" != "NONE" ]; then
    curl -s -X POST "$BASE/api/redaction/manual" \
        -H "Content-Type: application/json" \
        -d "{\"entryIndex\": $MANUAL_ENTRY, \"location\": \"$MANUAL_LOC\", \"value\": \"$MANUAL_VAL\"}" > /dev/null
fi

# Reset
curl -s -X POST "$BASE/api/redaction/reset" > /dev/null

RESET_CHECK=$(curl -s "$BASE/api/security" | python3 -c "
import json, sys
data = json.load(sys.stdin)
# After reset: all crit/warn should redact, manuals cleared
all_on = all(f['redact'] for f in data['findings'] if f['severity'] in ('critical','warning'))
no_manual = len(data['manualRedactions']) == 0
print('PASS' if all_on and no_manual else 'FAIL')
")
check "Reset restores defaults" "PASS" "$RESET_CHECK"

# Reapply
curl -s -X POST "$BASE/api/redaction/reapply-auto" > /dev/null

REAPPLY_CHECK=$(curl -s "$BASE/api/security" | python3 -c "
import json, sys
data = json.load(sys.stdin)
redacting = sum(1 for f in data['findings'] if f['redact'])
total = len(data['findings'])
print('PASS' if redacting == total else 'FAIL')
")
check "Reapply restores all auto redactions" "PASS" "$REAPPLY_CHECK"

# ============================================================
# TEST 8: Full round-trip — sanitized HAR rescanned shows 0 findings
# ============================================================
echo "=== TEST 8: Full round-trip ==="

curl -s -X POST "$BASE/api/export/har" -o "$TMPDIR/final.har"
curl -s -X POST "$BASE/api/export/edl" -o "$TMPDIR/final.edl.json"

FINAL_VALIDATE=$("$HARSCOPE" --validate "$TMPDIR/final.har" --edl "$TMPDIR/final.edl.json" 2>&1)
if echo "$FINAL_VALIDATE" | grep -q "RESULT: VALID"; then
    pass "Final EDL validation"
else
    fail "Final EDL validation"
    echo "$FINAL_VALIDATE" | tail -5
fi

# Reload sanitized HAR and rescan
curl -s -X POST "$BASE/api/open" \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"$TMPDIR/final.har\"}" > /dev/null

RESCAN_COUNT=$(curl -s "$BASE/api/security" | python3 -c "
import json, sys; print(len(json.load(sys.stdin)['findings']))
")
check "Sanitized HAR rescan finds 0 findings" "0" "$RESCAN_COUNT"

# ============================================================
# Summary
# ============================================================
echo ""
echo "========================================"
TOTAL=$((PASS + FAIL))
echo "Results: $PASS passed, $FAIL failed out of $TOTAL tests"
echo "========================================"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
