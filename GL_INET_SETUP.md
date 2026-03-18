# GL.iNet MT3000 — Anenji WiFi Dongle Redirect Setup

## What this does
The Anenji inverter's built-in WiFi tries to connect to a cloud server
at 8.218.202.213:18899. We redirect that traffic to the VPS (via Tailscale)
where the bridge is already running.

## Prerequisites
- Anenji inverter WiFi connected to the GL.iNet's WiFi network
- GL.iNet has Tailscale active (confirmed: gl-mt3000 at 100.81.132.111)
- VPS Tailscale IP: 100.97.225.102

## Step 1: Find the Anenji dongle's IP

SSH into the GL.iNet and check connected clients:

```bash
cat /tmp/dhcp.leases
# Look for a device with a MAC from the inverter's WiFi module
# Common OUIs for these dongles: ESP-based or USR-based
```

Or scan the ARP table:
```bash
ip neigh show
```

Note the IP. Example: 192.168.1.xxx

## Step 2: Add the firewall redirect

### Option A: Via UCI commands (recommended)

```bash
# Redirect cloud server traffic to VPS bridge
uci add firewall redirect
uci set firewall.@redirect[-1].name='Anenji Cloud Redirect'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].src_dip='8.218.202.213'
uci set firewall.@redirect[-1].src_dport='18899'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='100.97.225.102'
uci set firewall.@redirect[-1].dest_port='18899'
uci set firewall.@redirect[-1].proto='tcp'
uci set firewall.@redirect[-1].target='DNAT'

# Also redirect the data logging port
uci add firewall redirect
uci set firewall.@redirect[-1].name='Anenji Data Redirect'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].src_dip='8.218.202.213'
uci set firewall.@redirect[-1].src_dport='38899'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='100.97.225.102'
uci set firewall.@redirect[-1].dest_port='18899'
uci set firewall.@redirect[-1].proto='tcp'
uci set firewall.@redirect[-1].target='DNAT'

uci commit firewall
/etc/init.d/firewall restart
```

### Option B: If Option A doesn't work (direct iptables)

The dongle might not go through the firewall's PREROUTING chain
if it's on the same bridge. Use raw iptables:

```bash
# Get the Anenji dongle IP first (from Step 1)
ANENJI_IP="192.168.1.xxx"  # Replace with actual IP

iptables -t nat -A PREROUTING -s $ANENJI_IP -p tcp --dport 18899 -j DNAT --to-destination 100.97.225.102:18899
iptables -t nat -A PREROUTING -s $ANENJI_IP -p tcp --dport 38899 -j DNAT --to-destination 100.97.225.102:18899

# Make persistent
echo "iptables -t nat -A PREROUTING -s $ANENJI_IP -p tcp --dport 18899 -j DNAT --to-destination 100.97.225.102:18899" >> /etc/firewall.user
echo "iptables -t nat -A PREROUTING -s $ANENJI_IP -p tcp --dport 38899 -j DNAT --to-destination 100.97.225.102:18899" >> /etc/firewall.user
```

## Step 3: Verify

From the GL.iNet, test that the VPS bridge is reachable:
```bash
echo "JSON" | nc -w 3 100.97.225.102 9999
```

Should return JSON with "device_status_msg": "Offline" (until the dongle connects).

Then watch the bridge logs on the VPS:
```bash
docker logs -f anenji-bridge
```

You should see:
```
[*] Inverter connected from 192.168.1.xxx:xxxxx
[*] Sending Wake-up Command (AT+DTUPN?)...
[*] Dongle replied: <serial number>
```

## Troubleshooting

1. **Dongle doesn't connect**: The inverter's WiFi dongle might be configured
   to use a different cloud server. Check DNS:
   ```bash
   tcpdump -i br-lan -n host 192.168.1.xxx and port 18899
   ```

2. **DNS-based redirect** (if the dongle uses a hostname, not IP):
   Add to GL.iNet's dnsmasq config:
   ```bash
   uci add_list dhcp.@dnsmasq[0].address='/smartess.net/100.97.225.102'
   uci add_list dhcp.@dnsmasq[0].address='/dessmonitor.com/100.97.225.102'
   uci commit dhcp
   /etc/init.d/dnsmasq restart
   ```

3. **Bridge not reachable via Tailscale**:
   From GL.iNet: `ping 100.97.225.102`
   If unreachable, check Tailscale status: `tailscale status`
