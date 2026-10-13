import socket
import json
import time
import random

# !!! REPLACE WITH YOUR ACTUAL WINDOWS IP ADDRESS !!!
PC_IP = '172.21.117.21'  
PC_PORT = 5001

def send_telemetry():
    # Build your telemetry payload
    telemetry_payload = {
        "device_id": "linux_node_01",
        "timestamp": time.time(),
        "sensor_reading": round(random.uniform(20.0, 100.0), 2),
        "battery_percent": 94
    }
    
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((PC_IP, PC_PORT))
        
        # Convert dictionary to JSON string and add newline delimiter
        json_data = json.dumps(telemetry_payload) + "\n"
        print(f"[Sending JSON]: {json_data.strip()}")
        client_socket.sendall(json_data.encode('utf-8'))
        
        # Read the incoming response back from Windows
        response_buffer = b""
        while b"\n" not in response_buffer:
            chunk = client_socket.recv(1024)
            if not chunk:
                break
            response_buffer += chunk
            
        response_data = json.loads(response_buffer.decode('utf-8').strip())
        print(f"[Received JSON Back]: {response_data}\n")
        
        client_socket.close()
        
    except ConnectionRefusedError:
        print("[Error] Connection refused. Is the Windows script running and port 5001 open?")
    except Exception as e:
        print(f"[Error]: {e}")

if __name__ == "__main__":
    while True:
        send_telemetry()
        time.sleep(3)  # Send telemetry stream every 3 seconds
