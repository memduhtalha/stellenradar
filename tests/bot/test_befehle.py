from datetime import UTC
from pathlib import Path

import pytest

from werkstudent.bot import alle, befehle, einrichtung, personen
from werkstudent.bot.befehle import Deps, UserSpace
from werkstudent.config import load_categories
from werkstudent.lauf import RunResult
from werkstudent.modelle import Job, ProcessedJob
from werkstudent.speicher.registry import Registry
from werkstudent.speicher.store import Store

from .fakes import make_context, make_update

ME = 1000
OTHER = 2000
CATS = load_categories(Path("config/kategorien.yaml"))


class FakeRunner:
    running = False

    def __init__(self):
        self.runs = 0
        self.result = RunResult()
        self.released = 0

    async def run(self, now, force_backlog=False):
        self.runs += 1
        return self.result

    def release_held(self, now):
        self.released += 1
        return RunResult()

    collect_result = None
    collects = 0

    async def collect(self, now):
        self.collects += 1
        return self.collect_result


class FakeGeocoder:
    async def locate(self, place):
        return (51.1, 6.9) if place.lower() == "hilden" else None


def _space(user_id):
    store = Store(":memory:")
    store.init()
    return UserSpace(user_id=user_id, store=store, runner=FakeRunner(), geocoder=FakeGeocoder())


@pytest.fixture
def deps():
    reg = Registry(":memory:", admin_id=ME)
    reg.init()
    return Deps(registry=reg, categories=CATS, make_space=_space)


@pytest.fixture
def me(deps):
    return deps.space(ME)


def _saved_job(store):
    job = Job(source="stepstone", source_id="1", title="Werkstudent Cloud", company="Beispiel GmbH",
              location="Düsseldorf", url="u")
    p = ProcessedJob(job=job, kind="werkstudent", categories=["cloud"], distance_km=1, score=7, is_top=True,
                     dedupe_key="k")
    return store.save_job(p, job, "reported")


async def test_callback_from_foreign_user_ignored(deps):
    jid = _saved_job(deps.space(ME).store)
    upd = make_update(user_id=666, data=f"bm:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert deps.space(ME).store.bookmarks() == []
    assert upd.callback_query.answers == []


async def test_bookmark_callback_saves(deps):
    jid = _saved_job(deps.space(ME).store)
    upd = make_update(user_id=ME, data=f"bm:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert [b.job.source_id for b in deps.space(ME).store.bookmarks()] == ["1"]
    assert upd.callback_query.answers == ["⭐ Gemerkt"]


async def test_dismiss_asks_for_confirmation_first(deps):
    jid = _saved_job(deps.space(ME).store)
    upd = make_update(user_id=ME, data=f"dz:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert deps.space(ME).store.disliked_companies() == set()
    assert not upd.callback_query.message.deleted
    row = upd.callback_query.edited_markup.inline_keyboard[0]
    assert [(b.text, b.callback_data) for b in row] == [("👎 Ja, ausblenden", f"dzy:{jid}"), ("↩️ Abbrechen", f"dzn:{jid}")]
    assert upd.callback_query.answers == ["Wirklich ausblenden?"]


async def test_dismiss_confirmed_deletes_message(deps):
    jid = _saved_job(deps.space(ME).store)
    upd = make_update(user_id=ME, data=f"dzy:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert "beispiel" in deps.space(ME).store.disliked_companies()
    assert upd.callback_query.message.deleted


async def test_dismiss_cancel_restores_buttons_keeping_bookmark(deps):
    jid = _saved_job(deps.space(ME).store)
    deps.space(ME).store.bookmark(jid)
    upd = make_update(user_id=ME, data=f"dzn:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert deps.space(ME).store.disliked_companies() == set()
    assert [b.text for b in upd.callback_query.edited_markup.inline_keyboard[0]] == ["✅ Gemerkt", "👎 Uninteressant"]


async def test_gemerkt_sends_one_card_per_job_with_buttons(deps):
    first = _saved_job(deps.space(ME).store)
    deps.space(ME).store.bookmark(first)
    ctx = make_context(deps)
    await befehle.cmd_gemerkt(make_update(ME, text="/gemerkt"), ctx)
    header, card = ctx.bot.sent
    assert "Merkliste" in header.text and "1 Stelle" in header.text
    assert "<b>Werkstudent Cloud</b>" in card.text and "Beispiel GmbH" in card.text
    row = card.reply_markup.inline_keyboard[0]
    assert row[0].text == "🔗 Zur Anzeige" and row[0].url == "u"
    assert (row[1].text, row[1].callback_data) == ("🗑️ Entfernen", f"ubl:{first}")


async def test_gemerkt_empty(deps):
    ctx = make_context(deps)
    upd = make_update(ME, text="/gemerkt")
    await befehle.cmd_gemerkt(upd, ctx)
    assert ctx.bot.sent == [] and any("leer" in r for r in upd.message.replies)


async def test_remove_from_bookmark_list_deletes_card(deps):
    jid = _saved_job(deps.space(ME).store)
    deps.space(ME).store.bookmark(jid)
    upd = make_update(ME, data=f"ubl:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert deps.space(ME).store.bookmarks() == [] and upd.callback_query.message.deleted


async def test_jetzt_while_running_says_so(deps):
    deps.space(ME).runner.result = None
    upd = make_update(user_id=ME, text="/jetzt")
    await befehle.cmd_jetzt(upd, make_context(deps))
    assert any("Läuft gerade schon" in r for r in upd.message.replies)


async def test_foreign_user_command_ignored(deps):
    upd = make_update(user_id=666, text="/jetzt")
    await befehle.cmd_jetzt(upd, make_context(deps))
    assert deps.space(ME).runner.runs == 0 and upd.message.replies == []


async def test_pause_and_weiter(deps):
    ctx = make_context(deps)
    await befehle.cmd_pause(make_update(ME, text="/pause"), ctx)
    assert deps.space(ME).store.load_settings().paused
    await befehle.cmd_weiter(make_update(ME, text="/weiter"), ctx)
    assert not deps.space(ME).store.load_settings().paused
    assert deps.space(ME).runner.released == 1


async def test_wizard_full_flow_saves_settings(deps):
    ctx = make_context(deps)
    await einrichtung.cmd_start(make_update(ME, text="/start"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:art:werkstudent"), ctx)
    await einrichtung.on_text(make_update(ME, text="Hilden"), ctx)
    for data in ["set:radius:40", "set:cat:security", "set:cat:software", "set:cat:done",
                 "set:remote:1", "set:intern:0", "set:mode:taeglich"]:
        await einrichtung.on_button(make_update(ME, data=data), ctx)
    s = deps.space(ME).store.load_settings()
    assert s.location == "Hilden" and (s.lat, s.lon) == (51.1, 6.9)
    assert s.radius_km == 40
    assert s.categories == {"cloud", "ki", "software"}
    assert s.remote is True and s.internships is False and s.digest_mode == "taeglich"
    assert s.onboarded is True
    assert deps.space(ME).runner.runs == 1  # erster Lauf direkt nach der Einrichtung


async def test_wizard_unknown_place_asks_again(deps):
    ctx = make_context(deps)
    await einrichtung.cmd_start(make_update(ME, text="/start"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:art:werkstudent"), ctx)
    await einrichtung.on_text(make_update(ME, text="Atlantis"), ctx)
    assert any("Ort nicht gefunden" in m.text for m in ctx.bot.sent)
    assert ctx.user_data["setup"]["step"] == "ort"


async def test_wizard_requires_one_category(deps):
    ctx = make_context(deps)
    await einrichtung.cmd_start(make_update(ME, text="/start"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:art:werkstudent"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:ort:default"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:radius:25"), ctx)
    for k in ["cloud", "ki", "security"]:
        await einrichtung.on_button(make_update(ME, data=f"set:cat:{k}"), ctx)
    upd = make_update(ME, data="set:cat:done")
    await einrichtung.on_button(upd, ctx)
    assert upd.callback_query.answers[-1] == "Bitte mindestens einen Bereich wählen."
    assert ctx.user_data["setup"]["step"] == "cats"


async def test_einstellungen_single_item_change(deps):
    s = deps.space(ME).store.load_settings()
    s.onboarded = True
    deps.space(ME).store.save_settings(s)
    ctx = make_context(deps)
    await einrichtung.cmd_einstellungen(make_update(ME, text="/einstellungen"), ctx)
    await einrichtung.on_button(make_update(ME, data="menu:interval"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:interval:120"), ctx)
    assert deps.space(ME).store.load_settings().interval_minutes == 120
    assert deps.space(ME).runner.runs == 0


async def test_stale_settings_menu_does_not_undo_pause(deps):
    s = deps.space(ME).store.load_settings()
    s.onboarded = True
    deps.space(ME).store.save_settings(s)
    ctx = make_context(deps)
    await einrichtung.cmd_einstellungen(make_update(ME, text="/einstellungen"), ctx)
    await befehle.cmd_pause(make_update(ME, text="/pause"), ctx)
    await einrichtung.on_button(make_update(ME, data="menu:radius"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:radius:40"), ctx)
    s = deps.space(ME).store.load_settings()
    assert s.radius_km == 40 and s.paused is True


async def test_unsent_jobs_marked_after_failed_send(deps):
    from telegram.error import BadRequest

    from .fakes import FakeBot
    jid = _saved_job(deps.space(ME).store)
    deps.space(ME).runner.result = RunResult(to_send=[(jid, deps.space(ME).store.get_job(jid))])
    bot = FakeBot(fail_on={0: BadRequest("x")})  # erster send_message = die Stelle
    ctx = make_context(deps, bot=bot)
    await befehle.run_and_send(ctx, ME)
    assert [i for i, _ in deps.space(ME).store.jobs_with_status("unsent")] == [jid]


def _first_button(markup):
    return markup.inline_keyboard[0][0]


async def test_bookmark_shows_gemerkt_button(deps):
    jid = _saved_job(deps.space(ME).store)
    upd = make_update(user_id=ME, data=f"bm:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    btn = _first_button(upd.callback_query.edited_markup)
    assert btn.text == "✅ Gemerkt" and btn.callback_data == f"ub:{jid}"


async def test_unbookmark_restores_button(deps):
    jid = _saved_job(deps.space(ME).store)
    ctx = make_context(deps)
    await befehle.on_job_button(make_update(ME, data=f"bm:{jid}"), ctx)
    upd = make_update(ME, data=f"ub:{jid}")
    await befehle.on_job_button(upd, ctx)
    assert deps.space(ME).store.bookmarks() == []
    assert upd.callback_query.answers == ["Von der Merkliste entfernt"]
    btn = _first_button(upd.callback_query.edited_markup)
    assert btn.text == "⭐ Merken" and btn.callback_data == f"bm:{jid}"


async def test_einstellungen_hours_and_digest_time(deps):
    s = deps.space(ME).store.load_settings()
    s.onboarded = True
    deps.space(ME).store.save_settings(s)
    ctx = make_context(deps)
    await einrichtung.cmd_einstellungen(make_update(ME, text="/einstellungen"), ctx)
    await einrichtung.on_button(make_update(ME, data="menu:hours"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:hours:8-20"), ctx)
    await einrichtung.on_button(make_update(ME, data="menu:digest"), ctx)
    await einrichtung.on_button(make_update(ME, data="set:digest:20"), ctx)
    s = deps.space(ME).store.load_settings()
    assert (s.active_from, s.active_to, s.digest_hour) == (8, 20, 20)



# --- mehrere Personen -------------------------------------------------------------------


def _invite(deps):
    from datetime import datetime
    return deps.registry.create_invite(datetime.now(UTC))


async def test_einladen_gives_admin_a_start_link(deps):
    upd = make_update(ME, text="/einladen")
    await personen.cmd_einladen(upd, make_context(deps))
    assert any("https://t.me/werki_bot?start=" in r for r in upd.message.replies)


async def test_einladen_only_for_admin(deps):
    deps.registry.redeem(_invite(deps), OTHER, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    upd = make_update(OTHER, text="/einladen")
    await personen.cmd_einladen(upd, make_context(deps))
    assert upd.message.replies == []


async def test_start_with_invite_adds_person_and_notifies_admin(deps):
    ctx = make_context(deps)
    ctx.args = [_invite(deps)]
    await einrichtung.cmd_start(make_update(OTHER, text="/start x"), ctx)
    assert deps.registry.is_user(OTHER)
    assert ctx.user_data["setup"]["step"] == "art"
    assert any(m.chat_id == ME and "Einladung" in m.text for m in ctx.bot.sent)


async def test_start_without_invite_is_refused(deps):
    upd = make_update(OTHER, text="/start")
    ctx = make_context(deps)
    await einrichtung.cmd_start(upd, ctx)
    assert not deps.registry.is_user(OTHER)
    assert "setup" not in ctx.user_data
    assert any("privat" in r for r in upd.message.replies)


async def test_people_have_separate_bookmarks(deps):
    deps.registry.redeem(_invite(deps), OTHER, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    jid = _saved_job(deps.space(OTHER).store)
    await befehle.on_job_button(make_update(OTHER, data=f"bm:{jid}"), make_context(deps))
    assert len(deps.space(OTHER).store.bookmarks()) == 1
    assert deps.space(ME).store.bookmarks() == []
    ctx = make_context(deps)
    upd = make_update(ME, text="/gemerkt")
    await befehle.cmd_gemerkt(upd, ctx)
    assert ctx.bot.sent == [] and any("leer" in r for r in upd.message.replies)


async def test_gemerkt_is_sent_to_the_asking_person(deps):
    deps.registry.redeem(_invite(deps), OTHER, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    store = deps.space(OTHER).store
    store.bookmark(_saved_job(store))
    ctx = make_context(deps)
    await befehle.cmd_gemerkt(make_update(OTHER, text="/gemerkt"), ctx)
    assert ctx.bot.sent and all(m.chat_id == OTHER for m in ctx.bot.sent)


async def test_warnings_of_other_person_go_to_admin_only(deps):
    deps.registry.redeem(_invite(deps), OTHER, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    deps.space(OTHER).runner.result = RunResult(warnings=["⚠️ Indeed liefert seit 3 Läufen nichts"])
    ctx = make_context(deps)
    await befehle.run_and_send(ctx, OTHER)
    assert [m.chat_id for m in ctx.bot.sent] == [ME]


async def test_wizard_ausbildung_flow(deps):
    ctx = make_context(deps)
    ctx.args = [_invite(deps)]
    await einrichtung.cmd_start(make_update(OTHER, text="/start"), ctx)
    await einrichtung.on_button(make_update(OTHER, data="set:art:ausbildung"), ctx)
    await einrichtung.on_text(make_update(OTHER, text="Hilden"), ctx)
    await einrichtung.on_button(make_update(OTHER, data="set:radius:25"), ctx)
    cats_msg = ctx.bot.sent[-1]
    labels = [b.text for row in cats_msg.reply_markup.inline_keyboard for b in row]
    assert any("Immobilien" in t for t in labels) and not any("Cloud" in t for t in labels)
    await einrichtung.on_button(make_update(OTHER, data="set:cat:done"), ctx)
    assert ctx.user_data["setup"]["step"] == "mode"  # Remote/Praktika entfallen bei Ausbildung
    await einrichtung.on_button(make_update(OTHER, data="set:mode:sofort"), ctx)
    s = deps.space(OTHER).store.load_settings()
    assert s.art == "ausbildung" and s.categories == {"immobilien"} and s.onboarded
    assert deps.space(ME).store.load_settings().onboarded is False  # Admin unberührt


async def test_schedule_runs_each_onboarded_person_separately(deps):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from werkstudent.bot.zeitplan import run_due
    deps.registry.redeem(_invite(deps), OTHER, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    deps.registry.redeem(_invite(deps), 3000, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    for uid in (ME, OTHER):
        s = deps.space(uid).store.load_settings()
        s.onboarded = True
        deps.space(uid).store.save_settings(s)
    await run_due(make_context(deps), datetime(2026, 11, 4, 10, 0, tzinfo=ZoneInfo("Europe/Berlin")))
    assert deps.space(ME).runner.runs == 1 and deps.space(OTHER).runner.runs == 1
    assert deps.space(3000).runner.runs == 0  # noch nicht eingerichtet


async def test_error_for_one_person_does_not_stop_others(deps):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from werkstudent.bot.zeitplan import run_due

    class Broken(FakeRunner):
        async def run(self, now, force_backlog=False):
            raise KeyError("kaputt")

    deps.registry.redeem(_invite(deps), OTHER, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    deps.space(ME).runner = Broken()
    for uid in (ME, OTHER):
        s = deps.space(uid).store.load_settings()
        s.onboarded = True
        deps.space(uid).store.save_settings(s)
    await run_due(make_context(deps), datetime(2026, 11, 4, 10, 0, tzinfo=ZoneInfo("Europe/Berlin")))
    assert deps.space(OTHER).runner.runs == 1


async def test_failed_admin_notification_does_not_block_onboarding(deps):
    from telegram.error import Forbidden

    from .fakes import FakeBot
    ctx = make_context(deps, bot=FakeBot(fail_on={0: Forbidden("blocked")}))
    ctx.args = [_invite(deps)]
    await einrichtung.cmd_start(make_update(OTHER, text="/start"), ctx)
    assert ctx.user_data["setup"]["step"] == "art"


async def test_remote_menu_not_available_in_ausbildung(deps):
    sp = deps.space(ME)
    s = sp.store.load_settings()
    s.art, s.categories, s.onboarded = "ausbildung", {"immobilien"}, True
    sp.store.save_settings(s)
    ctx = make_context(deps)
    upd = make_update(ME, data="menu:remote")
    await einrichtung.on_button(upd, ctx)
    assert upd.callback_query.answers == ["Nur bei Werkstudentenstellen"]
    assert sp.store.load_settings().remote is False


# --- /personen ------------------------------------------------------------------------------


def _join(deps, uid, name="Lena"):
    from datetime import datetime
    deps.registry.redeem(_invite(deps), uid, datetime.now(UTC), name=name)


async def test_personen_lists_people_with_remove_button(deps):
    _join(deps, OTHER)
    ctx = make_context(deps)
    await personen.cmd_personen(make_update(ME, text="/personen"), ctx)
    texts = [m.text for m in ctx.bot.sent]
    assert any("Lena" in t for t in texts)
    buttons = [b.callback_data for m in ctx.bot.sent if m.reply_markup for row in m.reply_markup.inline_keyboard for b in row]
    assert f"rm:{OTHER}" in buttons and f"rm:{ME}" not in buttons


async def test_personen_only_for_admin(deps):
    _join(deps, OTHER)
    ctx = make_context(deps)
    await personen.cmd_personen(make_update(OTHER, text="/personen"), ctx)
    assert ctx.bot.sent == []


async def test_remove_person_asks_then_removes(deps):
    _join(deps, OTHER)
    deps.space(OTHER)
    ctx = make_context(deps)
    upd = make_update(ME, data=f"rm:{OTHER}")
    await personen.on_person_button(upd, ctx)
    assert deps.registry.is_user(OTHER)
    assert [b.callback_data for b in upd.callback_query.edited_markup.inline_keyboard[0]] == [f"rmy:{OTHER}", f"rmn:{OTHER}"]
    await personen.on_person_button(make_update(ME, data=f"rmy:{OTHER}"), ctx)
    assert not deps.registry.is_user(OTHER)
    upd = make_update(OTHER, text="/gemerkt")
    await befehle.cmd_gemerkt(upd, make_context(deps))
    assert upd.message.replies == []


async def test_person_buttons_ignored_for_non_admin(deps):
    _join(deps, OTHER)
    _join(deps, 3000, "Max")
    await personen.on_person_button(make_update(OTHER, data="rmy:3000"), make_context(deps))
    assert deps.registry.is_user(3000)


# --- Erinnerungen ---------------------------------------------------------------------------


async def test_reminder_is_sent_with_buttons(deps):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from werkstudent.bot.zeitplan import run_due
    store = deps.space(ME).store
    jid = _saved_job(store)
    store.bookmark(jid, now=datetime.now(UTC) - timedelta(days=4))
    s = store.load_settings(); s.onboarded = True; s.interval_minutes = 120; store.save_settings(s)
    store.set_last_successful_run(datetime.now(UTC))
    ctx = make_context(deps)
    await run_due(ctx, datetime.now(ZoneInfo("Europe/Berlin")).replace(hour=12))
    reminder = next(m for m in ctx.bot.sent if "Erinnerung" in m.text)
    assert "Werkstudent Cloud" in reminder.text
    assert [b.callback_data for b in reminder.reply_markup.inline_keyboard[0]] == [f"ap:{jid}", f"snz:{jid}"]
    ctx2 = make_context(deps)
    await run_due(ctx2, datetime.now(ZoneInfo("Europe/Berlin")).replace(hour=12))
    assert not any("Erinnerung" in m.text for m in ctx2.bot.sent)  # nur einmal


async def test_applied_button_marks_and_shows_in_bookmarks(deps):
    store = deps.space(ME).store
    jid = _saved_job(store)
    store.bookmark(jid)
    upd = make_update(ME, data=f"ap:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert upd.callback_query.answers == ["✅ Als beworben markiert"]
    ctx = make_context(deps)
    await befehle.cmd_gemerkt(make_update(ME, text="/gemerkt"), ctx)
    assert any("beworben am" in m.text for m in ctx.bot.sent)


async def test_snooze_button(deps):
    store = deps.space(ME).store
    jid = _saved_job(store)
    store.bookmark(jid)
    upd = make_update(ME, data=f"snz:{jid}")
    await befehle.on_job_button(upd, make_context(deps))
    assert upd.callback_query.answers == ["⏰ Ich erinnere dich in 3 Tagen"]


# --- Wochenrückblick -------------------------------------------------------------------------


async def test_weekly_review_on_sunday_once(deps):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from werkstudent.bot.zeitplan import run_due
    store = deps.space(ME).store
    s = store.load_settings(); s.onboarded = True; store.save_settings(s)
    _saved_job(store)
    sunday = datetime(2026, 11, 8, 18, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    ctx = make_context(deps)
    await run_due(ctx, sunday)
    weekly = [m for m in ctx.bot.sent if "Wochenrückblick" in m.text]
    assert len(weekly) == 1 and weekly[0].chat_id == ME
    ctx2 = make_context(deps)
    await run_due(ctx2, sunday.replace(minute=45))
    assert not any("Wochenrückblick" in m.text for m in ctx2.bot.sent)
    ctx3 = make_context(deps)
    await run_due(ctx3, datetime(2026, 11, 9, 18, 30, tzinfo=ZoneInfo("Europe/Berlin")))
    assert not any("Wochenrückblick" in m.text for m in ctx3.bot.sent)


# --- Sicherung -------------------------------------------------------------------------------


async def test_daily_backup_via_schedule(deps, tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from werkstudent.bot.zeitplan import run_due
    (tmp_path / "jobs.db").write_bytes(b"")
    deps.data_dir = tmp_path
    now = datetime(2026, 11, 4, 3, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    await run_due(make_context(deps), now)
    assert (tmp_path / "backup" / "2026-11-04").is_dir()
    assert deps.registry.get_meta("last_backup") == "2026-11-04"



# --- /alle ------------------------------------------------------------------------------------


def _many_jobs(store, n):
    from werkstudent.lauf import CollectResult
    items = []
    for i in range(n):
        job = Job(source="stepstone", source_id=str(i), title=f"Werkstudent Cloud {i}", company=f"Firma {i}",
                  location="Düsseldorf", url=f"https://x/{i}")
        p = ProcessedJob(job=job, kind="werkstudent", categories=["cloud"], distance_km=i, score=10 - i % 5,
                         is_top=i % 5 == 0, dedupe_key=f"k{i}")
        items.append((store.save_job(p, job, "reported"), p, i < 2))
    return CollectResult(items=items, source_counts={"stepstone": n})


async def test_alle_asks_how_many(deps):
    ctx = make_context(deps)
    await alle.cmd_alle(make_update(ME, text="/alle"), ctx)
    q = ctx.bot.sent[-1]
    assert "Wie viele" in q.text
    assert [b.callback_data for b in q.reply_markup.inline_keyboard[0]] == ["al:n:10", "al:n:25", "al:n:50", "al:n:0"]


async def test_alle_runs_live_search_and_shows_first_page(deps):
    sp = deps.space(ME)
    sp.runner.collect_result = _many_jobs(sp.store, 25)
    ctx = make_context(deps)
    upd = make_update(ME, data="al:n:0")
    await alle.on_alle_button(upd, ctx)
    assert sp.runner.collects == 1
    assert "Suche läuft" in upd.callback_query.edited_texts[0]
    page = ctx.bot.sent[-1]
    assert "25 gefunden" in page.text and "2 neu" in page.text and "Seite 1/3" in page.text
    assert "1. 🆕" in page.text and "Werkstudent Cloud 0" in page.text and "Werkstudent Cloud 10" not in page.text
    data = [b.callback_data for row in page.reply_markup.inline_keyboard for b in row]
    assert "al:j:0" in data and "al:j:9" in data and "al:p:1" in data and "al:f" in data


async def test_alle_limit_shows_only_best(deps):
    sp = deps.space(ME)
    sp.runner.collect_result = _many_jobs(sp.store, 25)
    ctx = make_context(deps)
    await alle.on_alle_button(make_update(ME, data="al:n:10"), ctx)
    page = ctx.bot.sent[-1]
    assert "die besten 10" in page.text and "Seite 1/1" in page.text


async def test_alle_paging_edits_same_message(deps):
    sp = deps.space(ME)
    sp.runner.collect_result = _many_jobs(sp.store, 25)
    ctx = make_context(deps)
    await alle.on_alle_button(make_update(ME, data="al:n:0"), ctx)
    sent_before = len(ctx.bot.sent)
    upd = make_update(ME, data="al:p:2")
    await alle.on_alle_button(upd, ctx)
    assert len(ctx.bot.sent) == sent_before
    assert "Seite 3/3" in upd.callback_query.edited_text and "21. " in upd.callback_query.edited_text


async def test_alle_number_sends_job_card(deps):
    sp = deps.space(ME)
    sp.runner.collect_result = _many_jobs(sp.store, 5)
    ctx = make_context(deps)
    await alle.on_alle_button(make_update(ME, data="al:n:0"), ctx)
    await alle.on_alle_button(make_update(ME, data="al:j:3"), ctx)
    card = ctx.bot.sent[-1]
    assert "Werkstudent Cloud 3" in card.text
    assert card.reply_markup.inline_keyboard[0][0].callback_data.startswith("bm:")


async def test_alle_file_export(deps):
    sp = deps.space(ME)
    sp.runner.collect_result = _many_jobs(sp.store, 5)
    ctx = make_context(deps)
    await alle.on_alle_button(make_update(ME, data="al:n:0"), ctx)
    await alle.on_alle_button(make_update(ME, data="al:f"), ctx)
    doc = ctx.bot.documents[-1]
    assert doc.chat_id == ME
    html = doc.document.input_file_content.decode("utf-8")
    assert "Werkstudent Cloud 4" in html and 'href="https://x/4"' in html


async def test_alle_while_running(deps):
    sp = deps.space(ME)
    sp.runner.collect_result = None
    upd = make_update(ME, data="al:n:10")
    await alle.on_alle_button(upd, make_context(deps))
    assert "läuft gerade schon" in upd.callback_query.edited_text


async def test_alle_ignored_for_strangers(deps):
    ctx = make_context(deps)
    await alle.cmd_alle(make_update(666, text="/alle"), ctx)
    await alle.on_alle_button(make_update(666, data="al:n:10"), ctx)
    assert ctx.bot.sent == [] and deps.space(ME).runner.collects == 0


async def test_alle_marks_bookmarked_and_applied(deps):
    sp = deps.space(ME)
    res = _many_jobs(sp.store, 3)
    sp.runner.collect_result = res
    sp.store.bookmark(res.items[1][0])
    sp.store.bookmark(res.items[2][0])
    from datetime import datetime
    sp.store.mark_applied(res.items[2][0], datetime.now(UTC))
    ctx = make_context(deps)
    await alle.on_alle_button(make_update(ME, data="al:n:0"), ctx)
    text = ctx.bot.sent[-1].text
    assert "2. 🆕 ⭐" in text and "3. ✅" in text



async def test_gemerkt_marks_probably_expired(deps):
    from datetime import datetime, timedelta
    store = deps.space(ME).store
    jid = _saved_job(store)
    store.bookmark(jid)
    old = datetime.now(UTC) - timedelta(days=6)
    store.touch_seen("stepstone", "1", old)
    store.record_source_result("stepstone", ok=True, count=5, now=datetime.now(UTC))
    ctx = make_context(deps)
    await befehle.cmd_gemerkt(make_update(ME, text="/gemerkt"), ctx)
    assert any("nicht mehr in den Suchergebnissen" in m.text for m in ctx.bot.sent)
