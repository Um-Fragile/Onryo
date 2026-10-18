#!/bin/bash
# Onryo network manager – boot-time network setup.
# Reads /etc/onryo/network-roles.json and /etc/onryo/wifi-networks.json,
# assigns roles, brings up AP and client connections.

set -uo pipefail
LOG="/var/log/onryo/netmgr.log"
mkdir -p "$(dirname "$LOG")"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [netmgr] $*" | tee -a "$LOG"; }

ROLES_FILE="/etc/onryo/network-roles.json"
WIFI_FILE="/etc/onryo/wifi-networks.json"

log "Onryo network manager starting"

# Resolve adapter names from MAC addresses (stable across reboots)
resolve_iface() {
  local mac="$1"
  for iface in /sys/class/net/*; do
    local name
    name=$(basename "$iface")
    [[ "$name" == "lo" ]] && continue
    local addr
    addr=$(cat "$iface/address" 2>/dev/null || true)
    if [[ "$addr" == "$mac" ]]; then
      echo "$name"
      return
    fi
  done
}

if [[ ! -f "$ROLES_FILE" ]]; then
  log "No roles file at $ROLES_FILE – skipping network setup"
  exit 0
fi

log "Roles file found: $ROLES_FILE"

# Parse roles using python (already installed as a dependency)
python3 - <<'PYEOF'
import json, subprocess, sys, os

ROLES_FILE = "/etc/onryo/network-roles.json"
WIFI_FILE  = "/etc/onryo/wifi-networks.json"

try:
    roles = json.loads(open(ROLES_FILE).read())
except Exception as e:
    print(f"[netmgr] Failed to read roles: {e}")
    sys.exit(0)

def resolve_iface(mac):
    import pathlib
    for p in pathlib.Path("/sys/class/net").iterdir():
        try:
            addr = (p / "address").read_text().strip()
            if addr == mac:
                return p.name
        except:
            pass
    return None

def run(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[netmgr] WARN: {' '.join(cmd)} -> {r.stderr.strip()}")
    return r

uplink_iface  = None
client_iface  = None
ap_iface      = None
pentest_iface = None

for mac, role in roles.items():
    iface = resolve_iface(mac) or mac
    print(f"[netmgr] {mac} -> {iface} ({role})")
    if role == "uplink":  uplink_iface  = iface
    if role == "client":  client_iface  = iface
    if role == "ap":      ap_iface      = iface
    if role == "pentest": pentest_iface = iface

# Bring up client adapter using NetworkManager saved profiles
if client_iface:
    wifi = []
    try:
        wifi = json.loads(open(WIFI_FILE).read())
    except:
        pass
    for net in sorted(wifi, key=lambda n: -n.get("priority", 0)):
        if not net.get("enabled", True):
            continue
        ssid = net.get("ssid", "")
        psk  = net.get("psk", "")
        print(f"[netmgr] Attempting connection to SSID: {ssid}")
        r = run("nmcli", "device", "wifi", "connect", ssid, "password", psk, "ifname", client_iface)
        if r.returncode == 0:
            print(f"[netmgr] Connected to {ssid}")
            break

# Leave pentest adapter unmanaged (NM hands-off)
if pentest_iface:
    run("nmcli", "device", "set", pentest_iface, "managed", "no")
    print(f"[netmgr] {pentest_iface} set unmanaged (pentest mode)")

print("[netmgr] Boot-time network setup complete")
PYEOF

log "Network manager boot complete"
