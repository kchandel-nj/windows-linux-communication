import socket
import json

SERVER_HOST = '0.0.0.0'
SERVER_PORT = 5001

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# Allows immediate port reuse if the script restarts
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind((SERVER_HOST, SERVER_PORT))
server_socket.listen(5)

print(f"[*] Windows Data Processor listening on port {SERVER_PORT}...")

try:
    while True:
        client_socket, client_address = server_socket.accept()
        print(f"[*] Connection established with {client_address}")
        
        # Read incoming data up to the newline character
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
            # Decode string and parse JSON
            telemetry = json.loads(data_buffer.decode('utf-8').strip())
            print(f"[Received Telemetry]: {telemetry}")
            
            # --- START TELEMETRY PROCESSING LOGIC ---
            # Example: Track processing status, calculate an offset, or trigger alerts
            sensor_val = telemetry.get("sensor_reading", 0)
            
            processed_response = {
                "status": "SUCCESS",
                "device_id": telemetry.get("device_id"),
                "computed_value": sensor_val * 1.055,  # Example math adjustment
                "alert_triggered": sensor_val > 80     # Example threshold logic
            }
            # --- END TELEMETRY PROCESSING LOGIC ---
            
            # Convert response to JSON string and append newline delimiter
            response_bytes = (json.dumps(processed_response) + "\n").encode('utf-8')
            client_socket.sendall(response_bytes)
            print(f"[Sent Response]: {processed_response}")
            
        except json.JSONDecodeError:
            print("[Error] Received invalid JSON format.")
            
        client_socket.close()

except KeyboardInterrupt:
    print("\n[*] Windows Server shutting down.")
finally:
    server_socket.close()
