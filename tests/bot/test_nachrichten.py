from datetime import UTC, datetime, timedelta
from pathlib import Path

from werkstudent.bot.nachrichten import format_backlog_intro, format_digest, format_job, format_status
from werkstudent.config import load_categories
from werkstudent.modelle import Job, ProcessedJob
from werkstudent.speicher.store import SourceState

CATS = {c.key: c for c in load_categories(Path("config/kategorien.yaml"))}
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def _pj(title="Werkstudent Cloud", company="Beispiel GmbH", url="https://www.stepstone.de/job/1",
        distance=3.2, hours=2, top=True, kind="werkstudent", remote=False, also_on=None):
    job = Job(source="stepstone", source_id="1", title=title, company=company, location="Düsseldorf", url=url,
              posted_at=NOW - timedelta(hours=hours) if hours is not None else None, remote=remote)
    return ProcessedJob(job=job, kind=kind, categories=["cloud"], distance_km=distance, score=10, is_top=top,
                        dedupe_key="k", also_on=also_on or [])


def _buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_format_top_job_layout():
    text, markup = format_job(7, _pj(also_on=[("indeed", "https://de.indeed.com/viewjob?jk=1")]), CATS, NOW)
    assert text.startswith("🔥 ☁️ Cloud &amp; DevOps")
    assert "<b>Werkstudent Cloud</b>" in text
    assert "(3 km)" in text
    assert "vor 2 Std." in text
    assert "Quelle: StepStone (auch auf: Indeed)" in text
    assert _buttons(markup) == ["bm:7", "dz:7"]


def test_format_non_top_has_no_fire():
    text, _ = format_job(1, _pj(top=False), CATS, NOW)
    assert text.startswith("☁️ Cloud &amp; DevOps")


def test_format_escapes_html():
    text, _ = format_job(1, _pj(company="A&B <Tech>", url="https://x.de/?a=1&b=2"), CATS, NOW)
    assert "A&amp;B &lt;Tech&gt;" in text
    assert 'href="https://x.de/?a=1&amp;b=2"' in text


def test_format_without_distance_and_date():
    text, _ = format_job(1, _pj(distance=None, hours=None), CATS, NOW)
    assert " km)" not in text and "📅" not in text


def test_format_days_old():
    text, _ = format_job(1, _pj(hours=50), CATS, NOW)
    assert "vor 2 Tagen" in text


def test_format_praktikum_and_remote_tags():
    text, _ = format_job(1, _pj(kind="praktikum", remote=True), CATS, NOW)
    assert "🎓 Praktikum/Abschlussarbeit" in text and "🏠 Remote" in text


def test_backlog_intro():
    assert format_backlog_intro(87) == "📦 Rückstau: 87 neue Stellen – hier die Top 10."


def test_digest_splits_over_4096():
    msgs = format_digest([_pj(title=f"Werkstudent Cloud Engineering Team Nummer {i}") for i in range(200)])
    assert len(msgs) > 1
    assert all(len(m) <= 4096 for m in msgs)
    assert "200" in msgs[0]


def test_digest_empty():
    assert format_digest([]) == []


def test_status_lists_sources():
    states = {"indeed": SourceState(consecutive_failures=2), "stepstone": SourceState(last_ok_at=NOW, last_ok_count=12)}
    text = format_status(states, {"indeed": "blockiert", "stepstone": 12}, NOW, NOW + timedelta(hours=1), paused=False)
    assert "StepStone" in text and "12" in text
    assert "Indeed" in text and "blockiert" in text


def test_format_job_bookmarked_button():
    _, markup = format_job(7, _pj(), CATS, NOW, bookmarked=True)
    assert [(b.text, b.callback_data) for b in markup.inline_keyboard[0]] == [("✅ Gemerkt", "ub:7"), ("👎 Uninteressant", "dz:7")]


def test_top_job_shows_excerpt_from_description():
    p = _pj()
    p.job.description = "Du baust mit uns Cloud-Infrastruktur auf Azure und automatisierst Deployments mit Terraform. " * 5
    text, _ = format_job(1, p, CATS, NOW)
    excerpt = next(line for line in text.split("\n") if line.startswith("<i>"))
    assert "Azure" in excerpt and excerpt.endswith("…</i>") and len(excerpt) < 260


def test_excerpt_falls_back_to_snippet_and_is_escaped():
    p = _pj()
    p.job.snippet = "Wir suchen Unterstützung für <Cloud> & DevOps im Team rund um unsere Plattform."
    text, _ = format_job(1, p, CATS, NOW)
    assert "<i>Wir suchen Unterstützung für &lt;Cloud&gt; &amp; DevOps" in text


def test_no_excerpt_for_non_top_or_short_text():
    p = _pj(top=False)
    p.job.description = "Lange Beschreibung " * 20
    assert "<i>" not in format_job(1, p, CATS, NOW)[0]
    q = _pj()
    q.job.snippet = "Homeoffice möglich"
    assert "<i>" not in format_job(1, q, CATS, NOW)[0]


def test_ausbildung_card_shows_start_and_deadline():
    p = _pj(kind="ausbildung")
    p.job.snippet = "Ausbildungsbeginn 1. August 2027 · Bewerbung bis 29.12.2026"
    text, _ = format_job(1, p, CATS, NOW)
    assert "🗓️ Beginn 1. August 2027" in text and "⏳ Bewerbung bis 29.12.2026" in text
