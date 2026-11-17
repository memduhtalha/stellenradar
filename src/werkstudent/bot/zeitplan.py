"""Zeitplan: stündliche Läufe im aktiven Zeitfenster, Nachholen nach Ausfall, tägliche Sammelnachricht."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from werkstudent.modelle import UserSettings

log = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
TICK_S = 60
ALIVE_S = 300


def is_active(now: datetime, s: UserSettings) -> bool:
    return s.active_from <= now.astimezone(BERLIN).hour < s.active_to


def _next_window_start(t: datetime, s: UserSettings) -> datetime:
    local = t.astimezone(BERLIN)
    start = local.replace(hour=s.active_from, minute=0, second=0, microsecond=0)
    return start if local.hour < s.active_from else start + timedelta(days=1)


def next_run_at(last: datetime | None, now: datetime, s: UserSettings) -> datetime:
    interval = timedelta(minutes=s.interval_minutes)
    if (last is None or now - last >= interval) and is_active(now, s):
        return now
    candidate = max(last + interval, now) if last else now
    if not is_active(candidate, s):
        return _next_window_start(candidate, s)
    return candidate


def digest_due(now: datetime, s: UserSettings, last: date | None) -> bool:
    local = now.astimezone(BERLIN)
    return local.hour >= s.digest_hour and last != local.date()


async def tick(context) -> None:
    """Läuft jede Minute."""
    await run_due(context, datetime.now(BERLIN))


async def run_due(context, now: datetime) -> None:
    """Für jede eingerichtete Person: Sammelnachricht und Suchlauf, wenn fällig – nacheinander."""
    from werkstudent.bot.befehle import run_and_send  # Import hier, um Zyklen zu vermeiden
    from werkstudent.bot.pruefen import maybe_send_review

    deps = context.bot_data["deps"]
    maybe_backup(deps, now)
    for user_id in deps.registry.users():
        try:
            sp = deps.space(user_id)
            settings = sp.store.load_settings()
            if not settings.onboarded:
                continue
            await maybe_send_digest(context, user_id, now, settings)
            await maybe_send_review(context, user_id, now, settings)
            if is_active(now, settings):
                await send_reminders(context, user_id, now)
            await maybe_send_weekly(context, user_id, now, settings)
            last = max(filter(None, [sp.store.last_successful_run(), sp.last_attempt]), default=None)
            if next_run_at(last, now, settings) <= now:
                await run_and_send(context, user_id, now)
        except Exception:  # noqa: BLE001 – ein Fehler bei einer Person darf die anderen nicht aufhalten
            log.exception("Zeitplan für Person %s fehlgeschlagen", user_id)


async def maybe_send_digest(context, user_id: int, now: datetime, settings: UserSettings) -> None:
    from werkstudent.bot.befehle import send_digest_now

    store = context.bot_data["deps"].space(user_id).store
    if settings.paused or not digest_due(now, settings, store.last_digest_date()):
        return
    store.set_last_digest_date(now.astimezone(BERLIN).date())
    # Auch nach einem Wechsel auf „Sofort“ noch liegen gebliebene Sammel-Stellen ausliefern.
    await send_digest_now(context, user_id)


def maybe_backup(deps, now: datetime) -> None:
    """Einmal pro Tag alle Datenbanken sichern, die letzten 7 Tage behalten."""
    from werkstudent.speicher.sicherung import create_backup, prune_backups

    today = now.astimezone(BERLIN).date().isoformat()
    if deps.data_dir is None or deps.registry.get_meta("last_backup") == today:
        return
    try:
        create_backup(deps.data_dir, now.astimezone(BERLIN).date())
        prune_backups(deps.data_dir)
        deps.registry.set_meta("last_backup", today)
        log.info("Sicherung erstellt: %s", today)
    except Exception:  # noqa: BLE001 – eine fehlgeschlagene Sicherung darf den Bot nicht stoppen
        log.exception("Sicherung fehlgeschlagen")


async def send_reminders(context, user_id: int, now: datetime) -> None:
    from werkstudent.bot.nachrichten import format_reminder
    from werkstudent.bot.senden import send_text

    store = context.bot_data["deps"].space(user_id).store
    due = store.due_reminders(now)
    missing = store.expired_ids([i for i, _ in due], now)
    for job_id, p in due:
        text, markup = format_reminder(job_id, p, missing=job_id in missing)
        store.reminder_sent(job_id)  # vorher markieren: lieber einmal zu wenig als jede Minute erinnern
        await send_text(context.bot, user_id, text, reply_markup=markup)


WEEKLY_DAY = 6  # Sonntag


async def maybe_send_weekly(context, user_id: int, now: datetime, settings: UserSettings) -> None:
    from werkstudent.bot.nachrichten import format_weekly
    from werkstudent.bot.senden import send_text

    local = now.astimezone(BERLIN)
    store = context.bot_data["deps"].space(user_id).store
    if local.weekday() != WEEKLY_DAY or local.hour < settings.digest_hour:
        return
    if store.get_meta("last_weekly") == local.date().isoformat():
        return
    store.set_meta("last_weekly", local.date().isoformat())
    await send_text(context.bot, user_id, format_weekly(store.week_stats(now - timedelta(days=7))))


async def alive_tick(context) -> None:
    """Eigener Job, damit lange Suchläufe das Lebenszeichen nicht blockieren."""
    from werkstudent.bot.lebenszeichen import mark_alive, maybe_ping

    deps = context.bot_data["deps"]
    now = datetime.now(BERLIN)
    mark_alive(deps, now)
    await maybe_ping(deps, now)


def schedule(app) -> None:
    app.job_queue.run_repeating(tick, interval=TICK_S, first=10, name="tick")
    app.job_queue.run_repeating(alive_tick, interval=ALIVE_S, first=5, name="lebenszeichen")
