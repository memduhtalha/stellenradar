"""/alle: Live-Suche, die alle aktuell passenden Stellen auflistet – eine Nachricht zum Blättern."""
from __future__ import annotations

import logging
from datetime import datetime

from telegram import InputFile
from telegram.constants import ParseMode

from werkstudent.bot.befehle import BERLIN, deps_of, space_of
from werkstudent.bot.nachrichten import alle_count_question, alle_html, format_alle_page, format_job
from werkstudent.bot.senden import send_text

log = logging.getLogger(__name__)


async def cmd_alle(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    text, markup = alle_count_question()
    await send_text(context.bot, sp.user_id, text, reply_markup=markup)


def _alle_marks(store) -> tuple[set[int], set[int]]:
    rows = store.bookmarks_with_ids()
    return {r[0] for r in rows if r[3] is None}, {r[0] for r in rows if r[3] is not None}


def _alle_page(context, store, page: int):
    state = context.user_data["alle"]
    entries = []
    for job_id, is_new in state["entries"]:
        p = store.get_job(job_id)
        if p is not None:
            entries.append((job_id, p, is_new))
    bookmarked, applied = _alle_marks(store)
    state["page"] = page
    return format_alle_page(entries, page, state["total"], state["new"], state["at"], bookmarked, applied)


async def on_alle_button(update, context) -> None:
    query = update.callback_query
    sp = space_of(update, context)
    if query is None or sp is None:
        return
    parts = (query.data or "").split(":")
    action, arg = parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""
    state = context.user_data.get("alle")

    if action == "n" and arg.isdigit():
        await query.answer()
        await _edit_text(query, "🔎 Suche läuft auf allen Portalen – das dauert ein paar Minuten …")
        now = datetime.now(BERLIN)
        result = await sp.runner.collect(now)
        if result is None:
            await _edit_text(query, "Eine Suche läuft gerade schon – bitte versuch es gleich noch einmal.")
            return
        deps = deps_of(context)
        for w in result.warnings:
            prefix = "" if sp.user_id == deps.admin_id else f"(Suche für Person {sp.user_id}) "
            await send_text(context.bot, deps.admin_id, prefix + w)
        limit = int(arg) or len(result.items)
        shown = result.items[:limit]
        context.user_data["alle"] = {
            "entries": [(job_id, is_new) for job_id, _, is_new in shown],
            "total": len(result.items),
            "new": sum(1 for _, _, is_new in result.items if is_new),
            "at": now,
            "page": 0,
        }
        await _edit_text(query, "✅ Suche fertig.")
        text, markup = _alle_page(context, sp.store, 0)
        await send_text(context.bot, sp.user_id, text, reply_markup=markup)
        return

    if state is None:
        await query.answer("Bitte /alle neu starten.")
        return
    if action == "p" and arg.isdigit():
        await query.answer()
        text, markup = _alle_page(context, sp.store, int(arg))
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                          disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001 – z. B. „message is not modified“
            log.info("Seite nicht aktualisiert: %s", e)
    elif action == "j" and arg.isdigit() and int(arg) < len(state["entries"]):
        job_id, _ = state["entries"][int(arg)]
        p = sp.store.get_job(job_id)
        await query.answer()
        if p is not None:
            text, markup = format_job(job_id, p, deps_of(context).category_map, datetime.now(BERLIN),
                                      bookmarked=sp.store.is_bookmarked(job_id))
            await send_text(context.bot, sp.user_id, text, reply_markup=markup)
    elif action == "f":
        await query.answer("📄 Datei kommt …")
        entries = [(jid, p, new) for jid, new in state["entries"] if (p := sp.store.get_job(jid)) is not None]
        name = f"stellen-{state['at'].astimezone(BERLIN).strftime('%Y-%m-%d-%H%M')}.html"
        await context.bot.send_document(
            sp.user_id, InputFile(alle_html(entries, state["at"]), filename=name),
            caption=f"📄 {len(entries)} Stellen – im Browser öffnen, die Titel sind Links.",
        )
    else:
        await query.answer()


async def _edit_text(query, text: str) -> None:
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:  # noqa: BLE001
        log.info("Text nicht aktualisiert: %s", e)
