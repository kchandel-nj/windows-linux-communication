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
    def __init__(self, engine=None):
        """engine overrides TTS_ENGINE from .env (e.g. "none" for text-only output)."""
        self._lock = threading.Lock()   # one utterance at a time
        self._busy = threading.Event()
        self._quiet_until = 0.0
        self._voice = None
        self._warned_aplay = False
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
        if not text:
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
        try:
            self._play_sounddevice(audio, rate)
        except Exception as e:
            # PortAudio sometimes finds no default output (e.g. "Error querying
            # device -1"); aplay goes through ALSA's default, which PipeWire handles
            if not shutil.which("aplay"):
                raise
            if not self._warned_aplay:
                print(f"[TTS] sounddevice output failed ({e}); using aplay instead.")
                self._warned_aplay = True
            cmd = ["aplay", "-q", "-r", str(rate), "-f", "S16_LE", "-c", "1", "-t", "raw"]
            if isinstance(SPEAKER_DEVICE, str):  # e.g. "pipewire", "pulse", "plughw:2,0"
                cmd[1:1] = ["-D", SPEAKER_DEVICE]
            subprocess.run(cmd, input=audio, check=True)

    def _play_sounddevice(self, audio, rate):
        import sounddevice as sd
        with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16",
                                device=SPEAKER_DEVICE) as stream:
            stream.write(audio)


def spoken_text(reply):
    """Pick what to say for a hub reply."""
    if reply.get("status") == "ERROR":
        return "Assistant unavailable."
    return reply.get("summary") or ""