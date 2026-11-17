"""„Zum Prüfen“: tägliche Liste, /pruefen, ✅ Passt / ❌ Passt nicht."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from werkstudent.bot import pruefen
from werkstudent.bot.befehle import Deps, UserSpace
from werkstudent.bot.zeitplan import run_due
from werkstudent.config import load_categories
from werkstudent.lauf import RunResult
from werkstudent.modelle import Job, ProcessedJob
from werkstudent.speicher.registry import Registry
from werkstudent.speicher.store import Store

from .fakes import make_context, make_update

ME = 1000
CATS = load_categories(Path("config/kategorien.yaml"))
B = ZoneInfo("Europe/Berlin")


class IdleRunner:
    running = False

    async def run(self, now, force_backlog=False):
        return RunResult()


@pytest.fixture
def deps():
    reg = Registry(":memory:", admin_id=ME)
    reg.init()

    def space(uid):
        store = Store(":memory:")
        store.init()
        return UserSpace(user_id=uid, store=store, runner=IdleRunner(), geocoder=None)

    return Deps(registry=reg, categories=CATS, make_space=space)


def _review(store, i, reason="Werkstudent nicht bestätigt – Anzeige nicht prüfbar"):
    job = Job(source="indeed", source_id=str(i), title=f"Cloud Engineer {i} (m/w/d)", company=f"Firma {i}",
              location="Düsseldorf", url=f"https://x/{i}")
    p = ProcessedJob(job=job, kind="werkstudent", categories=["cloud"], distance_km=3, score=4, is_top=False,
                     dedupe_key=f"k{i}", review_reason=reason)
    return store.save_job(p, job, "review")


def _onboard(store):
    s = store.load_settings()
    s.onboarded = True
    store.save_settings(s)
    store.set_last_successful_run(datetime(2026, 11, 17, 17, 0, tzinfo=B))


async def test_daily_review_list_is_sent_once_at_digest_hour(deps):
    store = deps.space(ME).store
    _onboard(store)
    for i in range(3):
        _review(store, i)
    ctx = make_context(deps)
    await run_due(ctx, datetime(2026, 11, 17, 17, 30, tzinfo=B))  # vor 18 Uhr: nichts
    assert not any("Zum Prüfen" in m.text for m in ctx.bot.sent)
    await run_due(ctx, datetime(2026, 11, 17, 18, 5, tzinfo=B))
    msgs = [m for m in ctx.bot.sent if "Zum Prüfen" in m.text]
    assert len(msgs) == 1 and "3" in msgs[0].text and "Cloud Engineer 0" in msgs[0].text
    await run_due(ctx, datetime(2026, 11, 17, 18, 30, tzinfo=B))
    assert len([m for m in ctx.bot.sent if "Zum Prüfen" in m.text]) == 1
    # jede Stelle kommt nur einmal in die tägliche Liste
    assert store.jobs_with_status("review") == [] and len(store.jobs_with_status("review_sent")) == 3


async def test_no_review_message_when_queue_empty(deps):
    store = deps.space(ME).store
    _onboard(store)
    ctx = make_context(deps)
    await run_due(ctx, datetime(2026, 11, 17, 18, 5, tzinfo=B))
    assert not any("Zum Prüfen" in m.text for m in ctx.bot.sent)


async def test_daily_list_shows_at_most_15(deps):
    store = deps.space(ME).store
    _onboard(store)
    for i in range(20):
        _review(store, i)
    ctx = make_context(deps)
    await run_due(ctx, datetime(2026, 11, 17, 18, 5, tzinfo=B))
    msg = next(m for m in ctx.bot.sent if "Zum Prüfen" in m.text)
    assert "Cloud Engineer 14" in msg.text and "Cloud Engineer 15" not in msg.text
    assert "5 weitere" in msg.text
    assert len(store.jobs_with_status("review_sent")) == 15 and len(store.jobs_with_status("review")) == 5


async def test_pruefen_command_shows_all_open(deps):
    store = deps.space(ME).store
    _review(store, 1)
    store.set_status([_review(store, 2)], "review_sent")
    ctx = make_context(deps)
    await pruefen.cmd_pruefen(make_update(ME, text="/pruefen"), ctx)
    text = ctx.bot.sent[-1].text
    assert "Cloud Engineer 1" in text and "Cloud Engineer 2" in text


async def test_pruefen_empty(deps):
    upd = make_update(ME, text="/pruefen")
    await pruefen.cmd_pruefen(upd, make_context(deps))
    assert any("Nichts zu prüfen" in r for r in upd.message.replies)


async def test_open_card_shows_reason_and_buttons(deps):
    store = deps.space(ME).store
    jid = _review(store, 1)
    ctx = make_context(deps)
    await pruefen.on_review_button(make_update(ME, data=f"rv:o:{jid}"), ctx)
    card = ctx.bot.sent[-1]
    assert "Anzeige nicht prüfbar" in card.text and "Cloud Engineer 1" in card.text
    data = [b.callback_data for row in card.reply_markup.inline_keyboard for b in row if b.callback_data]
    assert data == [f"rv:y:{jid}", f"rv:n:{jid}"]


async def test_passt_makes_it_a_normal_job(deps):
    store = deps.space(ME).store
    jid = _review(store, 1)
    upd = make_update(ME, data=f"rv:y:{jid}")
    await pruefen.on_review_button(upd, make_context(deps))
    assert [i for i, _ in store.jobs_with_status("reported")] == [jid]
    assert upd.callback_query.answers == ["✅ Übernommen"]
    assert upd.callback_query.edited_markup.inline_keyboard[0][0].callback_data == f"bm:{jid}"
    assert store.review_feedback() == [(jid, "passt", "Werkstudent nicht bestätigt – Anzeige nicht prüfbar")]


async def test_passt_nicht_hides_it_for_good(deps):
    store = deps.space(ME).store
    jid = _review(store, 1)
    upd = make_update(ME, data=f"rv:n:{jid}")
    await pruefen.on_review_button(upd, make_context(deps))
    assert [i for i, _ in store.jobs_with_status("dismissed")] == [jid]
    assert upd.callback_query.message.deleted
    assert store.review_feedback()[0][1] == "passt nicht"


async def test_review_buttons_only_for_own_jobs(deps):
    store = deps.space(ME).store
    jid = _review(store, 1)
    await pruefen.on_review_button(make_update(666, data=f"rv:y:{jid}"), make_context(deps))
    assert store.jobs_with_status("reported") == []



async def test_review_list_respects_pause(deps):
    store = deps.space(ME).store
    _onboard(store)
    s = store.load_settings()
    s.paused = True
    store.save_settings(s)
    _review(store, 1)
    ctx = make_context(deps)
    await run_due(ctx, datetime(2026, 11, 17, 18, 5, tzinfo=B))
    assert not any("Zum Prüfen" in m.text for m in ctx.bot.sent)


async def test_failed_review_send_is_retried_same_day(deps):
    from telegram.error import Forbidden

    from .fakes import FakeBot
    store = deps.space(ME).store
    _onboard(store)
    _review(store, 1)
    ctx = make_context(deps, bot=FakeBot(fail_on={0: Forbidden("x")}))
    await run_due(ctx, datetime(2026, 11, 17, 18, 5, tzinfo=B))
    assert len(store.jobs_with_status("review")) == 1
    await run_due(ctx, datetime(2026, 11, 17, 18, 10, tzinfo=B))
    assert any("Zum Prüfen" in m.text for m in ctx.bot.sent)


async def test_old_reviews_are_cleared_after_two_weeks(deps):
    store = deps.space(ME).store
    _onboard(store)
    jid = _review(store, 1)
    store._db.execute("UPDATE jobs SET created_at = ? WHERE id = ?",
                      ((datetime(2026, 11, 1, tzinfo=B)).isoformat(), jid))
    store._db.commit()
    await run_due(make_context(deps), datetime(2026, 11, 17, 18, 5, tzinfo=B))
    assert store.get_status(jid) == "dismissed"
