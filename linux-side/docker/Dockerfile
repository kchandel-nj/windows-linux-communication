FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        libportaudio2 libasound2-plugins alsa-utils espeak-ng wget unzip \
    && rm -rf /var/lib/apt/lists/*
# Send ALSA audio through the host's PipeWire/PulseAudio
RUN printf 'pcm.!default { type pulse }\nctl.!default { type pulse }\n' > /etc/asound.conf
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Speech-to-text model
ARG VOSK_MODEL=vosk-model-small-en-us-0.15
RUN wget -q https://alphacephei.com/vosk/models/${VOSK_MODEL}.zip \
    && unzip -q ${VOSK_MODEL}.zip && rm ${VOSK_MODEL}.zip
ENV VOSK_MODEL_PATH=/app/${VOSK_MODEL}

# Text-to-speech voice
ARG PIPER_VOICE_URL=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
RUN wget -q -O /app/voice.onnx "${PIPER_VOICE_URL}" \
    && wget -q -O /app/voice.onnx.json "${PIPER_VOICE_URL}.json"
ENV PIPER_VOICE=/app/voice.onnx

ENV PYTHONUNBUFFERED=1
COPY voice_client.py tts.py ./
CMD ["python", "voice_client.py"]