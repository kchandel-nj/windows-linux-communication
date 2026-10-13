# Wireless JSON Telemetry Stream (Windows-Linux Bridge)

This system establishes a cross-platform, real-time wireless communication bridge between a **Linux Client (or Raspberry Pi)** and a **Windows Server**. It is optimized for transmitting lightweight, structured data blocks using the TCP/IP protocol over local Wi-Fi.

## Current Functionality

*   **Bidirectional Network Loop:** The Linux node bundles hardware/sensor state variables into standard JSON telemetry objects, transmits them wirelessly, waits for a receipt payload, and confirms receipt.
*   **Centralized Heavy Data Processing:** The Windows machine operates as a persistent daemon. It intercepts incoming socket streams, serializes the string back into JSON, injects your math equations or business threshold logic, and spits back a response object.
*   **Newline-Delimited Framing (`\n`):** Network socket streams can fragment data packets over Wi-Fi. The scripts use a manual `\n` buffer scanner to cleanly separate consecutive JSON transmissions without corrupting payloads.
*   **Socket Portfolio Reuse:** Includes immediate port reuse flags (`SO_REUSEADDR`) on the host to prevent port lockups if you rapidly start or crash scripts during prototyping.

---

## Architectural Data Schema

### 1. Inbound Telemetry Payload (Linux ➔ Windows)
```json
{
  "device_id": "linux_node_01",
  "timestamp": 1791924960.0,
  "sensor_reading": 62.45,
  "battery_percent": 94
}
```

### 2. Processed Response Payload (Windows ➔ Linux)
```json
{
  "status": "SUCCESS",
  "device_id": "linux_node_01",
  "computed_value": 65.88,
  "alert_triggered": false
}
```

---

## Setup & Deployment Instructions

### Prerequisites
* Both computers must reside on the **same Wi-Fi or local network**.
* Python 3.x must be installed on both systems.

### Step 1: Find the Windows Host IP
Open **Command Prompt** on Windows, execute `ipconfig`, and extract your wireless network interface's **IPv4 Address** (typically matching format `192.168.1.X` or `10.0.0.X`).

### Step 2: Configure the Client Script
Open your `linux_client.py` script on the Linux system and replace the default target address string with your newly extracted Windows IP address:
```python
PC_IP = 'YOUR_EXTRACTED_WINDOWS_IP_HERE'
```

### Step 3: Launch the Windows Processing Daemon
Open **PowerShell** or **Command Prompt** on Windows, navigate to your script workspace directory, and execute:
```cmd
python pc_server.py
```
*If prompted by Windows Defender Firewall, check the **Private networks** configuration block and click **Allow Access**.*

### Step 4: Launch the Linux Telemetry Stream
Open a desktop terminal or SSH instance on your Linux system / Raspberry Pi, navigate to your script workspace directory, and execute:
```bash
python3 linux_client.py
```

### Interruption
To safely terminate either network engine execution at any point, focus that explicit terminal terminal window and issue a keyboard interupt hook: `Ctrl + C`.
