#!/bin/bash
source venv/bin/activate
python3 transcribe.py --file "*.wav" --model large
