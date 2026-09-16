#!/usr/bin/env zsh

# Compatibility notice for installs that still invoke the former venv setup.
# EditDB is now a uv-managed PEP 723 launcher and needs no project environment.

set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    print -u2 -- "EditDB requires uv. Install it with: brew install uv"
    exit 1
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"

print -- "EditDB no longer needs a setup step; uv resolves its dependencies."
print -- "Run: $script_dir/editdb path/to/your/database.sqlite"

# Fail here if launcher metadata or dependency resolution has drifted.
"$script_dir/editdb" --help >/dev/null
