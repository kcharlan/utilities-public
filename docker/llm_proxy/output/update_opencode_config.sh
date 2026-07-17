#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/.config/opencode/opencode.json}"

python3 -c "
import json, sys, os

provider_file = os.path.join('${SCRIPT_DIR}', 'opencode_provider_t3chat.json')
with open(provider_file) as f:
    new_provider = json.load(f)

target = sys.argv[1]
if os.path.exists(target):
    with open(target) as f:
        config = json.load(f)
else:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    config = {}

if 'provider' not in config:
    config['provider'] = {}

config['provider'].update(new_provider)

with open(target, 'w') as f:
    json.dump(config, f, indent=2)

provider_name = list(new_provider.keys())[0]
model_count = len(new_provider[provider_name]['models'])
print(f'Updated provider: {provider_name} ({model_count} models)')
print(f'Target file: {target}')
" "$TARGET"
