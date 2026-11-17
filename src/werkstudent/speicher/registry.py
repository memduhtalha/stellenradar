"""Wer den Bot nutzen darf – und Einladungen. Alles andere liegt in einer eigenen Datenbank pro Person."""
from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

INVITE_VALID = timedelta(hours=24)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, added_at TEXT NOT NULL, name TEXT);
CREATE TABLE IF NOT EXISTS invites (code TEXT PRIMARY KEY, expires_at TEXT NOT NULL, used_by INTEGER);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Registry:
    def __init__(self, path: str, admin_id: int):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self.admin_id = admin_id

    def init(self) -> None:
        self._db.executescript(_SCHEMA)
        if "name" not in {r[1] for r in self._db.execute("PRAGMA table_info(users)")}:
            self._db.execute("ALTER TABLE users ADD COLUMN name TEXT")
        self._add(self.admin_id, datetime.now(UTC))

    def _add(self, user_id: int, now: datetime, name: str | None = None) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO users (user_id, added_at, name) VALUES (?, ?, ?)", (user_id, now.isoformat(), name)
        )
        self._db.commit()

    def users_with_names(self) -> list[tuple[int, str | None]]:
        rows = self._db.execute(  # Admin zuerst
            "SELECT user_id, name FROM users ORDER BY user_id != ?, added_at, user_id", (self.admin_id,)
        )
        return [(r[0], r[1]) for r in rows]

    def remove(self, user_id: int) -> bool:
        """Entzieht den Zugang. Der Admin kann nicht entfernt werden; die Daten der Person bleiben liegen."""
        if user_id == self.admin_id:
            return False
        self._db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self._db.commit()
        return True

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._db.commit()

    def users(self) -> list[int]:
        return [uid for uid, _ in self.users_with_names()]

    def is_user(self, user_id: int) -> bool:
        return self._db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is not None

    def create_invite(self, now: datetime) -> str:
        code = secrets.token_urlsafe(9)  # nur Zeichen, die in einem t.me-Startlink erlaubt sind
        self._db.execute(
            "INSERT INTO invites (code, expires_at) VALUES (?, ?)", (code, (now + INVITE_VALID).isoformat())
        )
        self._db.commit()
        return code

    def redeem(self, code: str, user_id: int, now: datetime, name: str | None = None) -> bool:
        """Löst eine Einladung ein. Wer schon Nutzer ist, verbraucht den Code nicht."""
        if self.is_user(user_id):
            return True
        row = self._db.execute("SELECT expires_at, used_by FROM invites WHERE code = ?", (code,)).fetchone()
        if row is None or row[1] is not None or now > datetime.fromisoformat(row[0]):
            return False
        self._db.execute("UPDATE invites SET used_by = ? WHERE code = ?", (user_id, code))
        self._add(user_id, now, name)
        return True
