#!/bin/bash
# =============================================================================
# Onryo – uninstall.sh
# Run as root (or via sudo). Also callable from the GUI System page.
# Usage: sudo ./uninstall.sh [--keep-config] [--keep-logs] [--remove-docker]
# =============================================================================

set -uo pipefail

ONRYO_USER="onryo"
ONRYO_HOME="/opt/onryo"
ETC_DIR="/etc/onryo"
LOG_DIR="/var/log/onryo"
UNINSTALL_LOG="/var/log/onryo-uninstall.log"   # outside LOG_DIR (may be removed)
SYSTEMD_DIR="/etc/systemd/system"

KEEP_CONFIG=0
KEEP_LOGS=0
REMOVE_DOCKER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-config)   KEEP_CONFIG=1   ;;
    --keep-logs)     KEEP_LOGS=1     ;;
    --remove-docker) REMOVE_DOCKER=1 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

exec > >(tee -a "$UNINSTALL_LOG") 2>&1

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [uninstall] $*"; }
[[ "$(id -u)" -eq 0 ]] || { echo "Must run as root"; exit 1; }

log "=== Onryo uninstaller starting ==="

# ---- Step 1: Release input lockout FIRST ------------------------------------
log "Releasing input lockout..."
systemctl stop onryo-input-guard.service 2>/dev/null || true
# Give evdev grabs a moment to release
sleep 1

# ---- Step 2: Stop all onryo-* units -----------------------------------------
log "Stopping all Onryo systemd units..."
systemctl stop  'onryo-svc-*.service' 2>/dev/null || true
systemctl stop  onryo-core.service   2>/dev/null || true
systemctl stop  onryo-netmgr.service 2>/dev/null || true
systemctl stop  onryo-scan.timer     2>/dev/null || true
systemctl stop  onryo-scan.service   2>/dev/null || true

systemctl disable 'onryo-svc-*.service' 2>/dev/null || true
systemctl disable onryo-core.service    2>/dev/null || true
systemctl disable onryo-netmgr.service  2>/dev/null || true
systemctl disable onryo-scan.timer      2>/dev/null || true
systemctl disable onryo-scan.service    2>/dev/null || true
systemctl disable onryo-input-guard.service 2>/dev/null || true

# ---- Step 3: Docker containers and volumes ----------------------------------
if command -v docker &>/dev/null; then
  log "Stopping Onryo Docker containers..."

  # Stop containers defined in Onryo compose files
  find "$ONRYO_HOME/containers" -name "docker-compose.yml" 2>/dev/null | while read -r cf; do
    dir=$(dirname "$cf")
    log "Bringing down compose stack in $dir"
    docker compose -f "$cf" down 2>/dev/null || true
  done

  # Ask about volume removal
  if [[ -t 0 ]]; then
    read -rp "Remove Onryo container VOLUMES (data loss)? (yes/no) [no]: " RM_VOLS
    if [[ "$RM_VOLS" == "yes" ]]; then
      log "Removing volumes..."
      find "$ONRYO_HOME/containers" -name "docker-compose.yml" 2>/dev/null | while read -r cf; do
        docker compose -f "$cf" down --volumes 2>/dev/null || true
      done
    fi
  fi
fi

# ---- Step 4: Network cleanup ------------------------------------------------
log "Tearing down Onryo-created network config..."
# Remove bridge if it exists
ip link show br0 &>/dev/null && {
  log "Removing bridge br0"
  ip link set br0 down 2>/dev/null || true
  ip link delete br0 type bridge 2>/dev/null || true
}

# Restore pentest adapter to NM management
if [[ -f "$ETC_DIR/network-roles.json" ]]; then
  python3 - <<'PYEOF' 2>/dev/null || true
import json, subprocess
from pathlib import Path

roles_file = "/etc/onryo/network-roles.json"
roles = json.loads(Path(roles_file).read_text())

for mac, role in roles.items():
    if role == "pentest":
        for iface in Path("/sys/class/net").iterdir():
            try:
                if (iface / "address").read_text().strip() == mac:
                    subprocess.run(["nmcli", "device", "set", iface.name, "managed", "yes"])
                    print(f"[uninstall] Restored {iface.name} to NM management")
            except:
                pass
PYEOF
fi

# ---- Step 5: Remove systemd unit files --------------------------------------
log "Removing systemd unit files..."
rm -f "$SYSTEMD_DIR"/onryo-*.service
rm -f "$SYSTEMD_DIR"/onryo-*.timer
systemctl daemon-reload
log "systemd unit files removed"

# ---- Step 6: Remove sudoers entry -------------------------------------------
rm -f /etc/sudoers.d/onryo
log "Sudoers entry removed"

# ---- Step 7: Remove udev rules (if any were installed) ----------------------
rm -f /etc/udev/rules.d/99-onryo-*.rules
udevadm control --reload-rules 2>/dev/null || true

# ---- Step 8: Remove files ---------------------------------------------------
log "Removing $ONRYO_HOME..."
rm -rf "$ONRYO_HOME"

if [[ $KEEP_CONFIG -eq 1 ]]; then
  log "Keeping config: $ETC_DIR (--keep-config)"
else
  log "Removing $ETC_DIR..."
  rm -rf "$ETC_DIR"
fi

if [[ $KEEP_LOGS -eq 1 ]]; then
  log "Keeping logs: $LOG_DIR (--keep-logs)"
else
  log "Removing $LOG_DIR..."
  rm -rf "$LOG_DIR"
fi

# ---- Step 9: Remove system user ---------------------------------------------
if id "$ONRYO_USER" &>/dev/null; then
  log "Removing system user: $ONRYO_USER"
  userdel "$ONRYO_USER" 2>/dev/null || true
fi

# ---- Step 10: Optionally remove Docker --------------------------------------
if [[ $REMOVE_DOCKER -eq 1 ]]; then
  log "Removing Docker packages..."
  DEBIAN_FRONTEND=noninteractive apt-get remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin 2>/dev/null || true
else
  log "Docker packages left installed (use --remove-docker to remove)"
fi

log "=== Onryo uninstall complete ==="
echo ""
echo "  Uninstall log: $UNINSTALL_LOG"
echo "  Input devices have been released."
echo ""
