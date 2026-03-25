#!/usr/bin/env python3
"""
Test various write command formats against the dongle.
Tries: Eybond-wrapped PI30, raw PI30, raw Modbus RTU, JSON variants.
Monitors the dongle's response on all subscribed topics.
"""

import paho.mqtt.client as mqtt
import struct, time, sys, json, random

DONGLE_ID = "355003011143271300"
PREFIX = "/ESS3000/ke-12klsuf"
COMMAND_TOPIC = f"{PREFIX}/{DONGLE_ID}/command"
UPDATE_TOPIC = f"{PREFIX}/{DONGLE_ID}/update"

BROKER = "127.0.0.1"
PORT = 1883

# --- CRC from voltronic-wifi-bridge (Eybond/PI30 CRC) ---
def cal_crc_half(message):
    crc_ta = [
        0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
        0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef
    ]
    crc = 0
    for b in bytearray(message):
        da = (crc >> 8) >> 4
        crc = (crc << 4) & 0xFFFF
        crc = crc ^ crc_ta[da ^ (b >> 4)]
        crc = crc & 0xFFFF
        da = (crc >> 8) >> 4
        crc = (crc << 4) & 0xFFFF
        crc = crc ^ crc_ta[da ^ (b & 0x0f)]
        crc = crc & 0xFFFF
    # avoid special characters
    crcbytes = crc.to_bytes(2, 'big')
    result = list(crcbytes)
    for i in [0, 1]:
        if result[i] in [0x28, 0x0d, 0x0a]:
            result[i] += 1
    return bytes(result)

# --- Modbus CRC-16 ---
def modbus_crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)

# --- Build Eybond-framed PI30 command ---
def eybond_frame(pi30_cmd, is_set=True):
    """Wrap a PI30 command in Eybond framing."""
    counter = random.randint(100, 60000)
    crc = cal_crc_half(pi30_cmd)
    preamble = b'\x01\x04' if is_set else b'\xFF\x04'
    length = len(pi30_cmd) + len(crc) + 1 + 2  # +1 for 0x0D, +2 for preamble
    frame = struct.pack('>H', counter)  # 2-byte counter
    frame += b'\x00\x01'                # constant
    frame += struct.pack('>H', length)  # 2-byte length
    frame += preamble                   # FF 04 or 01 04
    frame += pi30_cmd                   # PI30 command
    frame += crc                        # 2-byte CRC
    frame += b'\x0d'                    # CR terminator
    return frame

# --- Build Modbus RTU write single register ---
def modbus_write_register(slave_addr, register, value):
    """Build Modbus function 0x06 (write single register) frame."""
    frame = struct.pack('>BBHH', slave_addr, 0x06, register, value)
    frame += modbus_crc16(frame)
    return frame

def hex_str(data):
    return ' '.join(f'{b:02x}' for b in data)

# --- Prepare all test payloads ---
def get_test_payloads():
    tests = []

    # === GROUP 1: Eybond-wrapped PI30 ===
    # POP02 = Solar→Battery→Utility (SBU)
    tests.append(("Eybond PI30: POP02 (SBU)", eybond_frame(b'POP02', is_set=True)))
    # QMOD query (should get mode response)
    tests.append(("Eybond PI30: QMOD query", eybond_frame(b'QMOD', is_set=False)))
    # QPI query (should get protocol ID)
    tests.append(("Eybond PI30: QPI query", eybond_frame(b'QPI', is_set=False)))

    # === GROUP 2: Raw PI30 with CRC ===
    cmd = b'POP02'
    crc = cal_crc_half(cmd)
    tests.append(("Raw PI30: POP02+CRC+CR", cmd + crc + b'\x0d'))
    tests.append(("Raw PI30: POP02+CRC (no CR)", cmd + crc))
    tests.append(("Raw PI30: POP02 (bare)", cmd))

    # === GROUP 3: Modbus RTU write single register ===
    # Register 301 (0x012D), value 2 (SBU), slave address 1
    tests.append(("Modbus RTU: reg 301=2 (addr 1)", modbus_write_register(1, 0x012D, 2)))
    # Slave address 5 (seen in some SRNE dongles)
    tests.append(("Modbus RTU: reg 301=2 (addr 5)", modbus_write_register(5, 0x012D, 2)))
    # Slave address 0 (broadcast)
    tests.append(("Modbus RTU: reg 301=2 (addr 0)", modbus_write_register(0, 0x012D, 2)))

    # === GROUP 4: JSON variants (extended) ===
    tests.append(("JSON: {register, value}", json.dumps({"register": 301, "value": 2}).encode()))
    tests.append(("JSON: {addr, reg, val, fn}", json.dumps({"addr": 1, "reg": 301, "val": 2, "fn": 6}).encode()))
    tests.append(("JSON: {cmd: write, data: hex}", json.dumps({"cmd": "write", "data": hex_str(modbus_write_register(1, 0x012D, 2))}).encode()))
    tests.append(("JSON: {setParam: {id:301, val:2}}", json.dumps({"setParam": {"id": 301, "val": 2}}).encode()))
    # EnerWise/Jiyi style?
    tests.append(("JSON: {type:set, param:output_mode, value:2}", json.dumps({"type": "set", "param": "output_mode", "value": 2}).encode()))
    tests.append(("JSON: {action:write, registers:[{301:2}]}", json.dumps({"action": "write", "registers": [{"301": 2}]}).encode()))

    # === GROUP 5: Hex-encoded Modbus in text ===
    frame = modbus_write_register(1, 0x012D, 2)
    tests.append(("Hex string: Modbus frame", frame.hex().encode()))
    tests.append(("Base64: Modbus frame", __import__('base64').b64encode(frame)))

    return tests

# --- Main ---
def main():
    responses = []

    def on_message(client, userdata, msg):
        ts = time.strftime("%H:%M:%S")
        responses.append((ts, msg.topic, msg.payload))
        print(f"  ← RESPONSE [{ts}] {msg.topic}: {msg.payload[:100]}", flush=True)

    c = mqtt.Client(client_id="write_tester", protocol=mqtt.MQTTv5)
    c.on_message = on_message
    c.connect(BROKER, PORT)
    c.subscribe(f"{PREFIX}/{DONGLE_ID}/#", qos=2)
    c.loop_start()

    tests = get_test_payloads()

    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for i, (name, payload) in enumerate(tests):
            print(f"  [{i:2d}] {name}")
            print(f"       Hex: {hex_str(payload)}")
        return

    # Run specific test or all
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        indices = [int(sys.argv[1])]
    else:
        indices = range(len(tests))

    print(f"[*] Sending {len(indices)} test payloads to {COMMAND_TOPIC}")
    print(f"[*] Listening for responses on {PREFIX}/{DONGLE_ID}/#\n")

    for i in indices:
        name, payload = tests[i]
        print(f"[{i:2d}] {name}", flush=True)
        print(f"     Hex: {hex_str(payload)}", flush=True)

        responses.clear()
        c.publish(COMMAND_TOPIC, payload, qos=2)
        time.sleep(3)  # wait for response

        if not responses:
            print(f"     → No response (3s timeout)", flush=True)
        print(flush=True)

    c.loop_stop()
    c.disconnect()
    print("[*] Done")

if __name__ == "__main__":
    main()
