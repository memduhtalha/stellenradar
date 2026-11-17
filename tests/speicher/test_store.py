from datetime import UTC, datetime, timedelta

import pytest

from werkstudent.modelle import Job, ProcessedJob
from werkstudent.speicher.store import Store

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.init()
    return s


def _pj(key="k1", company="Beispiel GmbH", source_id="1"):
    job = Job(source="stepstone", source_id=source_id, title="Werkstudent Cloud", company=company,
              location="Düsseldorf", url="https://x/1", posted_at=NOW - timedelta(hours=2))
    return ProcessedJob(job=job, kind="werkstudent", categories=["cloud"], distance_km=3.0,
                        score=8, is_top=True, dedupe_key=key)


def test_settings_roundtrip(store):
    s = store.load_settings()
    assert s.radius_km == 25 and s.categories == {"cloud", "ki", "security"}
    s.radius_km = 40
    s.categories = {"cloud"}
    store.save_settings(s)
    loaded = store.load_settings()
    assert loaded.radius_km == 40 and loaded.categories == {"cloud"}


def test_save_and_is_known(store):
    p = _pj()
    store.save_job(p, p.job, "reported")
    assert store.is_known("k1")
    assert not store.is_known("other")


def test_get_job_roundtrip_keeps_datetime(store):
    p = _pj()
    jid = store.save_job(p, p.job, "reported")
    got = store.get_job(jid)
    assert got.job.posted_at == p.job.posted_at and got.categories == ["cloud"]


def test_rejected_is_remembered_without_processed(store):
    job = Job(source="indeed", source_id="x1", title="t", company="c", location="l", url="u")
    store.save_job(None, job, "rejected")
    assert store.is_rejected("indeed", "x1")
    assert not store.is_rejected("indeed", "x2")


def test_status_transitions(store):
    id1 = store.save_job(_pj("a", source_id="1"), _pj().job, "held")
    store.save_job(_pj("b", source_id="2"), _pj().job, "held")
    assert len(store.jobs_with_status("held")) == 2
    store.set_status([id1], "reported")
    assert [i for i, _ in store.jobs_with_status("held")] != [id1]
    assert len(store.jobs_with_status("held")) == 1


def test_also_on_is_returned_with_job(store):
    p = _pj()
    jid = store.save_job(p, p.job, "reported")
    store.add_also_on("k1", "indeed", "https://indeed/1")
    assert store.get_job(jid).also_on == [("indeed", "https://indeed/1")]


def test_dismiss_adds_company(store):
    p = _pj()
    jid = store.save_job(p, p.job, "reported")
    store.dismiss(jid)
    assert "beispiel" in store.disliked_companies()


def test_bookmarks(store):
    p = _pj()
    jid = store.save_job(p, p.job, "reported")
    store.bookmark(jid)
    store.bookmark(jid)
    assert [b.dedupe_key for b in store.bookmarks()] == ["k1"]


def test_source_failures_count_and_reset(store):
    for _ in range(3):
        st = store.record_source_result("indeed", ok=False, count=0, now=NOW)
    assert st.consecutive_failures == 3
    store.set_warned("indeed", True)
    st = store.record_source_result("indeed", ok=True, count=12, now=NOW)
    assert st.consecutive_failures == 0 and st.last_ok_count == 12 and st.warned is False
    assert store.all_source_states()["indeed"].last_ok_at == NOW


def test_last_successful_run(store):
    assert store.last_successful_run() is None
    store.set_last_successful_run(NOW)
    assert store.last_successful_run() == NOW


def test_unbookmark_and_is_bookmarked(store):
    p = _pj()
    jid = store.save_job(p, p.job, "reported")
    assert not store.is_bookmarked(jid)
    store.bookmark(jid)
    assert store.is_bookmarked(jid)
    store.unbookmark(jid)
    assert not store.is_bookmarked(jid) and store.bookmarks() == []


def test_settings_ignore_unknown_and_fill_new_fields(store):
    store._db.execute("INSERT INTO settings (id, data) VALUES (1, ?)",
                      ('{"radius_km": 40, "categories": ["cloud"], "veraltetes_feld": 1}',))
    s = store.load_settings()
    assert s.radius_km == 40 and s.digest_hour == 18


def test_last_digest_date(store):
    from datetime import date
    assert store.last_digest_date() is None
    store.set_last_digest_date(date(2026, 11, 3))
    assert store.last_digest_date() == date(2026, 11, 3)


def test_bookmarks_with_ids_newest_first(store):
    a = store.save_job(_pj("a", source_id="1"), _pj().job, "reported")
    b = store.save_job(_pj("b", source_id="2"), _pj().job, "reported")
    store.bookmark(a)
    store.bookmark(b)
    rows = store.bookmarks_with_ids()
    assert [r[0] for r in rows] == [b, a]
    assert rows[0][2] is not None  # Zeitpunkt des Merkens
