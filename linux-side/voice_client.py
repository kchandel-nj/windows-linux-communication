"""
voice_client.py  (Linux side)

Listens on a microphone, turns speech into text with Vosk (offline),
and sends each finished phrase to the Windows server as newline-delimited JSON.
Waits for the server's JSON reply (Ollama telemetry) before sending the next one.

Keeps the existing behavior:
  - .env config (SERVER_IP, SERVER_PORT, DEVICE_ID)
  - auto-reconnect with 5 s back-off if Windows goes offline
  - Ctrl+C sends {"status": "SHUTDOWN"} so Windows knows we left
"""

import json
import os
import queue
import socket
import sys
import time
from datetime import datetime, timezone

import sounddevice as sd
from dotenv import load_dotenv, find_dotenv
from vosk import Model, KaldiRecognizer, SetLogLevel

# ---------- Config ----------
load_dotenv(find_dotenv())

SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5001"))
DEVICE_ID = os.getenv("DEVICE_ID", "linux-node-01")
MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "vosk-model-small-en-us-0.15")
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "60"))  # Ollama can be slow
RETRY_DELAY = 5

_mic = os.getenv("MIC_DEVICE", "").strip()
MIC_DEVICE = int(_mic) if _mic.isdigit() else (_mic or None)  # index, name, or default

audio_q = queue.Queue()


# ---------- Audio ----------
def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"[AUDIO] {status}", file=sys.stderr)
    audio_q.put(bytes(indata))


def clear_audio_queue():
    with audio_q.mutex:
        audio_q.queue.clear()


# ---------- Networking ----------
def connect():
    """Block until the Windows server accepts a connection."""
    while True:
        try:
            sock = socket.create_connection((SERVER_IP, SERVER_PORT), timeout=5)
            sock.settimeout(RESPONSE_TIMEOUT)
            print(f"[CONNECTED] Windows server at {SERVER_IP}:{SERVER_PORT}")
            return sock
        except OSError as e:
            print(f"[OFFLINE] Can't reach Windows ({e}). Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)


def send_json(sock, payload):
    sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def recv_line(sock, buffer):
    """Read until a full newline-terminated message is available."""
    while b"\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionResetError("Server closed the connection")
        buffer += chunk
    line, _, buffer = buffer.partition(b"\n")
    return line.decode("utf-8"), buffer


def show_reply(reply):
    try:
        data = json.loads(reply)
    except json.JSONDecodeError:
        print(f"[PC] (non-JSON) {reply}")
        return
    if data.get("status") == "SHUTDOWN":
        print("[ALERT] Windows server announced it is shutting down.")
    else:
        print("[PC] " + json.dumps(data, indent=2))


# ---------- Main ----------
def main():
    SetLogLevel(-1)  # silence Vosk's internal logging

    if not os.path.isdir(MODEL_PATH):
        print(f"[ERROR] Vosk model not found at '{MODEL_PATH}'. Set VOSK_MODEL_PATH in .env.")
        sys.exit(1)

    model = Model(MODEL_PATH)
    samplerate = int(sd.query_devices(MIC_DEVICE, "input")["default_samplerate"])
    rec = KaldiRecognizer(model, samplerate)

    sock = None
    buffer = b""
    try:
        sock = connect()
        with sd.RawInputStream(samplerate=samplerate, blocksize=8000, device=MIC_DEVICE,
                               dtype="int16", channels=1, callback=audio_callback):
            print("[LISTENING] Speak a command (Ctrl+C to quit)")
            while True:
                data = audio_q.get()
                if not rec.AcceptWaveform(data):
                    continue  # phrase not finished yet

                text = json.loads(rec.Result()).get("text", "").strip()
                if not text:
                    continue

                print(f"[HEARD] {text}")
                payload = {
                    "device_id": DEVICE_ID,
                    "type": "voice_command",
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                try:
                    send_json(sock, payload)
                    reply, buffer = recv_line(sock, buffer)
                    show_reply(reply)
                except OSError as e:  # reset, broken pipe, timeout
                    print(f"[ALERT] Lost connection to Windows ({e}). '{text}' was not processed.")
                    sock.close()
                    
                    # 1. Reconnect (Blocks here for multiples of 5 seconds)
                    sock = connect()
                    buffer = b""
                    
                    # 2. CLEAR HERE right before restarting the audio loop
                    clear_audio_queue()  
                    rec.Reset()
                    print("[LISTENING] Back online. Speak a command.")

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Ctrl+C detected, notifying Windows...")
        if sock:
            try:
                send_json(sock, {"status": "SHUTDOWN", "device_id": DEVICE_ID})
            except OSError:
                pass
    finally:
        if sock:
            sock.close()
        print("[EXIT] Voice client closed.")


if __name__ == "__main__":
    main()