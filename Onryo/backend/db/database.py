"""
Onryo – database helpers.
Single SQLite file; this module is the only place that opens connections.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("ONRYO_DB", "/opt/onryo/onryo.db")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db(path: str = DB_PATH) -> None:
    """Create tables from schema.sql if they don't exist (idempotent)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA_PATH.read_text())
        con.commit()


@contextmanager
def get_db(path: str = DB_PATH):
    """Yield a connected sqlite3 connection with row_factory set."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def log_event(event_type: str, message: str, service_id: int | None = None) -> None:
    """Append one row to the activity_log table."""
    with get_db() as db:
        db.execute(
            "INSERT INTO activity_log (event_type, service_id, message) VALUES (?,?,?)",
            (event_type, service_id, message),
        )
