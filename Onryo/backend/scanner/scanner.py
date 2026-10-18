"""
Onryo – Discovery scanner.
Walks configured watch directories one level deep, validates info.json files
against the expected schema, and upserts rows into the SQLite catalog DB.
Can be run as a one-shot script (onryo-scan.service) or called programmatically.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import get_db, log_event

logger = logging.getLogger("onryo.scanner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

VALID_TYPES = {"network", "automation", "pentest", "media", "utility", "docker", "custom"}
REQUIRED_FIELDS = {"name", "description", "type", "entrypoint"}
DIRS_CONFIG = os.environ.get("ONRYO_DIRS_CONFIG", "/etc/onryo/directories.json")
SCANNER_LOG = os.environ.get("ONRYO_SCANNER_LOG", "/var/log/onryo/scanner.log")


def _load_watch_dirs() -> list[str]:
    try:
        with open(DIRS_CONFIG) as fh:
            data = json.load(fh)
        dirs = data.get("directories", [])
        if not isinstance(dirs, list):
            raise ValueError("'directories' must be a list")
        return [str(d) for d in dirs]
    except FileNotFoundError:
        logger.warning("Directories config not found at %s; using /opt/onryo/plugins", DIRS_CONFIG)
        return ["/opt/onryo/plugins"]
    except Exception as exc:
        logger.error("Failed to read directories config: %s", exc)
        return ["/opt/onryo/plugins"]


def _validate_manifest(data: dict) -> list[str]:
    """Return a list of error strings; empty list means valid."""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in data or not data[field]:
            errors.append(f"Missing required field: '{field}'")
    if "type" in data and data["type"] not in VALID_TYPES:
        logger.warning("Unknown type '%s'; coercing to 'custom'", data["type"])
        data["type"] = "custom"
    return errors


def _upsert_service(db, path: str, manifest: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = db.execute("SELECT id, enabled FROM services WHERE path=?", (path,)).fetchone()
    if existing:
        db.execute(
            """UPDATE services SET
                name=?, description=?, type=?, entrypoint=?,
                log_location=?, settings_file=?, version=?,
                status=CASE status WHEN 'missing' THEN 'stopped' ELSE status END,
                last_seen=?
               WHERE path=?""",
            (
                manifest["name"],
                manifest.get("description", ""),
                manifest.get("type", "custom"),
                manifest.get("entrypoint", "run.sh"),
                manifest.get("log_location", f"/var/log/onryo/{manifest['name'].lower().replace(' ','-')}.log"),
                manifest.get("settings_file", ""),
                manifest.get("version", ""),
                now,
                path,
            ),
        )
        logger.info("Updated service: %s (%s)", manifest["name"], path)
    else:
        enabled = 1 if manifest.get("enabled_by_default", False) else 0
        db.execute(
            """INSERT INTO services
               (name, description, type, path, entrypoint, log_location,
                settings_file, version, enabled, status, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,'stopped',?)""",
            (
                manifest["name"],
                manifest.get("description", ""),
                manifest.get("type", "custom"),
                path,
                manifest.get("entrypoint", "run.sh"),
                manifest.get("log_location", f"/var/log/onryo/{manifest['name'].lower().replace(' ','-')}.log"),
                manifest.get("settings_file", ""),
                manifest.get("version", ""),
                enabled,
                now,
            ),
        )
        logger.info("Registered new service: %s (%s)", manifest["name"], path)
    log_event("scan", f"Synced service: {manifest['name']}")


def _mark_missing(db, known_paths: set[str]) -> None:
    rows = db.execute("SELECT id, path, name FROM services WHERE status != 'missing'").fetchall()
    for row in rows:
        if row["path"] not in known_paths:
            db.execute("UPDATE services SET status='missing' WHERE id=?", (row["id"],))
            logger.warning("Service directory gone – marked missing: %s", row["name"])
            log_event("scan", f"Marked missing: {row['name']}", row["id"])


def run_scan() -> int:
    """Run a full discovery scan. Returns count of discovered services."""
    watch_dirs = _load_watch_dirs()
    found_paths: set[str] = set()
    discovered = 0

    with get_db() as db:
        for watch_dir in watch_dirs:
            base = Path(watch_dir)
            if not base.is_dir():
                logger.warning("Watch directory does not exist: %s", watch_dir)
                continue
            for candidate in sorted(base.iterdir()):
                if not candidate.is_dir():
                    continue
                manifest_path = candidate / "info.json"
                if not manifest_path.exists():
                    logger.debug("No info.json in %s – skipping", candidate)
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text())
                except json.JSONDecodeError as exc:
                    logger.error("Invalid JSON in %s: %s", manifest_path, exc)
                    continue

                errors = _validate_manifest(manifest)
                if errors:
                    logger.error("Invalid manifest in %s: %s", manifest_path, "; ".join(errors))
                    continue

                svc_path = str(candidate)
                found_paths.add(svc_path)
                _upsert_service(db, svc_path, manifest)
                discovered += 1

        _mark_missing(db, found_paths)

    logger.info("Scan complete: %d service(s) discovered", discovered)
    return discovered


if __name__ == "__main__":
    count = run_scan()
    print(f"Scan complete: {count} service(s) discovered")
