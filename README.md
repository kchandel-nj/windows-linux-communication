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
| `pc_server.py` | Hub | Multi-client TCP server; sends voice commands to Ollama and returns JSON |
| `.env` | Both | IPs, port, device ID, and client settings |
| `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.dockerignore` | Wrist computer | Containerized client, Vosk model included |

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
INPUT_MODE=voice           # voice or text
MIC_DEVICE=                # blank = default, or a number/name from the device list
RESPONSE_TIMEOUT=60        # seconds to wait for Ollama
TTS_ENGINE=piper           # piper, espeak, or none
PIPER_VOICE=en_US-lessac-medium.onnx   # Piper voice file (.onnx.json must sit beside it)
SPEAKER_DEVICE=            # blank = default output, or a number/name from the device list
```

When running in Docker, leave out `VOSK_MODEL_PATH` and `PIPER_VOICE`; the image sets both. When running natively in voice mode, set it to the unzipped model folder.

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

## Running

### Hub (Windows)
1. Start Ollama and make sure your model is pulled (e.g. `ollama pull llama3.2`).
2. Allow inbound TCP 5001 in Windows Defender Firewall if prompted or blocked.
3. Run `python pc_server.py`.

### Wrist computer: natively
```bash
python3 -m pip install python-dotenv --break-system-packages   # or: sudo apt install python3-dotenv
INPUT_MODE=text python3 voice_client.py
```
Text mode needs only `python-dotenv` (plus `piper-tts` and `sounddevice` if you want speech). Voice mode also needs `vosk`, `sounddevice`, `libportaudio2`, and a Vosk model from alphacephei.com/vosk/models.

### Wrist computer: Docker
```bash
docker compose build

# Text mode (interactive)
docker compose run --rm -e INPUT_MODE=text voice-client

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