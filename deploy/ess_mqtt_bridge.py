#!/usr/bin/env python3
"""
Anenji ANJ-12KP ESS MQTT Bridge v6

Bridges the SmartESS WiFi dongle (MQTT) to Home Assistant via MQTT.

Architecture:
  Dongle → [MQTT port 18899] → this bridge → [MQTT solar/inverter/*] → HA
  HA automations → [MQTT solar/inverter/config/+/set] → this bridge → [MQTT command] → dongle → RS485 → inverter

Data flow:
  Dongle publishes to /ESS3000/ke-12klsuf/<did>/update (JSON telemetry)
  Bridge translates → solar/inverter/* for HA

Write flow:
  HA publishes to solar/inverter/config/{key}/set
  Bridge builds Modbus RTU FC06 frame
  Bridge publishes to /ESS3000/ke-12klsuf/<did>/command as:
    {"content": "01 06 XX XX 00 YY CRC_LO CRC_HI", "timestamp": <epoch_ms>}

Confirmed registers (from EnerWise cloud capture 2026-03-13):
  0x1201 = Output Source Priority  (0=UTI/On-Grid, 1=SBU/Battery-first)
  0x1209 = Energy Saving Mode      (0=off, 1=on)
  0x120F = Charge Source           (1=Solar-only, 2=Solar+Grid, 3=Solar-only no-grid)

No cloud bridge — dongle connects to local broker only.
"""

import threading
import time
import json
import os
import struct
import signal
import sys

import paho.mqtt.client as paho_mqtt

# --- CONFIGURATION ---
MQTT_HOST        = os.environ.get("MQTT_HOST",         "127.0.0.1")
MQTT_PORT        = int(os.environ.get("MQTT_PORT",     "1883"))
DONGLE_PORT      = int(os.environ.get("DONGLE_PORT",   "18899"))
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "solar/inverter")

DONGLE_DEVICE_ID = os.environ.get("DONGLE_DEVICE_ID", "355003011143271300")
DONGLE_PRODUCT   = os.environ.get("DONGLE_PRODUCT",   "ke-12klsuf")
DONGLE_BASE      = f"/ESS3000/{DONGLE_PRODUCT}/{DONGLE_DEVICE_ID}"
DONGLE_UPDATE    = f"{DONGLE_BASE}/update"
DONGLE_COMMAND   = f"{DONGLE_BASE}/command"

CONFIG_SET_TOPIC = f"{MQTT_TOPIC_PREFIX}/config/+/set"

# DeStatus code → human string (from EnerWise field study)
STATUS_MAP = {
    0: "Power On",
    1: "Standby",
    2: "Line Mode (On-Grid)",
    3: "Off-Grid (Battery)",
    4: "Bypass",
    5: "Charging",
    6: "Fault",
}

# --- MODBUS HELPERS ---
def modbus_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_fc06_hex(reg: int, value: int) -> str:
    """Build Modbus RTU FC06 Write Single Register frame as space-delimited hex string."""
    payload = bytes([
        0x01, 0x06,
        (reg >> 8) & 0xFF, reg & 0xFF,
        (value >> 8) & 0xFF, value & 0xFF,
    ])
    crc = modbus_crc16(payload)
    frame = payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    return " ".join(f"{b:02X}" for b in frame)


def dongle_command_payload(reg: int, value: int) -> str:
    """Build the EnerWise command JSON for a single register write."""
    hex_frame = build_fc06_hex(reg, value)
    ts = int(time.time() * 1000)
    return json.dumps({"content": hex_frame, "timestamp": ts})


# --- COMMAND MAP ---
# Maps HA MQTT config key + value → (register, int_value)
# Registers confirmed from EnerWise cloud capture unless noted.
COMMAND_MAP = {
    "output_priority": {
        # reg 0x1201 confirmed (2026-03-13 capture: 01 06 12 01 00 01 = SBU)
        "values": {
            "UTI":      (0x1201, 0), "ON_GRID":  (0x1201, 0), "GRID":     (0x1201, 0),
            "SBU":      (0x1201, 1), "OFF_GRID": (0x1201, 1), "BATTERY":  (0x1201, 1),
            "SOL":      (0x1201, 2), "SOLAR":    (0x1201, 2),
            "SUB":      (0x1201, 3),
            "SUF":      (0x1201, 4), "EXPORT":   (0x1201, 4),
        }
    },
    "work_mode": {
        "values": {
            "ON_GRID":  (0x1201, 0), "UTI":      (0x1201, 0),
            "SBU":      (0x1201, 1), "OFF_GRID": (0x1201, 1),
            "BATTERY":  (0x1201, 1), "HYBRID":   (0x1201, 1),
            "SOLAR":    (0x1201, 2), "SOL":      (0x1201, 2),
            "SUB":      (0x1201, 3),
            "SUF":      (0x1201, 4),
        }
    },
    "energy_saving": {
        # reg 0x1209 from context
        "values": {
            "OFF": (0x1209, 0), "0": (0x1209, 0),
            "ON":  (0x1209, 1), "1": (0x1209, 1),
        }
    },
    "charge_source": {
        # reg 0x120F from context — values tentative (inverter_bridge.py analogy)
        "values": {
            "SOLAR":       (0x120F, 1), "PV_FIRST":    (0x120F, 1), "CSO": (0x120F, 1),
            "SOLAR_GRID":  (0x120F, 2), "GRID":        (0x120F, 2), "SNU": (0x120F, 2),
            "SOLAR_ONLY":  (0x120F, 3), "OSO":         (0x120F, 3),
        }
    },
    # Numeric registers — values tentative (inverter_bridge.py register map)
    "ac_charge_current":   {"template": (0x014D, "int×10")},
    "max_charge_current":  {"template": (0x014C, "int×10")},
    "soc_back_to_grid":    {"template": (0x0155, "int")},
    "soc_back_to_battery": {"template": (0x0156, "int")},
    "soc_cutoff":          {"template": (0x0157, "int")},
    "bulk_charge_volt":    {"template": (0x0144, "float×10")},
    "float_charge_volt":   {"template": (0x0145, "float×10")},
    "low_dc_cutoff":       {"template": (0x0149, "float×10")},
}

# --- SHARED STATE ---
mqtt_ha = None       # Client connected to HA broker (port 1883)
mqtt_dongle = None   # Client connected to dongle broker (port 18899)


# --- DATA TRANSLATION ---
def translate_dongle_msg(msg: dict) -> dict:
    """Convert dongle 'msg' dict to the flat dict publish_to_ha expects."""
    def f(key, default=0.0):
        v = msg.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def i(key, default=0):
        v = msg.get(key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    batt_v = f("bV")
    batt_c = f("bC")   # positive = charging, negative = discharging
    batt_power = round(batt_v * batt_c, 1)

    # Sum all phase power for totals (split-phase: A=240V circuit, B+C=120V circuits)
    grid_power = i("grdPA") + i("grdPB") + i("grdPC")
    load_power = i("ldPA")  + i("ldPB")  + i("ldPC")

    de_status = i("DeStatus")

    return {
        "batt_soc":          i("bSoc"),
        "batt_volt":         batt_v,
        "batt_current":      batt_c,
        "batt_power_watt":   batt_power,

        "pv_input_watt":     i("sPPTl"),       # total PV power
        "pv1_power":         i("sPP1"),        # string 1 power
        "pv_input_volt":     f("spV1"),
        "pv_current":        f("spC1"),
        "pv_daily_kwh":      f("pvGenED"),
        "total_pv_energy_kwh": f("pvGenETotl"),

        "grid_power_watt":   grid_power,
        "grid_volt":         f("grdVA"),       # 240V split-phase
        "grid_freq":         f("grdFrq"),
        "total_grid_input_kwh": f("onGrdETotl"),

        "ac_load_real_watt": load_power,
        "load_daily_kwh":    f("ldCnsmDE"),
        "total_load_kwh":    f("ldCnsmETotl"),

        "temp_inv":          f("rTmpIn"),
        "temp_batt":         f("rTmpBat"),
        "temp_pv":           f("rTmpPV"),

        "device_status_code": de_status,
        "device_status_msg":  STATUS_MAP.get(de_status, f"Status {de_status}"),

        "fault_msg":    "No Fault",
        "warning_msg":  "No Warning",
    }


def publish_to_ha(data: dict):
    """Publish translated inverter data to solar/inverter/* MQTT topics."""
    if not mqtt_ha:
        return
    try:
        p = MQTT_TOPIC_PREFIX
        mqtt_ha.publish(f"{p}/battery/soc",              data.get("batt_soc", 0),           retain=True)
        mqtt_ha.publish(f"{p}/battery/voltage",          data.get("batt_volt", 0),           retain=True)
        mqtt_ha.publish(f"{p}/battery/current",          data.get("batt_current", 0),        retain=True)
        mqtt_ha.publish(f"{p}/battery/power",            data.get("batt_power_watt", 0),     retain=True)
        mqtt_ha.publish(f"{p}/pv/power",                 data.get("pv_input_watt", 0),       retain=True)
        mqtt_ha.publish(f"{p}/pv/pv1_power",             data.get("pv1_power", 0),           retain=True)
        mqtt_ha.publish(f"{p}/pv/voltage",               data.get("pv_input_volt", 0),       retain=True)
        mqtt_ha.publish(f"{p}/pv/current",               data.get("pv_current", 0),          retain=True)
        mqtt_ha.publish(f"{p}/pv/daily_yield",           data.get("pv_daily_kwh", 0),        retain=True)
        mqtt_ha.publish(f"{p}/grid/power",               data.get("grid_power_watt", 0),     retain=True)
        mqtt_ha.publish(f"{p}/grid/voltage",             data.get("grid_volt", 0),            retain=True)
        mqtt_ha.publish(f"{p}/grid/frequency",           data.get("grid_freq", 0),            retain=True)
        mqtt_ha.publish(f"{p}/load/power",               data.get("ac_load_real_watt", 0),   retain=True)
        mqtt_ha.publish(f"{p}/temp/inverter",            data.get("temp_inv", 0),             retain=True)
        mqtt_ha.publish(f"{p}/temp/battery",             data.get("temp_batt", 0),            retain=True)
        mqtt_ha.publish(f"{p}/temp/pv",                  data.get("temp_pv", 0),              retain=True)
        mqtt_ha.publish(f"{p}/bridge/status",            data.get("device_status_msg", ""),  retain=True)
        mqtt_ha.publish(f"{p}/bridge/last_poll",         time.strftime("%Y-%m-%dT%H:%M:%S"), retain=True)
        mqtt_ha.publish(f"{p}/energy/pv_total_kwh",      data.get("total_pv_energy_kwh", 0), retain=True)
        mqtt_ha.publish(f"{p}/energy/pv_daily_kwh",      data.get("pv_daily_kwh", 0),        retain=True)
        mqtt_ha.publish(f"{p}/energy/grid_input_total_kwh", data.get("total_grid_input_kwh", 0), retain=True)
        mqtt_ha.publish(f"{p}/energy/load_total_kwh",    data.get("total_load_kwh", 0),      retain=True)
        mqtt_ha.publish(f"{p}/energy/load_daily_kwh",    data.get("load_daily_kwh", 0),      retain=True)
        mqtt_ha.publish(f"{p}/fault",                    data.get("fault_msg", "No Fault"),  retain=True)
        mqtt_ha.publish(f"{p}/warning",                  data.get("warning_msg", "No Warning"), retain=True)
    except Exception as e:
        print(f"[!] HA publish error: {e}")


# --- WRITE HANDLER ---
def handle_config_set(topic: str, payload_str: str):
    """Translate HA MQTT config set → Modbus FC06 frame → dongle command."""
    parts = topic.split("/")
    if len(parts) < 4:
        return

    key = parts[-2]
    value_str = payload_str.strip().upper()
    print(f"[CMD] Received: {key} = {value_str}")

    if key not in COMMAND_MAP:
        print(f"[CMD] Unknown key: {key}")
        return

    cfg = COMMAND_MAP[key]

    if "values" in cfg:
        mapping = cfg["values"].get(value_str)
        if mapping is None:
            print(f"[CMD] Invalid value '{value_str}' for {key}")
            return
        reg, val = mapping

    elif "template" in cfg:
        reg, mode = cfg["template"]
        try:
            raw = float(payload_str.strip())
            if mode == "int":
                val = int(raw)
            elif mode == "int×10":
                val = int(raw * 10)
            elif mode == "float×10":
                val = int(round(raw * 10))
            else:
                val = int(raw)
        except ValueError:
            print(f"[CMD] Bad numeric value: {payload_str!r}")
            return
    else:
        return

    hex_frame = build_fc06_hex(reg, val)
    cmd_json = dongle_command_payload(reg, val)
    print(f"[CMD] → reg 0x{reg:04X} val {val} → {hex_frame}")

    ok = False
    if mqtt_dongle:
        result = mqtt_dongle.publish(DONGLE_COMMAND, cmd_json, qos=1)
        ok = result.rc == 0
        print(f"[CMD] Dongle publish rc={result.rc} ({'OK' if ok else 'FAIL'})")
    else:
        print("[CMD] Dongle client not connected")

    if mqtt_ha:
        mqtt_ha.publish(
            f"{MQTT_TOPIC_PREFIX}/config/last_command",
            json.dumps({
                "key": key, "value": value_str,
                "reg": f"0x{reg:04X}", "val": val,
                "frame": hex_frame, "ok": ok,
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }),
            retain=True,
        )


# --- DONGLE MQTT CALLBACKS ---
def on_dongle_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[*] Dongle broker connected (rc={reason_code})")
    client.subscribe(DONGLE_UPDATE, qos=0)
    print(f"[*] Subscribed to {DONGLE_UPDATE}")


def on_dongle_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        data_msg = payload.get("msg", {})
        translated = translate_dongle_msg(data_msg)
        soc    = translated.get("batt_soc", "?")
        pv     = translated.get("pv_input_watt", "?")
        grid   = translated.get("grid_power_watt", "?")
        load   = translated.get("ac_load_real_watt", "?")
        batt   = translated.get("batt_power_watt", "?")
        status = translated.get("device_status_msg", "?")
        status_code = translated.get("device_status_code", -1)

        # Skip publishing during "Power On" (status 0) — transient boot/mode-switch state.
        # The dongle briefly reports SOC=0 and all-zero power values during transitions;
        # publishing these would cause false zero flickers in HA dashboards.
        if status_code == 0:
            print(f"[~] Skipping publish: transient Power On state (SOC={soc}% all-zero) — not sent to HA")
            return

        publish_to_ha(translated)
        print(f"[*] SOC={soc}% PV={pv}W Grid={grid}W Load={load}W Batt={batt}W | {status}")
    except Exception as e:
        print(f"[!] Dongle message error: {e}")


def on_dongle_disconnect(client, userdata, flags, reason_code, properties=None):
    print(f"[!] Dongle broker disconnected (rc={reason_code}) — will auto-reconnect")
    if mqtt_ha:
        mqtt_ha.publish(f"{MQTT_TOPIC_PREFIX}/bridge/status", "Dongle Offline", retain=True)


# --- HA MQTT CALLBACKS ---
def on_ha_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[*] HA broker connected (rc={reason_code})")
    client.subscribe(CONFIG_SET_TOPIC, qos=1)
    print(f"[*] Subscribed to {CONFIG_SET_TOPIC}")


def on_ha_message(client, userdata, msg):
    if msg.topic.startswith(f"{MQTT_TOPIC_PREFIX}/config/") and msg.topic.endswith("/set"):
        try:
            handle_config_set(msg.topic, msg.payload.decode())
        except Exception as e:
            print(f"[!] Config set error: {e}")


# --- MAIN ---
def handle_exit(signum, frame):
    print("[*] Shutting down.")
    if mqtt_ha:
        mqtt_ha.publish(f"{MQTT_TOPIC_PREFIX}/bridge/status", "Offline", retain=True)
        mqtt_ha.disconnect()
    if mqtt_dongle:
        mqtt_dongle.disconnect()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    print("[*] Anenji ESS MQTT Bridge v6 starting")
    print(f"[*] Dongle broker: {MQTT_HOST}:{DONGLE_PORT}  topic: {DONGLE_UPDATE}")
    print(f"[*] HA broker:     {MQTT_HOST}:{MQTT_PORT}    topics: {MQTT_TOPIC_PREFIX}/*")
    print(f"[*] Command topic: {DONGLE_COMMAND}")

    # Client for HA / solar/inverter/* (port 1883)
    mqtt_ha = paho_mqtt.Client(
        client_id="anenji-ess-bridge-ha",
        protocol=paho_mqtt.MQTTv311,
        callback_api_version=paho_mqtt.CallbackAPIVersion.VERSION2,
    )
    mqtt_ha.on_connect = on_ha_connect
    mqtt_ha.on_message = on_ha_message
    mqtt_ha.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_ha.loop_start()

    # Client for dongle /ESS3000/... (port 18899)
    mqtt_dongle = paho_mqtt.Client(
        client_id="anenji-ess-bridge-dongle",
        protocol=paho_mqtt.MQTTv311,
        callback_api_version=paho_mqtt.CallbackAPIVersion.VERSION2,
    )
    mqtt_dongle.on_connect = on_dongle_connect
    mqtt_dongle.on_message = on_dongle_message
    mqtt_dongle.on_disconnect = on_dongle_disconnect
    mqtt_dongle.connect(MQTT_HOST, DONGLE_PORT, 60)
    mqtt_dongle.loop_start()

    print("[*] Bridge running.")
    while True:
        time.sleep(1)
