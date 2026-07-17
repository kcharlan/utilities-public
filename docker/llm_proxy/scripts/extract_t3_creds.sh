#!/usr/bin/env bash
set -euo pipefail

echo "=== T3.chat Manual Credential Encoder ==="
echo ""
echo "Finding the Cookie string:"
echo "  1. Open https://t3.chat → DevTools (F12) → Network tab"
echo "  2. Filter for '/api/chat', send a message"
echo "  3. Click the 'chat' entry → Headers tab"
echo "  4. Scroll to 'Request Headers' section"
echo "  5. Find 'Cookie:' — copy its full value"
echo ""
read -r -p "Paste Cookie value: " cookies
echo ""
echo "Finding the convexSessionId:"
echo "  1. Same 'chat' entry → click the Payload tab"
echo "  2. Find 'convexSessionId' in the tree"
echo "  3. Copy the UUID value"
echo ""
read -r -p "Paste convexSessionId: " convex_session_id
echo ""

json=$(printf '{"cookies":"%s","convex_session_id":"%s"}' "$cookies" "$convex_session_id")
encoded=$(echo -n "$json" | base64)

echo "=== Your T3_CHAT_CREDS ==="
echo ""
echo "export T3_CHAT_CREDS='$encoded'"
echo ""
echo "Add this to ~/.zshrc or ~/.bashrc"
