#!/usr/bin/env bash
# setup.sh — one-time setup for the SIRIUS wrist computer (Raspberry Pi OS / Debian)
#
#   ./setup.sh
#
# Safe to run again: anything already installed or downloaded is skipped.
# Installs system packages, creates ~/sirius-venv (used by run.sh), installs the
# Python packages, downloads the Vosk speech model and Piper voice, and creates
# a starter .env if there isn't one.

set -u
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
VENV="$HOME/sirius-venv"

VOSK_MODEL="vosk-model-small-en-us-0.15"
VOSK_URL="https://alphacephei.com/vosk/models/${VOSK_MODEL}.zip"
PIPER_VOICE="en_US-lessac-medium"
PIPER_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/${PIPER_VOICE}.onnx"

ok()   { echo "  [ok]   $*"; }
skip() { echo "  [skip] $*"; }
warn() { echo "  [warn] $*"; WARNINGS=$((WARNINGS + 1)); }
WARNINGS=0

echo "== 1/6 System packages"
sudo apt-get update -qq
if sudo apt-get install -y -qq python3-venv python3-pip libportaudio2 alsa-utils espeak-ng wget unzip; then
    ok "python3-venv, libportaudio2, alsa-utils, espeak-ng, wget, unzip"
else
    warn "apt install failed; check your internet connection and rerun"
fi

echo "== 2/6 Python virtual environment ($VENV)"
if [ -d "$VENV" ]; then
    skip "already exists"
else
    python3 -m venv "$VENV" && ok "created" || { warn "could not create venv"; exit 1; }
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q --upgrade pip

echo "== 3/6 Python packages"
# One at a time, so one failure doesn't block the rest
for pkg in python-dotenv sounddevice vosk piper-tts; do
    if pip install -q "$pkg"; then
        ok "$pkg"
    else
        case "$pkg" in
            piper-tts) warn "piper-tts failed to install; speech will fall back to espeak-ng" ;;
            vosk)      warn "vosk failed to install; voice input won't work (text input still will)" ;;
            *)         warn "$pkg failed to install" ;;
        esac
    fi
done

echo "== 4/6 Vosk speech-to-text model"
if [ -d "$PROJECT_DIR/$VOSK_MODEL" ]; then
    skip "$VOSK_MODEL already downloaded"
elif wget -q --show-progress -O "$VOSK_MODEL.zip" "$VOSK_URL" && unzip -q "$VOSK_MODEL.zip"; then
    rm -f "$VOSK_MODEL.zip"
    ok "$VOSK_MODEL"
else
    rm -f "$VOSK_MODEL.zip"
    warn "Vosk model download failed"
fi

echo "== 5/6 Piper voice (voices/)"
mkdir -p voices
if [ -f "voices/$PIPER_VOICE.onnx" ] && [ -f "voices/$PIPER_VOICE.onnx.json" ]; then
    skip "$PIPER_VOICE already downloaded"
elif [ -f "$PIPER_VOICE.onnx" ] && [ -f "$PIPER_VOICE.onnx.json" ]; then
    mv "$PIPER_VOICE.onnx" "$PIPER_VOICE.onnx.json" voices/   # from an earlier manual download
    ok "moved existing $PIPER_VOICE into voices/"
elif wget -q --show-progress -O "voices/$PIPER_VOICE.onnx" "$PIPER_URL" \
  && wget -q -O "voices/$PIPER_VOICE.onnx.json" "$PIPER_URL.json"; then
    ok "$PIPER_VOICE"
else
    rm -f "voices/$PIPER_VOICE.onnx" "voices/$PIPER_VOICE.onnx.json"
    warn "Piper voice download failed"
fi

echo "== 6/6 Config"
if [ -f .env ]; then
    skip ".env exists; adding only missing model paths"
else
    cat > .env <<EOF
SERVER_IP=192.168.1.50
SERVER_PORT=5001
DEVICE_ID=wrist-pi-01
INPUT_MODE=text
OUTPUT_MODE=text
MIC_DEVICE=
SPEAKER_DEVICE=
RESPONSE_TIMEOUT=60
TTS_ENGINE=piper
EOF
    ok "created .env; set SERVER_IP to the hub's address"
fi
grep -q '^VOSK_MODEL_PATH=' .env || echo "VOSK_MODEL_PATH=$PROJECT_DIR/$VOSK_MODEL" >> .env
grep -q '^PIPER_VOICE='     .env || echo "PIPER_VOICE=voices/$PIPER_VOICE.onnx" >> .env

# Keep the big model files out of git
if [ -f .gitignore ]; then
    for pattern in 'vosk-model-*/' 'voices/' '__pycache__/'; do
        grep -qxF "$pattern" .gitignore || echo "$pattern" >> .gitignore
    done
fi

chmod +x run.sh 2>/dev/null

echo "== Check"
python - <<'EOF'
for name in ("dotenv", "sounddevice", "vosk", "piper"):
    try:
        __import__(name)
        print(f"  [ok]   import {name}")
    except Exception as e:
        print(f"  [warn] import {name}: {e}")
EOF

echo
if [ "$WARNINGS" -eq 0 ]; then
    echo "Setup complete."
else
    echo "Setup finished with $WARNINGS warning(s); see [warn] lines above."
fi
echo "Next: check SERVER_IP in .env, then run ./run.sh text"