import socket
import json
import time
import random
import sys

# !!! REPLACE WITH YOUR ACTUAL WINDOWS IP ADDRESS !!!
PC_IP = '172.21.117.21'  
PC_PORT = 5001
DEVICE_ID = "linux_node_01"

def send_packet(payload):
    """Sends JSON packet to Windows. Returns True if successful, False if server is offline."""
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Set a 3-second timeout so it doesn't hang forever if the network is flaky
        client_socket.settimeout(3.0) 
        client_socket.connect((PC_IP, PC_PORT))
        
        json_data = json.dumps(payload) + "\n"
        client_socket.sendall(json_data.encode('utf-8'))
        
        if payload.get("status") != "SHUTDOWN":
            response_buffer = b""
            while b"\n" not in response_buffer:
                chunk = client_socket.recv(1024)
                if not chunk:
                    raise ConnectionResetError("Server disconnected unexpectedly.")
                response_buffer += chunk
            
            response_data = json.loads(response_buffer.decode('utf-8').strip())
            print(f"[Received JSON Back]: {response_data}\n")
            
        client_socket.close()
        return True
        
    except (ConnectionRefusedError, ConnectionResetError, socket.timeout):
        return False
    except Exception as e:
        print(f"[Unexpected Error]: {e}")
        return False

if __name__ == "__main__":
    print("[*] Linux Client starting stream. Press Ctrl+C to stop...")
    server_online = True
    
    try:
        while True:
            telemetry_payload = {
                "status": "RUNNING",
                "device_id": DEVICE_ID,
                "timestamp": time.time(),
                "sensor_reading": round(random.uniform(20.0, 100.0), 2),
                "battery_percent": 94
            }
            
            # Try to send the telemetry
            success = send_packet(telemetry_payload)
            
            if success:
                if not server_online:
                    print("\n[RECONNECTED] Windows Server is back online! Resuming stream.")
                    server_online = True
                print(f"[Sending JSON]: {json.dumps(telemetry_payload)}")
                time.sleep(3)
            else:
                if server_online:
                    print("\n[ALERT] Windows Server went offline or disconnected via Ctrl+C!")
                    print("[*] Entering Standby Mode. Attempting reconnect every 5 seconds...")
                    server_online = False
                
                time.sleep(5)  # Back off and wait before trying again
            
    except KeyboardInterrupt:
        print("\n[Ctrl+C Detected] Sending shutdown alert to Windows PC...")
        shutdown_payload = {
            "status": "SHUTDOWN",
            "device_id": DEVICE_ID,
            "message": "User terminated client script via Ctrl+C."
        }
        send_packet(shutdown_payload)
        print("[*] Shutdown alert sent. Exiting cleanly.")
        sys.exit(0)
