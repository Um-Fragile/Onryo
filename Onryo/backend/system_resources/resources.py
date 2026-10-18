"""
Onryo – System resource metrics collector.
Returns CPU, memory, disk, temperature, uptime, and per-process stats.
Requires: psutil
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def _no_psutil() -> dict:
    return {"error": "psutil not installed; run: pip install psutil"}


def get_host_info() -> dict[str, Any]:
    """Static host info: hostname, OS, kernel, boot time."""
    if not _HAS_PSUTIL:
        return _no_psutil()
    import platform
    boot = psutil.boot_time()
    uptime_s = int(time.time() - boot)
    h, m, s = uptime_s // 3600, (uptime_s % 3600) // 60, uptime_s % 60
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "kernel": platform.version(),
        "architecture": platform.machine(),
        "boot_time": int(boot),
        "uptime": f"{h}h {m}m {s}s",
        "uptime_seconds": uptime_s,
    }


def get_cpu() -> dict[str, Any]:
    if not _HAS_PSUTIL:
        return _no_psutil()
    freq = psutil.cpu_freq()
    return {
        "percent": psutil.cpu_percent(interval=0.2),
        "count_logical": psutil.cpu_count(logical=True),
        "count_physical": psutil.cpu_count(logical=False),
        "frequency_mhz": round(freq.current, 1) if freq else None,
        "load_avg_1m": round(psutil.getloadavg()[0], 2),
        "load_avg_5m": round(psutil.getloadavg()[1], 2),
        "load_avg_15m": round(psutil.getloadavg()[2], 2),
    }


def get_memory() -> dict[str, Any]:
    if not _HAS_PSUTIL:
        return _no_psutil()
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "total_mb": vm.total // (1024 * 1024),
        "used_mb": vm.used // (1024 * 1024),
        "available_mb": vm.available // (1024 * 1024),
        "percent": vm.percent,
        "swap_total_mb": sw.total // (1024 * 1024),
        "swap_used_mb": sw.used // (1024 * 1024),
        "swap_percent": sw.percent,
    }


def get_disk() -> list[dict[str, Any]]:
    if not _HAS_PSUTIL:
        return [_no_psutil()]
    partitions = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        partitions.append({
            "device": part.device,
            "mountpoint": part.mountpoint,
            "fstype": part.fstype,
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "percent": usage.percent,
        })
    return partitions


def get_temperatures() -> dict[str, Any]:
    if not _HAS_PSUTIL:
        return _no_psutil()
    if not hasattr(psutil, "sensors_temperatures"):
        return {"available": False}
    temps = psutil.sensors_temperatures()
    if not temps:
        return {"available": False}
    result: dict[str, list] = {}
    for name, entries in temps.items():
        result[name] = [
            {"label": e.label or name, "current": e.current, "high": e.high, "critical": e.critical}
            for e in entries
        ]
    return {"available": True, "sensors": result}


def get_network_io() -> list[dict[str, Any]]:
    if not _HAS_PSUTIL:
        return [_no_psutil()]
    counters = psutil.net_io_counters(pernic=True)
    return [
        {
            "iface": iface,
            "bytes_sent": c.bytes_sent,
            "bytes_recv": c.bytes_recv,
            "packets_sent": c.packets_sent,
            "packets_recv": c.packets_recv,
            "errin": c.errin,
            "errout": c.errout,
        }
        for iface, c in counters.items()
        if iface != "lo"
    ]


def get_top_processes(n: int = 10) -> list[dict[str, Any]]:
    if not _HAS_PSUTIL:
        return [_no_psutil()]
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(procs, key=lambda x: x.get("cpu_percent") or 0, reverse=True)[:n]


def get_all() -> dict[str, Any]:
    return {
        "host": get_host_info(),
        "cpu": get_cpu(),
        "memory": get_memory(),
        "disk": get_disk(),
        "temperatures": get_temperatures(),
        "network_io": get_network_io(),
        "top_processes": get_top_processes(),
    }
