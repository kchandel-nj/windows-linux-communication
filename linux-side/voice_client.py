"""
voice_client.py  (wrist computer / Linux side)

Sends crew commands to the Windows hub as newline-delimited JSON and prints
the hub's JSON reply (Ollama telemetry).

Two input modes, chosen with INPUT_MODE in .env (or on the command line):
  voice  (default) - microphone -> Vosk offline speech-to-text
  text             - type commands at a prompt (for testing without a mic)

Connection behavior:
  - a background thread listens to the hub at all times, so a hub shutdown
    (Ctrl+C on the PC) is announced immediately, not on the next command
  - auto-reconnect every 5 s whenever the hub is offline
  - Ctrl+C here sends {"status": "SHUTDOWN"} so the hub knows we left
"""

import json
import os
import queue
import socket
import sys
import threading
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
    """Owns the socket. A reader thread receives everything the hub sends:
    replies go into a queue for send_command(); SHUTDOWN or a dropped link
    triggers an alert and an automatic reconnect."""

    def __init__(self):
        self.sock = None
        self.replies = queue.Queue()
        self.connected = threading.Event()
        self.send_lock = threading.Lock()
        self.closing = False

    # --- connecting ---
    def start(self):
        self._connect_blocking()

    def _connect_blocking(self):
        while not self.closing:
            try:
                sock = socket.create_connection((SERVER_IP, SERVER_PORT), timeout=5)
            except OSError as e:
                print(f"[OFFLINE] Can't reach hub ({e}). Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
                continue
            sock.settimeout(None)
            self.sock = sock
            self._drain_replies()
            self.connected.set()
            print(f"[CONNECTED] Hub at {SERVER_IP}:{SERVER_PORT}")
            threading.Thread(target=self._reader, args=(sock,), daemon=True).start()
            return

    def _drain_replies(self):
        while True:
            try:
                self.replies.get_nowait()
            except queue.Empty:
                return

    # --- background listener ---
    def _reader(self, sock):
        buffer = b""
        hub_shutdown = False
        try:
            while not hub_shutdown:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, _, buffer = buffer.partition(b"\n")
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        self.replies.put({"_raw": line.decode("utf-8", errors="replace")})
                        continue
                    if msg.get("status") == "SHUTDOWN":
                        hub_shutdown = True
                        break
                    self.replies.put(msg)
        except OSError:
            pass

        if self.closing:
            return
        self.connected.clear()
        try:
            sock.close()
        except OSError:
            pass
        self.replies.put(None)  # wake any command waiting for a reply

        if hub_shutdown:
            print("\n[ALERT] Hub was shut down (Ctrl+C on the PC). Waiting for it to come back...")
        else:
            print("\n[ALERT] Lost connection to hub. Reconnecting...")
        self._connect_blocking()  # starts a fresh reader thread when back online

    def _force_reconnect(self):
        """Kick the reader so it notices the link is bad and reconnects."""
        self.connected.clear()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    # --- sending ---
    def _send(self, payload):
        with self.send_lock:
            self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def send_command(self, text):
        """Send one command and print the reply. Returns False if it wasn't processed."""
        payload = {
            "device_id": DEVICE_ID,
            "type": "voice_command",
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for attempt in (1, 2):
            # first attempt: fail fast if offline; retry: give the reconnect a moment
            wait = 0 if attempt == 1 else RETRY_DELAY + 2
            if not self.connected.wait(timeout=wait):
                print(f"[OFFLINE] Hub is offline. '{text}' was not sent.")
                return False
            try:
                self._send(payload)
            except OSError:
                self._force_reconnect()
                print(f"[RETRY] Send failed, retrying '{text}'...")
                continue

            try:
                reply = self.replies.get(timeout=RESPONSE_TIMEOUT)
            except queue.Empty:
                print(f"[ALERT] No reply within {RESPONSE_TIMEOUT:.0f}s.")
                self._force_reconnect()
                continue

            if reply is None:  # link dropped while waiting
                if attempt == 1:
                    print(f"[RETRY] Resending '{text}' once the hub is back...")
                continue
            show_reply(reply)
            return True

        print(f"[ALERT] '{text}' was not processed.")
        return False

    # --- leaving ---
    def shutdown(self):
        self.closing = True
        if self.connected.is_set():
            try:
                self._send({"status": "SHUTDOWN", "device_id": DEVICE_ID})
            except OSError:
                pass

    def close(self):
        self.closing = True
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


def show_reply(reply):
    if "_raw" in reply:
        print(f"[HUB] (non-JSON) {reply['_raw']}")
    else:
        print("[HUB] " + json.dumps(reply, indent=2))


# ---------- Text mode ----------
def run_text_mode(link):
    link.start()
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

    link.start()
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