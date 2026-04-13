# Local Cloud Bridge for Anenji / Easun / MPP Solar Inverters

**Unchain your inverter from the cloud.**

A fully local, privacy-focused control system for "Cloud-Only" Hybrid Inverters sold under brands like **Anenji**, **Easun**, **MPP Solar**, and others that use the **Desmonitor**, **SmartEss**, or **WatchPower** mobile apps.

The current registers are mapped for **SRNE-based single-phase inverters**. Voltronic/Axpert-based models use different registers and will need adjustment.

By hijacking the inverter's WiFi dongle traffic and redirecting it to a local Python bridge, you get **1-second real-time updates**, complete offline control, and instant Home Assistant integration — without opening the case, voiding the warranty, or using RS232 adapters.

## Features

- **HACS Compatible** — One-click install via the Home Assistant Community Store
- **Native HA Integration** — Config flow UI, auto-created entities, zero YAML editing required
- **1-Second Real-Time Updates** — Replaces the slow 5-minute cloud polling with instant high-frequency Modbus reads
- **100% Local Control** — Transparent TCP bridge. No data leaves your network
- **Full Device Management from Home Assistant:**
  - Output Modes: UTI, SOL, SBU, SUB, SUF
  - Battery Management: AC Charge Amps, SOC Thresholds, Battery Type, Voltage Limits
  - System Controls: Buzzer, LCD Backlight, AC Input Range
- **MQTT Publishing** — Optional MQTT output for flexible HA integration (auto-discovery compatible topic structure)
- **Energy Tracking** — Cumulative kWh counters for PV, Grid, Load, Battery Charge/Discharge (persisted to disk)
- **Smart Calculations** — Real-time Battery Current, PV Current, Power Factor, all derived from raw registers
- **Docker Ready** — Single-container deployment with persistent energy data
- **No Hardware Mods** — Uses the inverter's existing WiFi dongle

## Verified Hardware

| Model | Status |
|---|---|
| ANENJI ANJ-6200W-48V | Verified |
| ANENJI ANJ-12KP-48V | Verified |
| Vevor EM6200-48L | Verified |
| Other SRNE-based (Easun, MPP Solar) | Should work — registers may vary |

## How It Works

```
┌──────────────┐     ┌─────────────┐     ┌──────────────────┐
│  WiFi Dongle │────>│ DNAT/iptables│────>│  Bridge (18899)  │
│  (Inverter)  │     │  (Router)   │     │  Python + MQTT   │
└──────────────┘     └─────────────┘     └────────┬─────────┘
                                                   │
                                          ┌────────┴─────────┐
                                          │ Home Assistant    │
                                          │ (nc → port 9999) │
                                          │  or MQTT sensors  │
                                          └──────────────────┘
```

The inverter's WiFi dongle tries to connect to a cloud server at `8.218.202.213:18899`. A firewall rule (DNAT) redirects that traffic to your local bridge. The bridge emulates the cloud handshake, then polls Modbus registers every second.

## Quick Start (HACS — Recommended)

### Prerequisites
1. The bridge server must be running (see [Bridge Setup](#quick-start-docker) below)
2. [HACS](https://hacs.xyz) must be installed in your Home Assistant

### Install via HACS

1. Open HACS in Home Assistant
2. Click the three dots (top right) → **Custom repositories**
3. Add `https://github.com/Millerderek/anenji-ha-bridge` as **Integration**
4. Search for "Anenji" in HACS and click **Install**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration → Anenji Inverter Bridge**
7. Enter your bridge server's IP and port (default: 9999)

That's it. The integration auto-creates:
- **26 sensors** — Battery, PV, Grid, Load, Temperature, Energy counters, Status
- **3 switches** — LCD Backlight, Grid Charging, Return to Default Screen
- **8 number controls** — Charge amps, SOC thresholds, voltage limits
- **5 select dropdowns** — Output mode, Charger priority, Buzzer, AC range, Battery type

All entities appear under a single "Anenji Inverter" device.

### Manual Install (without HACS)

1. Copy `custom_components/anenji_bridge/` into your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via **Settings → Devices & Services**

---

## Quick Start (Docker)

```bash
git clone https://github.com/YOUR_USER/anenji-ha-bridge.git
cd anenji-ha-bridge
docker compose up -d
```

The bridge starts on port **18899** (inverter) and **9999** (control/query).

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MQTT_ENABLED` | `true` | Enable/disable MQTT publishing |
| `MQTT_HOST` | `127.0.0.1` | MQTT broker address |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_TOPIC_PREFIX` | `solar/inverter` | MQTT topic prefix |
| `MQTT_PUBLISH_INTERVAL` | `5.0` | Seconds between MQTT publishes |
| `POLL_INTERVAL` | `1` | Seconds between Modbus polls |
| `CONTROL_PORT` | `9999` | TCP port for HA command interface |
| `ENERGY_FILE` | `/data/inverter_energy.json` | Path for persistent energy counters |
| `INVERTER_RATED_WATT` | `12000` | Inverter rated wattage (for load % calc) |

## Installation

### Step 0: Redirect the Dongle's Traffic

The WiFi dongle must believe your bridge IS the cloud server. Choose one method:

#### Option A: Router-Based (OpenWRT / pfSense)

Add to your OpenWRT `/etc/config/firewall`:

```ini
config redirect 'inverter_hijack'
    option name 'Inverter Hijack'
    option src 'lan'
    option proto 'tcp'
    option src_ip 'INVERTER_IP'
    option src_dip '8.218.202.213'
    option src_dport '18899'
    option dest_ip 'BRIDGE_IP'
    option dest_port '18899'
    option target 'DNAT'

config nat 'inverter_snat'
    option name 'Inverter Loopback'
    option src 'lan'
    option proto 'tcp'
    option dest_ip 'BRIDGE_IP'
    option dest_port '18899'
    option target 'MASQUERADE'
```

Replace `INVERTER_IP` with your inverter dongle's IP and `BRIDGE_IP` with your bridge server's IP.

#### Option B: Standalone Linux Server (Raspberry Pi, LXC, VM)

Use this if you don't have an OpenWRT router. The bridge server acts as the inverter's gateway.

1. **Install dependencies:**
   ```bash
   apt update && apt install dnsmasq iptables-persistent -y
   ```

2. **Configure DHCP** (`/etc/dnsmasq.conf`):
   ```ini
   interface=eth0
   bind-interfaces
   port=0

   dhcp-range=192.168.1.100,192.168.1.240,12h
   dhcp-option=6,8.8.8.8
   dhcp-option=3,ROUTER_IP

   # Tag the inverter dongle by its MAC address
   dhcp-host=AA:BB:CC:DD:EE:FF,INVERTER_IP,Solar-Inverter,set:solar_inverter
   dhcp-option=tag:solar_inverter,3,BRIDGE_IP
   ```

3. **Configure routing & firewall:**
   ```bash
   sysctl -w net.ipv4.ip_forward=1
   iptables -t nat -A PREROUTING -s INVERTER_IP -p tcp --dport 18899 -j REDIRECT --to-port 18899
   iptables -t nat -A PREROUTING -s INVERTER_IP -p tcp --dport 38899 -j REDIRECT --to-port 18899
   iptables -A FORWARD -s INVERTER_IP -j DROP
   netfilter-persistent save
   ```

#### Option C: Remote Bridge via GL.iNet Router + Tailscale

See [GL_INET_SETUP.md](GL_INET_SETUP.md) for a guide on redirecting traffic through a travel router to a remote VPS.

### Step 1: Identify Your Cloud Target

Confirm the cloud server IP and port your dongle is connecting to:

```bash
apt update && apt install dsniff tcpdump
# Spoof: tell the inverter YOU are the router
arpspoof -i eth0 -t INVERTER_IP ROUTER_IP
# In another terminal, watch the traffic:
tcpdump -i eth0 host INVERTER_IP and port 18899
```

You should see connections to `8.218.202.213:18899`.

### Step 2: Start the Bridge

**Docker (recommended):**
```bash
docker compose up -d
docker logs -f anenji-bridge
```

**Systemd (bare metal):**
```bash
cp inverter_bridge.py /opt/anenji-bridge/
pip install paho-mqtt

cat > /etc/systemd/system/anenji-bridge.service << 'EOF'
[Unit]
Description=Anenji Inverter Local Cloud Bridge
After=network.target

[Service]
ExecStart=/usr/bin/python3 -u /opt/anenji-bridge/inverter_bridge.py
WorkingDirectory=/opt/anenji-bridge
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now anenji-bridge
```

### Step 3: Verify the Connection

```bash
echo "JSON" | nc -w 3 BRIDGE_IP 9999
```

Should return JSON with all sensor data. Before the dongle connects, you'll see `"device_status_msg": "Offline"`.

### Step 4: Home Assistant Integration

**Option A: HACS (Recommended)** — See [Quick Start (HACS)](#quick-start-hacs--recommended) above. No YAML needed.

**Option B: Manual YAML** — If you prefer YAML-based configuration, copy the files from the `homeassistant/` directory:

- **`homeassistant/configuration.yaml`** — Sensors, shell commands, template entities, switches, number controls
- **`homeassistant/automations.yaml`** — Automation rules that sync HA dropdowns with inverter settings

Find-and-replace `BRIDGE_IP` with your actual bridge server IP address, then restart HA.

## Testing the Bridge

Query all sensor data:
```bash
echo "JSON" | nc -w 1 BRIDGE_IP 9999
```

Send a command:
```bash
# Switch to Solar First mode
echo "MODE_1" | nc -w 5 BRIDGE_IP 9999

# Set AC charge amps to 30A
echo "SET_AMPS_30" | nc -w 5 BRIDGE_IP 9999

# Set battery back-to-grid SOC to 15%
echo "SET_SOC_GRID_15" | nc -w 5 BRIDGE_IP 9999
```

## Command Reference

| Command | Description |
|---|---|
| `JSON` | Return all sensor data as JSON |
| `MODE_0` to `MODE_4` | Set output mode (UTI/SOL/SBU/SUB/SUF) |
| `CSO_SET` / `SNU_SET` / `OSO_SET` | Set charger priority |
| `CHARGE_ON` / `CHARGE_OFF` | Enable/disable grid charging |
| `SET_AMPS_x` | Set max AC charge current (amps) |
| `SET_TOTAL_AMPS_x` | Set max total charge current (amps) |
| `SET_SOC_GRID_x` | Set back-to-grid SOC % |
| `SET_SOC_BATT_x` | Set back-to-battery SOC % |
| `SET_SOC_CUTOFF_x` | Set cut-off SOC % |
| `SET_BUZZER_0` to `SET_BUZZER_3` | Set buzzer mode |
| `SET_BACKLIGHT_0` / `SET_BACKLIGHT_1` | LCD backlight off/on |
| `SET_BATTERY_TYPE_x` | Set battery type (0=AGN,1=FLD,2=USR,4=LI2,6=LI4,8=LIb) |
| `SET_BULK_VOLT_x` | Set bulk charge voltage |
| `SET_FLOAT_VOLT_x` | Set float charge voltage |
| `SET_LOW_DC_CUTOFF_x` | Set low DC cut-off voltage |
| `SET_RETURN_DEFAULT_0/1` | Return to default screen off/on |
| `SET_AC_RANGE_0/1/2` | AC input range (APL/UPS/GEN) |

## Register Map

| Register | Function | Unit / Description |
|---|---|---|
| **100-101** | Fault Code | 32-bit combined fault flags |
| **108-109** | Warning Code | 32-bit combined warning flags |
| **201** | Device Status | 0=Power On, 1=Standby, 2=Line, 3=Batt, 4=Bypass, 5=Charging, 6=Fault |
| **202** | Grid Voltage | 0.1 V |
| **203** | Grid Frequency | 0.01 Hz |
| **204** | Grid Power | Watts |
| **205** | Output Voltage | 0.1 V |
| **211** | Output Current | 0.1 A |
| **213** | Active Output Power | Watts (real load) |
| **214** | Apparent Output | VA |
| **215** | Battery Voltage | 0.1 V |
| **219** | PV Voltage | 0.1 V |
| **223** | PV Input Power | Watts |
| **224** | PV Charging Power | Watts (solar→battery) |
| **226** | Inverter Temp | °C |
| **227** | DC/Heatsink Temp | °C |
| **229** | Battery SOC | % |
| **232** | Net Battery Current | 0.1 A (signed: + charging, - discharging) |
| **301** | Output Mode | 0=UTI, 1=SOL, 2=SBU, 3=SUB, 4=SUF |
| **302** | AC Input Range | 0=Appliances, 1=UPS, 2=Gen |
| **303** | Buzzer Mode | 0=Mute, 1=Src/Warn/Flt, 2=Warn/Flt, 3=Flt |
| **305** | LCD Backlight | 0=Off, 1=On |
| **306** | Return to Default | 0=Disabled, 1=Enabled |
| **322** | Battery Type | 0=AGN, 1=FLD, 2=USR, 4=LI2, 6=LI4, 8=LIb |
| **324** | Bulk Charge Volt | 0.1 V |
| **325** | Float Charge Volt | 0.1 V |
| **329** | Low DC Cutoff Volt | 0.1 V |
| **331** | Charger Priority | 1=CSO, 2=SNU, 3=OSO |
| **332** | Max Total Amps | 0.1 A |
| **333** | Max AC Amps | 0.1 A |
| **341** | SOC Back to Grid | % |
| **342** | SOC Back to Batt | % |
| **343** | SOC Cut-off | % |

## Tools

### Register Hunter (`tools/register_hunter.py`)

A discovery tool for mapping unknown registers. It takes a snapshot, waits for you to change a setting on the inverter's LCD, then reports which registers changed. This is how the register map above was built.

```bash
python3 tools/register_hunter.py
```

## Disclaimer & Safety Warning

**Use at your own risk.** This project is not affiliated with Anenji, Easun, MPP Solar, Vevor, or any other manufacturer.

- **Active Control Risk:** This bridge supports **writing settings** to the inverter (Registers 300+). Changing parameters like Max Charging Amps or Battery Cut-off Limits can stress your battery or inverter if set incorrectly. Always verify your battery's datasheet first.
- **Cloud Disconnection:** By design, this bridge **hijacks** the inverter's network traffic. The official mobile app will permanently show "Offline", and you will not receive firmware updates while the bridge is running.
- **Expert Use Only:** The write-logic touches the inverter's internal memory. Do not modify shell commands unless you understand Modbus protocol for your specific device.

## Credits

Adapted from [samuelolteanu/Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters](https://github.com/samuelolteanu/Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters).

## License

GPL-3.0 — See [LICENSE](LICENSE)
