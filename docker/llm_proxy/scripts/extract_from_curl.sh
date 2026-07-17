#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 [curl_file]"
    echo ""
    echo "Extract T3.chat credentials from a cURL command."
    echo ""
    echo "  curl_file  Path to a file containing the cURL command (optional)."
    echo "             If omitted, reads from stdin interactively."
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

if [ -n "${1:-}" ]; then
    # File argument provided
    if [ ! -f "$1" ]; then
        echo "ERROR: File not found: $1"
        exit 1
    fi
    echo "=== T3.chat Credential Extractor (from cURL) ==="
    echo ""
    echo "Reading cURL command from: $1"
    curl_cmd=$(cat "$1")
else
    # Interactive mode
    echo "=== T3.chat Credential Extractor (from cURL) ==="
    echo ""
    echo "Steps to get your cURL command:"
    echo "  1. Open https://t3.chat in Chrome and log in"
    echo "  2. Open DevTools: press F12 (or Cmd+Option+I on Mac)"
    echo "  3. Click the Network tab"
    echo "  4. In the filter bar, type:  /api/chat"
    echo "  5. Send any message in T3.chat (e.g. type 'hello' and press Enter)"
    echo "  6. A 'chat' entry appears in the Network tab"
    echo "  7. Right-click the 'chat' entry → Copy → Copy as cURL"
    echo ""
    echo "Paste your cURL command below, then press Enter and Ctrl+D:"
    echo ""
    curl_cmd=$(cat)
fi

# Extract cookies: Chrome uses -b for cookies, some browsers use -H 'Cookie: ...'
# Uses sed since macOS BSD grep lacks -P (Perl regex)
cookies=$(echo "$curl_cmd" | sed -n "s/.*-b '\([^']*\)'.*/\1/p" | head -1)
if [ -z "$cookies" ]; then
    cookies=$(echo "$curl_cmd" | sed -n 's/.*-b "\([^"]*\)".*/\1/p' | head -1)
fi
if [ -z "$cookies" ]; then
    cookies=$(echo "$curl_cmd" | sed -n "s/.*-H 'Cookie: \([^']*\)'.*/\1/p" | head -1)
fi
if [ -z "$cookies" ]; then
    cookies=$(echo "$curl_cmd" | sed -n 's/.*-H "Cookie: \([^"]*\)".*/\1/p' | head -1)
fi

if [ -z "$cookies" ]; then
    echo "ERROR: Could not find cookies in cURL command."
    echo "Expected -b '...' or -H 'Cookie: ...' flag."
    echo "Make sure you copied the full cURL command from DevTools."
    exit 1
fi

# convex-session-id is available both as a cookie AND in the JSON body.
# Extract from cookies first (more reliable), fall back to body.
convex_session_id=$(echo "$cookies" | sed -n 's/.*convex-session-id=\([^;]*\).*/\1/p' | head -1)
if [ -z "$convex_session_id" ]; then
    convex_session_id=$(echo "$curl_cmd" | sed -n 's/.*"convexSessionId":"\([^"]*\)".*/\1/p' | head -1)
fi

if [ -z "$convex_session_id" ]; then
    echo "ERROR: Could not find convex-session-id in cookies or body."
    exit 1
fi

# Build and encode credentials
json=$(printf '{"cookies":"%s","convex_session_id":"%s"}' "$cookies" "$convex_session_id")
encoded=$(echo -n "$json" | base64)

echo ""
echo "=== Success! ==="
echo ""
echo "Cookie: ${cookies:0:60}..."
echo "convexSessionId: $convex_session_id"
echo ""
echo "Add this to your shell profile (~/.zshrc or ~/.bashrc):"
echo ""
echo "export T3_CHAT_CREDS='$encoded'"
