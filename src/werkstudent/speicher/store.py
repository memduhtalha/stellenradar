"""SQLite-Speicher für Stellen, Einstellungen und Quellenstatus."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from werkstudent.modelle import Job, ProcessedJob, UserSettings
from werkstudent.verarbeitung.duplikate import normalize_company

REMIND_AFTER = timedelta(days=3)
EXPIRED_AFTER = timedelta(days=3)

JobStatus = Literal["reported", "silent", "digest", "held", "rejected", "unsent", "dismissed", "review", "review_sent"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    data TEXT,
    created_at TEXT NOT NULL,
    last_seen TEXT
);
CREATE INDEX IF NOT EXISTS jobs_dedupe ON jobs(dedupe_key);
CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source, source_id);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS also_on (
    dedupe_key TEXT NOT NULL, source TEXT NOT NULL, url TEXT NOT NULL,
    PRIMARY KEY (dedupe_key, source)
);
CREATE TABLE IF NOT EXISTS bookmarks (
    job_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, remind_after TEXT, applied_at TEXT
);
CREATE TABLE IF NOT EXISTS disliked_companies (company TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_state (
    name TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    warned INTEGER NOT NULL DEFAULT 0,
    last_ok_at TEXT,
    last_ok_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_feedback (
    job_id INTEGER NOT NULL, verdict TEXT NOT NULL, reason TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geocache (place TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL);
"""


@dataclass
class SourceState:
    consecutive_failures: int = 0
    warned: bool = False
    last_ok_at: datetime | None = None
    last_ok_count: int = 0


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _pj_to_json(p: ProcessedJob) -> str:
    d = asdict(p)
    d["job"]["posted_at"] = p.job.posted_at.isoformat() if p.job.posted_at else None
    d.pop("also_on")  # liegt in eigener Tabelle
    return json.dumps(d, ensure_ascii=False)


def _pj_from_json(raw: str) -> ProcessedJob:
    d = json.loads(raw)
    job = d.pop("job")
    job["posted_at"] = _dt(job["posted_at"])
    return ProcessedJob(job=Job(**job), **d)


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row

    def init(self) -> None:
        self._db.executescript(_SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        """Ältere Datenbanken um neue Spalten ergänzen (bestehende Einträge bleiben, wie sie sind)."""
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(bookmarks)")}
        for col in ("remind_after", "applied_at"):
            if col not in cols:
                self._db.execute(f"ALTER TABLE bookmarks ADD COLUMN {col} TEXT")
        if "last_seen" not in {r[1] for r in self._db.execute("PRAGMA table_info(jobs)")}:
            # Bestand gilt beim Umstellen als „jetzt online“ – sonst wäre alles sofort „abgelaufen“
            self._db.execute("ALTER TABLE jobs ADD COLUMN last_seen TEXT")
            self._db.execute("UPDATE jobs SET last_seen = ?", (datetime.now(UTC).isoformat(),))

    # --- Stellen -----------------------------------------------------------

    def is_known(self, dedupe_key: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM jobs WHERE dedupe_key = ? AND status != 'rejected' LIMIT 1", (dedupe_key,)
        ).fetchone()
        return row is not None

    def is_seen_source_id(self, source: str, source_id: str) -> bool:
        """Dieselbe Anzeige schon einmal verarbeitet (auch wenn der Titel inzwischen geändert wurde)."""
        row = self._db.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND source_id = ? AND status != 'rejected' LIMIT 1",
            (source, source_id),
        ).fetchone()
        return row is not None

    def source_of(self, dedupe_key: str) -> str | None:
        row = self._db.execute(
            "SELECT source FROM jobs WHERE dedupe_key = ? AND status != 'rejected' ORDER BY id LIMIT 1", (dedupe_key,)
        ).fetchone()
        return row["source"] if row else None

    def find_job(self, source: str, source_id: str) -> tuple[int, str] | None:
        """(Job-ID, Status) einer schon verarbeiteten Anzeige – unpassende (rejected) zählen nicht."""
        row = self._db.execute(
            "SELECT id, status FROM jobs WHERE source = ? AND source_id = ? AND status != 'rejected' "
            "AND data IS NOT NULL ORDER BY id LIMIT 1",
            (source, source_id),
        ).fetchone()
        return (row["id"], row["status"]) if row else None

    def find_by_key(self, dedupe_key: str) -> tuple[int, str] | None:
        row = self._db.execute(
            "SELECT id, status FROM jobs WHERE dedupe_key = ? AND status != 'rejected' AND data IS NOT NULL "
            "ORDER BY id LIMIT 1",
            (dedupe_key,),
        ).fetchone()
        return (row["id"], row["status"]) if row else None

    def is_rejected(self, source: str, source_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND source_id = ? AND status = 'rejected' LIMIT 1",
            (source, source_id),
        ).fetchone()
        return row is not None

    def save_job(self, p: ProcessedJob | None, job: Job, status: JobStatus) -> int:
        cur = self._db.execute(
            "INSERT INTO jobs (dedupe_key, source, source_id, status, data, created_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                p.dedupe_key if p else None,
                job.source,
                job.source_id,
                status,
                _pj_to_json(p) if p else None,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def add_also_on(self, dedupe_key: str, source: str, url: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO also_on (dedupe_key, source, url) VALUES (?, ?, ?)", (dedupe_key, source, url)
        )
        self._db.commit()

    def _also_on(self, dedupe_key: str) -> list[tuple[str, str]]:
        rows = self._db.execute(
            "SELECT source, url FROM also_on WHERE dedupe_key = ? ORDER BY rowid", (dedupe_key,)
        ).fetchall()
        return [(r["source"], r["url"]) for r in rows]

    def _load(self, row: sqlite3.Row) -> ProcessedJob:
        p = _pj_from_json(row["data"])
        p.also_on = self._also_on(p.dedupe_key)
        return p

    def jobs_with_status(self, status: JobStatus) -> list[tuple[int, ProcessedJob]]:
        rows = self._db.execute(
            "SELECT id, data FROM jobs WHERE status = ? AND data IS NOT NULL ORDER BY id", (status,)
        ).fetchall()
        return [(r["id"], self._load(r)) for r in rows]

    def set_status(self, job_ids: list[int], status: JobStatus) -> None:
        self._db.executemany("UPDATE jobs SET status = ? WHERE id = ?", [(status, i) for i in job_ids])
        self._db.commit()

    # --- zuletzt online gesehen ------------------------------------------------------------

    def touch_seen(self, source: str, source_id: str, now: datetime) -> None:
        self._db.execute(
            "UPDATE jobs SET last_seen = ? WHERE source = ? AND source_id = ? AND status != 'rejected'",
            (now.isoformat(), source, source_id),
        )
        self._db.commit()

    def touch_job(self, job_id: int, now: datetime) -> None:
        self._db.execute("UPDATE jobs SET last_seen = ? WHERE id = ?", (now.isoformat(), job_id))
        self._db.commit()

    def last_seen(self, job_id: int) -> datetime | None:
        row = self._db.execute("SELECT last_seen, created_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _dt(row["last_seen"] or row["created_at"]) if row else None

    def expired_ids(self, job_ids: list[int], now: datetime) -> set[int]:
        """Nicht mehr in den Suchergebnissen: seit EXPIRED_AFTER nicht gesehen, obwohl die Quelle danach noch
        mindestens einen Tag funktioniert hat. Nur ein Hinweis – die Portale suchen meist nur 7–14 Tage zurück,
        die Anzeige kann also noch online sein."""
        expired: set[int] = set()
        states = self.all_source_states()
        for job_id in job_ids:
            row = self._db.execute("SELECT source FROM jobs WHERE id = ?", (job_id,)).fetchone()
            seen = self.last_seen(job_id)
            if row is None or seen is None or now - seen < EXPIRED_AFTER:
                continue
            st = states.get(row["source"])
            if st and st.last_ok_at and st.last_ok_at - seen >= timedelta(days=1):
                expired.add(job_id)
        return expired

    def count_status(self, *statuses: str) -> int:
        marks = ",".join("?" * len(statuses))
        return self._db.execute(f"SELECT COUNT(*) FROM jobs WHERE status IN ({marks})", statuses).fetchone()[0]

    def expire_reviews(self, before: datetime) -> None:
        """Alte, nie entschiedene „Zum Prüfen“-Stellen ausräumen."""
        self._db.execute(
            "UPDATE jobs SET status = 'dismissed' WHERE status IN ('review', 'review_sent') AND created_at < ?",
            (before.isoformat(),),
        )
        self._db.commit()

    def get_status(self, job_id: int) -> str | None:
        row = self._db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row["status"] if row else None

    def record_review_feedback(self, job_id: int, verdict: str, reason: str | None) -> None:
        self._db.execute(
            "INSERT INTO review_feedback (job_id, verdict, reason, at) VALUES (?, ?, ?, ?)",
            (job_id, verdict, reason, datetime.now(UTC).isoformat()),
        )
        self._db.commit()

    def review_feedback(self) -> list[tuple[int, str, str | None]]:
        rows = self._db.execute("SELECT job_id, verdict, reason FROM review_feedback ORDER BY rowid").fetchall()
        return [(r["job_id"], r["verdict"], r["reason"]) for r in rows]

    def get_job(self, job_id: int) -> ProcessedJob | None:
        row = self._db.execute("SELECT data FROM jobs WHERE id = ? AND data IS NOT NULL", (job_id,)).fetchone()
        return self._load(row) if row else None

    # --- Merkliste & Ausblenden ---------------------------------------------

    def bookmark(self, job_id: int, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self._db.execute(
            "INSERT OR IGNORE INTO bookmarks (job_id, created_at, remind_after) VALUES (?, ?, ?)",
            (job_id, now.isoformat(), (now + REMIND_AFTER).isoformat()),
        )
        self._db.commit()

    def due_reminders(self, now: datetime) -> list[tuple[int, ProcessedJob]]:
        """Gemerkte, noch nicht beworbene Stellen, bei denen eine Erinnerung fällig ist."""
        rows = self._db.execute(
            "SELECT j.id, j.data, b.remind_after FROM bookmarks b JOIN jobs j ON j.id = b.job_id "
            "WHERE b.applied_at IS NULL AND b.remind_after IS NOT NULL ORDER BY b.rowid"
        ).fetchall()
        return [(r["id"], self._load(r)) for r in rows if datetime.fromisoformat(r["remind_after"]) <= now]

    def reminder_sent(self, job_id: int) -> None:
        self._db.execute("UPDATE bookmarks SET remind_after = NULL WHERE job_id = ?", (job_id,))
        self._db.commit()

    def snooze(self, job_id: int, now: datetime) -> None:
        self._db.execute(
            "UPDATE bookmarks SET remind_after = ? WHERE job_id = ?", ((now + REMIND_AFTER).isoformat(), job_id)
        )
        self._db.commit()

    def mark_applied(self, job_id: int, now: datetime) -> None:
        self._db.execute(
            "UPDATE bookmarks SET applied_at = ?, remind_after = NULL WHERE job_id = ?", (now.isoformat(), job_id)
        )
        self._db.commit()

    def week_stats(self, since: datetime) -> dict:
        rows = self._db.execute(
            "SELECT source, COUNT(*) AS n FROM jobs WHERE status IN ('reported', 'digest', 'silent', 'held', 'unsent') "
            "AND data IS NOT NULL AND created_at >= ? GROUP BY source ORDER BY n DESC",
            (since.isoformat(),),
        ).fetchall()
        quellen = {r["source"]: r["n"] for r in rows}
        open_ = self._db.execute("SELECT COUNT(*) FROM bookmarks WHERE applied_at IS NULL").fetchone()[0]
        applied = self._db.execute(
            "SELECT COUNT(*) FROM bookmarks WHERE applied_at >= ?", (since.isoformat(),)
        ).fetchone()[0]
        return {"neu": sum(quellen.values()), "quellen": quellen, "gemerkt_offen": open_, "beworben": applied}

    def unbookmark(self, job_id: int) -> None:
        self._db.execute("DELETE FROM bookmarks WHERE job_id = ?", (job_id,))
        self._db.commit()

    def is_bookmarked(self, job_id: int) -> bool:
        return self._db.execute("SELECT 1 FROM bookmarks WHERE job_id = ?", (job_id,)).fetchone() is not None

    def bookmarks_with_ids(self) -> list[tuple[int, ProcessedJob, datetime, datetime | None]]:
        """Gemerkte Stellen, die zuletzt gemerkte zuerst: (Job-ID, Stelle, gemerkt am, beworben am)."""
        rows = self._db.execute(
            "SELECT j.id, j.data, b.created_at, b.applied_at FROM bookmarks b JOIN jobs j ON j.id = b.job_id "
            "ORDER BY b.rowid DESC"
        ).fetchall()
        return [
            (r["id"], self._load(r), datetime.fromisoformat(r["created_at"]), _dt(r["applied_at"])) for r in rows
        ]

    def bookmarks(self) -> list[ProcessedJob]:
        rows = self._db.execute(
            "SELECT j.data FROM bookmarks b JOIN jobs j ON j.id = b.job_id ORDER BY b.created_at DESC"
        ).fetchall()
        return [self._load(r) for r in rows]

    def dismiss(self, job_id: int) -> None:
        p = self.get_job(job_id)
        if p is None:
            return
        self._db.execute("DELETE FROM bookmarks WHERE job_id = ?", (job_id,))
        self._db.execute("UPDATE jobs SET status = 'dismissed' WHERE id = ?", (job_id,))
        self._db.execute(
            "INSERT OR IGNORE INTO disliked_companies (company) VALUES (?)", (normalize_company(p.job.company),)
        )
        self._db.commit()

    def disliked_companies(self) -> set[str]:
        return {r["company"] for r in self._db.execute("SELECT company FROM disliked_companies")}

    # --- Einstellungen -------------------------------------------------------

    def load_settings(self) -> UserSettings:
        row = self._db.execute("SELECT data FROM settings WHERE id = 1").fetchone()
        if row is None:
            return UserSettings()
        d = json.loads(row["data"])
        known = {f.name for f in fields(UserSettings)}  # alte/neue Felder tolerieren
        d = {k: v for k, v in d.items() if k in known}
        if "categories" in d:
            d["categories"] = set(d["categories"])
        return UserSettings(**d)

    def save_settings(self, s: UserSettings) -> None:
        d = asdict(s)
        d["categories"] = sorted(s.categories)
        self._db.execute(
            "INSERT INTO settings (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (json.dumps(d, ensure_ascii=False),),
        )
        self._db.commit()

    # --- Quellenstatus -------------------------------------------------------

    def _source_state(self, name: str) -> SourceState:
        row = self._db.execute("SELECT * FROM source_state WHERE name = ?", (name,)).fetchone()
        if row is None:
            return SourceState()
        return SourceState(
            consecutive_failures=row["consecutive_failures"],
            warned=bool(row["warned"]),
            last_ok_at=_dt(row["last_ok_at"]),
            last_ok_count=row["last_ok_count"],
        )

    def _put_source_state(self, name: str, st: SourceState) -> None:
        self._db.execute(
            """INSERT INTO source_state (name, consecutive_failures, warned, last_ok_at, last_ok_count)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET consecutive_failures = excluded.consecutive_failures,
                 warned = excluded.warned, last_ok_at = excluded.last_ok_at, last_ok_count = excluded.last_ok_count""",
            (
                name,
                st.consecutive_failures,
                int(st.warned),
                st.last_ok_at.isoformat() if st.last_ok_at else None,
                st.last_ok_count,
            ),
        )
        self._db.commit()

    def record_source_result(self, name: str, ok: bool, count: int, now: datetime) -> SourceState:
        st = self._source_state(name)
        if ok:
            st = SourceState(consecutive_failures=0, warned=False, last_ok_at=now, last_ok_count=count)
        else:
            st.consecutive_failures += 1
        self._put_source_state(name, st)
        return st

    def set_warned(self, name: str, warned: bool) -> None:
        st = self._source_state(name)
        st.warned = warned
        self._put_source_state(name, st)

    def all_source_states(self) -> dict[str, SourceState]:
        names = [r["name"] for r in self._db.execute("SELECT name FROM source_state ORDER BY name")]
        return {n: self._source_state(n) for n in names}

    # --- Meta ----------------------------------------------------------------

    def last_successful_run(self) -> datetime | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = 'last_successful_run'").fetchone()
        return _dt(row["value"]) if row else None

    def set_last_successful_run(self, t: datetime) -> None:
        self._db.execute(
            "INSERT INTO meta (key, value) VALUES ('last_successful_run', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (t.isoformat(),),
        )
        self._db.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._db.commit()

    def last_digest_date(self) -> date | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = 'last_digest_date'").fetchone()
        return date.fromisoformat(row["value"]) if row else None

    def set_last_digest_date(self, d: date) -> None:
        self._db.execute(
            "INSERT INTO meta (key, value) VALUES ('last_digest_date', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (d.isoformat(),),
        )
        self._db.commit()

    # --- Geocache --------------------------------------------------------------

    def geocache_get(self, place: str) -> tuple[float, float] | None:
        row = self._db.execute("SELECT lat, lon FROM geocache WHERE place = ?", (place,)).fetchone()
        return (row["lat"], row["lon"]) if row else None

    def geocache_put(self, place: str, lat: float, lon: float) -> None:
        self._db.execute("INSERT OR REPLACE INTO geocache (place, lat, lon) VALUES (?, ?, ?)", (place, lat, lon))
        self._db.commit()
