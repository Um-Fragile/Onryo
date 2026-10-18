#!/bin/bash
# Onryo – privileged helper (root-owned, narrow scope)
# Called by the non-root onryo service user to perform the handful of
# privileged operations the framework needs.  Never do anything outside
# this explicit allow-list.

set -euo pipefail
LOGFILE="/var/log/onryo/helper.log"
mkdir -p "$(dirname "$LOGFILE")"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [helper] $*" | tee -a "$LOGFILE" >&2; }

ACTION="${1:-}"
shift || true

case "$ACTION" in

  # --- systemd unit management -------------------------------------------
  enable)
    UNIT="$1"
    [[ "$UNIT" == onryo-svc-* ]] || { log "DENIED: enable $UNIT"; exit 1; }
    log "enable $UNIT"
    systemctl enable --now "$UNIT"
    ;;

  disable)
    UNIT="$1"
    [[ "$UNIT" == onryo-svc-* ]] || { log "DENIED: disable $UNIT"; exit 1; }
    log "disable $UNIT"
    systemctl disable --now "$UNIT"
    ;;

  start)
    UNIT="$1"
    [[ "$UNIT" == onryo-* ]] || { log "DENIED: start $UNIT"; exit 1; }
    log "start $UNIT"
    systemctl start "$UNIT"
    ;;

  stop)
    UNIT="$1"
    [[ "$UNIT" == onryo-* ]] || { log "DENIED: stop $UNIT"; exit 1; }
    log "stop $UNIT"
    systemctl stop "$UNIT"
    ;;

  write-unit)
    SRC="$1"
    DST="$2"
    [[ "$DST" == /etc/systemd/system/onryo-svc-* ]] || { log "DENIED: write-unit $DST"; exit 1; }
    log "write-unit $SRC -> $DST"
    install -m 644 "$SRC" "$DST"
    systemctl daemon-reload
    ;;

  # --- networking (bridge) -----------------------------------------------
  bridge-add)
    BRIDGE="$1"
    IFACE="$2"
    log "bridge-add $IFACE -> $BRIDGE"
    ip link add name "$BRIDGE" type bridge 2>/dev/null || true
    ip link set "$BRIDGE" up
    ip link set "$IFACE" master "$BRIDGE"
    ;;

  bridge-remove)
    BRIDGE="$1"
    IFACE="$2"
    log "bridge-remove $IFACE from $BRIDGE"
    ip link set "$IFACE" nomaster
    ;;

  wifi-reload)
    log "wifi-reload"
    systemctl reload-or-restart NetworkManager
    ;;

  # --- system AP (Onryo ap_manager.py) -----------------------------------
  # These are the privileged steps APManager.start()/stop() cannot do as
  # the non-root onryo user.  Channel switching for both the system AP
  # and the Vision plugin AP both go through ap-chan-switch.

  ap-setup)
    # ap-setup <iface> <ip/prefix>
    # Flush old addresses, assign AP IP, bring the interface up.
    IFACE="$1"
    ADDR="$2"   # e.g. 192.168.42.1/24
    [[ "$IFACE" =~ ^[a-zA-Z0-9_]+$ ]] || { log "DENIED: bad iface $IFACE"; exit 1; }
    log "ap-setup $IFACE $ADDR"
    ip addr flush dev "$IFACE"
    ip addr add "$ADDR" dev "$IFACE"
    ip link set "$IFACE" up
    ;;

  ap-teardown)
    # ap-teardown <iface>
    IFACE="$1"
    [[ "$IFACE" =~ ^[a-zA-Z0-9_]+$ ]] || { log "DENIED: bad iface $IFACE"; exit 1; }
    log "ap-teardown $IFACE"
    systemctl stop hostapd  2>/dev/null || true
    systemctl stop dnsmasq  2>/dev/null || true
    ip addr flush dev "$IFACE" 2>/dev/null || true
    ;;

  ap-start-daemons)
    # ap-start-daemons
    # (Re)start hostapd and dnsmasq after ap-setup has configured the iface.
    log "ap-start-daemons"
    systemctl restart hostapd
    systemctl restart dnsmasq
    echo 1 > /proc/sys/net/ipv4/ip_forward
    ;;

  ap-chan-switch)
    # ap-chan-switch <iface> <freq_mhz> [<center_freq_mhz>] [ht|vht]
    # Shared by both the system AP and the Vision plugin AP.
    IFACE="$1"
    FREQ="$2"
    CENTER="${3:-0}"
    MODE="${4:-ht}"
    [[ "$IFACE" =~ ^[a-zA-Z0-9_]+$ ]] || { log "DENIED: bad iface $IFACE";  exit 1; }
    [[ "$FREQ"  =~ ^[0-9]+$ ]]         || { log "DENIED: bad freq $FREQ";    exit 1; }
    [[ "$CENTER" =~ ^[0-9]+$ ]]        || { log "DENIED: bad center $CENTER"; exit 1; }
    log "ap-chan-switch $IFACE freq=$FREQ center=$CENTER mode=$MODE"
    if [[ "$MODE" == "vht" && "$CENTER" != "0" ]]; then
      hostapd_cli -i "$IFACE" chan_switch 10 "$FREQ" \
        center_freq1="$CENTER" sec_channel_offset=0 bandwidth=80 vht
    else
      hostapd_cli -i "$IFACE" chan_switch 10 "$FREQ" sec_channel_offset=0 ht
    fi
    ;;

  ap-set-txpower)
    IFACE="$1"
    DBM="$2"
    [[ "$IFACE" =~ ^[a-zA-Z0-9_]+$ ]] || { log "DENIED: bad iface"; exit 1; }
    [[ "$DBM"   =~ ^[0-9]+$ ]]         || { log "DENIED: bad txpower"; exit 1; }
    log "ap-set-txpower $IFACE ${DBM}dBm"
    iw dev "$IFACE" set txpower fixed "$((DBM * 100))"
    ;;

  ap-monitor-on)
    # Put interface into monitor mode (for Vision pentest scanner)
    IFACE="$1"
    [[ "$IFACE" =~ ^[a-zA-Z0-9_]+$ ]] || { log "DENIED: bad iface"; exit 1; }
    log "ap-monitor-on $IFACE"
    ip link set "$IFACE" down
    iw dev "$IFACE" set type monitor
    ip link set "$IFACE" up
    ;;

  ap-monitor-off)
    IFACE="$1"
    [[ "$IFACE" =~ ^[a-zA-Z0-9_]+$ ]] || { log "DENIED: bad iface"; exit 1; }
    log "ap-monitor-off $IFACE"
    ip link set "$IFACE" down
    iw dev "$IFACE" set type managed
    ip link set "$IFACE" up
    ;;

  # --- input lockout -------------------------------------------------------
  lockout-release)
    log "lockout-release – signaling input guard"
    systemctl kill --signal=SIGTERM onryo-input-guard.service 2>/dev/null || true
    ;;

  # --- uninstall -----------------------------------------------------------
  uninstall)
    log "uninstall triggered"
    /opt/onryo/uninstall.sh "$@"
    ;;

  *)
    log "Unknown action: $ACTION"
    exit 1
    ;;
esac
