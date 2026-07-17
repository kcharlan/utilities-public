#!/bin/bash

rm -rf venv
python3.12 -m venv venv
source venv/bin/activate

pip install opencv-python numpy Click tqdm appdirs
pip install --upgrade scenedetect[opencv]

