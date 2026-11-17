"""Tägliche Sicherung aller Datenbanken nach data/backup/JJJJ-MM-TT/ – die letzten 7 Tage bleiben."""
from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import date
from pathlib import Path

KEEP_DAYS = 7
_DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _databases(data_dir: Path) -> list[Path]:
    files = [data_dir / "registry.db", data_dir / "jobs.db", *sorted((data_dir / "users").glob("*.db"))]
    return [f for f in files if f.is_file()]


def create_backup(data_dir: Path, day: date) -> Path:
    """Kopiert jede Datenbank über die SQLite-Backup-Funktion – sicher auch während der Bot schreibt."""
    dest = data_dir / "backup" / day.isoformat()
    for src in _databases(data_dir):
        target = dest / src.relative_to(data_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(src) as source, sqlite3.connect(target) as copy:
            source.backup(copy)
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def prune_backups(data_dir: Path, keep: int = KEEP_DAYS) -> None:
    """Löscht nur ältere Tagesordner – andere Dateien in data/backup/ bleiben unangetastet."""
    root = data_dir / "backup"
    if not root.is_dir():
        return
    days = sorted(p for p in root.iterdir() if p.is_dir() and _DAY_DIR.match(p.name))
    for old in days[:-keep] if keep else days:
        shutil.rmtree(old)
