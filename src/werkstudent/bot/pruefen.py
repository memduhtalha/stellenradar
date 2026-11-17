"""„Zum Prüfen“: Stellen, die passen könnten, sich aber nicht abschließend prüfen ließen.

Einmal am Tag (zur Uhrzeit der Sammelnachricht) kommt eine Liste mit den neuen; /pruefen zeigt alle offenen.
✅ Passt macht daraus eine normale Stelle, ❌ Passt nicht blendet sie dauerhaft aus.
Die Entscheidungen werden mitgeschrieben, um die Filter später nachzuschärfen.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from werkstudent.bot.befehle import _delete, _set_markup, reply, space_of
from werkstudent.bot.nachrichten import job_buttons, source_label
from werkstudent.bot.senden import send_text
from werkstudent.modelle import ProcessedJob, UserSettings

log = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
DAILY_MAX = 15
REVIEW_MAX_AGE = timedelta(days=14)
OPEN = ("review", "review_sent")


def _line(n: int, p: ProcessedJob) -> str:
    j = p.job
    place = escape(j.location or "Ort unbekannt")
    if p.distance_km is not None:
        place += f" ({round(p.distance_km)} km)"
    return (f"{n}. <b>{escape(j.title)}</b>\n"
            f"    {escape(j.company or 'Firma unbekannt')} · {place} · {source_label(j.source)}\n"
            f"    ❓ {escape(p.review_reason or 'unklar')}")


def format_review_list(items: list[tuple[int, ProcessedJob]], total: int) -> tuple[str, InlineKeyboardMarkup]:
    head = (f"🔍 <b>Zum Prüfen</b> – {total} Stellen könnten passen, ließen sich aber nicht abschließend prüfen."
            "\nTippe auf eine Nummer und entscheide mit ✅ oder ❌.")
    lines = [_line(i + 1, p) for i, (_, p) in enumerate(items)]
    if total > len(items):
        lines.append(f"\n… und {total - len(items)} weitere – alle mit /pruefen.")
    buttons = [InlineKeyboardButton(str(i + 1), callback_data=f"rv:o:{jid}") for i, (jid, _) in enumerate(items)]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    return head + "\n\n" + "\n".join(lines), InlineKeyboardMarkup(rows)


def format_review_card(job_id: int, p: ProcessedJob) -> tuple[str, InlineKeyboardMarkup]:
    j = p.job
    place = escape(j.location or "Ort unbekannt")
    if p.distance_km is not None:
        place += f" ({round(p.distance_km)} km)"
    text = "\n".join([
        "🔍 <b>Zum Prüfen</b>",
        f"<b>{escape(j.title)}</b>",
        f"🏢 {escape(j.company or 'Firma unbekannt')} · 📍 {place} · {source_label(j.source)}",
        f"❓ {escape(p.review_reason or 'unklar')}",
        "Bitte kurz die Anzeige ansehen – passt sie?",
    ])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Passt", callback_data=f"rv:y:{job_id}"),
         InlineKeyboardButton("❌ Passt nicht", callback_data=f"rv:n:{job_id}")],
        [InlineKeyboardButton("🔗 Zur Anzeige", url=j.url)],
    ])
    return text, markup


def _open_items(store) -> list[tuple[int, ProcessedJob]]:
    items = [item for status in OPEN for item in store.jobs_with_status(status)]
    return sorted(items, key=lambda t: t[0])


async def maybe_send_review(context, user_id: int, now: datetime, settings: UserSettings) -> None:
    """Einmal am Tag zur Sammelnachricht-Uhrzeit: neue „Zum Prüfen“-Stellen als eine Liste."""
    store = context.bot_data["deps"].space(user_id).store
    local = now.astimezone(BERLIN)
    today = local.date().isoformat()
    store.expire_reviews(now - REVIEW_MAX_AGE)
    if settings.paused or local.hour < settings.digest_hour or store.get_meta("last_review") == today:
        return
    new = store.jobs_with_status("review")
    if not new:
        store.set_meta("last_review", today)
        return
    shown = new[:DAILY_MAX]
    text, markup = format_review_list(shown, len(new))
    if await send_text(context.bot, user_id, text, reply_markup=markup):
        store.set_meta("last_review", today)  # erst nach Erfolg – sonst beim nächsten Tick erneut
        store.set_status([jid for jid, _ in shown], "review_sent")  # jede Stelle nur einmal in der Tagesliste


async def cmd_pruefen(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    items = _open_items(sp.store)
    if not items:
        await reply(update, "✅ Nichts zu prüfen.")
        return
    text, markup = format_review_list(items[:DAILY_MAX], len(items))
    await send_text(context.bot, sp.user_id, text, reply_markup=markup)


async def on_review_button(update, context) -> None:
    query = update.callback_query
    sp = space_of(update, context)
    if query is None or sp is None:
        return
    parts = (query.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await query.answer()
        return
    action, job_id = parts[1], int(parts[2])
    store = sp.store
    p = store.get_job(job_id)
    if p is None or store.get_status(job_id) not in OPEN:
        await query.answer("Schon erledigt.")
        return
    if action == "o":
        await query.answer()
        text, markup = format_review_card(job_id, p)
        await context.bot.send_message(sp.user_id, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                       disable_web_page_preview=True)
    elif action == "y":
        store.set_status([job_id], "reported")
        store.record_review_feedback(job_id, "passt", p.review_reason)
        await query.answer("✅ Übernommen")
        await _set_markup(query, job_buttons(job_id, store.is_bookmarked(job_id)))
    elif action == "n":
        store.set_status([job_id], "dismissed")
        store.record_review_feedback(job_id, "passt nicht", p.review_reason)
        await query.answer("❌ Aussortiert")
        await _delete(query)
    else:
        await query.answer()
