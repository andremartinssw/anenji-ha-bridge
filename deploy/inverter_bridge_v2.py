#!/usr/bin/env python3
"""
Anenji ANJ-12KP Inverter Bridge v2 — VPS TCP Intercept + MQTT Control

Intercepts the WiFi dongle's cloud connection (port 18899) on the VPS.
Requires DNAT at your router: <cloud_ip>:18899 → <vps_ip>:18899

Features:
  - Direct Modbus read/write to ALL internal registers via dongle TCP
  - MQTT command subscription (solar/inverter/config/+/set) for HA automations
  - Publishes full telemetry + charger_priority + ac_charge_current to MQTT
  - Coexists with ess_mqtt_bridge.py (cloud MQTT fallback for telemetry)

Based on inverter_bridge.py (samuelolteanu/Local-Cloud-Bridge adaptation).
"""

import socket
import threading
import struct
import time
import json
import os
import signal
import sys

# --- CONFIGURATION ---
INVERTER_PORT = int(os.environ.get("INVERTER_PORT", "18899"))
LOCAL_CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "9999"))
BIND_IP = '0.0.0.0'
POLL_INTERVAL = 1.0
INVERTER_RATED_WATT = 12000
OFFLINE_THRESHOLD = 10

# --- MQTT ---
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "solar/inverter")
MQTT_PUBLISH_INTERVAL = float(os.environ.get("MQTT_PUBLISH_INTERVAL", "5.0"))
CONFIG_SET_TOPIC = f"{MQTT_TOPIC_PREFIX}/config/+/set"

# --- TRANSLATION MAPS ---
STATUS_MAP = {
    0: "Power On", 1: "Standby", 2: "Line Mode (On-Grid)",
    3: "Off-Grid (Battery)", 4: "Bypass", 5: "Charging", 6: "Fault"
}
BATTERY_TYPE_MAP = {
    0: "AGN", 1: "FLD", 2: "USR", 4: "LI2", 6: "LI4", 8: "LIb"
}
FAULT_BIT_MAP = {
    1: "F01: Over temp inverter", 2: "F02: Over temp DCDC", 3: "F03: Batt volt high",
    4: "F04: Over temp PV", 5: "F05: Output short", 6: "F06: Output volt high",
    7: "F07: Overload timeout", 8: "F08: Bus volt high", 9: "F09: Bus soft start fail",
    10: "F10: PV over current", 11: "F11: PV over volt", 12: "F12: DCDC over current",
    13: "F13: Over current/surge", 14: "F14: Bus volt low", 15: "F15: Inverter fail",
    18: "F18: Op current offset", 19: "F19: Inv current offset", 20: "F20: DCDC current offset",
    21: "F21: PV current offset", 22: "F22: Output volt low", 23: "F23: Inv negative power"
}
WARNING_BIT_MAP = {
    0: "W01: Grid Offline", 2: "W02: Temp high", 4: "W04: Low battery",
    6: "W06: PV Disconnected", 7: "W07: Overload", 10: "W10: Power derating",
    14: "W14: Fan blocked", 15: "W15: PV energy low",
    19: "W19: BMS Comms Fail", 21: "W21: BMS Over Current"
}

# --- SHARED STATE ---
current_inverter_conn = None
modbus_lock = threading.Lock()
last_cmd_time = 0
mqtt_client = None
command_queue = []
command_lock = threading.Lock()


# --- HELPERS ---
def decode_flags(val, map_dict, prefix="Unknown"):
    if val == 0:
        return []
    return [map_dict.get(bit, f"{prefix} (Bit {bit})")
            for bit in range(32) if (val >> bit) & 1]


def to_signed(val):
    return val - 65536 if val >= 32768 else val


# --- MODBUS ---
def modbus_crc(data):
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 1) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)


def build_write_packet(reg, value):
    payload = struct.pack('>BBHHB', 1, 16, reg, 1, 2) + struct.pack('>H', value)
    return payload + modbus_crc(payload)


def build_read_packet(start, count):
    payload = struct.pack('>BBHH', 1, 3, start, count)
    return payload + modbus_crc(payload)


def flush_buffer(conn):
    try:
        conn.settimeout(0.01)
        while conn.recv(1024):
            pass
    except Exception:
        pass
    finally:
        conn.settimeout(2.5)


def read_modbus_response(conn):
    try:
        raw = conn.recv(1024)
        if len(raw) < 5 or raw[1] & 0x80:
            return None
        if modbus_crc(raw[:-2]) != raw[-2:]:
            return None
        return [x[0] for x in struct.iter_unpack('>H', raw[3: 3 + raw[2]])]
    except Exception:
        return None


# --- MQTT ---
def setup_mqtt():
    global mqtt_client
    try:
        import paho.mqtt.client as paho_mqtt
        mqtt_client = paho_mqtt.Client(
            paho_mqtt.CallbackAPIVersion.VERSION2,
            client_id="anenji-bridge-tcp",
            protocol=paho_mqtt.MQTTv311
        )
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"[*] MQTT connected to {MQTT_HOST}:{MQTT_PORT}")
    except ImportError:
        print("[!] paho-mqtt not installed — MQTT disabled")
    except Exception as e:
        print(f"[!] MQTT connection failed: {e}")
        mqtt_client = None


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    print(f"[*] MQTT connected (rc={rc}), subscribing to {CONFIG_SET_TOPIC}")
    client.subscribe(CONFIG_SET_TOPIC, qos=1)


def on_mqtt_message(client, userdata, msg, properties=None):
    """Handle HA config set commands via MQTT."""
    topic = msg.topic
    payload = msg.payload.decode().strip().upper()

    if not topic.startswith(f"{MQTT_TOPIC_PREFIX}/config/") or not topic.endswith("/set"):
        return

    parts = topic.split("/")
    key = parts[-2]  # e.g. "charger_priority", "output_priority"

    print(f"[MQTT-CMD] {key} = {payload}")

    cmd = None
    if key == "output_priority" or key == "work_mode":
        mode_map = {"UTI": 0, "ON_GRID": 0, "GRID": 0,
                    "SBU": 1, "OFF_GRID": 1, "BATTERY": 1, "HYBRID": 1,
                    "SOL": 2, "SOLAR": 2, "SUB": 3, "SUF": 4, "EXPORT": 4}
        val = mode_map.get(payload)
        if val is not None:
            cmd = ("output_priority", 301, val)

    elif key == "charge_source" or key == "charger_priority":
        cs_map = {"CSO": 1, "SOLAR_FIRST": 1, "SOLAR": 1, "PV_FIRST": 1, "SOF": 1,
                  "SNU": 2, "SOLAR_GRID": 2, "GRID": 2, "CHARGE_ON": 2,
                  "OSO": 3, "SOLAR_ONLY": 3, "CHARGE_OFF": 3}
        val = cs_map.get(payload)
        if val is not None:
            cmd = ("charger_priority", 331, val)

    elif key == "ac_charge_current":
        try:
            amps = int(float(payload))
            if 0 <= amps <= 60:
                cmd = ("max_ac_amps", 333, amps * 10)
        except ValueError:
            pass

    elif key == "max_charge_current":
        try:
            amps = int(float(payload))
            if 0 <= amps <= 60:
                cmd = ("max_total_amps", 332, amps * 10)
        except ValueError:
            pass

    elif key == "soc_back_to_grid":
        try:
            val = int(float(payload))
            if 0 <= val <= 100:
                cmd = ("soc_back_to_grid", 341, val)
        except ValueError:
            pass

    elif key == "soc_back_to_battery":
        try:
            val = int(float(payload))
            if 0 <= val <= 100:
                cmd = ("soc_back_to_batt", 342, val)
        except ValueError:
            pass

    if cmd:
        if current_inverter_conn is None:
            print(f"[MQTT-CMD] Dropped (no dongle): {cmd[0]} reg {cmd[1]} = {cmd[2]}")
        else:
            with command_lock:
                command_queue.append(cmd)
            print(f"[MQTT-CMD] Queued: reg {cmd[1]} = {cmd[2]}")
    else:
        print(f"[MQTT-CMD] Unknown/invalid: {key} = {payload}")


def publish_mqtt(data):
    if not mqtt_client:
        return
    try:
        p = MQTT_TOPIC_PREFIX
        mqtt_client.publish(f"{p}/battery/soc", data.get("batt_soc", ""), retain=True)
        mqtt_client.publish(f"{p}/battery/voltage", data.get("batt_volt", ""), retain=True)
        mqtt_client.publish(f"{p}/battery/current", data.get("batt_current", ""), retain=True)
        mqtt_client.publish(f"{p}/battery/power", data.get("batt_power_watt", ""), retain=True)
        mqtt_client.publish(f"{p}/pv/power", data.get("pv_input_watt", ""), retain=True)
        mqtt_client.publish(f"{p}/pv/pv1_power", data.get("pv_input_watt", ""), retain=True)
        mqtt_client.publish(f"{p}/pv/voltage", data.get("pv_input_volt", ""), retain=True)
        mqtt_client.publish(f"{p}/pv/current", data.get("pv_current", ""), retain=True)
        mqtt_client.publish(f"{p}/pv/daily_yield", data.get("pv_daily_kwh", 0), retain=True)
        mqtt_client.publish(f"{p}/grid/power", data.get("grid_power_watt", ""), retain=True)
        mqtt_client.publish(f"{p}/grid/voltage", data.get("grid_volt", ""), retain=True)
        mqtt_client.publish(f"{p}/grid/frequency", data.get("grid_freq", ""), retain=True)
        mqtt_client.publish(f"{p}/load/power", data.get("ac_load_real_watt", ""), retain=True)
        mqtt_client.publish(f"{p}/bridge/status", data.get("device_status_msg", "Unknown"), retain=True)
        mqtt_client.publish(f"{p}/bridge/last_poll", time.strftime("%Y-%m-%dT%H:%M:%S"), retain=True)
        mqtt_client.publish(f"{p}/bridge/tcp_status", "connected" if current_inverter_conn else "disconnected", retain=True)
        mqtt_client.publish(f"{p}/temp/inverter", data.get("temp_inv", ""), retain=True)
        mqtt_client.publish(f"{p}/temp/battery", data.get("temp_dc", ""), retain=True)
        mqtt_client.publish(f"{p}/fault", data.get("fault_msg", "No Fault"), retain=True)
        mqtt_client.publish(f"{p}/warning", data.get("warning_msg", "No Warning"), retain=True)
        # Config state — these are the key registers we need for automations
        mqtt_client.publish(f"{p}/config/charger_priority", data.get("charger_priority", ""), retain=True)
        mqtt_client.publish(f"{p}/config/output_mode", data.get("output_mode", ""), retain=True)
        mqtt_client.publish(f"{p}/config/max_ac_amps", data.get("max_ac_amps", ""), retain=True)
        mqtt_client.publish(f"{p}/config/max_total_amps", data.get("max_total_amps", ""), retain=True)
        mqtt_client.publish(f"{p}/config/soc_back_to_grid", data.get("soc_back_to_grid", ""), retain=True)
        mqtt_client.publish(f"{p}/config/soc_back_to_batt", data.get("soc_back_to_batt", ""), retain=True)
        mqtt_client.publish(f"{p}/config/soc_cutoff", data.get("soc_cutoff", ""), retain=True)
        # Energy totals
        mqtt_client.publish(f"{p}/energy/pv_total_kwh", data.get("total_pv_energy_kwh", 0), retain=True)
        mqtt_client.publish(f"{p}/energy/grid_input_total_kwh", data.get("total_grid_input_kwh", 0), retain=True)
        mqtt_client.publish(f"{p}/energy/load_total_kwh", data.get("total_load_kwh", 0), retain=True)
        mqtt_client.publish(f"{p}/energy/load_daily_kwh", data.get("load_daily_kwh", 0), retain=True)
    except Exception as e:
        print(f"[!] MQTT publish error: {e}")


# --- ENERGY PERSISTENCE ---
ENERGY_FILE = os.environ.get("ENERGY_FILE", "/data/inverter_energy.json")
SAVE_INTERVAL = 300
energy_lock = threading.Lock()


def load_or_create_energy_data():
    default = {
        "total_pv_kwh": 0.0, "total_grid_input_kwh": 0.0,
        "total_load_kwh": 0.0, "total_battery_charge_kwh": 0.0,
        "total_battery_discharge_kwh": 0.0
    }
    if os.path.exists(ENERGY_FILE):
        try:
            with open(ENERGY_FILE) as f:
                data = json.load(f)
            for k in default:
                data.setdefault(k, default[k])
            print(f"[*] Loaded energy: PV={data['total_pv_kwh']:.2f}kWh Grid={data['total_grid_input_kwh']:.2f}kWh")
            return data
        except Exception as e:
            print(f"[!] Energy load error: {e}")
    else:
        os.makedirs(os.path.dirname(ENERGY_FILE), exist_ok=True)
    return default.copy()


energy_data = load_or_create_energy_data()


def save_energy_to_disk():
    with energy_lock:
        try:
            os.makedirs(os.path.dirname(ENERGY_FILE), exist_ok=True)
            with open(ENERGY_FILE + ".tmp", 'w') as f:
                json.dump(energy_data, f, indent=2)
            os.replace(ENERGY_FILE + ".tmp", ENERGY_FILE)
        except Exception as e:
            print(f"[!] Energy save failed: {e}")


def get_empty_data():
    return {
        "fault_code": 0, "fault_msg": "No Fault", "fault_list": [],
        "warning_code": 0, "warning_msg": "No Warning", "warning_list": [],
        "device_status_code": None, "device_status_msg": "Offline",
        "batt_volt": None, "batt_soc": None, "batt_current": None, "batt_power_watt": None,
        "ac_load_real_watt": None, "ac_load_va": None, "ac_load_pct": None,
        "grid_power_watt": None, "grid_volt": None, "grid_freq": None, "grid_current": None,
        "pv_input_watt": None, "pv_input_volt": None, "pv_current": None, "pv_charging_watt": None,
        "temp_dc": None, "temp_inv": None,
        "ac_out_volt": None, "ac_out_amp": None, "ac_output_amp": None,
        "charger_priority": 3, "output_mode": 0, "ac_input_range": 0,
        "buzzer_mode": 3, "backlight_status": 1,
        "max_total_amps": None, "max_ac_amps": None,
        "soc_back_to_grid": 100, "soc_back_to_batt": 100, "soc_cutoff": 0,
        "battery_type_code": None, "battery_type_msg": None,
        "bulk_charge_volt": None, "float_charge_volt": None, "low_dc_cutoff_volt": None,
        "total_pv_energy_kwh": round(energy_data["total_pv_kwh"], 4),
        "total_grid_input_kwh": round(energy_data["total_grid_input_kwh"], 4),
        "total_load_kwh": round(energy_data["total_load_kwh"], 4),
    }


latest_data_json = get_empty_data()


# --- PROCESS QUEUED MQTT COMMANDS ---
def process_commands(conn):
    """Process any queued MQTT commands via direct Modbus write."""
    global last_cmd_time
    with command_lock:
        cmds = list(command_queue)
        command_queue.clear()

    for name, reg, val in cmds:
        try:
            with modbus_lock:
                flush_buffer(conn)
                conn.send(build_write_packet(reg, val))
                last_cmd_time = time.time()
                time.sleep(0.15)
                # Read response (write echo)
                try:
                    resp = conn.recv(1024)
                except Exception:
                    resp = b''

            # Update local state
            if name == "charger_priority":
                latest_data_json["charger_priority"] = val
            elif name == "output_priority":
                latest_data_json["output_mode"] = val
            elif name == "max_ac_amps":
                latest_data_json["max_ac_amps"] = val / 10.0
            elif name == "max_total_amps":
                latest_data_json["max_total_amps"] = val / 10.0
            elif name in ("soc_back_to_grid", "soc_back_to_batt"):
                latest_data_json[name] = val

            ok = len(resp) >= 8 and not (resp[1] & 0x80) if resp else False
            status = "OK" if ok else "sent (unconfirmed)"
            print(f"[MQTT-CMD] Wrote reg {reg} = {val} ({name}) → {status}")

            # Publish confirmation
            if mqtt_client:
                mqtt_client.publish(
                    f"{MQTT_TOPIC_PREFIX}/config/last_command",
                    json.dumps({
                        "key": name, "reg": reg, "val": val,
                        "ok": ok, "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }),
                    retain=True
                )
        except Exception as e:
            print(f"[MQTT-CMD] Write failed: {e}")


# --- MAIN INVERTER SERVER ---
def inverter_server():
    global current_inverter_conn, latest_data_json, last_cmd_time

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((BIND_IP, INVERTER_PORT))
    s.listen(1)
    print(f"[*] Listening for dongle on port {INVERTER_PORT}...")

    while True:
        try:
            conn, addr = s.accept()
            current_inverter_conn = conn
            conn.settimeout(5.0)
            print(f"[*] Dongle connected from {addr[0]}:{addr[1]}")

            # Cloud emulation handshake
            try:
                conn.send(b'AT+DTUPN?\r\n')
                reply = conn.recv(1024)
                print(f"[*] Dongle replied: {reply.decode(errors='ignore').strip()}")
                time.sleep(0.5)
            except Exception as e:
                print(f"[!] Handshake failed: {e}")
                conn.close()
                continue

            conn.settimeout(2.5)
            consecutive_failures = 0
            loop_counter = 0
            last_integration_time = time.time()
            last_save_time = time.time()
            last_mqtt_time = time.time()

            while True:
                now = time.time()
                time_delta = now - last_integration_time
                last_integration_time = now

                # Process any queued MQTT commands
                if command_queue:
                    process_commands(conn)

                with modbus_lock:
                    try:
                        flush_buffer(conn)
                        conn.send(build_read_packet(200, 40))
                        time.sleep(0.15)
                        vals = read_modbus_response(conn)

                        if vals is None:
                            consecutive_failures += 1
                            if consecutive_failures >= OFFLINE_THRESHOLD:
                                break
                        else:
                            consecutive_failures = 0

                            v_batt = vals[15] / 10.0
                            if v_batt < 10.0:
                                v_batt = 48.0
                            v_pv = vals[19] / 10.0
                            p_pv = vals[23]
                            p_pv_btt = vals[24]
                            v_grid = vals[2] / 10.0
                            p_grid = vals[4]
                            p_load = vals[13]
                            raw_batt_current = to_signed(vals[32])
                            batt_current = raw_batt_current / 10.0
                            batt_p = int(batt_current * v_batt)

                            # Energy integration
                            if 0 < time_delta < 5.0:
                                with energy_lock:
                                    if p_pv > 0:
                                        energy_data["total_pv_kwh"] += (p_pv * time_delta) / 3600000.0
                                    if p_grid > 0:
                                        energy_data["total_grid_input_kwh"] += (p_grid * time_delta) / 3600000.0
                                    if p_load > 0:
                                        energy_data["total_load_kwh"] += (p_load * time_delta) / 3600000.0
                                    if batt_p > 0:
                                        energy_data["total_battery_charge_kwh"] += (batt_p * time_delta) / 3600000.0
                                    elif batt_p < 0:
                                        energy_data["total_battery_discharge_kwh"] += (abs(batt_p) * time_delta) / 3600000.0

                                    latest_data_json["total_pv_energy_kwh"] = round(energy_data["total_pv_kwh"], 4)
                                    latest_data_json["total_grid_input_kwh"] = round(energy_data["total_grid_input_kwh"], 4)
                                    latest_data_json["total_load_kwh"] = round(energy_data["total_load_kwh"], 4)

                            if (now - last_save_time) > SAVE_INTERVAL:
                                save_energy_to_disk()
                                last_save_time = now

                            latest_data_json.update({
                                "device_status_code": vals[1],
                                "device_status_msg": STATUS_MAP.get(vals[1], "Active"),
                                "grid_volt": v_grid,
                                "grid_freq": vals[3] / 100.0,
                                "grid_power_watt": p_grid,
                                "grid_current": round(p_grid / v_grid, 1) if v_grid > 0 else 0.0,
                                "ac_out_volt": vals[5] / 10.0,
                                "ac_out_amp": vals[11] / 10.0,
                                "ac_output_amp": vals[11] / 10.0,
                                "ac_load_real_watt": p_load,
                                "ac_load_va": vals[14],
                                "ac_load_pct": round(min((vals[14] / INVERTER_RATED_WATT) * 100, 300), 1),
                                "batt_volt": v_batt,
                                "batt_soc": vals[29],
                                "batt_power_watt": batt_p,
                                "batt_current": batt_current,
                                "pv_input_watt": p_pv,
                                "pv_charging_watt": p_pv_btt,
                                "pv_input_volt": v_pv,
                                "pv_current": round(p_pv / v_pv, 2) if v_pv > 0 else 0.0,
                                "temp_dc": vals[27],
                                "temp_inv": vals[26],
                            })

                            # Faults every 2 loops
                            if loop_counter % 2 == 0:
                                conn.send(build_read_packet(100, 12))
                                time.sleep(0.1)
                                vf = read_modbus_response(conn)
                                if vf and len(vf) >= 10:
                                    fault_val = (vf[0] << 16) | vf[1]
                                    warn_val = (vf[8] << 16) | vf[9]
                                    f_list = decode_flags(fault_val, FAULT_BIT_MAP, "Unknown F")
                                    w_list = decode_flags(warn_val, WARNING_BIT_MAP, "Unknown W")
                                    latest_data_json.update({
                                        "fault_code": fault_val,
                                        "fault_msg": ", ".join(f_list) if f_list else "No Fault",
                                        "warning_code": warn_val,
                                        "warning_msg": ", ".join(w_list) if w_list else "No Warning",
                                    })

                            # Config reads every 5 loops (skip during command cooldown)
                            is_cooldown = (time.time() - last_cmd_time) < 10.0
                            if (loop_counter % 5 == 0) and not is_cooldown:
                                conn.send(build_read_packet(301, 6))
                                time.sleep(0.1)
                                v300 = read_modbus_response(conn)
                                if v300:
                                    latest_data_json.update({
                                        "output_mode": v300[0],
                                        "ac_input_range": v300[1],
                                        "buzzer_mode": v300[2],
                                        "backlight_status": v300[4],
                                    })

                                conn.send(build_read_packet(331, 3))
                                time.sleep(0.1)
                                v330 = read_modbus_response(conn)
                                if v330:
                                    latest_data_json.update({
                                        "charger_priority": v330[0],
                                        "max_total_amps": v330[1] / 10.0,
                                        "max_ac_amps": v330[2] / 10.0,
                                    })

                                conn.send(build_read_packet(341, 3))
                                time.sleep(0.1)
                                vsoc = read_modbus_response(conn)
                                if vsoc:
                                    latest_data_json.update({
                                        "soc_back_to_grid": vsoc[0],
                                        "soc_back_to_batt": vsoc[1],
                                        "soc_cutoff": vsoc[2],
                                    })

                                conn.send(build_read_packet(322, 8))
                                time.sleep(0.1)
                                v322 = read_modbus_response(conn)
                                if v322 and len(v322) >= 8:
                                    latest_data_json.update({
                                        "battery_type_code": v322[0],
                                        "battery_type_msg": BATTERY_TYPE_MAP.get(v322[0], f"Unknown ({v322[0]})"),
                                        "bulk_charge_volt": v322[2] / 10.0,
                                        "float_charge_volt": v322[3] / 10.0,
                                        "low_dc_cutoff_volt": v322[7] / 10.0,
                                    })

                            # MQTT publish
                            if mqtt_client and (now - last_mqtt_time) > MQTT_PUBLISH_INTERVAL:
                                publish_mqtt(latest_data_json)
                                last_mqtt_time = now

                    except Exception:
                        consecutive_failures += 1
                        if consecutive_failures >= OFFLINE_THRESHOLD:
                            break

                loop_counter += 1
                time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"[!] Connection error: {e}")
            time.sleep(1)
        finally:
            if current_inverter_conn:
                print("[!] Dongle disconnected")
                current_inverter_conn.close()
                current_inverter_conn = None
            latest_data_json = get_empty_data()
            if mqtt_client:
                publish_mqtt(latest_data_json)


# --- CONTROL SERVER (legacy TCP port 9999) ---
def control_server():
    global last_cmd_time
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((BIND_IP, LOCAL_CONTROL_PORT))
    s.listen(5)
    print(f"[*] Control server on port {LOCAL_CONTROL_PORT}")

    while True:
        try:
            client, _ = s.accept()
            req = client.recv(1024).strip().decode().upper()

            if req == "JSON":
                client.send(json.dumps(latest_data_json).encode())
            elif req == "STATUS":
                connected = "connected" if current_inverter_conn else "disconnected"
                client.send(json.dumps({
                    "tcp": connected,
                    "charger_priority": latest_data_json.get("charger_priority"),
                    "batt_soc": latest_data_json.get("batt_soc"),
                    "batt_current": latest_data_json.get("batt_current"),
                }).encode())
            elif current_inverter_conn and req:
                # Legacy TCP command format (backwards compatible)
                cmd = None
                if req.startswith("MODE_"):
                    cmd = ("output_priority", 301, int(req.split("_")[1]))
                elif req in ("CSO_SET",):
                    cmd = ("charger_priority", 331, 1)
                elif req in ("SNU_SET", "CHARGE_ON"):
                    cmd = ("charger_priority", 331, 2)
                elif req in ("OSO_SET", "CHARGE_OFF"):
                    cmd = ("charger_priority", 331, 3)
                elif req.startswith("SET_AMPS_"):
                    val = int(req.split("_")[2])
                    cmd = ("max_ac_amps", 333, val * 10)
                elif req.startswith("SET_TOTAL_AMPS_"):
                    val = int(req.split("_")[3])
                    cmd = ("max_total_amps", 332, val * 10)
                elif req.startswith("SET_SOC_GRID_"):
                    cmd = ("soc_back_to_grid", 341, int(req.split("_")[3]))
                elif req.startswith("SET_SOC_BATT_"):
                    cmd = ("soc_back_to_batt", 342, int(req.split("_")[3]))

                if cmd:
                    with command_lock:
                        command_queue.append(cmd)
                    client.send(b"OK")
                else:
                    client.send(b"UNKNOWN_CMD")
            else:
                client.send(b"NO_CONN")
            client.close()
        except Exception:
            pass


# --- MAIN ---
def handle_exit(signum, frame):
    print("[*] Shutting down — saving energy data")
    save_energy_to_disk()
    if mqtt_client:
        mqtt_client.disconnect()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    print(f"[*] ANJ-12KP Bridge v2 starting")
    print(f"[*] Dongle port: {INVERTER_PORT}, Control port: {LOCAL_CONTROL_PORT}")
    print(f"[*] MQTT: {MQTT_HOST}:{MQTT_PORT}, topic: {MQTT_TOPIC_PREFIX}")

    setup_mqtt()

    t1 = threading.Thread(target=inverter_server, daemon=True)
    t2 = threading.Thread(target=control_server, daemon=True)
    t1.start()
    t2.start()

    while True:
        time.sleep(1)
