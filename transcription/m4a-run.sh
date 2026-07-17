#!/bin/bash
source venv/bin/activate
python3 transcribe.py --file "*.m4a" --model large
