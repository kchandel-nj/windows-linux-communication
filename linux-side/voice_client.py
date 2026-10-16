"""
voice_client.py  (wrist computer / Linux side)

Sends crew commands to the Windows hub as newline-delimited JSON and prints
the hub's JSON reply (Ollama telemetry).

Two input modes, chosen with INPUT_MODE in .env (or on the command line):
  voice  (default) - microphone -> Vosk offline speech-to-text
  text             - type commands at a prompt (for testing without a mic)

Kept from before:
  - .env config (SERVER_IP, SERVER_PORT, DEVICE_ID, ...)
  - auto-reconnect with 5 s back-off if the hub goes offline
  - Ctrl+C sends {"status": "SHUTDOWN"} so the hub knows we left
"""

import json
import os
import queue
import socket
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv, find_dotenv

# ---------- Config ----------
load_dotenv(find_dotenv())

SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5001"))
DEVICE_ID = os.getenv("DEVICE_ID", "linux-node-01")
INPUT_MODE = os.getenv("INPUT_MODE", "voice").strip().lower()
MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "vosk-model-small-en-us-0.15")
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "60"))  # Ollama can be slow
RETRY_DELAY = 5

_mic = os.getenv("MIC_DEVICE", "").strip()
MIC_DEVICE = int(_mic) if _mic.isdigit() else (_mic or None)  # index, name, or default


# ---------- Connection to the hub ----------
class HubLink:
    def __init__(self):
        self.sock = None
        self.buffer = b""

    def connect(self):
        """Block until the hub accepts a connection."""
        while True:
            try:
                self.sock = socket.create_connection((SERVER_IP, SERVER_PORT), timeout=5)
                self.sock.settimeout(RESPONSE_TIMEOUT)
                self.buffer = b""
                print(f"[CONNECTED] Hub at {SERVER_IP}:{SERVER_PORT}")
                return
            except OSError as e:
                print(f"[OFFLINE] Can't reach hub ({e}). Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

    def _send(self, payload):
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def _recv_line(self):
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionResetError("Hub closed the connection")
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return line.decode("utf-8")

    def send_command(self, text):
        """Send one command and print the reply. Returns False if the link dropped."""
        payload = {
            "device_id": DEVICE_ID,
            "type": "voice_command",
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._send(payload)
            show_reply(self._recv_line())
            return True
        except OSError as e:  # reset, broken pipe, timeout
            print(f"[ALERT] Lost connection to hub ({e}). '{text}' was not processed.")
            self.close()
            self.connect()
            return False

    def shutdown(self):
        if self.sock:
            try:
                self._send({"status": "SHUTDOWN", "device_id": DEVICE_ID})
            except OSError:
                pass

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


def show_reply(reply):
    try:
        data = json.loads(reply)
    except json.JSONDecodeError:
        print(f"[HUB] (non-JSON) {reply}")
        return
    if data.get("status") == "SHUTDOWN":
        print("[ALERT] Hub announced it is shutting down.")
    else:
        print("[HUB] " + json.dumps(data, indent=2))


# ---------- Text mode ----------
def run_text_mode(link):
    link.connect()
    print("[TEXT MODE] Type a command and press Enter (Ctrl+C to quit)")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:  # Ctrl+D or no stdin
            raise KeyboardInterrupt
        if text:
            link.send_command(text)


# ---------- Voice mode ----------
def run_voice_mode(link):
    # Imported here so text mode works even without audio libraries installed
    import sounddevice as sd
    from vosk import Model, KaldiRecognizer, SetLogLevel

    SetLogLevel(-1)
    if not os.path.isdir(MODEL_PATH):
        print(f"[ERROR] Vosk model not found at '{MODEL_PATH}'. Set VOSK_MODEL_PATH in .env.")
        sys.exit(1)

    model = Model(MODEL_PATH)
    samplerate = int(sd.query_devices(MIC_DEVICE, "input")["default_samplerate"])
    rec = KaldiRecognizer(model, samplerate)
    audio_q = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[AUDIO] {status}", file=sys.stderr)
        audio_q.put(bytes(indata))

    link.connect()
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
            if not link.send_command(text):
                with audio_q.mutex:          # drop speech captured while offline
                    audio_q.queue.clear()
                rec.Reset()
                print("[LISTENING] Back online. Speak a command.")


# ---------- Main ----------
def main():
    modes = {"voice": run_voice_mode, "text": run_text_mode}
    if INPUT_MODE not in modes:
        print(f"[ERROR] INPUT_MODE must be 'voice' or 'text', got '{INPUT_MODE}'.")
        sys.exit(1)

    link = HubLink()
    try:
        modes[INPUT_MODE](link)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Ctrl+C detected, notifying hub...")
        link.shutdown()
    finally:
        link.close()
        print("[EXIT] Client closed.")


if __name__ == "__main__":
    main()