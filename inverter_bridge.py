#!/usr/bin/env python3
"""
Anenji / Easun / MPP Solar — Local Cloud Bridge
Intercepts the WiFi dongle's cloud connection (port 18899) and polls
Modbus registers locally for 1-second real-time data + full control.

Exposes port 9999 for HA command_line integration and publishes to MQTT.

Adapted from samuelolteanu/Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters
License: GPL-3.0
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
INVERTER_PORT = 18899
LOCAL_CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "9999"))
BIND_IP = '0.0.0.0'
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))
INVERTER_RATED_WATT = int(os.environ.get("INVERTER_RATED_WATT", "12000"))
OFFLINE_THRESHOLD = 10

# --- MQTT (optional — publishes to existing HA topic structure) ---
MQTT_ENABLED = os.environ.get("MQTT_ENABLED", "true").lower() == "true"
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "solar/inverter")
MQTT_PUBLISH_INTERVAL = float(os.environ.get("MQTT_PUBLISH_INTERVAL", "5.0"))

mqtt_client = None
if MQTT_ENABLED:
    try:
        import paho.mqtt.client as paho_mqtt
        mqtt_client = paho_mqtt.Client(client_id="anenji-bridge", protocol=paho_mqtt.MQTTv311)
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"[*] MQTT connected to {MQTT_HOST}:{MQTT_PORT}")
    except ImportError:
        print("[!] paho-mqtt not installed — MQTT disabled. pip install paho-mqtt")
        mqtt_client = None
    except Exception as e:
        print(f"[!] MQTT connection failed: {e} — MQTT disabled")
        mqtt_client = None

# --- ENERGY PERSISTENCE ---
ENERGY_FILE = os.environ.get("ENERGY_FILE", "/data/inverter_energy.json")
SAVE_INTERVAL = 300  # Save to disk every 5 minutes

# --- TRANSLATION MAPS ---
STATUS_MAP = {
    0: "Power On", 1: "Standby", 2: "Line Mode (On-Grid)",
    3: "Off-Grid (Battery)", 4: "Bypass", 5: "Charging", 6: "Fault"
}

BATTERY_TYPE_MAP = {
    0: "AGN", 1: "FLD", 2: "USR", 4: "LI2",
    6: "LI4", 8: "LIb"
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
energy_lock = threading.Lock()


# --- HELPERS ---
def decode_flags(val, map_dict, prefix="Unknown"):
    active_list = []
    if val == 0:
        return []
    for bit in range(32):
        if (val >> bit) & 1:
            msg = map_dict.get(bit, f"{prefix} (Bit {bit})")
            active_list.append(msg)
    return active_list


def load_or_create_energy_data():
    default_structure = {
        "total_pv_kwh": 0.0,
        "total_grid_input_kwh": 0.0,
        "total_load_kwh": 0.0,
        "total_battery_charge_kwh": 0.0,
        "total_battery_discharge_kwh": 0.0
    }

    if os.path.exists(ENERGY_FILE):
        try:
            with open(ENERGY_FILE, 'r') as f:
                data = json.load(f)
                for key in default_structure:
                    if key not in data:
                        data[key] = default_structure[key]
                print(f"[*] Loaded energy data: PV={data['total_pv_kwh']:.2f} kWh, "
                      f"Grid={data['total_grid_input_kwh']:.2f} kWh, "
                      f"Load={data['total_load_kwh']:.2f} kWh")
                return data
        except Exception as e:
            print(f"[!] Error loading energy file: {e}")
            return default_structure.copy()
    else:
        os.makedirs(os.path.dirname(ENERGY_FILE), exist_ok=True)
        print("[*] No energy file found. Creating new structure.")
        return default_structure.copy()


energy_data = load_or_create_energy_data()


def save_energy_to_disk():
    with energy_lock:
        try:
            os.makedirs(os.path.dirname(ENERGY_FILE), exist_ok=True)
            with open(ENERGY_FILE + ".tmp", 'w') as f:
                json.dump(energy_data, f, indent=2)
            os.replace(ENERGY_FILE + ".tmp", ENERGY_FILE)
        except Exception as e:
            print(f"[!] Energy Save Failed: {e}")


# --- MQTT PUBLISHING ---
def publish_mqtt(data):
    if not mqtt_client:
        return
    try:
        prefix = MQTT_TOPIC_PREFIX
        # Battery
        mqtt_client.publish(f"{prefix}/battery/soc", data.get("batt_soc", ""), retain=True)
        mqtt_client.publish(f"{prefix}/battery/voltage", data.get("batt_volt", ""), retain=True)
        mqtt_client.publish(f"{prefix}/battery/current", data.get("batt_current", ""), retain=True)
        mqtt_client.publish(f"{prefix}/battery/power", data.get("batt_power_watt", ""), retain=True)
        # PV
        mqtt_client.publish(f"{prefix}/pv/power", data.get("pv_input_watt", ""), retain=True)
        mqtt_client.publish(f"{prefix}/pv/pv1_power", data.get("pv_input_watt", ""), retain=True)
        mqtt_client.publish(f"{prefix}/pv/voltage", data.get("pv_input_volt", ""), retain=True)
        mqtt_client.publish(f"{prefix}/pv/current", data.get("pv_current", ""), retain=True)
        # Grid
        mqtt_client.publish(f"{prefix}/grid/power", data.get("grid_power_watt", ""), retain=True)
        mqtt_client.publish(f"{prefix}/grid/voltage", data.get("grid_volt", ""), retain=True)
        mqtt_client.publish(f"{prefix}/grid/frequency", data.get("grid_freq", ""), retain=True)
        # Load
        mqtt_client.publish(f"{prefix}/load/power", data.get("ac_load_real_watt", ""), retain=True)
        # Status
        mqtt_client.publish(f"{prefix}/bridge/status", data.get("device_status_msg", "Unknown"), retain=True)
        mqtt_client.publish(f"{prefix}/bridge/last_poll", time.strftime("%Y-%m-%dT%H:%M:%S%z"), retain=True)
        # Energy totals
        mqtt_client.publish(f"{prefix}/energy/pv_total_kwh", data.get("total_pv_energy_kwh", 0), retain=True)
        mqtt_client.publish(f"{prefix}/energy/grid_input_total_kwh", data.get("total_grid_input_kwh", 0), retain=True)
        mqtt_client.publish(f"{prefix}/energy/load_total_kwh", data.get("total_load_kwh", 0), retain=True)
        # Fault/Warning
        mqtt_client.publish(f"{prefix}/fault", data.get("fault_msg", "No Fault"), retain=True)
        mqtt_client.publish(f"{prefix}/warning", data.get("warning_msg", "No Warning"), retain=True)
    except Exception as e:
        print(f"[!] MQTT publish error: {e}")


def get_empty_data():
    data = {
        "fault_code": 0, "fault_msg": "No Fault", "fault_list": [],
        "warning_code": 0, "warning_msg": "No Warning", "warning_list": [],
        "device_status_code": None, "device_status_msg": "Offline",
        "batt_volt": None, "ac_load_va": None, "ac_load_real_watt": None, "ac_load_pct": None,
        "batt_power_watt": None, "grid_power_watt": None, "ac_output_amp": None, "pv_input_watt": None,
        "pv_charging_watt": None,
        "pv_input_volt": None, "pv_current": None, "batt_soc": None, "temp_dc": None, "temp_inv": None,
        "max_total_amps": None, "max_ac_amps": None, "batt_current": None, "grid_volt": None,
        "grid_freq": None, "ac_out_volt": None, "ac_out_amp": None, "return_to_default": 0,
        "charger_priority": 3, "output_mode": 0, "ac_input_range": 0, "buzzer_mode": 3,
        "backlight_status": 1, "soc_back_to_grid": 100, "soc_back_to_batt": 100, "soc_cutoff": 0,
        "grid_current": None, "inverter_temp": None, "grid_charge_setting": 0,
        "battery_type_code": None, "battery_type_msg": None,
        "bulk_charge_volt": None, "float_charge_volt": None, "low_dc_cutoff_volt": None,
        "total_pv_energy_kwh": round(energy_data["total_pv_kwh"], 4),
        "total_grid_input_kwh": round(energy_data["total_grid_input_kwh"], 4),
        "total_load_kwh": round(energy_data["total_load_kwh"], 4),
        "total_battery_charge_kwh": round(energy_data["total_battery_charge_kwh"], 4),
        "total_battery_discharge_kwh": round(energy_data["total_battery_discharge_kwh"], 4)
    }
    return data


latest_data_json = get_empty_data()


# --- MODBUS HELPERS ---
def modbus_crc(data):
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for i in range(8):
            if (crc & 1) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)


def to_signed(val):
    return val - 65536 if val >= 32768 else val


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
    except:
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
    except:
        return None


# --- MAIN INVERTER SERVER ---
def inverter_server():
    global current_inverter_conn, latest_data_json, last_cmd_time
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((BIND_IP, INVERTER_PORT))
    s.listen(1)

    consecutive_failures = 0
    loop_counter = 0
    last_integration_time = time.time()
    last_save_time = time.time()
    last_mqtt_time = time.time()

    while True:
        try:
            print("[*] Waiting for Inverter connection on port 18899...")
            conn, addr = s.accept()
            current_inverter_conn = conn
            conn.settimeout(5.0)
            print(f"[*] Inverter connected from {addr[0]}:{addr[1]}")

            # Cloud emulation handshake
            try:
                print("[*] Sending Wake-up Command (AT+DTUPN?)...")
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

            # Polling loop
            while True:
                now = time.time()
                time_delta = now - last_integration_time
                last_integration_time = now

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

                            # Sensor decoding
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
                                    latest_data_json["total_battery_charge_kwh"] = round(energy_data["total_battery_charge_kwh"], 4)
                                    latest_data_json["total_battery_discharge_kwh"] = round(energy_data["total_battery_discharge_kwh"], 4)

                            # Auto save
                            if (now - last_save_time) > SAVE_INTERVAL:
                                save_energy_to_disk()
                                last_save_time = now

                            # JSON update
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
                                "ac_load_watt": p_load,
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
                                "inverter_temp": vals[26]
                            })

                            # Faults/warnings every 2 loops
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
                                        "fault_list": f_list,
                                        "warning_code": warn_val,
                                        "warning_msg": ", ".join(w_list) if w_list else "No Warning",
                                        "warning_list": w_list
                                    })

                            # Config reads every 5 loops (when not in command cooldown)
                            is_cooldown = (time.time() - last_cmd_time) < 10.0
                            if (loop_counter % 5 == 0) and (not is_cooldown):
                                conn.send(build_read_packet(301, 6))
                                time.sleep(0.1)
                                v300 = read_modbus_response(conn)
                                if v300:
                                    latest_data_json.update({
                                        "output_mode": v300[0], "ac_input_range": v300[1],
                                        "buzzer_mode": v300[2], "backlight_status": v300[4],
                                        "return_to_default": v300[5]
                                    })

                                conn.send(build_read_packet(331, 3))
                                time.sleep(0.1)
                                v330 = read_modbus_response(conn)
                                if v330:
                                    latest_data_json.update({
                                        "charger_priority": v330[0],
                                        "max_total_amps": v330[1] / 10.0,
                                        "max_ac_amps": v330[2] / 10.0
                                    })

                                conn.send(build_read_packet(341, 3))
                                time.sleep(0.1)
                                vsoc = read_modbus_response(conn)
                                if vsoc:
                                    latest_data_json.update({
                                        "soc_back_to_grid": vsoc[0],
                                        "soc_back_to_batt": vsoc[1],
                                        "soc_cutoff": vsoc[2]
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
                                        "low_dc_cutoff_volt": v322[7] / 10.0
                                    })

                            # MQTT publish at configured interval
                            if mqtt_client and (now - last_mqtt_time) > MQTT_PUBLISH_INTERVAL:
                                publish_mqtt(latest_data_json)
                                last_mqtt_time = now

                    except Exception:
                        consecutive_failures += 1
                        if consecutive_failures >= OFFLINE_THRESHOLD:
                            break
                loop_counter += 1
                time.sleep(POLL_INTERVAL)
        except:
            print("[!] Connection lost, waiting for reconnect...")
            time.sleep(1)
        finally:
            if current_inverter_conn:
                print("[!] Inverter disconnected")
                current_inverter_conn.close()
                current_inverter_conn = None
            latest_data_json = get_empty_data()
            if mqtt_client:
                publish_mqtt(latest_data_json)


# --- CONTROL SERVER (port 9999) ---
def control_server():
    global latest_data_json, last_cmd_time
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((BIND_IP, LOCAL_CONTROL_PORT))
    s.listen(5)
    print(f"[*] Control server listening on port {LOCAL_CONTROL_PORT}")

    while True:
        try:
            client, _ = s.accept()
            req = client.recv(1024).strip().decode().upper()

            if req == "JSON":
                client.send(json.dumps(latest_data_json).encode())
            elif current_inverter_conn and req:
                cmd_packet = None
                if req.startswith("MODE_"):
                    cmd_packet = build_write_packet(301, int(req.split("_")[1]))
                    latest_data_json["output_mode"] = int(req.split("_")[1])
                elif req.startswith("SET_AC_RANGE_"):
                    cmd_packet = build_write_packet(302, int(req.split("_")[3]))
                    latest_data_json["ac_input_range"] = int(req.split("_")[3])
                elif req == "CSO_SET":
                    cmd_packet = build_write_packet(331, 1)
                    latest_data_json["charger_priority"] = 1
                elif req in ("SNU_SET", "CHARGE_ON"):
                    cmd_packet = build_write_packet(331, 2)
                    latest_data_json["charger_priority"] = 2
                elif req in ("OSO_SET", "CHARGE_OFF"):
                    cmd_packet = build_write_packet(331, 3)
                    latest_data_json["charger_priority"] = 3
                elif req.startswith("SET_AMPS_"):
                    val = int(req.split("_")[2])
                    cmd_packet = build_write_packet(333, val * 10)
                    latest_data_json["max_ac_amps"] = val
                elif req.startswith("SET_TOTAL_AMPS_"):
                    val = int(req.split("_")[3])
                    cmd_packet = build_write_packet(332, val * 10)
                    latest_data_json["max_total_amps"] = val
                elif req.startswith("SET_SOC_GRID_"):
                    val = int(req.split("_")[3])
                    cmd_packet = build_write_packet(341, val)
                    latest_data_json["soc_back_to_grid"] = val
                elif req.startswith("SET_SOC_BATT_"):
                    val = int(req.split("_")[3])
                    cmd_packet = build_write_packet(342, val)
                    latest_data_json["soc_back_to_batt"] = val
                elif req.startswith("SET_SOC_CUTOFF_"):
                    val = int(req.split("_")[3])
                    cmd_packet = build_write_packet(343, val)
                    latest_data_json["soc_cutoff"] = val
                elif req.startswith("SET_BUZZER_"):
                    cmd_packet = build_write_packet(303, int(req.split("_")[2]))
                    latest_data_json["buzzer_mode"] = int(req.split("_")[2])
                elif req.startswith("SET_BACKLIGHT_"):
                    cmd_packet = build_write_packet(305, int(req.split("_")[2]))
                    latest_data_json["backlight_status"] = int(req.split("_")[2])
                elif req.startswith("SET_RETURN_DEFAULT_"):
                    cmd_packet = build_write_packet(306, int(req.split("_")[3]))
                    latest_data_json["return_to_default"] = int(req.split("_")[3])
                elif req.startswith("SET_BATTERY_TYPE_"):
                    val = int(req.split("_")[3])
                    cmd_packet = build_write_packet(322, val)
                    latest_data_json["battery_type_code"] = val
                elif req.startswith("SET_BULK_VOLT_"):
                    val = float(req.split("_")[3])
                    cmd_packet = build_write_packet(324, int(val * 10))
                    latest_data_json["bulk_charge_volt"] = val
                elif req.startswith("SET_FLOAT_VOLT_"):
                    val = float(req.split("_")[3])
                    cmd_packet = build_write_packet(325, int(val * 10))
                    latest_data_json["float_charge_volt"] = val
                elif req.startswith("SET_LOW_DC_CUTOFF_"):
                    val = float(req.split("_")[4])
                    cmd_packet = build_write_packet(329, int(val * 10))
                    latest_data_json["low_dc_cutoff_volt"] = val

                if cmd_packet:
                    with modbus_lock:
                        flush_buffer(current_inverter_conn)
                        current_inverter_conn.send(cmd_packet)
                        last_cmd_time = time.time()
                    client.send(b"OK")
                else:
                    client.send(b"UNKNOWN_CMD")
            else:
                client.send(b"NO_CONN")
            client.close()
        except:
            pass


def handle_exit(signum, frame):
    print("[*] Stopping... Saving energy data.")
    save_energy_to_disk()
    if mqtt_client:
        mqtt_client.disconnect()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    print(f"[*] Anenji Local Cloud Bridge starting (rated {INVERTER_RATED_WATT}W)")
    print(f"[*] Inverter port: {INVERTER_PORT}, Control port: {LOCAL_CONTROL_PORT}")
    print(f"[*] MQTT: {'enabled' if mqtt_client else 'disabled'}")

    t1 = threading.Thread(target=inverter_server, daemon=True)
    t2 = threading.Thread(target=control_server, daemon=True)
    t1.start()
    t2.start()
    while True:
        time.sleep(1)
