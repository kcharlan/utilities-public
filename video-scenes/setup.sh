#!/bin/bash

rm -rf venv
python3.12 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
