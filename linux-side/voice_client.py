"""
voice_client.py  (wrist computer / Linux side)

Sends crew commands to the Windows hub as newline-delimited JSON and prints
the hub's JSON reply (Ollama telemetry).

Input and output are chosen independently, on the command line or in .env:

  -i / --input   text | voice | both     (INPUT_MODE,  default voice)
  -o / --output  text | speech           (OUTPUT_MODE, default speech)

  text in,  text out:     python voice_client.py -i text -o text
  mic in,   text out:     python voice_client.py -i voice -o text
  text in,  speech out:   python voice_client.py -i text -o speech
  mic in,   speech out:   python voice_client.py -i voice -o speech
  mic + keyboard:         python voice_client.py -i both

Replies are always printed; "speech" also reads them aloud (see tts.py).

Connection behavior:
  - a background thread listens to the hub at all times, so a hub shutdown
    (Ctrl+C on the PC) is announced immediately, not on the next command
  - auto-reconnect every 5 s whenever the hub is offline
  - Ctrl+C here sends {"status": "SHUTDOWN"} so the hub knows we left
"""

import argparse
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

from tts import Speaker, spoken_text  # after load_dotenv so it sees TTS settings
from wake import find_wake, WAKE_PHRASE, WAKE_TIMEOUT

SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5001"))
DEVICE_ID = os.getenv("DEVICE_ID", "linux-node-01")
MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "vosk-model-small-en-us-0.15")
if not os.path.isabs(MODEL_PATH):  # relative paths are relative to this folder
    MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), MODEL_PATH)
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "60"))  # Ollama can be slow
RETRY_DELAY = 5

_mic = os.getenv("MIC_DEVICE", "").strip()
MIC_DEVICE = int(_mic) if _mic.isdigit() else (_mic or None)  # index, name, or default


# ---------- Connection to the hub ----------
class HubLink:
    """Owns the socket. A reader thread receives everything the hub sends:
    replies go into a queue for send_command(); SHUTDOWN or a dropped link
    triggers an alert and an automatic reconnect."""

    def __init__(self, speaker):
        self.speaker = speaker
        self.sock = None
        self.ever_dropped = False
        self.replies = queue.Queue()
        self.connected = threading.Event()
        self.send_lock = threading.Lock()
        self.command_lock = threading.Lock()  # one command in flight (mic + keyboard)
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
            if self.ever_dropped:
                self.speaker.say("Hub online.")
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

        self.ever_dropped = True
        if hub_shutdown:
            print("\n[ALERT] Hub was shut down (Ctrl+C on the PC). Waiting for it to come back...")
        else:
            print("\n[ALERT] Lost connection to hub. Reconnecting...")
        self.speaker.say("Hub offline.")
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
        with self.command_lock:
            return self._send_command(text)

    def _send_command(self, text):
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
            self.speaker.say(spoken_text(reply))
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


# ---------- Text input ----------
def text_loop(link):
    print("[TEXT] Type a command and press Enter (Ctrl+C to quit)")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:  # Ctrl+D or no stdin
            raise KeyboardInterrupt
        if text:
            link.send_command(text)


# ---------- Voice input ----------
class VoiceInput:
    """Microphone -> Vosk speech-to-text. Loads the model up front so problems show immediately."""

    def __init__(self, speaker, wake=True):
        self.wake = wake
        self.awake_until = 0.0    # monotonic time when the follow-up window closes
        self.beeped = False       # already beeped for the utterance in progress
        # Imported here so text-only runs work without audio libraries installed
        import sounddevice as sd
        from vosk import Model, KaldiRecognizer, SetLogLevel

        SetLogLevel(-1)
        if not os.path.isdir(MODEL_PATH):
            print(f"[ERROR] Vosk model not found at '{MODEL_PATH}'. Set VOSK_MODEL_PATH in .env.")
            sys.exit(1)

        self.sd = sd
        self.speaker = speaker
        self.samplerate = self._pick_samplerate()
        print(f"[MIC] Recording at {self.samplerate} Hz")
        self.rec = KaldiRecognizer(Model(MODEL_PATH), self.samplerate)
        self.audio_q = queue.Queue()
        self.overflows = 0

    def _pick_samplerate(self):
        """Vosk's models are trained at 16 kHz, and recording at 16 kHz is ~3x less work
        than 48 kHz, which helps the Pi keep up. PipeWire resamples if the mic can't."""
        try:
            self.sd.check_input_settings(device=MIC_DEVICE, samplerate=16000,
                                         channels=1, dtype="int16")
            return 16000
        except Exception:
            return int(self.sd.query_devices(MIC_DEVICE, "input")["default_samplerate"])

    def _callback(self, indata, frames, time_info, status):
        if status:
            # An occasional overflow just drops a few milliseconds of audio. Report it
            # once, then only every 50th time, so the console stays readable.
            self.overflows += 1
            if self.overflows == 1 or self.overflows % 50 == 0:
                print(f"[AUDIO] {status} (x{self.overflows})", file=sys.stderr)
        if self.speaker.is_active():
            return  # don't transcribe our own voice
        self.audio_q.put(bytes(indata))

    # ---------- wake word ----------
    def _is_awake(self):
        return time.monotonic() < self.awake_until

    def _wake_up(self):
        if not self.beeped:
            self.speaker.beep()
            self.beeped = True
            print(f"[WAKE] Listening (follow-ups for {WAKE_TIMEOUT:.0f}s)")
        self.awake_until = time.monotonic() + WAKE_TIMEOUT

    def _check_partial(self):
        """Beep as soon as the wake phrase shows up mid-sentence, not after it ends."""
        if self.beeped or self._is_awake():
            return
        partial = json.loads(self.rec.PartialResult()).get("partial", "")
        if find_wake(partial) is not None:
            self._wake_up()

    def _command_from(self, text):
        """Decide what (if anything) to send for a finished utterance."""
        if not self.wake:
            return text
        after = find_wake(text)
        if after is not None:              # "hey sirius ..." (with or without a command)
            self._wake_up()
            return after or None
        if self.beeped:                    # partial heard the wake word, final text dropped it
            self.awake_until = time.monotonic() + WAKE_TIMEOUT
            return text
        if self._is_awake():               # follow-up within the window
            return text
        print(f"[ASLEEP] Ignored: {text}  (say \"{WAKE_PHRASE}\" first)")
        return None

    # ---------- main loop ----------
    def run(self, link):
        # latency="high" gives the audio system a bigger buffer, which prevents overflows
        with self.sd.RawInputStream(samplerate=self.samplerate, blocksize=4000, device=MIC_DEVICE,
                                    dtype="int16", channels=1, latency="high",
                                    callback=self._callback):
            if self.wake:
                print(f"[LISTENING] Say \"{WAKE_PHRASE}\" to start")
            else:
                print("[LISTENING] Speak a command")
            was_awake = False
            while True:
                try:
                    data = self.audio_q.get(timeout=0.5)
                except queue.Empty:
                    data = None

                # Announce when the follow-up window closes
                awake = self._is_awake()
                if was_awake and not awake and self.wake:
                    print(f"[SLEEP] Say \"{WAKE_PHRASE}\" to wake")
                was_awake = awake
                if data is None:
                    continue

                if not self.rec.AcceptWaveform(data):
                    if self.wake:
                        self._check_partial()
                    continue  # phrase not finished yet

                text = json.loads(self.rec.Result()).get("text", "").strip()
                command = self._command_from(text) if text else None
                self.beeped = False
                if not command:
                    continue

                print(f"[HEARD] {command}")
                link.send_command(command)
                if self.wake:  # follow-up window starts after the reply is finished
                    self.awake_until = time.monotonic() + WAKE_TIMEOUT
                    was_awake = True
                with self.audio_q.mutex:   # drop anything captured while waiting / speaking
                    self.audio_q.queue.clear()
                self.rec.Reset()

    def run_safely(self, link):
        """For 'both' mode: a mic failure shouldn't take down text input."""
        try:
            self.run(link)
        except Exception as e:
            print(f"\n[ERROR] Voice input stopped ({e}). Text input still works.")


# ---------- Main ----------
def parse_args():
    parser = argparse.ArgumentParser(
        description="SIRIUS wrist computer client",
        epilog="Examples:  -i text -o text   |   -i voice -o text   |   -i both -o speech")
    parser.add_argument("-i", "--input", choices=["text", "voice", "both"],
                        default=os.getenv("INPUT_MODE", "voice").strip().lower(),
                        help="how commands are given (default: INPUT_MODE in .env, else voice)")
    parser.add_argument("-w", "--wake", choices=["on", "off"],
                        default=os.getenv("WAKE_WORD", "on").strip().lower(),
                        help='require the wake word before voice commands (default: WAKE_WORD in .env, else on)')
    parser.add_argument("-o", "--output", choices=["text", "speech"],
                        default=os.getenv("OUTPUT_MODE", "speech").strip().lower(),
                        help="how replies are given; text always prints (default: OUTPUT_MODE in .env, else speech)")
    args = parser.parse_args()
    # defaults from .env aren't checked by argparse, so check them here
    if args.input not in ("text", "voice", "both"):
        parser.error(f"INPUT_MODE must be text, voice, or both (got '{args.input}')")
    if args.wake not in ("on", "off"):
        parser.error(f"WAKE_WORD must be on or off (got '{args.wake}')")
    if args.output not in ("text", "speech"):
        parser.error(f"OUTPUT_MODE must be text or speech (got '{args.output}')")
    return args


def main():
    args = parse_args()
    wake_note = f"  |  wake word: {args.wake}" if args.input != "text" else ""
    print(f"[MODE] input: {args.input}  |  output: {args.output}{wake_note}")

    speaker = Speaker(quiet=True) if args.output == "text" else Speaker()
    voice = VoiceInput(speaker, wake=(args.wake == "on")) if args.input in ("voice", "both") else None

    link = HubLink(speaker)
    try:
        link.start()
        if args.input == "text":
            text_loop(link)
        elif args.input == "voice":
            voice.run(link)
        else:  # both: mic in the background, keyboard in front
            threading.Thread(target=voice.run_safely, args=(link,), daemon=True).start()
            text_loop(link)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Ctrl+C detected, notifying hub...")
        link.shutdown()
    finally:
        link.close()
        print("[EXIT] Client closed.")


if __name__ == "__main__":
    main()