"""Nur für den Admin: Personen einladen (/einladen) und verwalten (/personen)."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from werkstudent.bot.befehle import _set_markup, deps_of, reply, user_of
from werkstudent.bot.nachrichten import format_person, remove_confirm_buttons
from werkstudent.bot.senden import send_text

log = logging.getLogger(__name__)


async def cmd_einladen(update, context) -> None:
    deps = deps_of(context)
    if user_of(update) != deps.admin_id:
        log.info("/einladen von Nicht-Admin %s ignoriert", user_of(update))
        return
    log.info("Einladungslink erstellt")
    code = deps.registry.create_invite(datetime.now(UTC))
    link = f"https://t.me/{context.bot.username}?start={code}"
    await reply(
        update,
        "✉️ <b>Einladung</b>\n"
        f"Schick diesen Link an die Person:\n{link}\n\n"
        "Er gilt 24 Stunden und nur einmal. Die Person bekommt einen eigenen Bereich – "
        "sie sieht nichts von deinen Stellen oder deiner Merkliste.",
    )


async def cmd_personen(update, context) -> None:
    deps = deps_of(context)
    if user_of(update) != deps.admin_id:
        return
    for uid, name in deps.registry.users_with_names():
        settings = deps.space(uid).store.load_settings()
        text, markup = format_person(uid, name, settings, is_admin=uid == deps.admin_id)
        await send_text(context.bot, deps.admin_id, text, reply_markup=markup)


async def on_person_button(update, context) -> None:
    deps = deps_of(context)
    query = update.callback_query
    if query is None or user_of(update) != deps.admin_id:
        return
    action, _, raw_id = (query.data or "").partition(":")
    if not raw_id.isdigit():
        await query.answer()
        return
    uid = int(raw_id)
    if action == "rm":
        await query.answer("Wirklich entfernen?")
        await _set_markup(query, remove_confirm_buttons(uid))
    elif action == "rmy":
        if deps.registry.remove(uid):
            deps.forget(uid)
            await query.answer("Entfernt")
            await _set_markup(query, None)
            await send_text(context.bot, deps.admin_id,
                            "🗑️ Zugang entzogen. Die Daten der Person bleiben gespeichert – "
                            "mit einer neuen Einladung wäre alles wieder da.")
        else:
            await query.answer("Das geht nicht")
    elif action == "rmn":
        await query.answer("Abgebrochen")
        await _set_markup(query, format_person(uid, None, deps.space(uid).store.load_settings(), False)[1])
    else:
        await query.answer()
