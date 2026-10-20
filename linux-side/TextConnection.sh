#!/bin/bash

# Run for text-based input
# Make sure packages installed
python3 -m pip install python-dotenv --break-system-packages

# Initialize for text input
INPUT_MODE=text python3 voice_client.py
