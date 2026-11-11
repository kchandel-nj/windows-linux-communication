"""
tts.py  (wrist computer text-to-speech)

Speaks short replies to the crew member, fully offline.

Engines (TTS_ENGINE in .env):
  piper   (default) - natural neural voice, runs on a Raspberry Pi
  espeak            - robotic but tiny and instant (espeak-ng)
  none              - print only, no audio

If Piper can't load, it falls back to espeak-ng, then to none.
"""

import os
import shutil
import subprocess
import threading
import time

TTS_ENGINE = os.getenv("TTS_ENGINE", "piper").strip().lower()
_HERE = os.path.dirname(os.path.abspath(__file__))
PIPER_VOICE = os.getenv("PIPER_VOICE", "voices/en_US-lessac-medium.onnx")
if not os.path.isabs(PIPER_VOICE):  # relative paths are relative to this folder
    PIPER_VOICE = os.path.join(_HERE, PIPER_VOICE)
_spk = os.getenv("SPEAKER_DEVICE", "").strip()
SPEAKER_DEVICE = int(_spk) if _spk.isdigit() else (_spk or None)

# Ignore the mic for this long after speech ends, so the tail of our own
# voice (and room echo) isn't transcribed as a command
MIC_QUIET_TAIL = 0.6


class Speaker:
    def __init__(self, engine=None, quiet=False):
        """engine overrides TTS_ENGINE from .env.
        quiet=True (text-only output mode): no speech and no [TTS]/[SAY] lines."""
        self.quiet = quiet
        self._lock = threading.Lock()   # one utterance at a time
        self._busy = threading.Event()
        self._quiet_until = 0.0
        self._voice = None
        self._player = None  # playback method that worked, reused after the first success
        if quiet:
            self.engine = "none"
        else:
            self.engine = self._init_engine((engine or TTS_ENGINE).strip().lower())
            print(f"[TTS] Engine: {self.engine}")

    # ---------- setup ----------
    def _init_engine(self, engine):
        if engine == "piper":
            try:
                from piper import PiperVoice
                if not os.path.isfile(PIPER_VOICE):
                    raise FileNotFoundError(f"voice file '{PIPER_VOICE}' not found")
                self._voice = PiperVoice.load(PIPER_VOICE)
                return "piper"
            except Exception as e:  # missing package, bad voice file, etc.
                print(f"[TTS] Piper unavailable ({e}); trying espeak-ng.")
                engine = "espeak"
        if engine == "espeak":
            if shutil.which("espeak-ng"):
                return "espeak"
            print("[TTS] espeak-ng not installed; speech disabled.")
        return "none"

    # ---------- mic gating ----------
    def is_active(self):
        """True while speaking (plus a short tail). The mic ignores audio then."""
        return self._busy.is_set() or time.monotonic() < self._quiet_until

    # ---------- speaking ----------
    def say(self, text):
        """Speak text and block until done. Never raises."""
        text = (text or "").strip()
        if not text or self.quiet:
            return
        print(f"[SAY] {text}")
        if self.engine == "none":
            return
        with self._lock:
            self._busy.set()
            try:
                if self.engine == "piper":
                    self._say_piper(text)
                else:
                    subprocess.run(["espeak-ng", "-s", "170", text],
                                   check=False, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"[TTS] Playback failed: {e}")
            finally:
                self._quiet_until = time.monotonic() + MIC_QUIET_TAIL
                self._busy.clear()

    def _say_piper(self, text):
        chunks = list(self._voice.synthesize(text))
        if not chunks:
            return
        rate = chunks[0].sample_rate
        audio = b"".join(c.audio_int16_bytes for c in chunks)
        self._play(audio, rate)

    # ---------- playback ----------
    def _players(self):
        """Ways to play raw 16-bit mono audio, most reliable first.
        pw-play / paplay send audio straight to the desktop's default output
        (whatever is selected in the taskbar sound menu, e.g. a USB headset)."""
        players = []
        if SPEAKER_DEVICE is not None:  # an explicit choice wins
            players.append(("sounddevice", SPEAKER_DEVICE))
        if shutil.which("pw-play"):
            players.append(("pw-play", None))
        if shutil.which("paplay"):
            players.append(("paplay", None))
        players.append(("sounddevice", None))
        if shutil.which("aplay"):
            for dev in ("pipewire", "pulse", "default"):
                players.append(("aplay", dev))
        return players

    def _play(self, audio, rate):
        # Reuse whatever worked last time
        if self._player:
            try:
                return self._run_player(self._player, audio, rate)
            except Exception:
                self._player = None  # device unplugged etc.; search again

        errors = []
        for player in self._players():
            try:
                self._run_player(player, audio, rate)
                self._player = player
                name, dev = player
                print(f"[TTS] Playing through {name}" + (f" ({dev})" if dev is not None else ""))
                return
            except Exception as e:
                errors.append(f"{player[0]}{'(' + str(player[1]) + ')' if player[1] is not None else ''}: {e}")
        raise RuntimeError("no audio output worked -> " + " | ".join(errors))

    @staticmethod
    def _run_player(player, audio, rate):
        name, dev = player
        if name == "sounddevice":
            import sounddevice as sd
            with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16", device=dev) as stream:
                stream.write(audio)
            return
        if name == "pw-play":
            cmd = ["pw-play", "--rate", str(rate), "--channels", "1", "--format", "s16", "-"]
        elif name == "paplay":
            cmd = ["paplay", "--raw", f"--rate={rate}", "--channels=1", "--format=s16le"]
        else:  # aplay
            cmd = ["aplay", "-q", "-D", dev, "-r", str(rate), "-f", "S16_LE", "-c", "1", "-t", "raw"]
        result = subprocess.run(cmd, input=audio, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode(errors="replace").strip()[:120] or f"exit {result.returncode}")


def spoken_text(reply):
    """Pick what to say for a hub reply."""
    if reply.get("status") == "ERROR":
        return "Assistant unavailable."
    return reply.get("summary") or ""