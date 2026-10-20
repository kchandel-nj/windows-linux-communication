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
| `.env` | Both | IPs, port, device ID, and client settings |
| `requirements.txt` | Wrist computer | Python packages (used by Docker and manual installs) |
| `docker/` | Wrist computer | `Dockerfile`, `docker-compose.yml`, `Dockerfile.dockerignore`; containerized client with models included |
| `voices/` | Wrist computer | Piper voice files (`.onnx` + `.onnx.json`); downloaded by `setup.sh`, not committed |

## Configuration (`.env`)

Hub (`.env` one folder above `pc_server.py`):
```
SERVER_PORT=5001
OLLAMA_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_TIMEOUT=50          # keep below the client's RESPONSE_TIMEOUT
OLLAMA_KEEP_ALIVE=-1       # keep the model loaded in GPU memory (or e.g. 30m)
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
1. Start Ollama and make sure your model is pulled (e.g. `ollama pull llama3.2`).
2. Allow inbound TCP 5001 in Windows Defender Firewall if prompted or blocked.
3. Run `python pc_server.py`.

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

Log prefixes: `[CONNECTED]`, `[LISTENING]`, `[TEXT MODE]`, `[HEARD]`, `[HUB]`, `[OFFLINE]`, `[ALERT]`, `[RETRY]`, `[SHUTDOWN]`, `[EXIT]`.

## Troubleshooting

**`no configuration file provided: not found`:** run Docker commands from the folder containing `docker-compose.yml`, and check that downloads weren't renamed (e.g. `docker-compose.yml.txt`).

**`dotenv` not found on Linux:** use `sudo apt install python3-dotenv` or add `--break-system-packages` to pip.

**Every reply is `"status": "ERROR"` with "Ollama unreachable":** start Ollama on the hub and confirm the model in `OLLAMA_MODEL` is pulled (`ollama list`).

**`.env` settings ignored on the hub (startup line shows the wrong model):** `pc_server.py` looks for `.env` next to itself, then one folder up, and prints which file it loaded. Check the file isn't secretly named `.env.txt` (`Get-ChildItem -Force`).

**Hub ignores Ctrl+C on Windows:** fixed by the 1-second accept timeout; if you're on an older copy of `pc_server.py`, update it.

**Voice mode hears nothing:**
- In a VirtualBox VM: enable Audio Input in VM settings *and* under Devices → Audio while running; try the Windows DirectSound driver or ICH AC97 controller; confirm the Windows mic privacy setting and default input device.
- Check the input in Ubuntu with `pavucontrol` (not muted, meter moves).
- On a Linux desktop, route the container through PipeWire/PulseAudio (mount the pulse socket, set `MIC_DEVICE=pulse`) instead of `/dev/snd`.
- Use `INPUT_MODE=text` to test the rest of the pipeline in the meantime.

## Status

- Socket link, reconnect, shutdown alerts, `.env` config, and Docker packaging: working.
- Text mode end to end (wrist → hub → Ollama → wrist): working.
- Ollama responses are not yet grounded in live TSS data.
- Voice mode: mic input not yet reaching the Ubuntu VirtualBox test machine. Not expected to affect the Raspberry Pi target.
- Text-to-speech of reply summaries: implemented; to be tested on the target audio hardware.
- Planned: relaying responses to the HMD.