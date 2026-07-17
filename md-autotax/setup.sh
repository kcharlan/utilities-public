#!/bin/bash
set -euo pipefail

python3 -m venv venv
venv/bin/python -m pip install pandas streamlit
