#!/bin/bash
# Port: anker_charge_monitor/tools/resolve_signing_identity.sh, 4f965e8 (unchanged).
set -euo pipefail
# Resolve matching identities, including usable self-signed local identities.
# Valid-only filtering tests trust policy, not whether codesign can use the key.
selection=${1-CodexBar Local}
if [ -z "$selection" ] || [ "$selection" = - ]; then
    echo 'Select an existing code-signing identity with SIGN_IDENTITY (exact name or full 40-hex fingerprint); ad-hoc signing is unsupported.' >&2
    exit 1
fi
if ! identities=$(security find-identity -p codesigning); then
    echo 'Cannot query code-signing identities; check Keychain availability and retry with SIGN_IDENTITY.' >&2
    exit 1
fi
# Pass the selection through the environment, not awk source or -v escapes.
if ! fingerprint=$(SIGNING_SELECTION="$selection" awk '
    BEGIN { selection = ENVIRON["SIGNING_SELECTION"]; isHash = length(selection) == 40 && selection !~ /[^[:xdigit:]]/ }
    /^[[:space:]]*Matching identities[[:space:]]*$/ { matching = 1; next }
    /^[[:space:]]*Valid identities only[[:space:]]*$/ { matching = 0 }
    matching && /^[[:space:]]*[0-9]+\) [[:xdigit:]]+ "/ {
        record = $0
        sub(/^[[:space:]]*[0-9]+\) /, "", record)
        hash = substr(record, 1, 40)
        if (hash ~ /[^[:xdigit:]]/ || substr(record, 41, 2) != " \"") next
        name = substr(record, 43)
        sub(/"([[:space:]]+\([^"\r\n]*\))?[[:space:]]*$/, "", name)
        if ((isHash && toupper(hash) == toupper(selection)) || (!isHash && name == selection)) {
            count++; chosen = toupper(hash)
        }
    }
    END { if (count == 1) print chosen; else exit 1 }
' <<< "$identities"); then
    echo 'Signing identity missing or ambiguous. Use SIGN_IDENTITY with an existing exact name or full 40-hex fingerprint (default: CodexBar Local); inspect security find-identity -p codesigning.' >&2
    exit 1
fi
printf '%s\n' "$fingerprint"
