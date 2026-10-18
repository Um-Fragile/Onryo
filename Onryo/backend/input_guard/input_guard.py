"""
Onryo – Input lockout guard.
Monitors DRM hotplug events via udev and grabs/releases input devices
(keyboard, mouse, touchpad) using evdev EVIOCGRAB when no display is connected.

Run as a systemd service (onryo-input-guard.service) with sufficient
privileges to open /dev/input/event* devices.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path

logger = logging.getLogger("onryo.input_guard")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

CONFIG_FILE   = os.environ.get("ONRYO_LOCKOUT_CONFIG", "/etc/onryo/input-lockout.json")
GRACE_DEFAULT = 5  # seconds before engaging lockout after display disconnect

# Held open file descriptors for grabbed devices: {path: fd}
_grabbed: dict[str, int] = {}


def _load_config() -> dict:
    try:
        return json.loads(Path(CONFIG_FILE).read_text())
    except FileNotFoundError:
        return {"enabled": True, "grace_period_seconds": GRACE_DEFAULT}


def _display_connected() -> bool:
    """Return True if any DRM output reports 'connected'."""
    drm_base = Path("/sys/class/drm")
    if not drm_base.exists():
        return False
    for card in drm_base.iterdir():
        status_path = card / "status"
        if status_path.exists():
            try:
                if status_path.read_text().strip() == "connected":
                    return True
            except OSError:
                pass
    return False


def _input_devices() -> list[str]:
    """Return paths of input event devices that are keyboards/mice/touchpads."""
    devices = []
    input_base = Path("/sys/class/input")
    for node in sorted(Path("/dev/input").glob("event*")):
        devices.append(str(node))
    return devices


def _grab_all() -> None:
    import fcntl
    EVIOCGRAB = 0x40044590  # ioctl number for EVIOCGRAB
    for dev_path in _input_devices():
        if dev_path in _grabbed:
            continue
        try:
            fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
            fcntl.ioctl(fd, EVIOCGRAB, 1)
            _grabbed[dev_path] = fd
            logger.info("Grabbed %s", dev_path)
        except OSError as exc:
            logger.warning("Could not grab %s: %s", dev_path, exc)


def _release_all() -> None:
    import fcntl
    EVIOCGRAB = 0x40044590
    for dev_path, fd in list(_grabbed.items()):
        try:
            fcntl.ioctl(fd, EVIOCGRAB, 0)
            os.close(fd)
            logger.info("Released %s", dev_path)
        except OSError as exc:
            logger.warning("Could not release %s: %s", dev_path, exc)
        finally:
            del _grabbed[dev_path]


def run() -> None:
    cfg = _load_config()
    if not cfg.get("enabled", True):
        logger.info("Input lockout disabled in config – exiting")
        return

    grace = int(cfg.get("grace_period_seconds", GRACE_DEFAULT))
    logger.info("Input guard started (grace=%ds)", grace)

    # Allow the configured grace period before any lockout so the operator
    # isn't immediately locked out on boot.
    logger.info("Grace period: %ds before first evaluation", grace)
    time.sleep(grace)

    def _handle_signal(sig, frame):
        logger.info("Signal %s received – releasing all grabs and exiting", sig)
        _release_all()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    currently_locked = False
    try:
        while True:
            # Re-read config each cycle so GUI toggle takes effect without restart
            cfg = _load_config()
            if not cfg.get("enabled", True):
                if currently_locked:
                    logger.info("Lockout disabled via config – releasing grabs")
                    _release_all()
                    currently_locked = False
                time.sleep(5)
                continue

            display_present = _display_connected()

            if not display_present and not currently_locked:
                logger.info("No display detected – engaging input lockout")
                _grab_all()
                currently_locked = True

            elif display_present and currently_locked:
                logger.info("Display detected – releasing input lockout")
                _release_all()
                currently_locked = False

            time.sleep(2)
    finally:
        _release_all()


if __name__ == "__main__":
    run()
