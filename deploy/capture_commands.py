#!/usr/bin/env python3
"""
Dual MQTT monitor: captures SmartESS write commands from both local broker
and cloud broker (47.76.167.109).

Local monitor: subscribes to dongle's /command topic on our Mosquitto
Cloud monitor: connects to real SmartESS cloud as the dongle, subscribes
               to /command topic to capture what the app sends.

Any captured commands are logged with full hex dump + decoded payload.
"""

import paho.mqtt.client as mqtt
import json, time, sys, threading, os
from datetime import datetime

DONGLE_ID = "355003011143271300"
PREFIX = "/ESS3000/ke-12klsuf"
COMMAND_TOPIC = f"{PREFIX}/{DONGLE_ID}/command"
UPDATE_TOPIC = f"{PREFIX}/{DONGLE_ID}/update"
OTA_TOPIC = f"{PREFIX}/{DONGLE_ID}/ota/upgrade"

# Cloud credentials (extracted from dongle's MQTT CONNECT)
CLOUD_HOST = "47.76.167.109"
CLOUD_PORT = 1883
CLOUD_USER = "esstech"
CLOUD_PASS = "VnhVP94SLXaz6Mka"
CLOUD_CLIENT = f"0{DONGLE_ID}"

LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 1883

LOG_FILE = "/root/anenji-bridge/deploy/captured_commands.log"

captured = []

def hex_dump(data):
    if isinstance(data, str):
        data = data.encode()
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hexpart = ' '.join(f'{b:02x}' for b in chunk)
        ascpart = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  {i:04x}: {hexpart:<48s}  {ascpart}")
    return '\n'.join(lines)

def log_command(source, topic, payload):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw = payload if isinstance(payload, bytes) else payload.encode()

    entry = f"\n{'='*70}\n"
    entry += f"[{ts}] CAPTURED from {source}\n"
    entry += f"Topic: {topic}\n"
    entry += f"Length: {len(raw)} bytes\n"
    entry += f"Hex dump:\n{hex_dump(raw)}\n"

    # Try decode as UTF-8
    try:
        text = raw.decode('utf-8')
        entry += f"UTF-8: {text}\n"
        # Try parse as JSON
        try:
            j = json.loads(text)
            entry += f"JSON: {json.dumps(j, indent=2)}\n"
        except:
            pass
    except:
        entry += "Not valid UTF-8\n"

    entry += f"{'='*70}\n"

    print(entry, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(entry)

    captured.append({"ts": ts, "source": source, "topic": topic, "raw": raw.hex(), "len": len(raw)})

# --- LOCAL MONITOR ---
def start_local_monitor():
    def on_connect(client, userdata, flags, rc, properties=None):
        print(f"[LOCAL] Connected to local broker (rc={rc})", flush=True)
        # Subscribe to ALL dongle topics to capture everything
        client.subscribe(f"{PREFIX}/{DONGLE_ID}/#", qos=2)
        client.subscribe("solar/inverter/#", qos=1)
        print(f"[LOCAL] Subscribed to {PREFIX}/{DONGLE_ID}/# and solar/inverter/#", flush=True)

    def on_message(client, userdata, msg):
        # Skip known data topics - we only want commands
        if msg.topic == UPDATE_TOPIC:
            return  # skip data publishes, too noisy
        # Log everything else
        log_command("LOCAL", msg.topic, msg.payload)

    c = mqtt.Client(client_id="command_capture_local", protocol=mqtt.MQTTv5)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(LOCAL_HOST, LOCAL_PORT)
    c.loop_forever()

# --- CLOUD MONITOR ---
def start_cloud_monitor():
    """Connect to real SmartESS cloud as the dongle to intercept commands."""

    def on_connect(client, userdata, flags, rc, properties=None):
        print(f"[CLOUD] Connected to SmartESS cloud {CLOUD_HOST}:{CLOUD_PORT} (rc={rc})", flush=True)
        # Subscribe to same topics the dongle subscribes to
        client.subscribe(COMMAND_TOPIC, qos=2)
        client.subscribe(OTA_TOPIC, qos=2)
        print(f"[CLOUD] Subscribed to {COMMAND_TOPIC}", flush=True)
        print(f"[CLOUD] Subscribed to {OTA_TOPIC}", flush=True)

    def on_message(client, userdata, msg):
        log_command("CLOUD", msg.topic, msg.payload)
        # Also forward to local broker so bridge can see it
        try:
            fwd = mqtt.Client(client_id="cloud_fwd_tmp", protocol=mqtt.MQTTv5)
            fwd.connect(LOCAL_HOST, LOCAL_PORT)
            fwd.publish(msg.topic, msg.payload, qos=2)
            fwd.disconnect()
            print(f"[CLOUD] Forwarded to local broker: {msg.topic}", flush=True)
        except Exception as e:
            print(f"[CLOUD] Forward failed: {e}", flush=True)

    def on_disconnect(client, userdata, rc, properties=None, reasonCode=None):
        print(f"[CLOUD] Disconnected (rc={rc}), reconnecting...", flush=True)

    c = mqtt.Client(client_id=CLOUD_CLIENT, protocol=mqtt.MQTTv5)
    c.username_pw_set(CLOUD_USER, CLOUD_PASS)
    c.on_connect = on_connect
    c.on_message = on_message
    c.on_disconnect = on_disconnect
    c.reconnect_delay_set(min_delay=1, max_delay=30)

    try:
        c.connect(CLOUD_HOST, CLOUD_PORT)
        c.loop_forever()
    except Exception as e:
        print(f"[CLOUD] Connection failed: {e}", flush=True)
        print("[CLOUD] Retrying in 10s...", flush=True)
        time.sleep(10)
        start_cloud_monitor()

if __name__ == "__main__":
    print(f"[*] Dual MQTT Command Capture starting", flush=True)
    print(f"[*] Dongle: {DONGLE_ID}", flush=True)
    print(f"[*] Command topic: {COMMAND_TOPIC}", flush=True)
    print(f"[*] Log file: {LOG_FILE}", flush=True)
    print(f"[*] Waiting for commands...", flush=True)

    # Clear old log
    with open(LOG_FILE, 'w') as f:
        f.write(f"# Command Capture Log - Started {datetime.now()}\n")

    # Start both monitors in threads
    t_local = threading.Thread(target=start_local_monitor, daemon=True)
    t_cloud = threading.Thread(target=start_cloud_monitor, daemon=True)

    t_local.start()
    t_cloud.start()

    # Keep main alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[*] Captured {len(captured)} commands total")
        print(f"[*] Log saved to {LOG_FILE}")
