#!/usr/bin/env bash
# Quick presets for the wrist computer client.
#   ./run.sh text     text in,  text out
#   ./run.sh mic      mic in,   text out
#   ./run.sh speak    text in,  speech out
#   ./run.sh full     mic in,   speech out
#   ./run.sh both     mic + keyboard in, speech out
# Anything else is passed straight through, e.g. ./run.sh -i both -o text
cd "$(dirname "$0")"
[ -f "$HOME/sirius-venv/bin/activate" ] && source "$HOME/sirius-venv/bin/activate"

case "$1" in
  text)  shift; set -- -i text  -o text   "$@" ;;
  mic)   shift; set -- -i voice -o text   "$@" ;;
  speak) shift; set -- -i text  -o speech "$@" ;;
  full)  shift; set -- -i voice -o speech "$@" ;;
  both)  shift; set -- -i both  -o speech "$@" ;;
esac
exec python3 voice_client.py "$@"