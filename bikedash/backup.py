"""Sicherung der lokalen Datenbank.

create_backup() erstellt eine konsistente Kopie (SQLite-Backup-API) unter
data/backups/. db_bytes() liefert die DB als Bytes für den Download-Button.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from . import config
from .config import DB_PATH

BACKUP_DIR = DB_PATH.parent / "backups"


def create_backup() -> Path:
    """Konsistente Kopie der DB nach data/backups/bikedash-<zeit>.db."""
    if config.is_cloud():
        raise RuntimeError(
            "Datei-Backup nur für die lokale SQLite. Die Cloud-DB (Neon) "
            "hat eigene automatische Backups."
        )
    if not DB_PATH.exists():
        raise FileNotFoundError("Es gibt noch keine Datenbank zum Sichern.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"bikedash-{stamp}.db"
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)  # atomar, auch bei offener DB sicher
        finally:
            dst.close()
    finally:
        src.close()
    return target


def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("bikedash-*.db"), reverse=True)


def prune_backups(keep: int = 14) -> int:
    """Behält die neuesten `keep` Backups, löscht ältere. Gibt Anzahl gelöscht."""
    backups = list_backups()
    removed = 0
    for old in backups[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def db_bytes() -> bytes:
    return DB_PATH.read_bytes() if DB_PATH.exists() else b""
