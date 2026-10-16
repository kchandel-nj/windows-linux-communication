"""
pc_server.py  (central hub / Windows side)

TCP server for the wrist computers. Each connection stays open and handles
any number of newline-delimited JSON commands, one reply per command.

  {"type": "voice_command", "text": ...}  -> sent to local Ollama, JSON reply returned
  {"status": "SHUTDOWN"}                  -> client is leaving; connection closed
  anything else                           -> legacy sensor_reading processing

Each client gets its own thread, so several wrist computers can connect at once.
"""

import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request

from dotenv import load_dotenv

# .env lives one folder up from this file
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(parent_dir, ".env"))

SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.getenv("SERVER_PORT", 5001))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", 50))  # keep below the client's RESPONSE_TIMEOUT
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "-1")  # -1 = keep model loaded in VRAM

# Edit this to match your real telemetry schema.
SYSTEM_PROMPT = """You are the onboard assistant for a lunar EVA suit system.
Respond ONLY with a single JSON object, no markdown, no extra text, using exactly these keys:
  "intent":  short snake_case label for what the crew member asked (e.g. "oxygen_status")
  "summary": one short sentence to be read aloud to the crew member
  "data":    an object with any relevant telemetry fields and values
If you do not know a value, use null. Never invent readings."""


# ---------- Ollama ----------
def ask_ollama(text):
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": text,
        "stream": False,
        "format": "json",          # Ollama forces valid JSON output
        "options": {"num_predict": 300},  # cap reply length so output can't run on forever
        "keep_alive": int(OLLAMA_KEEP_ALIVE) if OLLAMA_KEEP_ALIVE.lstrip("-").isdigit() else OLLAMA_KEEP_ALIVE,
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
        raw = json.loads(resp.read())["response"].strip()

    # Strip markdown fences in case the model adds them anyway
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("model did not return a JSON object")
    return result


# ---------- Message handling ----------
def handle_message(message):
    device_id = message.get("device_id")

    if message.get("type") == "voice_command":
        text = message.get("text", "")
        print(f"[COMMAND] {device_id}: {text}")
        try:
            result = ask_ollama(text)
        except (TimeoutError, socket.timeout) as e:  # Ollama reachable but too slow
            print(f"[Error] Ollama took longer than {OLLAMA_TIMEOUT:.0f}s: {e}")
            return {"status": "ERROR", "device_id": device_id, "command": text,
                    "error": f"Ollama timed out after {OLLAMA_TIMEOUT:.0f}s"}
        except OSError as e:  # Ollama not running, connection refused, HTTP error
            print(f"[Error] Ollama unreachable: {e}")
            return {"status": "ERROR", "device_id": device_id, "command": text,
                    "error": f"Ollama unreachable: {e}"}
        except (ValueError, KeyError) as e:  # bad or non-JSON model output
            print(f"[Error] Bad model output: {e}")
            return {"status": "ERROR", "device_id": device_id, "command": text,
                    "error": f"Bad model output: {e}"}
        reply = {**result, "status": "SUCCESS", "device_id": device_id, "command": text}
        print(f"[REPLY] {reply}\n")
        return reply

    # Legacy telemetry path
    print(f"[Received Telemetry]: {message}\n")
    sensor_val = message.get("sensor_reading", 0)
    return {
        "status": "SUCCESS",
        "device_id": device_id,
        "computed_value": sensor_val * 1.055,
        "alert_triggered": sensor_val > 80,
    }


def send_json(sock, payload):
    # No indent: the reply must stay on a single line
    sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def handle_client(client_socket, client_address):
    ip = client_address[0]
    device_id = "unknown"
    buffer = b""
    print(f"[+] Client connected from {ip}")

    try:
        while True:
            while b"\n" not in buffer:
                chunk = client_socket.recv(4096)
                if not chunk:
                    raise ConnectionResetError("client closed the connection")
                buffer += chunk
            line, _, buffer = buffer.partition(b"\n")
            if not line.strip():
                continue

            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                print("[Error] Received invalid JSON format.\n")
                send_json(client_socket, {"status": "ERROR", "error": "invalid JSON"})
                continue

            device_id = message.get("device_id", device_id)

            if message.get("status") == "SHUTDOWN":
                print(f"\n[ALERT] Linux Client ({device_id}) was disconnected via Ctrl+C!")
                break

            send_json(client_socket, handle_message(message))

    except OSError as e:  # reset, aborted, broken pipe
        print(f"[ALERT] Client {device_id} ({ip}) dropped unexpectedly: {e}")
    finally:
        client_socket.close()


# ---------- Main ----------
def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((SERVER_HOST, SERVER_PORT))
    server_socket.listen(5)
    # Short timeout so Ctrl+C works on Windows (accept() otherwise blocks it)
    server_socket.settimeout(1.0)

    print(f"[*] Hub listening on port {SERVER_PORT} (Ollama model: {OLLAMA_MODEL})...")

    try:
        while True:
            try:
                client_socket, client_address = server_socket.accept()
            except socket.timeout:
                continue
            client_socket.settimeout(None)
            threading.Thread(target=handle_client, args=(client_socket, client_address),
                             daemon=True).start()
    except KeyboardInterrupt:
        print("\n[*] Hub detected Ctrl+C! Shutting down...")
    finally:
        server_socket.close()
        sys.exit(0)


if __name__ == "__main__":
    main()