"""Erinnerungen, Wochenstatistik, Migration, Nutzer entfernen, Sicherung."""
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from werkstudent.modelle import Job, ProcessedJob
from werkstudent.speicher.registry import Registry
from werkstudent.speicher.sicherung import create_backup, prune_backups
from werkstudent.speicher.store import Store

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.init()
    return s


def _save(store, i=1, status="reported", source="stepstone"):
    job = Job(source=source, source_id=str(i), title=f"Werkstudent Cloud {i}", company="F", location="D", url=f"u{i}")
    p = ProcessedJob(job=job, kind="werkstudent", categories=["cloud"], distance_km=1, score=7, is_top=True,
                     dedupe_key=f"k{i}")
    return store.save_job(p, job, status)


# --- Erinnerungen ------------------------------------------------------------------------


def test_reminder_due_three_days_after_bookmark(store):
    jid = _save(store)
    store.bookmark(jid, now=NOW)
    assert store.due_reminders(NOW + timedelta(days=2)) == []
    assert [i for i, _ in store.due_reminders(NOW + timedelta(days=3, minutes=1))] == [jid]


def test_reminder_sent_once_then_snooze_and_applied(store):
    jid = _save(store)
    store.bookmark(jid, now=NOW)
    later = NOW + timedelta(days=4)
    store.reminder_sent(jid)
    assert store.due_reminders(later) == []
    store.snooze(jid, later)
    assert [i for i, _ in store.due_reminders(later + timedelta(days=3, minutes=1))] == [jid]
    store.mark_applied(jid, later)
    assert store.due_reminders(later + timedelta(days=30)) == []
    (_, _, _, applied_at), = store.bookmarks_with_ids()
    assert applied_at == later


def test_old_database_gets_new_bookmark_columns(tmp_path):
    path = tmp_path / "alt.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE bookmarks (job_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL)")
    db.execute("INSERT INTO bookmarks VALUES (1, ?)", (NOW.isoformat(),))
    db.commit()
    db.close()
    s = Store(str(path))
    s.init()
    cols = {r[1] for r in s._db.execute("PRAGMA table_info(bookmarks)")}
    assert {"remind_after", "applied_at"} <= cols
    assert s.due_reminders(NOW + timedelta(days=30)) == []  # alte Einträge erinnern nicht plötzlich


# --- Wochenstatistik -----------------------------------------------------------------------


def test_week_stats(store):
    for i in range(3):
        _save(store, i, "reported", "stepstone")
    _save(store, 10, "digest", "indeed")
    _save(store, 11, "rejected", "indeed")
    a = _save(store, 12, "reported", "linkedin")
    store.bookmark(a, now=NOW)
    store.mark_applied(a, datetime.now(UTC))
    stats = store.week_stats(datetime.now(UTC) - timedelta(days=7))
    assert stats["neu"] == 5
    assert stats["quellen"] == {"stepstone": 3, "indeed": 1, "linkedin": 1}
    assert stats["gemerkt_offen"] == 0 and stats["beworben"] == 1


# --- Nutzerliste ------------------------------------------------------------------------------


def test_registry_names_and_remove():
    r = Registry(":memory:", admin_id=1000)
    r.init()
    code = r.create_invite(NOW)
    assert r.redeem(code, 2000, NOW, name="Lena")
    assert r.users_with_names() == [(1000, None), (2000, "Lena")]
    assert r.remove(2000) is True
    assert not r.is_user(2000)
    assert r.remove(1000) is False and r.is_user(1000)  # Admin kann nicht entfernt werden


def test_registry_old_users_table_gets_name_column(tmp_path):
    path = tmp_path / "registry.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, added_at TEXT NOT NULL)")
    db.execute("INSERT INTO users VALUES (2000, ?)", (NOW.isoformat(),))
    db.commit()
    db.close()
    r = Registry(str(path), admin_id=1000)
    r.init()
    assert (2000, None) in r.users_with_names()


def test_registry_meta():
    r = Registry(":memory:", admin_id=1000)
    r.init()
    assert r.get_meta("last_backup") is None
    r.set_meta("last_backup", "2026-11-03")
    assert r.get_meta("last_backup") == "2026-11-03"


# --- Sicherung ----------------------------------------------------------------------------------


def _db(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE t (v TEXT)")
    db.execute("INSERT INTO t VALUES (?)", (value,))
    db.commit()
    db.close()


def test_create_backup_copies_all_databases(tmp_path):
    _db(tmp_path / "jobs.db", "admin")
    _db(tmp_path / "registry.db", "reg")
    _db(tmp_path / "users" / "2000.db", "lena")
    dest = create_backup(tmp_path, date(2026, 11, 3))
    assert dest == tmp_path / "backup" / "2026-11-03"
    copy = sqlite3.connect(dest / "users" / "2000.db")
    assert copy.execute("SELECT v FROM t").fetchone() == ("lena",)
    assert (dest / "jobs.db").exists() and (dest / "registry.db").exists()


def test_prune_keeps_seven_newest_and_other_files(tmp_path):
    for d in range(1, 11):
        (tmp_path / "backup" / f"2026-11-{d:02d}").mkdir(parents=True)
    manual = tmp_path / "backup" / "jobs-20261103-2045.db"
    manual.write_text("x")
    prune_backups(tmp_path, keep=7)
    left = sorted(p.name for p in (tmp_path / "backup").iterdir())
    assert left == [f"2026-11-{d:02d}" for d in range(4, 11)] + ["jobs-20261103-2045.db"]



# --- abgelaufene Stellen ----------------------------------------------------------------------


def test_expired_only_when_source_kept_working(store):
    jid = _save(store, 1)
    store.touch_seen("stepstone", "1", NOW)
    later = NOW + timedelta(days=4)
    assert store.expired_ids([jid], later) == set()  # Quelle lief seitdem nicht → keine Aussage
    store.record_source_result("stepstone", ok=True, count=10, now=later)
    assert store.expired_ids([jid], later) == {jid}
    store.touch_seen("stepstone", "1", later)  # wieder gesehen
    assert store.expired_ids([jid], later) == set()


def test_recently_seen_is_not_expired(store):
    jid = _save(store, 1)
    store.touch_seen("stepstone", "1", NOW)
    store.record_source_result("stepstone", ok=True, count=10, now=NOW + timedelta(days=2))
    assert store.expired_ids([jid], NOW + timedelta(days=2)) == set()


def test_old_database_gets_last_seen_column(tmp_path):
    path = tmp_path / "alt.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, dedupe_key TEXT, source TEXT NOT NULL, "
               "source_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT, created_at TEXT NOT NULL)")
    db.commit()
    db.close()
    s = Store(str(path))
    s.init()
    assert "last_seen" in {r[1] for r in s._db.execute("PRAGMA table_info(jobs)")}


def test_reminder_still_due_for_job_missing_from_search(store):
    jid = _save(store, 1)
    store.bookmark(jid, now=NOW)
    store.touch_seen("stepstone", "1", NOW)
    later = NOW + timedelta(days=5)
    store.record_source_result("stepstone", ok=True, count=10, now=later)
    assert [i for i, _ in store.due_reminders(later)] == [jid]  # Suche reicht nur 7–14 Tage zurück
