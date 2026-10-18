"""
Onryo – inotify-based directory watcher.
Runs alongside (or instead of) the timer-based scan.
Watches every configured directory for IN_CREATE, IN_DELETE, IN_MOVED_*
events and triggers a re-scan immediately when info.json files appear or
disappear.

Requires: inotify-simple  (pip install inotify-simple)
Falls back gracefully if the package is missing (logs a warning and exits).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger("onryo.watcher")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanner.scanner import run_scan, _load_watch_dirs

try:
    import inotify_simple  # type: ignore
    _HAS_INOTIFY = True
except ImportError:
    _HAS_INOTIFY = False


def run() -> None:
    if not _HAS_INOTIFY:
        logger.warning(
            "inotify-simple not installed – directory watcher disabled. "
            "Install with: pip install inotify-simple"
        )
        return

    watch_dirs = _load_watch_dirs()
    if not watch_dirs:
        logger.warning("No watch directories configured – watcher exiting")
        return

    inotify = inotify_simple.INotify()
    flags = (
        inotify_simple.flags.CREATE
        | inotify_simple.flags.DELETE
        | inotify_simple.flags.MOVED_TO
        | inotify_simple.flags.MOVED_FROM
    )

    wd_map: dict[int, str] = {}
    for d in watch_dirs:
        p = Path(d)
        if p.is_dir():
            wd = inotify.add_watch(str(p), flags)
            wd_map[wd] = str(p)
            logger.info("Watching %s", p)
        else:
            logger.warning("Watch directory does not exist yet: %s", d)

    if not wd_map:
        logger.warning("No directories could be watched – watcher exiting")
        return

    logger.info("inotify watcher running on %d director(y/ies)", len(wd_map))

    _last_scan: float = 0.0
    _DEBOUNCE = 2.0  # seconds – coalesce rapid bursts of events

    while True:
        events = inotify.read(timeout=5000)  # ms; non-blocking poll
        if not events:
            continue

        for event in events:
            name = event.name
            # Only care about info.json appearing/disappearing
            if "info.json" in name or not name:  # empty name = directory itself
                now = time.monotonic()
                if now - _last_scan >= _DEBOUNCE:
                    logger.info(
                        "inotify event in %s – triggering scan",
                        wd_map.get(event.wd, "?"),
                    )
                    run_scan()
                    _last_scan = time.monotonic()
                break  # one scan per burst


if __name__ == "__main__":
    run()
