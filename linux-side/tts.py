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
PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-lessac-medium.onnx")
_spk = os.getenv("SPEAKER_DEVICE", "").strip()
SPEAKER_DEVICE = int(_spk) if _spk.isdigit() else (_spk or None)

# Ignore the mic for this long after speech ends, so the tail of our own
# voice (and room echo) isn't transcribed as a command
MIC_QUIET_TAIL = 0.6


class Speaker:
    def __init__(self):
        self._lock = threading.Lock()   # one utterance at a time
        self._busy = threading.Event()
        self._quiet_until = 0.0
        self._voice = None
        self.engine = self._init_engine(TTS_ENGINE)
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
        import sounddevice as sd
        stream = None
        try:
            for chunk in self._voice.synthesize(text):
                if stream is None:  # open once we know the voice's sample rate
                    stream = sd.RawOutputStream(samplerate=chunk.sample_rate, channels=1,
                                                dtype="int16", device=SPEAKER_DEVICE)
                    stream.start()
                stream.write(chunk.audio_int16_bytes)
        finally:
            if stream is not None:
                stream.stop()   # waits for buffered audio to finish playing
                stream.close()


def spoken_text(reply):
    """Pick what to say for a hub reply."""
    if reply.get("status") == "ERROR":
        return "Assistant unavailable."
    return reply.get("summary") or ""