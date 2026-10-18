"""
Onryo – Network manager.
Handles adapter-role mapping, bridge building, Wi-Fi client list,
and AP configuration.  Privileged operations are delegated to the helper.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("onryo.network_manager")

ROLES_FILE = os.environ.get("ONRYO_NET_ROLES", "/etc/onryo/network-roles.json")
WIFI_FILE  = os.environ.get("ONRYO_WIFI_FILE",  "/etc/onryo/wifi-networks.json")
HELPER_BIN = os.environ.get("ONRYO_HELPER",     "/opt/onryo/privileged_helper/helper.sh")

VALID_ROLES = {"uplink", "client", "ap", "pentest"}


# ---------------------------------------------------------------------------
# Role / adapter helpers
# ---------------------------------------------------------------------------

def load_roles() -> dict:
    """Return {mac: role} mapping from /etc/onryo/network-roles.json."""
    try:
        return json.loads(Path(ROLES_FILE).read_text())
    except FileNotFoundError:
        return {}


def save_roles(roles: dict) -> None:
    Path(ROLES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(ROLES_FILE).write_text(json.dumps(roles, indent=2))


def list_adapters() -> list[dict]:
    """
    Return a list of {name, mac, role, state} for every physical network adapter.
    Resolves role by MAC first (stable), falls back to interface name.
    """
    roles = load_roles()
    adapters = []
    base = Path("/sys/class/net")
    for iface in sorted(base.iterdir()):
        # Skip virtual/loopback
        if iface.name == "lo":
            continue
        mac_path = iface / "address"
        if not mac_path.exists():
            continue
        mac = mac_path.read_text().strip()
        state_path = iface / "operstate"
        state = state_path.read_text().strip() if state_path.exists() else "unknown"
        role = roles.get(mac) or roles.get(iface.name, "unassigned")
        adapters.append({"name": iface.name, "mac": mac, "role": role, "state": state})
    return adapters


def set_role(mac: str, role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {VALID_ROLES}")
    roles = load_roles()
    # Uplink protection: warn caller if they're re-assigning the current uplink
    for k, v in roles.items():
        if v == "uplink" and k == mac and role != "uplink":
            logger.warning("Changing uplink adapter role – operator confirmed.")
    roles[mac] = role
    save_roles(roles)


# ---------------------------------------------------------------------------
# Bridge builder
# ---------------------------------------------------------------------------

def bridge_add(iface: str, bridge: str = "br0") -> None:
    """Add an interface to a Linux bridge (via privileged helper)."""
    _require_not_uplink(iface)
    _call_helper("bridge-add", bridge, iface)
    logger.info("Added %s to bridge %s", iface, bridge)


def bridge_remove(iface: str, bridge: str = "br0") -> None:
    _call_helper("bridge-remove", bridge, iface)
    logger.info("Removed %s from bridge %s", iface, bridge)


def list_bridge_members(bridge: str = "br0") -> list[str]:
    try:
        result = subprocess.run(
            ["ip", "link", "show", "master", bridge],
            capture_output=True, text=True, timeout=5
        )
        members = []
        for line in result.stdout.splitlines():
            if "@" in line:
                members.append(line.split(":")[1].strip().split("@")[0])
        return members
    except Exception as exc:
        logger.error("Could not list bridge members: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Wi-Fi client (priority list)
# ---------------------------------------------------------------------------

def load_wifi_networks() -> list[dict]:
    try:
        return json.loads(Path(WIFI_FILE).read_text())
    except FileNotFoundError:
        return []


def save_wifi_networks(networks: list[dict]) -> None:
    Path(WIFI_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(WIFI_FILE).write_text(json.dumps(networks, indent=2))


def add_wifi_network(ssid: str, psk: str, priority: int = 0) -> None:
    networks = load_wifi_networks()
    networks = [n for n in networks if n.get("ssid") != ssid]  # deduplicate
    networks.append({"ssid": ssid, "psk": psk, "priority": priority, "enabled": True})
    networks.sort(key=lambda n: n.get("priority", 0), reverse=True)
    save_wifi_networks(networks)
    _call_helper("wifi-reload")


def remove_wifi_network(ssid: str) -> None:
    networks = [n for n in load_wifi_networks() if n.get("ssid") != ssid]
    save_wifi_networks(networks)
    _call_helper("wifi-reload")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_not_uplink(iface: str) -> None:
    roles = load_roles()
    adapters = list_adapters()
    for a in adapters:
        if a["name"] == iface and roles.get(a["mac"]) == "uplink":
            raise PermissionError(
                f"Adapter {iface} is tagged as 'uplink' and is protected from bridging. "
                "Use set_role() to change this first and confirm you understand the risk."
            )


def _call_helper(action: str, *args: str) -> None:
    cmd = [HELPER_BIN, action, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Helper failed [{action}]: {result.stderr.strip()}")
