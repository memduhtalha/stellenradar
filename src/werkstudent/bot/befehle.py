"""Befehle (/jetzt, /pause, …) und die Buttons unter jeder Stelle.

Jede Person hat ihren eigenen Bereich (UserSpace) mit eigener Datenbank – nichts wird geteilt.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram.constants import ParseMode

from werkstudent.bot.nachrichten import (
    MAX_BOOKMARK_CARDS,
    dismiss_confirm_buttons,
    format_bookmark_card,
    format_bookmarks_header,
    format_digest,
    format_status,
    job_buttons,
)
from werkstudent.bot.senden import send_jobs, send_text
from werkstudent.bot.zeitplan import next_run_at
from werkstudent.lauf import RunResult
from werkstudent.modelle import Category

log = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

COMMANDS = [
    ("start", "Einrichtung starten"),
    ("einstellungen", "Ort, Umkreis, Bereiche … ändern"),
    ("jetzt", "Sofort suchen"),
    ("status", "Letzter Lauf und Zustand der Quellen"),
    ("gemerkt", "Merkliste anzeigen"),
    ("alle", "Live-Suche: alle aktuellen Stellen auflisten"),
    ("pruefen", "Unsichere Stellen ansehen und entscheiden"),
    ("pause", "Benachrichtigungen pausieren"),
    ("weiter", "Benachrichtigungen fortsetzen"),
    ("hilfe", "Alle Befehle"),
]

HELP_TEXT = "🤖 <b>Job-Alarm</b>\n\n" + "\n".join(f"/{c} – {d}" for c, d in COMMANDS)
ADMIN_COMMANDS = [
    ("einladen", "Weitere Person einladen"),
    ("personen", "Wer den Bot nutzt – Personen entfernen"),
]
ADMIN_HELP = "\n\n<b>Nur für dich:</b>\n" + "\n".join(f"/{c} – {d}" for c, d in ADMIN_COMMANDS)


@dataclass
class UserSpace:
    """Alles, was zu einer Person gehört."""

    user_id: int
    store: object
    runner: object
    geocoder: object
    last_attempt: datetime | None = None
    last_counts: dict = field(default_factory=dict)


class Deps:
    def __init__(
        self,
        registry,
        categories: list[Category],
        make_space: Callable[[int], UserSpace],
        data_dir: Path | None = None,
    ):
        self.registry = registry
        self.categories = categories
        self.data_dir = data_dir  # für die tägliche Sicherung
        self.healthcheck_url: str | None = None  # optionaler externer Wächter (siehe lebenszeichen.py)
        self.ping = None  # async (url) -> None
        self._make_space = make_space
        self._spaces: dict[int, UserSpace] = {}

    def forget(self, user_id: int) -> None:
        self._spaces.pop(user_id, None)

    @property
    def admin_id(self) -> int:
        return self.registry.admin_id

    def space(self, user_id: int) -> UserSpace:
        if user_id not in self._spaces:
            self._spaces[user_id] = self._make_space(user_id)
        return self._spaces[user_id]

    @property
    def category_map(self) -> dict[str, Category]:
        return {c.key: c for c in self.categories}


def deps_of(context) -> Deps:
    return context.bot_data["deps"]


def user_of(update) -> int | None:
    user = update.effective_user
    return user.id if user is not None else None


def is_allowed(update, deps: Deps) -> bool:
    uid = user_of(update)
    return uid is not None and deps.registry.is_user(uid)


def space_of(update, context) -> UserSpace | None:
    """Bereich der Person, die geschrieben hat – oder None, wenn sie den Bot nicht nutzen darf."""
    deps = deps_of(context)
    return deps.space(user_of(update)) if is_allowed(update, deps) else None


async def reply(update, text: str) -> None:
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def run_and_send(
    context, user_id: int, now: datetime | None = None, force_backlog: bool = False
) -> RunResult | None:
    sp = deps_of(context).space(user_id)
    now = now or datetime.now(BERLIN)
    sp.last_attempt = now
    result = await sp.runner.run(now, force_backlog=force_backlog)
    if result is not None:
        sp.last_counts = result.source_counts
        await deliver(context, user_id, result, now)
    return result


async def deliver(context, user_id: int, result: RunResult, now: datetime) -> None:
    """Stellen an die Person; technische Warnungen nur an den Admin.
    Was nicht ankommt, wird als „unsent“ beim nächsten Lauf erneut geschickt."""
    deps = deps_of(context)
    warnings, result.warnings = result.warnings, []
    for w in warnings:
        prefix = "" if user_id == deps.admin_id else f"(Suche für Person {user_id}) "
        await send_text(context.bot, deps.admin_id, prefix + w)
    failed = await send_jobs(context.bot, user_id, result, deps.category_map, now)
    deps.space(user_id).store.set_status(failed, "unsent")


async def send_digest_now(context, user_id: int) -> None:
    store = deps_of(context).space(user_id).store
    items = store.jobs_with_status("digest")
    sent = [await send_text(context.bot, user_id, t) for t in format_digest([p for _, p in items])]
    if sent and all(sent):  # sonst beim nächsten Mal erneut versuchen
        store.set_status([i for i, _ in items], "reported")


# --- Befehle ---------------------------------------------------------------------


async def cmd_jetzt(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    if getattr(sp.runner, "running", False):
        await reply(update, "Läuft gerade schon – Ergebnisse kommen gleich.")
        return
    await reply(update, "🔎 Suche läuft …")
    result = await run_and_send(context, sp.user_id)
    if result is None:
        await reply(update, "Läuft gerade schon – Ergebnisse kommen gleich.")
    elif not result.to_send:
        await reply(update, "Keine neuen Stellen gefunden.")


async def cmd_pause(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    s = sp.store.load_settings()
    s.paused = True
    sp.store.save_settings(s)
    await reply(update, "⏸️ Pausiert. Ich suche weiter und schicke dir alles nach /weiter.")


async def cmd_weiter(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    s = sp.store.load_settings()
    s.paused = False
    sp.store.save_settings(s)
    now = datetime.now(BERLIN)
    result = sp.runner.release_held(now)
    await reply(update, f"▶️ Weiter geht's – {len(result.to_send)} Stellen aus der Pause.")
    await deliver(context, sp.user_id, result, now)


async def cmd_status(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    s = sp.store.load_settings()
    last = sp.store.last_successful_run()
    newest = max(filter(None, [last, sp.last_attempt]), default=None)
    text = format_status(
        sp.store.all_source_states(),
        sp.last_counts,
        last,
        next_run_at(newest, datetime.now(BERLIN), s) if s.onboarded else None,
        s.paused,
    )
    await reply(update, text)


async def cmd_gemerkt(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    items = sp.store.bookmarks_with_ids()
    if not items:
        await reply(update, "⭐ Deine Merkliste ist leer. Tippe bei einer Stelle auf ⭐ Merken.")
        return
    await send_text(context.bot, sp.user_id, format_bookmarks_header(len(items)))
    now = datetime.now(UTC)
    gone = sp.store.expired_ids([i[0] for i in items[:MAX_BOOKMARK_CARDS]], now)
    for job_id, p, saved_at, applied_at in items[:MAX_BOOKMARK_CARDS]:
        offline = (now - sp.store.last_seen(job_id)).days if job_id in gone else None
        text, markup = format_bookmark_card(job_id, p, deps_of(context).category_map, saved_at, applied_at, offline)
        await send_text(context.bot, sp.user_id, text, reply_markup=markup)


async def cmd_hilfe(update, context) -> None:
    deps = deps_of(context)
    if is_allowed(update, deps):
        await reply(update, HELP_TEXT + (ADMIN_HELP if user_of(update) == deps.admin_id else ""))


# --- Buttons unter Stellen ------------------------------------------------------------


async def _set_markup(query, markup) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception as e:  # noqa: BLE001 – z. B. „message is not modified“
        log.info("Buttons nicht aktualisiert: %s", e)


async def _set_buttons(query, job_id: int, bookmarked: bool) -> None:
    await _set_markup(query, job_buttons(job_id, bookmarked))


async def _delete(query) -> None:
    try:
        await query.message.delete()
    except Exception as e:  # noqa: BLE001 – alte Nachrichten lassen sich evtl. nicht löschen
        log.info("Nachricht nicht gelöscht: %s", e)


async def on_job_button(update, context) -> None:
    query = update.callback_query
    sp = space_of(update, context)
    if query is None or sp is None:
        return
    store = sp.store  # Job-IDs gelten nur in der Datenbank dieser Person
    action, _, raw_id = (query.data or "").partition(":")
    if not raw_id.isdigit():
        await query.answer()
        return
    job_id = int(raw_id)
    if action == "bm":
        store.bookmark(job_id)
        await query.answer("⭐ Gemerkt")
        await _set_buttons(query, job_id, bookmarked=True)
    elif action == "ub":
        store.unbookmark(job_id)
        await query.answer("Von der Merkliste entfernt")
        await _set_buttons(query, job_id, bookmarked=False)
    elif action == "ubl":  # „Entfernen“ in der Merkliste
        store.unbookmark(job_id)
        await query.answer("Von der Merkliste entfernt")
        await _delete(query)
    elif action == "ap":  # aus der Erinnerung: beworben
        store.mark_applied(job_id, datetime.now(UTC))
        await query.answer("✅ Als beworben markiert")
        await _set_markup(query, None)
    elif action == "snz":
        store.snooze(job_id, datetime.now(UTC))
        await query.answer("⏰ Ich erinnere dich in 3 Tagen")
        await _set_markup(query, None)
    elif action == "dz":  # erst nachfragen – versehentliches Tippen soll nichts ausblenden
        await query.answer("Wirklich ausblenden?")
        await _set_markup(query, dismiss_confirm_buttons(job_id))
    elif action == "dzy":
        store.dismiss(job_id)
        await query.answer("Ausgeblendet")
        await _delete(query)
    elif action == "dzn":
        await query.answer("Abgebrochen")
        await _set_buttons(query, job_id, bookmarked=store.is_bookmarked(job_id))
    else:
        await query.answer()
