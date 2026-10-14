FROM python:3.11-slim

# PortAudio for sounddevice; alsa-utils gives you arecord for mic testing
RUN apt-get update && apt-get install -y --no-install-recommends \
        libportaudio2 alsa-utils wget unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the speech model into the image (change with --build-arg VOSK_MODEL=...)
ARG VOSK_MODEL=vosk-model-small-en-us-0.15
RUN wget -q https://alphacephei.com/vosk/models/${VOSK_MODEL}.zip \
    && unzip -q ${VOSK_MODEL}.zip && rm ${VOSK_MODEL}.zip
ENV VOSK_MODEL_PATH=/app/${VOSK_MODEL}

# Print logs immediately instead of buffering
ENV PYTHONUNBUFFERED=1

COPY voice_client.py .

CMD ["python", "voice_client.py"]
