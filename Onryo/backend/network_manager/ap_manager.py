"""
Onryo – hostapd + dnsmasq AP config generator and runtime manager.

Supports:
  - 2.4 GHz 802.11b/g/n  (hw_mode=g, HT20/HT40)
  - 5 GHz   802.11a/n/ac  (hw_mode=a, HT40, VHT 80 MHz)
  - Channel hopping daemon (background thread, hostapd_cli chan_switch)
  - Auto best-channel selection (scans for congestion via iw)
  - phy capability discovery via 'iw phy'
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import string
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("onryo.ap_manager")

_ETC            = Path("/etc/onryo")
_HOSTAPD_CONF   = Path("/etc/hostapd/onryo-ap.conf")
_DNSMASQ_CONF   = Path("/etc/dnsmasq.d/onryo-ap.conf")

# ---------------------------------------------------------------------------
# Channel tables
# ---------------------------------------------------------------------------

# 2.4 GHz: channel → frequency (MHz)
CHANNELS_2G: dict[int, int] = {ch: 2407 + ch * 5 for ch in range(1, 14)}
CHANNELS_2G[14] = 2484

# 5 GHz UNII bands (channel → frequency)
CHANNELS_5G: dict[int, int] = {
    # UNII-1
    36: 5180, 40: 5200, 44: 5220, 48: 5240,
    # UNII-2A (DFS)
    52: 5260, 56: 5280, 60: 5300, 64: 5320,
    # UNII-2C (DFS)
    100: 5500, 104: 5520, 108: 5540, 112: 5560,
    116: 5580, 120: 5600, 124: 5620, 128: 5640,
    132: 5660, 136: 5680, 140: 5700, 144: 5720,
    # UNII-3
    149: 5745, 153: 5765, 157: 5785, 161: 5805, 165: 5825,
}

# Non-DFS 5 GHz channels (safe default for channel hopping without DFS radar wait)
CHANNELS_5G_NO_DFS: list[int] = [36, 40, 44, 48, 149, 153, 157, 161, 165]

# Default non-overlapping 2.4 GHz channels
CHANNELS_2G_NO_OVERLAP: list[int] = [1, 6, 11]

# VHT 80 MHz: primary channel → (center_seg0_channel, allowed_primaries)
# center = lowest_ch + 6  (for a group of 4 x 20 MHz = 80 MHz)
_VHT80_GROUPS: list[tuple[int, int]] = [
    (42,  [36, 40, 44, 48]),
    (58,  [52, 56, 60, 64]),
    (106, [100, 104, 108, 112]),
    (122, [116, 120, 124, 128]),
    (138, [132, 136, 140, 144]),
    (155, [149, 153, 157, 161]),
]


def _vht80_center(channel: int) -> int | None:
    """Return VHT 80 MHz center segment 0 index for *channel*, or None if not valid."""
    for center, primaries in _VHT80_GROUPS:
        if channel in primaries:
            return center
    return None


def _ht_capab(channel: int, band: str, width: int = 20) -> str:
    """
    Return an HT capab string appropriate for the channel and width.
    width: 20 or 40.
    """
    caps = ["[SHORT-GI-20]"]
    if width == 40:
        # HT40+: secondary channel is above; HT40-: below
        ht40_plus  = {36, 44, 52, 60, 100, 108, 116, 124, 132, 140, 149, 157}
        ht40_minus = {40, 48, 56, 64, 104, 112, 120, 128, 136, 144, 153, 161}
        if channel in ht40_plus:
            caps.append("[HT40+]")
            caps.append("[SHORT-GI-40]")
        elif channel in ht40_minus:
            caps.append("[HT40-]")
            caps.append("[SHORT-GI-40]")
    if band == "a":
        caps.append("[DSSS_CCK-40]")
    return "".join(caps)


_HELPER = os.environ.get("ONRYO_HELPER", "/opt/onryo/backend/privileged_helper/helper.sh")


def _helper(*args: str) -> tuple[bool, str]:
    """Call the privileged helper. Returns (ok, message)."""
    result = subprocess.run(
        ["sudo", _HELPER, *args],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        logger.warning("helper %s failed: %s", args, result.stderr.strip())
        return False, result.stderr.strip()
    return True, result.stdout.strip()


def _channel_to_freq(channel: int, band: str) -> int:
    if band == "a":
        return CHANNELS_5G.get(channel, 5000 + channel * 5)
    return CHANNELS_2G.get(channel, 2407 + channel * 5)


# ---------------------------------------------------------------------------
# hostapd config renderer
# ---------------------------------------------------------------------------

def render_hostapd_conf(
    iface:      str,
    ssid:       str,
    password:   str,
    channel:    int   = 6,
    band:       str   = "bg",   # bg | a
    width:      int   = 20,     # 20 | 40 | 80
    ieee80211ac: bool = True,   # enable VHT on 5 GHz when True
    bridge:     str | None = None,
    country:    str   = "US",
) -> str:
    """
    Render a hostapd.conf appropriate for the given band and channel.

    Band "bg" → 2.4 GHz 802.11b/g/n
    Band "a"  → 5 GHz 802.11a/n(/ac when ieee80211ac=True and width=80)
    """
    hw_mode   = "a" if band == "a" else "g"
    ht_cap    = _ht_capab(channel, band, min(width, 40))
    bridge_ln = f"bridge={bridge}\n" if bridge else ""
    country_ln = f"country_code={country}\n" if country else ""

    # Base 802.11n block
    lines = [
        f"interface={iface}",
        bridge_ln.rstrip("\n"),
        f"driver=nl80211",
        country_ln.rstrip("\n"),
        f"ieee80211d=1",
        f"ssid={ssid}",
        f"hw_mode={hw_mode}",
        f"channel={channel}",
        f"ieee80211n=1",
        f"wmm_enabled=1",
        f"ht_capab={ht_cap}",
        f"macaddr_acl=0",
        f"auth_algs=1",
        f"ignore_broadcast_ssid=0",
        f"wpa=2",
        f"wpa_passphrase={password}",
        f"wpa_key_mgmt=WPA-PSK",
        f"wpa_pairwise=CCMP",
        f"rsn_pairwise=CCMP",
    ]

    # 5 GHz extras
    if band == "a":
        lines.append("ieee80211h=1")  # DFS / TPC required on 5 GHz
        if ieee80211ac and width == 80:
            center = _vht80_center(channel)
            if center is not None:
                lines += [
                    "ieee80211ac=1",
                    "vht_oper_chwidth=1",          # 80 MHz
                    f"vht_oper_centr_freq_seg0_idx={center}",
                    "vht_capab=[SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][MAX-MPDU-11454][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN]",
                ]
            else:
                # Fall back to HT40 if channel not in a VHT80 group
                lines.append("ieee80211ac=1")
        elif ieee80211ac:
            lines.append("ieee80211ac=1")

    # Filter blank lines
    return "\n".join(ln for ln in lines if ln) + "\n"


# ---------------------------------------------------------------------------
# dnsmasq config renderer
# ---------------------------------------------------------------------------

def render_dnsmasq_conf(
    iface:      str,
    dhcp_start: str = "192.168.42.10",
    dhcp_end:   str = "192.168.42.100",
    dhcp_mask:  str = "255.255.255.0",
    dhcp_lease: str = "24h",
    router_ip:  str = "192.168.42.1",
    dns_server: str = "1.1.1.1",
) -> str:
    return (
        f"interface={iface}\n"
        f"bind-interfaces\n"
        f"server={dns_server}\n"
        f"domain-needed\n"
        f"bogus-priv\n"
        f"dhcp-range={dhcp_start},{dhcp_end},{dhcp_mask},{dhcp_lease}\n"
        f"dhcp-option=3,{router_ip}\n"
        f"dhcp-option=6,{dns_server}\n"
    )


# ---------------------------------------------------------------------------
# phy capability discovery
# ---------------------------------------------------------------------------

def get_phy_info(iface: str) -> dict[str, Any]:
    """
    Query 'iw phy' to discover supported bands and channels.
    Returns {'bands': {'2.4': [1..13], '5': [36,40,...]}, 'supports_ac': bool}
    """
    result: dict[str, Any] = {"bands": {"2.4": [], "5": []}, "supports_ac": False}
    try:
        # Find the phy name for this interface
        phy_out = subprocess.check_output(
            ["iw", "dev", iface, "info"], text=True, stderr=subprocess.DEVNULL
        )
        phy_match = re.search(r"wiphy\s+(\d+)", phy_out)
        phy_name = f"phy{phy_match.group(1)}" if phy_match else "phy0"

        phy_info = subprocess.check_output(
            ["iw", "phy", phy_name, "info"], text=True, stderr=subprocess.DEVNULL
        )

        # Detect VHT (802.11ac) support
        if "VHT Capabilities" in phy_info:
            result["supports_ac"] = True

        # Parse band sections
        current_band: str | None = None
        for line in phy_info.splitlines():
            if "Band 1" in line:
                current_band = "2.4"
            elif "Band 2" in line or "Band 3" in line:
                current_band = "5"
            ch_match = re.search(r"\*\s+(\d+)\s+MHz\s+\[(\d+)\]", line)
            if ch_match and current_band:
                ch = int(ch_match.group(2))
                if "(disabled)" not in line and "(no IR)" not in line:
                    result["bands"][current_band].append(ch)
    except Exception as exc:
        logger.warning("get_phy_info failed: %s", exc)
    return result


# ---------------------------------------------------------------------------
# Channel congestion scan
# ---------------------------------------------------------------------------

def scan_best_channel(iface: str, band: str = "bg") -> int:
    """
    Scan the air with 'iw dev scan' and return the least-congested channel
    for the given band.  Falls back to channel 6 (2.4 GHz) or 36 (5 GHz)
    if scanning fails or the interface is in AP mode (can't scan).
    """
    default = 36 if band == "a" else 6
    candidates = list(CHANNELS_5G_NO_DFS) if band == "a" else CHANNELS_2G_NO_OVERLAP
    congestion: dict[int, int] = {ch: 0 for ch in candidates}
    try:
        raw = subprocess.check_output(
            ["iw", "dev", iface, "scan", "passive"],
            text=True, stderr=subprocess.DEVNULL, timeout=15
        )
        for line in raw.splitlines():
            freq_match = re.search(r"freq:\s+(\d+)", line)
            if freq_match:
                freq = int(freq_match.group(1))
                # Map freq → channel
                if band == "a":
                    for ch, f in CHANNELS_5G.items():
                        if f == freq and ch in congestion:
                            congestion[ch] += 1
                else:
                    for ch, f in CHANNELS_2G.items():
                        if f == freq and ch in congestion:
                            congestion[ch] += 1
    except Exception as exc:
        logger.info("Channel scan skipped: %s", exc)
        return default
    return min(congestion, key=lambda ch: congestion[ch])


# ---------------------------------------------------------------------------
# Channel hopper
# ---------------------------------------------------------------------------

class ChannelHopper:
    """
    Background thread that cycles through *channel_list* every *interval* seconds
    using 'hostapd_cli chan_switch'.
    """

    def __init__(self, iface: str, band: str, channel_list: list[int], interval: int = 30):
        self.iface        = iface
        self.band         = band
        self.channel_list = channel_list
        self.interval     = interval
        self._stop        = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_ch: int = channel_list[0] if channel_list else 0
        self._hop_count   = 0

    # ---- public API --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="onryo-ch-hop")
        self._thread.start()
        logger.info("Channel hopper started on %s, channels=%s, interval=%ds",
                    self.iface, self.channel_list, self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Channel hopper stopped")

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict[str, Any]:
        return {
            "running":      self.running,
            "current_ch":   self._current_ch,
            "hop_count":    self._hop_count,
            "channel_list": self.channel_list,
            "interval":     self.interval,
            "band":         self.band,
        }

    # ---- internal ----------------------------------------------------------

    def _run(self) -> None:
        idx = 0
        while not self._stop.is_set():
            ch = self.channel_list[idx % len(self.channel_list)]
            self._switch(ch)
            idx += 1
            self._stop.wait(self.interval)

    def _switch(self, channel: int) -> None:
        freq   = _channel_to_freq(channel, self.band)
        center = _vht80_center(channel) if self.band == "a" else None
        center_freq = _channel_to_freq(center, "a") if center else 0
        mode   = "vht" if (self.band == "a" and center) else "ht"

        ok, msg = _helper("ap-chan-switch", self.iface,
                          str(freq), str(center_freq), mode)
        if ok:
            self._current_ch = channel
            self._hop_count += 1
            logger.debug("Hopped to channel %d (freq %d MHz)", channel, freq)
        else:
            logger.warning("chan_switch to %d failed: %s", channel, msg)


# ---------------------------------------------------------------------------
# APManager – high-level class used by the API
# ---------------------------------------------------------------------------

class APManager:
    """Stateful AP manager: config persistence, lifecycle, channel hopping."""

    def __init__(self) -> None:
        self._hopper: ChannelHopper | None = None

    # ---- config ------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        cfg_file = _ETC / "ap-config.json"
        if cfg_file.exists():
            return json.loads(cfg_file.read_text())
        return {
            "ssid":               "OnryoAP",
            "password":           "onryo1234",
            "channel":            6,
            "band":               "bg",
            "width":              20,
            "ieee80211ac":        True,
            "country":            "US",
            "ap_ip":              "192.168.42.1",
            "dhcp_start":         "192.168.42.10",
            "dhcp_end":           "192.168.42.100",
            "channel_hop":        False,
            "channel_hop_interval": 30,
            "channel_hop_list":   [],
        }

    def save_config(self, cfg: dict) -> None:
        _ETC.mkdir(parents=True, exist_ok=True)
        (_ETC / "ap-config.json").write_text(json.dumps(cfg, indent=2))

    # ---- lifecycle ---------------------------------------------------------

    def _iface(self) -> str:
        cfg = self.get_config()
        return cfg.get("iface", "wlan0")

    def start(self) -> tuple[bool, str]:
        cfg   = self.get_config()
        iface = cfg.get("iface", "wlan0")
        ap_ip = cfg.get("ap_ip", "192.168.42.1")
        try:
            write_configs(iface, cfg)
            ok, msg = _helper("ap-setup", iface, f"{ap_ip}/24")
            if not ok:
                return False, f"ap-setup failed: {msg}"
            ok, msg = _helper("ap-start-daemons")
            if not ok:
                return False, f"ap-start-daemons failed: {msg}"
            if cfg.get("channel_hop"):
                hop_list     = cfg.get("channel_hop_list") or self._default_hop_list(cfg.get("band", "bg"))
                hop_interval = int(cfg.get("channel_hop_interval", 30))
                self.start_channel_hopping(hop_list, hop_interval)
            return True, "AP started"
        except Exception as exc:
            return False, str(exc)

    def stop(self) -> tuple[bool, str]:
        self.stop_channel_hopping()
        iface = self._iface()
        try:
            ok, msg = _helper("ap-teardown", iface)
            _HOSTAPD_CONF.unlink(missing_ok=True)
            _DNSMASQ_CONF.unlink(missing_ok=True)
            return ok, "AP stopped" if ok else msg
        except Exception as exc:
            return False, str(exc)

    # ---- channel hopping ---------------------------------------------------

    def start_channel_hopping(self, channel_list: list[int], interval: int = 30) -> None:
        self.stop_channel_hopping()
        cfg  = self.get_config()
        band = cfg.get("band", "bg")
        iface = cfg.get("iface", "wlan0")
        if not channel_list:
            channel_list = self._default_hop_list(band)
        self._hopper = ChannelHopper(iface, band, channel_list, interval)
        self._hopper.start()

    def stop_channel_hopping(self) -> None:
        if self._hopper:
            self._hopper.stop()
            self._hopper = None

    def get_hop_status(self) -> dict[str, Any]:
        if self._hopper:
            return self._hopper.status()
        return {"running": False, "current_ch": None, "hop_count": 0,
                "channel_list": [], "interval": 0, "band": ""}

    def _default_hop_list(self, band: str) -> list[int]:
        return CHANNELS_5G_NO_DFS if band == "a" else CHANNELS_2G_NO_OVERLAP

    # ---- channel discovery -------------------------------------------------

    def get_available_channels(self) -> dict[str, Any]:
        """Return phy-supported channels and whether VHT/AC is available."""
        iface = self._iface()
        phy = get_phy_info(iface)
        return {
            "channels_2g":   sorted(phy["bands"]["2.4"]) or list(CHANNELS_2G.keys()),
            "channels_5g":   sorted(phy["bands"]["5"])   or list(CHANNELS_5G.keys()),
            "channels_5g_no_dfs": CHANNELS_5G_NO_DFS,
            "supports_ac":   phy["supports_ac"],
            "freq_map_2g":   {str(ch): freq for ch, freq in CHANNELS_2G.items()},
            "freq_map_5g":   {str(ch): freq for ch, freq in CHANNELS_5G.items()},
        }

    def auto_best_channel(self) -> int:
        cfg   = self.get_config()
        iface = cfg.get("iface", "wlan0")
        band  = cfg.get("band", "bg")
        return scan_best_channel(iface, band)

    # ---- clients -----------------------------------------------------------

    def connected_clients(self) -> list[dict[str, str]]:
        leases = Path("/var/lib/misc/dnsmasq.leases")
        if not leases.exists():
            return []
        clients = []
        for line in leases.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                clients.append({"mac": parts[1], "ip": parts[2], "hostname": parts[3]})
        return clients

    # ---- helpers -----------------------------------------------------------

    def regen_password(self) -> str:
        alphabet = string.ascii_letters + string.digits
        pw = "".join(secrets.choice(alphabet) for _ in range(16))
        cfg = self.get_config()
        cfg["password"] = pw
        self.save_config(cfg)
        return pw


# ---------------------------------------------------------------------------
# Low-level write_configs (used by APManager.start and helper.sh)
# ---------------------------------------------------------------------------

def write_configs(iface: str, cfg: dict) -> None:
    ssid        = cfg.get("ssid", "OnryoAP")
    password    = cfg.get("password", "onryo1234")
    channel     = int(cfg.get("channel", 6))
    band        = cfg.get("band", "bg")
    width       = int(cfg.get("width", 20))
    ieee80211ac = bool(cfg.get("ieee80211ac", True))
    country     = cfg.get("country", "US")
    bridge      = cfg.get("bridge")

    hostapd_conf = render_hostapd_conf(
        iface, ssid, password, channel, band, width, ieee80211ac, bridge, country
    )
    _HOSTAPD_CONF.parent.mkdir(parents=True, exist_ok=True)
    _HOSTAPD_CONF.write_text(hostapd_conf)

    dnsmasq_conf = render_dnsmasq_conf(
        iface      = iface,
        router_ip  = cfg.get("ap_ip", "192.168.42.1"),
        dhcp_start = cfg.get("dhcp_start", "192.168.42.10"),
        dhcp_end   = cfg.get("dhcp_end",   "192.168.42.100"),
    )
    _DNSMASQ_CONF.parent.mkdir(parents=True, exist_ok=True)
    _DNSMASQ_CONF.write_text(dnsmasq_conf)
