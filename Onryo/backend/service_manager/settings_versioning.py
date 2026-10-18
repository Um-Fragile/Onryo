"""
Onryo – Settings file versioning helper.

Provides:
  backup_settings(path, max_versions=10)  -- copies current file to path.bak.N
  save_settings(path, content, validator=None, max_versions=10)
      -- validates new content, backs up old file, writes new file atomically
"""

from __future__ import annotations

import re
import shutil
import tempfile
import json
from pathlib import Path
from typing import Callable, Optional

import yaml  # pyyaml


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def backup_settings(path: Path, max_versions: int = 10) -> Optional[Path]:
    """Copy *path* to path.bak.<N> (incrementing) and prune old backups.
    Returns the backup path, or None if original did not exist."""
    path = Path(path)
    if not path.exists():
        return None

    # Find next backup number
    existing = sorted(
        path.parent.glob(f"{path.name}.bak.*"),
        key=_backup_number,
    )
    next_n = (_backup_number(existing[-1]) + 1) if existing else 1
    backup_path = path.with_suffix(path.suffix + f".bak.{next_n}")
    shutil.copy2(path, backup_path)

    # Prune old backups, keeping last max_versions
    all_backups = sorted(
        path.parent.glob(f"{path.name}.bak.*"),
        key=_backup_number,
    )
    for old in all_backups[:-max_versions]:
        old.unlink(missing_ok=True)

    return backup_path


def save_settings(
    path: Path,
    content: str,
    *,
    max_versions: int = 10,
    extra_validator: Optional[Callable[[str], None]] = None,
) -> None:
    """Validate *content* parses, back up the old file, then write atomically.

    Raises:
        ValueError – if the content doesn't parse as YAML/JSON or
                     *extra_validator* raises.
    """
    path = Path(path)
    _validate_content(path, content)
    if extra_validator is not None:
        extra_validator(content)

    backup_settings(path, max_versions=max_versions)

    # Atomic write via tmp + rename (same filesystem)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.tmp.",
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(content)
        tmp.flush()
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def list_backups(path: Path) -> list[Path]:
    """Return backup files sorted oldest → newest."""
    path = Path(path)
    return sorted(
        path.parent.glob(f"{path.name}.bak.*"),
        key=_backup_number,
    )


def restore_backup(path: Path, version: int) -> None:
    """Overwrite *path* with a specific backup version."""
    backup = path.with_suffix(path.suffix + f".bak.{version}")
    if not backup.exists():
        raise FileNotFoundError(f"Backup not found: {backup}")
    backup_settings(path)  # back up current before restoring
    shutil.copy2(backup, path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backup_number(p: Path) -> int:
    """Extract the trailing integer from a .bak.N filename."""
    m = re.search(r"\.bak\.(\d+)$", p.name)
    return int(m.group(1)) if m else 0


def _validate_content(path: Path, content: str) -> None:
    """Try to parse *content* as YAML or JSON depending on the file suffix."""
    suffix = path.suffix.lower()
    try:
        if suffix in {".json"}:
            json.loads(content)
        elif suffix in {".yaml", ".yml", ".env", ""}:
            yaml.safe_load(content)
        else:
            # Attempt YAML first, then JSON
            try:
                yaml.safe_load(content)
            except yaml.YAMLError:
                json.loads(content)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ValueError(f"Settings file did not parse: {exc}") from exc
