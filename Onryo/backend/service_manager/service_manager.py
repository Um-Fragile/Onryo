"""
Onryo – Service manager.
Generates per-plugin systemd unit files and calls the privileged helper
to enable/disable/start/stop them.  The web API calls into this module;
it never touches systemd directly (privilege separation).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("onryo.service_manager")

UNIT_DIR = os.environ.get("ONRYO_UNIT_DIR", "/etc/systemd/system")
HELPER_BIN = os.environ.get("ONRYO_HELPER", "/opt/onryo/privileged_helper/helper.sh")


def _unit_name(service_name: str) -> str:
    slug = service_name.lower().replace(" ", "-").replace("_", "-")
    return f"onryo-svc-{slug}.service"


def generate_unit(name: str, path: str, entrypoint: str, log_location: str) -> str:
    """Return the text of a systemd unit file for a discovered service."""
    unit_name = _unit_name(name)
    log_dir = os.path.dirname(log_location)
    content = f"""[Unit]
Description=Onryo managed service: {name}
After=onryo-core.service
PartOf=onryo-core.service

[Service]
Type=simple
User=onryo
Group=onryo
WorkingDirectory={path}
ExecStart=/bin/bash {entrypoint}
Restart=on-failure
RestartSec=5
StandardOutput=append:{log_location}
StandardError=append:{log_location}
RuntimeDirectory=onryo-svc-{name.lower().replace(" ", "-")}
RuntimeDirectoryMode=0750

[Install]
WantedBy=multi-user.target
"""
    return content


def write_unit(name: str, path: str, entrypoint: str, log_location: str) -> Path:
    """Write a systemd unit file to disk (via privileged helper) and return its path."""
    unit_name = _unit_name(name)
    unit_content = generate_unit(name, path, entrypoint, log_location)
    unit_path = Path(UNIT_DIR) / unit_name

    # Write to a temp file; helper moves it to /etc/systemd/system
    tmp = Path("/tmp") / unit_name
    tmp.write_text(unit_content)
    _call_helper("write-unit", str(tmp), str(unit_path))
    tmp.unlink(missing_ok=True)
    return unit_path


def enable_service(name: str) -> None:
    unit = _unit_name(name)
    _call_helper("enable", unit)
    logger.info("Enabled %s", unit)


def disable_service(name: str) -> None:
    unit = _unit_name(name)
    _call_helper("disable", unit)
    logger.info("Disabled %s", unit)


def start_service(name: str) -> None:
    unit = _unit_name(name)
    _call_helper("start", unit)
    logger.info("Started %s", unit)


def stop_service(name: str) -> None:
    unit = _unit_name(name)
    _call_helper("stop", unit)
    logger.info("Stopped %s", unit)


def service_status(name: str) -> str:
    """Return 'running', 'stopped', or 'error'."""
    unit = _unit_name(name)
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=5
        )
        state = result.stdout.strip()
        if state == "active":
            return "running"
        if state in ("failed", "activating"):
            return "error"
        return "stopped"
    except Exception as exc:
        logger.warning("Could not check status for %s: %s", unit, exc)
        return "unknown"


def _call_helper(action: str, *args: str) -> None:
    cmd = [HELPER_BIN, action, *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"Helper failed [{action}]: {result.stderr.strip()}")
    except FileNotFoundError:
        raise RuntimeError(f"Privileged helper not found at {HELPER_BIN}")
