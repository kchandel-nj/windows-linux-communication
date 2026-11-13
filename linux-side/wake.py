"""
wake.py  (wrist computer wake word)

Finds the wake phrase in recognized speech. Runs on the same Vosk recognizer
as commands, so no extra packages or models are needed.

"Sirius" isn't a common English word, so the small Vosk model usually hears it
as something close ("serious", "series", "cirrus"...). Those sound-alikes are
accepted too. If you change WAKE_PHRASE, list your own sound-alikes in
WAKE_ALIASES (comma-separated full phrases) after checking what Vosk hears:
run with the wake word on and watch the [ASLEEP] lines.

Settings (.env):
  WAKE_WORD     on | off           (default on; also -w / --wake on the command line)
  WAKE_PHRASE   phrase to listen for (default "hey sirius")
  WAKE_ALIASES  extra phrases that also count, e.g. "hey serious, a serious"
  WAKE_TIMEOUT  seconds to stay awake for follow-ups (default 10)
"""

import os
import re

WAKE_PHRASE = os.getenv("WAKE_PHRASE", "hey sirius").strip().lower()
WAKE_TIMEOUT = float(os.getenv("WAKE_TIMEOUT", "10"))
_aliases = [a.strip().lower() for a in os.getenv("WAKE_ALIASES", "").split(",") if a.strip()]

# How Vosk tends to hear these words
_SOUND_ALIKES = {
    "hey": ["hey", "hay", "hi", "hate"],
    "sirius": ["sirius", "serious", "series", "cirrus", "cyrus", "syria", "sirus", "sirius's"],
}


def _phrase_pattern(phrase):
    parts = []
    for word in phrase.split():
        options = _SOUND_ALIKES.get(word, [word])
        parts.append("(?:" + "|".join(re.escape(o) for o in options) + ")")
    return r"\s+".join(parts)


_patterns = [_phrase_pattern(WAKE_PHRASE)] + [re.escape(a).replace(r"\ ", r"\s+") for a in _aliases]
_WAKE_RE = re.compile(r"\b(?:" + "|".join(_patterns) + r")\b", re.IGNORECASE)


def find_wake(text):
    """If text contains the wake phrase, return what was said after it
    ("" if nothing); otherwise None.
      "hey serious what's my oxygen" -> "what's my oxygen"
      "hey sirius"                   -> ""
      "what's my oxygen"             -> None
    """
    match = _WAKE_RE.search(text or "")
    if not match:
        return None
    return text[match.end():].strip(" ,.!?")


if __name__ == "__main__":
    # Try it:  python wake.py "hey serious what is my oxygen"
    import sys
    phrase = " ".join(sys.argv[1:]) or "hey serious what is my oxygen level"
    print(repr(phrase), "->", repr(find_wake(phrase)))