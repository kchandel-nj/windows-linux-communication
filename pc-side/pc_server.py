import os
import socket
import json
import sys
from dotenv import load_dotenv, find_dotenv

# Get the path of the current file's directory, then move one folder up
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(parent_dir, '.env')

# Load variables from .env file
load_dotenv(dotenv_path=dotenv_path)

# Server listens on 0.0.0.0 (all network paths), pulls port from .env
SERVER_HOST = '0.0.0.0'
SERVER_PORT = int(os.getenv("SERVER_PORT", 5001))

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind((SERVER_HOST, SERVER_PORT))
server_socket.listen(5)

print(f"[*] Windows Data Processor listening on port {SERVER_PORT}...")

try:
    while True:
        client_socket, client_address = server_socket.accept()
        
        data_buffer = b""
        while b"\n" not in data_buffer:
            chunk = client_socket.recv(1024)
            if not chunk:
                break
            data_buffer += chunk
            
        if not data_buffer:
            client_socket.close()
            continue

        try:
            message = json.loads(data_buffer.decode('utf-8').strip())
            
            if message.get("status") == "SHUTDOWN":
                print(f"\n[ALERT] Linux Client ({message.get('device_id')}) was disconnected via Ctrl+C!")
                client_socket.close()
                continue
                
            print(f"[Received Telemetry]: {message}")
            
            sensor_val = message.get("sensor_reading", 0)
            processed_response = {
                "status": "SUCCESS",
                "device_id": message.get("device_id"),
                "computed_value": sensor_val * 1.055,
                "alert_triggered": sensor_val > 80
            }
            
            response_bytes = (json.dumps(processed_response) + "\n").encode('utf-8')
            client_socket.sendall(response_bytes)
            
        except json.JSONDecodeError:
            print("[Error] Received invalid JSON format.")
            
        client_socket.close()

except KeyboardInterrupt:
    print("\n[*] Windows Server detected Ctrl+C! Shutting down...")
finally:
    server_socket.close()
    sys.exit(0)
