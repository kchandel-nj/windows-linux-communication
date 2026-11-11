# SIRIUS Voice Command Pipeline

A crew member's wrist computer (Linux / Raspberry Pi) captures a command, sends it to the central hub (Windows desktop), the hub runs it through a local Ollama model, and a JSON telemetry reply comes back.

```
Crew voice / typed text
        │
        ▼
Wrist computer (Linux / Pi)  ──TCP, newline JSON──▶  Central hub (Windows)
  voice_client.py                                     pc_server.py
  Vosk speech-to-text                                 Ollama (localhost:11434)
        ▲                                             NASA TSS ingest
        └────────────── JSON telemetry reply ─────────────┘
```

## Files

| File | Where it runs | Purpose |
|---|---|---|
| `voice_client.py` | Wrist computer | Captures commands (voice or text), sends them to the hub, prints and speaks replies |
| `tts.py` | Wrist computer | Offline text-to-speech (Piper, espeak-ng fallback) |
| `run.sh` | Wrist computer | Presets for the input/output modes |
| `setup.sh` | Wrist computer | One-time setup: packages, venv, Vosk model, Piper voice, starter `.env` |
| `pc_server.py` | Hub | Multi-client TCP server; sends voice commands to Ollama and returns JSON |
| `setup.bat`, `run.bat` | Hub | One-time Windows setup; start the hub |
| `demo_telemetry.py` | Hub | Simulated suit telemetry for demos (`TELEMETRY_SOURCE=demo`) |
| `.env` | Both | IPs, port, device ID, and client settings |
| `requirements.txt` | Wrist computer | Python packages (used by Docker and manual installs) |
| `docker/` | Wrist computer | `Dockerfile`, `docker-compose.yml`, `Dockerfile.dockerignore`; containerized client with models included |
| `voices/` | Wrist computer | Piper voice files (`.onnx` + `.onnx.json`); downloaded by `setup.sh`, not committed |

## Configuration (`.env`)

Hub (`.env` next to `pc_server.py`, or one folder up). **On the `classroom-demo` branch this sample is preset for the classroom demo**; copy it as-is:
```
SERVER_PORT=5001
OLLAMA_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_TIMEOUT=50          # keep below the client's RESPONSE_TIMEOUT
OLLAMA_KEEP_ALIVE=-1       # keep the model loaded in GPU memory (or e.g. 30m)
TELEMETRY_SOURCE=demo      # demo (simulated values) or none (until the TSS client exists)
PROMPT_STYLE=classroom     # classroom (friendly, grades 8-12) or mission (terse, NASA style)
GUARDRAIL=on               # on, or off to demonstrate hallucinations
DEMO_SPEED=10              # demo only: simulated EVA minutes per real minute
DEMO_EVENT_RATE=0.05       # demo only: chance of a random event each simulated minute (0 = none)
DEMO_SEED=                 # demo only: a number replays the same EVA every time; blank = new EVA each run
```

Wrist computer:

```
SERVER_IP=192.168.1.50     # hub's IPv4 address (run ipconfig on Windows)
SERVER_PORT=5001
DEVICE_ID=linux-node-01
INPUT_MODE=voice           # text, voice, or both (default when no -i flag)
OUTPUT_MODE=speech         # text or speech (default when no -o flag)
MIC_DEVICE=                # blank = default, or a number/name from the device list
RESPONSE_TIMEOUT=60        # seconds to wait for Ollama
TTS_ENGINE=piper           # piper, espeak, or none
SPEAKER_DEVICE=            # blank = default output, or a number/name from the device list
VOSK_MODEL_PATH=vosk-model-small-en-us-0.15   # unzipped Vosk model folder (voice input)
PIPER_VOICE=voices/en_US-lessac-medium.onnx   # Piper voice; its .onnx.json must sit beside it
```

Keep `VOSK_MODEL_PATH` and `PIPER_VOICE` as the relative paths shown: they're relative to `linux-side/`, and the Docker image puts the model and voice at the same relative locations, so one `.env` works both natively and in Docker. Only change them if you use a different model or voice (and download it to match).

## Message protocol

Every message is one JSON object followed by a newline (`\n`).

Command (wrist → hub):
```json
{"device_id": "linux-node-01", "type": "voice_command", "text": "what is my oxygen level", "timestamp": "2026-10-16T20:57:14+00:00"}
```

Reply (hub → wrist): exactly **one** JSON object on **one** line per command. Ollama's output is merged with status fields:
```json
{"intent": "oxygen_status", "summary": "Oxygen is at 82 percent.", "data": {"o2_percent": 82}, "status": "SUCCESS", "device_id": "linux-node-01", "command": "what is my oxygen level"}
```
On failure (Ollama down, bad model output, invalid JSON) the hub still replies once, with `"status": "ERROR"` and an `"error"` message. The reply schema is set by `SYSTEM_PROMPT` in `pc_server.py`; edit it to match your telemetry fields.

Shutdown (either direction; the client listens in the background, so it reacts instantly):
```json
{"status": "SHUTDOWN", "device_id": "linux-node-01"}
```

Connections stay open for any number of commands. Each client runs in its own thread, so multiple wrist computers can connect at once.

## Input and output modes

Input and output are chosen independently. Replies are always printed; `speech` also reads them aloud.

| Preset | Flags | Input | Output |
|---|---|---|---|
| `./run.sh text` | `-i text -o text` | keyboard | text |
| `./run.sh mic` | `-i voice -o text` | microphone | text |
| `./run.sh speak` | `-i text -o speech` | keyboard | text + speech |
| `./run.sh full` | `-i voice -o speech` | microphone | text + speech |
| `./run.sh both` | `-i both -o speech` | microphone and keyboard | text + speech |

`run.sh` activates `~/sirius-venv` if it exists. Any flags can also be passed directly: `python3 voice_client.py -i both -o text`. Without flags, `INPUT_MODE` / `OUTPUT_MODE` from `.env` are used. Run `python3 voice_client.py --help` for the full list.

## Running

### Hub (Windows)
**First time:** double-click `setup.bat` in the hub folder (safe to rerun). It installs Python and Ollama with winget if they're missing, installs `requirements.txt`, creates a starter `.env`, pulls the model named in `OLLAMA_MODEL`, and adds a firewall rule for `SERVER_PORT` (asks for admin permission once). At the end it lists the PC's IPv4 addresses to use as `SERVER_IP` on the wrist computer. If it just installed Python, close the window and run it again.

**Running:** double-click `run.bat`, or run `python pc_server.py`. Ollama must be running (tray icon); check `ollama ps` for `100% GPU`.

### Wrist computer: natively

**First time:** on a fresh Pi, run `./setup.sh` once (safe to rerun). It installs everything, creates `~/sirius-venv`, downloads the models, and creates a starter `.env`. Then set `SERVER_IP` in `.env`.

**Running:** from `linux-side/`, pick a preset:
```bash
./run.sh text     # type commands, replies as text
./run.sh mic      # speak commands, replies as text
./run.sh speak    # type commands, replies as text + speech
./run.sh full     # speak commands, replies as text + speech
./run.sh both     # speak or type commands, replies as text + speech
./run.sh          # no preset: uses INPUT_MODE / OUTPUT_MODE from .env
```
Or give any combination of flags directly; they pass straight through to `voice_client.py`:
```bash
./run.sh -i both -o text     # speak or type, text-only replies
./run.sh --help              # all options
```
`run.sh` switches into `~/sirius-venv` automatically if it exists, so there's no need to activate it first. Press Ctrl+C to quit; the hub is notified.

Speech output needs a speaker; with none connected, use `text` or `mic`. Voice input needs a microphone.

**Manual install, if you prefer not to use `setup.sh`:** text-only runs need just `python-dotenv`. Speech also needs `piper-tts`, `sounddevice`, `libportaudio2`, and a Piper voice in `voices/`. Voice input also needs `vosk` and a Vosk model from alphacephei.com/vosk/models.

### Wrist computer: Docker
Run these from `linux-side/docker/` (or from `linux-side/` with `-f docker/docker-compose.yml` after `docker compose`).
```bash
docker compose build

# Any mode (interactive)
docker compose run --rm voice-client python voice_client.py -i text -o text

# Voice mode
docker compose run --rm voice-client python -m sounddevice   # find your mic, set MIC_DEVICE
docker compose up -d
docker compose logs -f
docker compose stop          # sends SHUTDOWN to the hub
```

## Audio setup (Raspberry Pi)

The Pi 5 has no headphone jack or built-in mic, so use a USB headset (easiest: mic and speaker in one), or a USB/Bluetooth speaker plus a USB mic.

1. Make sure ALSA programs are routed through PipeWire (`setup.sh` installs these; reboot after installing by hand):
   ```bash
   sudo apt install pipewire-alsa pipewire-bin pulseaudio-utils
   ```
2. Select the headset for **output and input** from the taskbar speaker icon, or with `wpctl status` then `wpctl set-default <number>` (the default sink has a `*`).
3. Leave `MIC_DEVICE` and `SPEAKER_DEVICE` blank in `.env` so the desktop's selection is used.
4. Test outside the app:
   ```bash
   pw-play /usr/share/sounds/alsa/Front_Center.wav            # speaker via PipeWire
   speaker-test -t wav -c 2 -l 1                              # speaker via ALSA
   arecord -d 5 -f S16_LE -r 16000 test.wav && aplay test.wav # mic
   ```
5. Run `./run.sh full`. At startup look for `[MIC] Recording at 16000 Hz` and `[TTS] Engine: piper`; after the first reply, `[TTS] Playing through pw-play`.

The client records at 16 kHz (Vosk's native rate, and about a third of the CPU work of 48 kHz) and tries several playback methods in order (`SPEAKER_DEVICE` if set, `pw-play`, `paplay`, sounddevice, `aplay`), keeping the first that works.

## Text-to-speech

The wrist computer reads each reply's `summary` aloud; errors are spoken as "Assistant unavailable." It also says "Hub offline." / "Hub online." when the connection changes. The hub's system prompt keeps summaries telegraphic, per the NASA guidance ("Primary O2 47%, Secondary 99%.").

While speaking (plus 0.6 s afterward) the mic is ignored, so the assistant never transcribes its own voice.

If Piper fails to load it falls back to espeak-ng, then to text only; the `[TTS] Engine:` line at startup shows which is active.

Native setup:
```bash
python3 -m pip install piper-tts --break-system-packages
sudo apt install espeak-ng          # optional fallback
mkdir -p voices && cd voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```
Other voices: browse the rhasspy/piper-voices repository on Hugging Face and download both the `.onnx` and `.onnx.json` files.

## Classroom demo mode

This branch (`classroom-demo`) is set up for demonstrations to students (grades 8-12). The hub `.env` sample under Configuration, and the starter `.env` that `setup.bat` creates, already turn demo mode on (`TELEMETRY_SOURCE=demo`, `PROMPT_STYLE=classroom`). Start `pc_server.py` and check the startup line: `Telemetry: demo | Prompt: classroom | Guardrail: on`.

To run the regular mission behavior instead, change those two lines to `TELEMETRY_SOURCE=none` and `PROMPT_STYLE=mission`, or use the `main` branch.

- **Simulated telemetry** (`demo_telemetry.py`) stands in for NASA's TSS, and every run is different: starting values and drain rates are randomized, readings wander naturally, and random events occur during the EVA, each triggering warnings:

  | Event | What happens | Warnings |
  |---|---|---|
  | Exertion | heart rate climbs ~50 bpm | `HIGH HEART RATE` |
  | O2 leak | oxygen drains 4x faster, suit pressure dips | `RAPID O2 LOSS`, `LOW SUIT PRESSURE` |
  | CO2 scrubber saturation | CO2 climbs until the scrubber switches A to B | `HIGH CO2` |
  | Overheating | suit temperature rises toward 85 F | `SUIT TEMPERATURE HIGH` |
  | Battery drain | battery drains 5x faster | `LOW BATTERY` (once below 20%) |

  Every reading also changes from moment to moment: oxygen and battery drain smoothly (shown to two decimals), the EVA clock runs, position keeps moving, and sensors carry small jitter, so asking the same question twice always gives a slightly different answer. The hub's guardrail accepts a telemetry value exactly or rounded (99.43 may be spoken as "99" or "99.4").

  The suit also reacts on its own: primary O2 hands over to secondary when nearly empty. `DEMO_SPEED` sets how fast EVA time passes (default 10x, so changes show up within a class period), `DEMO_EVENT_RATE` how often events happen, and `DEMO_SEED` replays an identical EVA, useful for rehearsing a demo. Restarting the hub starts a new EVA. Run `python demo_telemetry.py` to preview a whole 4-hour EVA instantly.
- **Classroom prompt:** friendly one-to-two-sentence answers that explain what a reading means, mention warnings first, answer general space questions in plain language, and steer off-topic questions back to the mission.
- **Guardrail demo:** general answers can't include numbers (only telemetry numbers are allowed), so "How far is the Moon?" answered with a number is blocked and spoken as "Data unavailable." To show students why the guardrail exists, set `GUARDRAIL=off`, restart, and ask questions the telemetry can't answer; the model will often make up confident-sounding numbers. Turn it back on afterward.

Good questions to try: "What's my oxygen level?", "How's my heart rate?", "How far am I from the lander?", "Is my battery okay?", "Why do astronauts need spacesuits?"

## Behavior

| Event | What happens |
|---|---|
| Ctrl+C on the wrist computer | Sends `SHUTDOWN` to the hub, then exits |
| `docker compose stop` | Same as Ctrl+C (`stop_signal: SIGINT`) |
| Hub offline at startup | `[OFFLINE]` message, retries every 5 s |
| Connection drops mid-command | Reconnects and resends the command once (`[RETRY]`) |
| Hub stopped with Ctrl+C | Hub sends `SHUTDOWN` to every client; client immediately shows `[ALERT] Hub was shut down` and reconnects every 5 s until the hub is back |
| Hub crashes or network drops | Client immediately shows `[ALERT] Lost connection to hub` and reconnects |
| Command sent while hub is offline | `[OFFLINE] ... was not sent` (not queued) |
| Client disconnects (Ctrl+C or drop) | Hub prints an `[ALERT]` with the device ID; other clients are unaffected |
| No reply within `RESPONSE_TIMEOUT` | Treated as a dropped connection |

Log prefixes (wrist computer): `[MODE]` chosen input/output, `[MIC]` recording rate, `[TTS]` speech engine and playback method, `[CONNECTED]`, `[LISTENING]`, `[TEXT]`, `[HEARD]` what the mic recognized, `[HUB]` reply, `[SAY]` what's being spoken, `[AUDIO]` audio warnings, `[OFFLINE]`, `[ALERT]`, `[RETRY]`, `[SHUTDOWN]`, `[EXIT]`.

Log prefixes (hub): `[COMMAND]`, `[REPLY]`, `[GUARD]` hallucination guardrail blocked a value, `[Error]`, `[ALERT]`.

## Troubleshooting

**`no configuration file provided: not found`:** run Docker commands from the folder containing `docker-compose.yml`, and check that downloads weren't renamed (e.g. `docker-compose.yml.txt`).

**`dotenv` not found on Linux:** use `sudo apt install python3-dotenv` or add `--break-system-packages` to pip.

**Every reply is `"status": "ERROR"` with "Ollama unreachable":** start Ollama on the hub and confirm the model in `OLLAMA_MODEL` is pulled (`ollama list`).

**`.env` settings ignored on the hub (startup line shows the wrong model):** `pc_server.py` looks for `.env` next to itself, then one folder up, and prints which file it loaded. Check the file isn't secretly named `.env.txt` (`Get-ChildItem -Force`).

**Hub ignores Ctrl+C on Windows:** fixed by the 1-second accept timeout; if you're on an older copy of `pc_server.py`, update it.

**Speech: `[SAY]` appears but nothing is heard:**
- `[TTS] Playing through sounddevice` (not `pw-play`) and silence usually means ALSA isn't routed to PipeWire, so audio went to another output (e.g. HDMI). Install `pipewire-alsa pipewire-bin` and reboot.
- Check the headset is the default sink (`wpctl status`, `*`), isn't muted (`wpctl get-volume @DEFAULT_AUDIO_SINK@`), and its cable volume/mute switch.
- If `pw-play /usr/share/sounds/alsa/Front_Center.wav` is silent too, test the hardware directly: `aplay -l`, then `speaker-test -D plughw:<card>,0 -t wav -c 2 -l 1`. If that works, `SPEAKER_DEVICE=plughw:<card>,0` in `.env` is a direct workaround.
- `[TTS] Playback failed: no audio output worked -> ...` lists why each method failed.
- `[TTS] Engine: espeak` or `none`: Piper didn't load (not installed in the venv, or voice missing from `voices/`); the line above it says why.

**`[AUDIO] input overflow`:** a few milliseconds of mic audio were dropped. Occasional ones are harmless (they're reported once, then every 50th). Frequent ones: check `[MIC]` says 16000 Hz and close other heavy programs.

**Voice mode hears nothing:**
- Select the headset as input in the taskbar sound menu and test with the `arecord` command above.
- In a VirtualBox VM: enable Audio Input in VM settings *and* under Devices → Audio while running; confirm the Windows mic privacy setting and default input device.
- In Docker on a desktop, the container must use the PipeWire/PulseAudio compose setup (`MIC_DEVICE=pulse`).
- Use `./run.sh text` to test the rest of the pipeline in the meantime.

**Hub: "Python was not found" on Windows:** `python` is a Microsoft Store shortcut. Use `py` instead (`setup.bat`/`run.bat` do this automatically), or turn off the python.exe entries under Settings → Apps → Advanced app settings → App execution aliases.

**Hub: 404 from Ollama:** the model in `OLLAMA_MODEL` isn't pulled on this PC (`ollama pull <name>`), or `.env` isn't being read (the startup line shows which model is in use).

## Status

- Socket link, reconnect, shutdown alerts, `.env` config, and Docker packaging: working.
- Text mode end to end (wrist → hub → Ollama → wrist): working.
- Ollama responses are not yet grounded in live TSS data.
- Voice input and spoken replies on the Raspberry Pi 5 with a USB headset: working.
- Hallucination guardrail: blocks any spoken number not present in telemetry.
- Planned: relaying responses to the HMD.