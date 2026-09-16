#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"

python3 -m venv "$SCRIPT_DIR/venv"
"$SCRIPT_DIR/venv/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"
