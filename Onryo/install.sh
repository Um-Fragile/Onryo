#!/bin/bash
# =============================================================================
# Onryo – install.sh
# Run as root (or via sudo). Idempotent – safe to re-run.
# Usage: sudo ./install.sh [--non-interactive --config preseed.json]
# =============================================================================

set -euo pipefail

ONRYO_USER="onryo"
ONRYO_HOME="/opt/onryo"
ETC_DIR="/etc/onryo"
LOG_DIR="/var/log/onryo"
INSTALL_LOG="$LOG_DIR/install.log"
SYSTEMD_DIR="/etc/systemd/system"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

NON_INTERACTIVE=0
PRESEED=""

# ---- Argument parsing -------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=1 ;;
    --config) PRESEED="$2"; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

# ---- Logging ----------------------------------------------------------------
mkdir -p "$LOG_DIR"
exec > >(tee -a "$INSTALL_LOG") 2>&1

log()  { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [install] $*"; }
die()  { log "ERROR: $*"; exit 1; }
ask()  {
  local prompt="$1" default="$2" var="$3"
  if [[ $NON_INTERACTIVE -eq 1 ]]; then
    eval "$var='$default'"
    return
  fi
  read -rp "$prompt [$default]: " input
  eval "$var='${input:-$default}'"
}

log "=== Onryo installer starting ==="

# ---- Pre-flight checks ------------------------------------------------------
[[ "$(id -u)" -eq 0 ]] || die "Must run as root"

OS_ID=$(. /etc/os-release && echo "$ID")
[[ "$OS_ID" == "ubuntu" ]] || log "WARN: Expected Ubuntu, got $OS_ID – proceeding anyway"

ARCH=$(uname -m)
log "Architecture: $ARCH | OS: $OS_ID"

# Count wireless adapters
WIFI_COUNT=$(ls /sys/class/ieee80211 2>/dev/null | wc -l)
ETH_COUNT=$(ls /sys/class/net | grep -E '^(eth|en)' | wc -l || true)
log "Detected $WIFI_COUNT wireless adapter(s), $ETH_COUNT ethernet adapter(s)"
if [[ $WIFI_COUNT -lt 3 ]]; then
  log "WARN: Expected 3 wireless adapters, found $WIFI_COUNT. Some features may be unavailable."
fi

# ---- Install OS dependencies ------------------------------------------------
log "Installing OS dependencies..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-venv python3-pip \
  sqlite3 \
  hostapd dnsmasq \
  network-manager \
  udev \
  iproute2 iputils-ping \
  curl wget git \
  build-essential \
  --no-install-recommends

# ---- Install Docker ---------------------------------------------------------
if ! command -v docker &>/dev/null; then
  log "Installing Docker..."
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
else
  log "Docker already installed: $(docker --version)"
fi

# ---- Create onryo user and directories --------------------------------------
if ! id "$ONRYO_USER" &>/dev/null; then
  log "Creating system user: $ONRYO_USER"
  useradd --system --home-dir "$ONRYO_HOME" --shell /usr/sbin/nologin --create-home "$ONRYO_USER"
else
  log "User $ONRYO_USER already exists"
fi

# Add to docker group
usermod -aG docker "$ONRYO_USER" || true

mkdir -p "$ONRYO_HOME" "$ETC_DIR" "$LOG_DIR"
chown -R "$ONRYO_USER:$ONRYO_USER" "$ONRYO_HOME" "$LOG_DIR"
chown root:root "$ETC_DIR"
chmod 755 "$ETC_DIR"

# ---- Copy repo files --------------------------------------------------------
log "Copying framework files to $ONRYO_HOME..."
rsync -a --exclude='.git' "$REPO_DIR/" "$ONRYO_HOME/"
chown -R "$ONRYO_USER:$ONRYO_USER" "$ONRYO_HOME"

# Privileged helper must be root-owned, not writable by onryo user
chown root:root "$ONRYO_HOME/backend/privileged_helper/helper.sh"
chmod 755 "$ONRYO_HOME/backend/privileged_helper/helper.sh"

# ---- Python virtualenv + dependencies ----------------------------------------
log "Setting up Python virtualenv..."
python3 -m venv "$ONRYO_HOME/venv"
"$ONRYO_HOME/venv/bin/pip" install --quiet --upgrade pip
"$ONRYO_HOME/venv/bin/pip" install --quiet \
  fastapi uvicorn[standard] \
  pydantic \
  pyyaml \
  docker \
  aiofiles

# ---- sudoers entry for privileged helper ------------------------------------
SUDOERS_FILE="/etc/sudoers.d/onryo"
cat > "$SUDOERS_FILE" <<EOF
# Onryo – allow the onryo user to call the privileged helper
$ONRYO_USER ALL=(root) NOPASSWD: $ONRYO_HOME/backend/privileged_helper/helper.sh
EOF
chmod 440 "$SUDOERS_FILE"
log "Sudoers entry written: $SUDOERS_FILE"

# ---- Interactive configuration prompts -------------------------------------
log "--- Configuration ---"

# Admin password
if [[ $NON_INTERACTIVE -eq 0 ]]; then
  while true; do
    read -rsp "Admin GUI password: " ADMIN_PW; echo
    read -rsp "Confirm password:   " ADMIN_PW2; echo
    [[ "$ADMIN_PW" == "$ADMIN_PW2" ]] && break
    echo "Passwords do not match. Try again."
  done
else
  ADMIN_PW="${PRESEED_ADMIN_PW:-changeme}"
fi
ADMIN_HASH=$(python3 -c "import hashlib; print(hashlib.sha256('$ADMIN_PW'.encode()).hexdigest())")

ask "Initial Wi-Fi SSID (client adapter)"     ""     WIFI_SSID
ask "Initial Wi-Fi password"                   ""     WIFI_PSK
ask "AP hotspot SSID"                          "OnryoAP"  AP_SSID
ask "AP hotspot password"                      "onryo1234" AP_PSK
ask "Enable input lockout? (yes/no)"           "yes"  INPUT_LOCKOUT
ask "Plugin scan directory"                    "/opt/onryo/plugins" SCAN_DIR

INPUT_LOCKOUT_BOOL=1
[[ "$INPUT_LOCKOUT" == "no" ]] && INPUT_LOCKOUT_BOOL=0

# Adapter role assignment
log "Detected network adapters:"
ip link show | grep -E '^[0-9]+:' | awk '{print $2}' | tr -d ':' | grep -v lo
if [[ $NON_INTERACTIVE -eq 0 ]]; then
  echo ""
  echo "Assign adapter roles. Press Enter to skip an adapter."
  read -rp "Uplink (ethernet) adapter name: "  UPLINK_IFACE
  read -rp "Client (wifi 1) adapter name:   "  CLIENT_IFACE
  read -rp "AP (wifi 2) adapter name:        "  AP_IFACE
  read -rp "Pentest (wifi 3) adapter name:   "  PENTEST_IFACE
else
  UPLINK_IFACE="" CLIENT_IFACE="" AP_IFACE="" PENTEST_IFACE=""
fi

# ---- Write config files ------------------------------------------------------
log "Writing /etc/onryo config files..."

mkdir -p "$SCAN_DIR"
chown "$ONRYO_USER:$ONRYO_USER" "$SCAN_DIR"

# directories.json
cat > "$ETC_DIR/directories.json" <<EOF
{
  "directories": ["$SCAN_DIR", "$ONRYO_HOME/containers"]
}
EOF

# wifi-networks.json
cat > "$ETC_DIR/wifi-networks.json" <<EOF
[
  {"ssid": "$WIFI_SSID", "psk": "$WIFI_PSK", "priority": 10, "enabled": true}
]
EOF

# ap-config.json
cat > "$ETC_DIR/ap-config.json" <<EOF
{
  "ssid": "$AP_SSID",
  "password": "$AP_PSK",
  "channel": 6,
  "band": "bg"
}
EOF

# input-lockout.json
cat > "$ETC_DIR/input-lockout.json" <<EOF
{
  "enabled": $( [[ $INPUT_LOCKOUT_BOOL -eq 1 ]] && echo "true" || echo "false" ),
  "grace_period_seconds": 5
}
EOF

# network-roles.json – resolve MACs from interface names
ROLES_JSON="{"
FIRST=1
for pair in "uplink:$UPLINK_IFACE" "client:$CLIENT_IFACE" "ap:$AP_IFACE" "pentest:$PENTEST_IFACE"; do
  role="${pair%%:*}"
  iface="${pair##*:}"
  [[ -z "$iface" ]] && continue
  mac=$(cat "/sys/class/net/$iface/address" 2>/dev/null || echo "")
  [[ -z "$mac" ]] && { log "WARN: Could not resolve MAC for $iface"; continue; }
  [[ $FIRST -eq 0 ]] && ROLES_JSON+=","
  ROLES_JSON+="\"$mac\": \"$role\""
  FIRST=0
done
ROLES_JSON+="}"
echo "$ROLES_JSON" > "$ETC_DIR/network-roles.json"

# Store admin hash in DB via Python (DB created on first app start)
cat > /tmp/onryo_init_db.py <<'PYEOF'
import sys; sys.path.insert(0, '/opt/onryo')
from backend.db.database import init_db, get_db
init_db()
import os
with get_db() as db:
    db.execute("INSERT INTO app_settings (key,value) VALUES ('admin_pw_hash',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (os.environ['ADMIN_HASH'],))
PYEOF
ADMIN_HASH="$ADMIN_HASH" "$ONRYO_HOME/venv/bin/python" /tmp/onryo_init_db.py
chown "$ONRYO_USER:$ONRYO_USER" "$ONRYO_HOME/onryo.db" 2>/dev/null || true

# ---- Install systemd unit files ----------------------------------------------
log "Installing systemd units..."
for unit in "$REPO_DIR/systemd/"*; do
  install -m 644 "$unit" "$SYSTEMD_DIR/"
done

# Update paths in units to point to actual install location
for unit in "$SYSTEMD_DIR"/onryo-*.{service,timer}; do
  sed -i "s|/opt/onryo|$ONRYO_HOME|g" "$unit" 2>/dev/null || true
done

systemctl daemon-reload

# Enable (but don't start yet – let boot ordering handle it)
systemctl enable onryo-scan.timer
systemctl enable onryo-scan.service
systemctl enable onryo-netmgr.service
systemctl enable onryo-core.service
systemctl enable onryo-input-guard.service

# ---- Run first scan ---------------------------------------------------------
log "Running initial discovery scan..."
sudo -u "$ONRYO_USER" ONRYO_DB="$ONRYO_HOME/onryo.db" \
  "$ONRYO_HOME/venv/bin/python" -m backend.scanner.scanner || log "WARN: Initial scan failed – will retry on boot"

# ---- Minecraft stack prompt -------------------------------------------------
if [[ $NON_INTERACTIVE -eq 0 ]]; then
  read -rp "Enable Minecraft server now? (yes/no) [no]: " MC_ENABLE
else
  MC_ENABLE="no"
fi

if [[ "$MC_ENABLE" == "yes" ]]; then
  sudo -u "$ONRYO_USER" ONRYO_DB="$ONRYO_HOME/onryo.db" python3 - <<'PYEOF'
import sys; sys.path.insert(0, '/opt/onryo')
from backend.db.database import get_db
with get_db() as db:
    db.execute("UPDATE services SET enabled=1 WHERE name='Minecraft Server'")
PYEOF
  log "Minecraft server enabled."
fi

# ---- Final summary -----------------------------------------------------------
LAN_IP=$(hostname -I | awk '{print $1}')
log "=== Onryo installation complete ==="
echo ""
echo "  Web GUI:      http://$LAN_IP:8080"
echo "  AP SSID:      $AP_SSID"
echo "  AP Password:  $AP_PSK"
echo "  Install log:  $INSTALL_LOG"
echo ""
echo "  Start Onryo now: systemctl start onryo-core"
echo ""
