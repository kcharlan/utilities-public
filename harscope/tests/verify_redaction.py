#!/usr/bin/env python3
"""
Helper for run_tests.sh — verifies redaction state in exported HAR files.

Usage (called by run_tests.sh, not typically run directly):
    python3 verify_redaction.py <security.json> <har_file> <mode> [args...]

Modes:
    all_redacted        — Verify every finding with redact=True is [REDACTED] in HAR
    check_kept <id>     — Verify finding <id> is NOT [REDACTED] (was toggled to keep)
    check_bulk          — Verify criticals are redacted, warnings are not
    check_manual <entry> <key> — Verify a manually redacted key is [REDACTED]
    check_manual_removed <entry> <key> — Verify a manually un-redacted key is NOT [REDACTED]
    find_manual_target  — Find a non-flagged JSON body key suitable for manual redaction test
"""

import json
import re
import sys


def expand_json_key_path(keys):
    """Expand key path segments like 'modifications[0]' into ['modifications', '[0]']."""
    expanded = []
    for k in keys:
        if '[' in k and not k.startswith('['):
            parts = k.split('[', 1)
            expanded.append(parts[0])
            expanded.append('[' + parts[1])
        else:
            expanded.append(k)
    return expanded


def navigate_json(obj, key_path_str):
    """Navigate a parsed JSON object using a dotted key path with array indices.

    Returns the value at the path, or raises on failure.
    """
    parts = key_path_str.split('.')
    parts = expand_json_key_path(parts)
    current = obj
    for p in parts:
        if p.startswith('[') and p.endswith(']'):
            current = current[int(p[1:-1])]
        elif isinstance(current, dict):
            current = current[p]
        else:
            raise KeyError(f"Cannot navigate {p} in {type(current)}")
    return current


def get_body_text(entry, location):
    """Get the body text and its key ('text' or 'data') for a finding location."""
    loc_lower = location.lower()
    if '_websocketmessages' in loc_lower:
        ws_match = re.search(r'_webSocketMessages\[(\d+)\]', location, re.IGNORECASE)
        if ws_match:
            idx = int(ws_match.group(1))
            ws_msgs = entry.get('_webSocketMessages', [])
            if idx < len(ws_msgs):
                return ws_msgs[idx].get('data', ''), 'data'
        return '', 'data'
    elif 'request' in loc_lower and 'postdata' in loc_lower:
        return entry.get('request', {}).get('postData', {}).get('text', ''), 'text'
    elif 'response' in loc_lower:
        return entry.get('response', {}).get('content', {}).get('text', ''), 'text'
    return '', 'text'


def extract_key_path(location):
    """Extract the JSON key path after (parsed). in a location string."""
    parsed_idx = location.find('(parsed).')
    if parsed_idx >= 0:
        path = location[parsed_idx + 9:]
        path = path.replace('(parsed)', '').replace('(base64)', '')
        return path
    return None


def get_entry_index(location):
    """Extract entry index from location like entries[N].xxx."""
    m = re.match(r'entries\[(\d+)\]', location)
    return int(m.group(1)) if m else None


def read_finding_value(entries, finding):
    """Read the current value at a finding's location in the HAR."""
    location = finding['location']
    entry_idx = get_entry_index(location)
    if entry_idx is None or entry_idx >= len(entries):
        return None

    entry = entries[entry_idx]
    loc_lower = location.lower()

    # Non-body findings (headers, cookies, etc.)
    if '(parsed)' not in location:
        # Header
        if '.headers[' in loc_lower:
            m = re.search(r'\.headers\[(\d+)\]\.(\w+)', location, re.IGNORECASE)
            if m:
                idx = int(m.group(1))
                section = 'request' if '.request.' in loc_lower else 'response'
                headers = entry.get(section, {}).get('headers', [])
                if idx < len(headers):
                    return headers[idx].get('value')
        # Cookie
        elif '.cookies[' in loc_lower:
            m = re.search(r'\.cookies\[(\d+)\]\.(\w+)', location, re.IGNORECASE)
            if m:
                idx = int(m.group(1))
                section = 'request' if '.request.' in loc_lower else 'response'
                cookies = entry.get(section, {}).get('cookies', [])
                if idx < len(cookies):
                    return cookies[idx].get('value')
        elif '.cookies.' in loc_lower:
            m = re.search(r'\.cookies\.(\w+)', location, re.IGNORECASE)
            if m:
                section = 'request' if '.request.' in loc_lower else 'response'
                target = m.group(1).lower()
                for cookie in entry.get(section, {}).get('cookies', []):
                    if str(cookie.get('name', '')).lower() == target:
                        return cookie.get('value')
        # Query string parameter
        elif '.querystring[' in loc_lower:
            m = re.search(r'\.queryString\[(\d+)\]\.(\w+)', location, re.IGNORECASE)
            if m:
                idx = int(m.group(1))
                params = entry.get('request', {}).get('queryString', [])
                if idx < len(params):
                    return params[idx].get('value')
        # WS message data (whole, not parsed)
        elif '_websocketmessages' in loc_lower and location.endswith('.data'):
            ws_match = re.search(r'_webSocketMessages\[(\d+)\]', location, re.IGNORECASE)
            if ws_match:
                idx = int(ws_match.group(1))
                ws_msgs = entry.get('_webSocketMessages', [])
                if idx < len(ws_msgs):
                    return ws_msgs[idx].get('data')
        # Response content text (whole)
        elif location.endswith('.content.text') or location.endswith('.text'):
            if 'response' in loc_lower:
                return entry.get('response', {}).get('content', {}).get('text')
            elif 'request' in loc_lower and 'postdata' in loc_lower:
                return entry.get('request', {}).get('postData', {}).get('text')
        elif location.endswith('.request.url'):
            return entry.get('request', {}).get('url')
        return None

    # Body with (parsed) — parse JSON and navigate
    key_path = extract_key_path(location)
    if not key_path:
        return None

    body_text, _ = get_body_text(entry, location)
    if not body_text:
        return None

    try:
        parsed = json.loads(body_text)
        return navigate_json(parsed, key_path)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        return None


def mode_all_redacted(security_json, har_file):
    """Verify all findings with redact=True are [REDACTED] in the exported HAR."""
    with open(security_json) as f:
        data = json.load(f)
    with open(har_file) as f:
        har = json.load(f)

    entries = har['log']['entries']
    findings = data['findings']

    for f in findings:
        if not f['redact']:
            continue

        val = read_finding_value(entries, f)
        if val != '[REDACTED]':
            loc = f['location']
            print(f"FAIL: [{f['id']}] {loc} = {repr(val)[:80]}", file=sys.stderr)
            print("FAIL")
            return

    print("PASS")


def mode_check_kept(security_json, har_file, finding_id):
    """Verify a specific finding is NOT [REDACTED] (was kept)."""
    with open(security_json) as f:
        data = json.load(f)
    with open(har_file) as f:
        har = json.load(f)

    entries = har['log']['entries']
    finding = None
    for ff in data['findings']:
        if ff['id'] == finding_id:
            finding = ff
            break

    if not finding:
        print("FAIL", end="")
        return

    val = read_finding_value(entries, finding)
    if val == '[REDACTED]':
        print("FAIL", end="")
    else:
        print("PASS", end="")


def mode_check_bulk(security_json, har_file):
    """Verify criticals are [REDACTED] and warnings are NOT."""
    with open(security_json) as f:
        data = json.load(f)
    with open(har_file) as f:
        har = json.load(f)

    entries = har['log']['entries']

    # Check one critical is redacted
    for f in data['findings']:
        if f['severity'] == 'critical':
            val = read_finding_value(entries, f)
            if val != '[REDACTED]':
                print("FAIL", end="")
                return
            break

    # Check one warning is NOT redacted
    for f in data['findings']:
        if f['severity'] == 'warning' and f.get('category') != 'Cookie Flags':
            val = read_finding_value(entries, f)
            if val == '[REDACTED]':
                print("FAIL", end="")
                return
            break

    print("PASS", end="")


def mode_check_manual(security_json, har_file, entry_idx, key_name):
    """Verify a manually redacted key is [REDACTED]."""
    with open(har_file) as f:
        har = json.load(f)

    entry = har['log']['entries'][int(entry_idx)]
    # Search all body containers for the key
    for container_getter in [
        lambda: json.loads(entry.get('request', {}).get('postData', {}).get('text', '{}')),
        lambda: json.loads(entry.get('response', {}).get('content', {}).get('text', '{}')),
    ]:
        try:
            parsed = container_getter()
            if isinstance(parsed, dict) and key_name in parsed:
                if parsed[key_name] == '[REDACTED]':
                    print("PASS", end="")
                else:
                    print("FAIL", end="")
                return
        except (json.JSONDecodeError, TypeError):
            continue

    # Check WS messages
    for ws_msg in entry.get('_webSocketMessages', []):
        try:
            parsed = json.loads(ws_msg.get('data', '{}'))
            if isinstance(parsed, dict) and key_name in parsed:
                if parsed[key_name] == '[REDACTED]':
                    print("PASS", end="")
                else:
                    print("FAIL", end="")
                return
        except (json.JSONDecodeError, TypeError):
            continue

    print("FAIL", end="")


def mode_check_manual_removed(security_json, har_file, entry_idx, key_name):
    """Verify a key is NOT [REDACTED] after manual redaction was removed."""
    with open(har_file) as f:
        har = json.load(f)

    entry = har['log']['entries'][int(entry_idx)]
    for container_getter in [
        lambda: json.loads(entry.get('request', {}).get('postData', {}).get('text', '{}')),
        lambda: json.loads(entry.get('response', {}).get('content', {}).get('text', '{}')),
    ]:
        try:
            parsed = container_getter()
            if isinstance(parsed, dict) and key_name in parsed:
                if parsed[key_name] != '[REDACTED]':
                    print("PASS", end="")
                else:
                    print("FAIL", end="")
                return
        except (json.JSONDecodeError, TypeError):
            continue

    for ws_msg in entry.get('_webSocketMessages', []):
        try:
            parsed = json.loads(ws_msg.get('data', '{}'))
            if isinstance(parsed, dict) and key_name in parsed:
                if parsed[key_name] != '[REDACTED]':
                    print("PASS", end="")
                else:
                    print("FAIL", end="")
                return
        except (json.JSONDecodeError, TypeError):
            continue

    print("FAIL", end="")


def mode_find_manual_target(security_json, har_file):
    """Find a non-flagged JSON body key suitable for manual redaction.

    Outputs: entryIndex|location|value|keyName
    """
    with open(security_json) as f:
        data = json.load(f)
    with open(har_file) as f:
        har = json.load(f)

    # Collect all flagged key paths per entry
    flagged = set()
    for f in data['findings']:
        key_path = extract_key_path(f['location'])
        entry_idx = get_entry_index(f['location'])
        if key_path and entry_idx is not None:
            flagged.add((entry_idx, key_path.lower()))

    entries = har['log']['entries']

    # Search for a non-flagged top-level key in a JSON body
    for i, entry in enumerate(entries):
        # Check request body
        for section, container_path in [
            ('request', 'request.postData'),
            ('response', 'response.content'),
        ]:
            if section == 'request':
                text = entry.get('request', {}).get('postData', {}).get('text', '')
                loc_prefix = f'entries[{i}].request.postData.text(parsed)'
            else:
                text = entry.get('response', {}).get('content', {}).get('text', '')
                loc_prefix = f'entries[{i}].response.content.text(parsed)'

            if not text:
                continue
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue

            for key, val in parsed.items():
                if isinstance(val, str) and len(val) < 100 and (i, key.lower()) not in flagged:
                    location = f'{loc_prefix}.{key}'
                    safe_val = val.replace('|', ' ')
                    print(f'{i}|{location}|{safe_val}|{key}', end="")
                    return

        # Check WS messages
        for j, ws_msg in enumerate(entry.get('_webSocketMessages', [])):
            text = ws_msg.get('data', '')
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue

            loc_prefix = f'entries[{i}]._webSocketMessages[{j}].data(parsed)'
            for key, val in parsed.items():
                if isinstance(val, (str, int, bool)) and (i, key.lower()) not in flagged:
                    str_val = str(val) if not isinstance(val, str) else val
                    if len(str_val) < 100:
                        location = f'{loc_prefix}.{key}'
                        safe_val = str_val.replace('|', ' ')
                        print(f'{i}|{location}|{safe_val}|{key}', end="")
                        return

    print("0|NONE||", end="")


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: verify_redaction.py <security.json> <har_file> <mode> [args...]", file=sys.stderr)
        sys.exit(1)

    security_json = sys.argv[1]
    har_file = sys.argv[2]
    mode = sys.argv[3]
    args = sys.argv[4:]

    if mode == 'all_redacted':
        mode_all_redacted(security_json, har_file)
    elif mode == 'check_kept':
        mode_check_kept(security_json, har_file, int(args[0]))
    elif mode == 'check_bulk':
        mode_check_bulk(security_json, har_file)
    elif mode == 'check_manual':
        mode_check_manual(security_json, har_file, args[0], args[1])
    elif mode == 'check_manual_removed':
        mode_check_manual_removed(security_json, har_file, args[0], args[1])
    elif mode == 'find_manual_target':
        mode_find_manual_target(security_json, har_file)
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)
