# Wireless JSON Telemetry Stream (With Bidirectional Exit Handling)

This system establishes a robust, cross-platform, real-time wireless communication bridge between a **Linux Client (or Raspberry Pi)** and a **Windows Server**. It uses standard TCP/IP network sockets over Wi-Fi to send structured JSON packets, handle remote connection drops, and recover automatically without crashing.

## Current Functionality

*   **Bidirectional Network Loop:** The Linux node bundles hardware metrics into JSON telemetry objects, transmits them wirelessly, and receives back a confirmation receipt.
*   **Centralized Heavy Data Processing:** The Windows machine operates as a persistent server daemon, intercepting streams, processing values (e.g., threshold logic), and returning responses.
*   **Graceful Client Shutdown Alert:** Pressing `Ctrl+C` on the Linux client triggers a catch intercept, sending a final `"status": "SHUTDOWN"` packet to inform the Windows server before exiting.
*   **Automated Server Standby & Reconnection:** If the Windows server is killed (`Ctrl+C` or a crash), the Linux client instantly catches the network error, drops into a low-overhead **Standby Mode**, and polls every 5 seconds until Windows turns back on to seamlessly resume.
*   **Framing & Reuse Controls:** Includes `\n` newline parsing to prevent socket fragmentation and `SO_REUSEADDR` to bypass OS port-lock limitations during fast script restarts.

---

## State Machine Data Schema

### 1. Inbound Telemetry Payload (Linux ➔ Windows)
```json
{
  "status": "RUNNING",
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

### 3. Graceful Client Teardown Alert (Linux ➔ Windows)
```json
{
  "status": "SHUTDOWN",
  "device_id": "linux_node_01",
  "message": "User terminated client script via Ctrl+C."
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

---

## Network Failure Scenarios & Behavior

| Event Scenario | System Behavior |
| :--- | :--- |
| **Ctrl+C on Linux Client** | Linux pauses execution ➔ transmits `SHUTDOWN` block to Windows ➔ Windows terminal alerts `[ALERT] Linux Client was disconnected...` ➔ Linux closes cleanly. |
| **Ctrl+C on Windows Server** | Windows drops out ➔ Linux catches connection refusal on next loop ➔ Linux alerts `[ALERT] Windows Server went offline!` ➔ Linux spins in standby checking for server. |
| **Windows Server Restarts** | Linux standby scanner finds open port 5001 on host ➔ prints `[RECONNECTED] Windows Server is back online!` ➔ Telemetry cycle automatically resumes. |
