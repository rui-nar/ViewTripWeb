"""Daily SQLite backup — create, list, restore, and prune backups."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_MAX_BACKUPS = 30


def _db_path() -> Path:
    db_url = os.environ.get("DATABASE_URL", "sqlite:///viewtripweb.db")
    if db_url.startswith("sqlite:///"):
        return Path(db_url[len("sqlite:///"):])
    if db_url.startswith("sqlite://"):
        return Path(db_url[len("sqlite://"):])
    raise ValueError(f"Unsupported DATABASE_URL scheme: {db_url}")


def _backup_dir() -> Path:
    d = _db_path().parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stem() -> str:
    return _db_path().stem


def backup_db() -> Path:
    """Copy the live DB into backups/<stem>_YYYY-MM-DD.db using SQLite's online backup API."""
    src = _db_path()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = _backup_dir() / f"{_stem()}_{date_str}.db"

    src_conn = sqlite3.connect(str(src))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    _prune_old_backups()
    return dest


def restore_db(date_str: str) -> None:
    """Restore the backup for *date_str* (YYYY-MM-DD) into the live DB.

    Uses SQLite's backup API so it is safe while the process is running.
    Disposes the SQLAlchemy pool so the next request gets a fresh connection.
    """
    backup_file = _backup_dir() / f"{_stem()}_{date_str}.db"
    if not backup_file.exists():
        raise FileNotFoundError(f"No backup found for {date_str}")

    live = _db_path()
    src_conn = sqlite3.connect(str(backup_file))
    try:
        dest_conn = sqlite3.connect(str(live))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    # Drop all pooled connections so the next request reads the restored state.
    from models.db import engine
    engine.dispose()


def list_backups() -> list[dict]:
    """Return backups sorted newest-first, each as {date, size_bytes}."""
    result = []
    prefix = f"{_stem()}_"
    try:
        for f in sorted(_backup_dir().iterdir(), reverse=True):
            if f.name.startswith(prefix) and f.suffix == ".db":
                date_str = f.stem[len(prefix):]
                result.append({"date": date_str, "size_bytes": f.stat().st_size})
    except FileNotFoundError:
        pass
    return result


def _prune_old_backups() -> None:
    prefix = f"{_stem()}_"
    files = sorted(
        [f for f in _backup_dir().iterdir() if f.name.startswith(prefix) and f.suffix == ".db"],
        reverse=True,
    )
    for old in files[_MAX_BACKUPS:]:
        old.unlink(missing_ok=True)
