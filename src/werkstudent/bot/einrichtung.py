"""Einrichtung per Fragen und Buttons: /start (alle Fragen) und /einstellungen (einzelne Punkte).

Jede Person richtet ihren eigenen Bereich ein. Neue Personen kommen nur über einen Einladungslink hinein.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from html import escape

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Kb
from telegram.constants import ParseMode

from werkstudent.bot.befehle import deps_of, reply, run_and_send, space_of, user_of
from werkstudent.modelle import UserSettings

STEPS = {
    "werkstudent": ["art", "ort", "radius", "cats", "remote", "intern", "mode"],
    "ausbildung": ["art", "ort", "radius", "cats", "mode"],  # Remote/Praktika passen nicht zur Ausbildung
}
ARTS = [("werkstudent", "🎓 Werkstudentenstelle"), ("ausbildung", "🧰 Ausbildungsplatz")]
RADII = [10, 25, 40, 60]
INTERVALS = [30, 60, 120]
HOURS = [(6, 22), (7, 22), (8, 20), (0, 24)]
DIGEST_HOURS = [12, 18, 20]
DEFAULT_PLACE = ("Düsseldorf", 51.2277, 6.7735)
log = logging.getLogger(__name__)

MENU = [
    ("art", "🧭 Suchart"),
    ("ort", "📍 Ort"),
    ("radius", "📏 Umkreis"),
    ("cats", "🗂️ Bereiche"),
    ("remote", "🏠 Remote"),
    ("intern", "🎓 Praktika"),
    ("mode", "🔔 Meldungen"),
    ("interval", "⏱️ Intervall"),
    ("hours", "🕖 Suchzeiten"),
    ("digest", "🗓️ Sammelnachricht"),
]
WERKSTUDENT_ONLY = {"remote", "intern"}


def _mark(selected: bool, label: str) -> str:
    return f"✓ {label}" if selected else label


def _yes_no(prefix: str, current: bool) -> Kb:
    return Kb([[Btn(_mark(current, "Ja"), callback_data=f"set:{prefix}:1"),
                Btn(_mark(not current, "Nein"), callback_data=f"set:{prefix}:0")]])


def _categories_for(art: str, categories) -> list:
    return [c for c in categories if c.art == art]


def _cats_keyboard(draft: UserSettings, categories) -> Kb:
    rows = [
        [Btn(f"{'✅' if c.key in draft.categories else '☐'} {c.emoji} {c.label}", callback_data=f"set:cat:{c.key}")]
        for c in _categories_for(draft.art, categories)
    ]
    rows.append([Btn("Fertig", callback_data="set:cat:done")])
    return Kb(rows)


def _question(step: str, draft: UserSettings, categories) -> tuple[str, Kb]:
    if step == "art":
        return ("🧭 Was suchst du?",
                Kb([[Btn(_mark(key == draft.art, label), callback_data=f"set:art:{key}")] for key, label in ARTS]))
    if step == "ort":
        return ("📍 Wo suchst du? Schreib einen Ort oder tippe auf Düsseldorf.",
                Kb([[Btn("Düsseldorf", callback_data="set:ort:default")]]))
    if step == "radius":
        return ("📏 Welcher Umkreis?",
                Kb([[Btn(_mark(r == draft.radius_km, f"{r} km"), callback_data=f"set:radius:{r}") for r in RADII]]))
    if step == "cats":
        return "🗂️ Welche Bereiche interessieren dich? Tippe zum An-/Abwählen.", _cats_keyboard(draft, categories)
    if step == "remote":
        return "🏠 Sollen reine Remote-Stellen aus ganz Deutschland auch kommen?", _yes_no("remote", draft.remote)
    if step == "intern":
        return "🎓 Praktika und Abschlussarbeiten auch?", _yes_no("intern", draft.internships)
    if step == "mode":
        return (f"🔔 Stellen ohne 🔥 sofort schicken oder gesammelt um {draft.digest_hour} Uhr?",
                Kb([[Btn(_mark(draft.digest_mode == "sofort", "Sofort"), callback_data="set:mode:sofort"),
                     Btn(_mark(draft.digest_mode == "taeglich", "Tägliche Sammelnachricht"),
                         callback_data="set:mode:taeglich")]]))
    if step == "interval":
        return (f"⏱️ Wie oft soll ich suchen ({draft.active_from}–{draft.active_to} Uhr)?",
                Kb([[Btn(_mark(m == draft.interval_minutes, f"{m} Min"), callback_data=f"set:interval:{m}")
                     for m in INTERVALS]]))
    if step == "hours":
        def label(a: int, b: int) -> str:
            return "rund um die Uhr" if (a, b) == (0, 24) else f"{a}–{b} Uhr"

        return ("🕖 Zu welchen Zeiten soll ich suchen?",
                Kb([[Btn(_mark((a, b) == (draft.active_from, draft.active_to), label(a, b)),
                         callback_data=f"set:hours:{a}-{b}")] for a, b in HOURS]))
    if step == "digest":
        return ("🗓️ Um wie viel Uhr soll die Sammelnachricht kommen?",
                Kb([[Btn(_mark(h == draft.digest_hour, f"{h} Uhr"), callback_data=f"set:digest:{h}")
                     for h in DIGEST_HOURS]]))
    raise ValueError(step)


def summary(s: UserSettings, categories) -> str:
    cats = ", ".join(f"{c.emoji} {c.label}" for c in categories if c.key in s.categories and c.art == s.art)
    art = dict(ARTS)[s.art]
    lines = [
        "✅ <b>Gespeichert</b>",
        f"{art} · 📍 {escape(s.location)} · {s.radius_km} km",
        f"🗂️ {escape(cats)}",
    ]
    if s.art == "werkstudent":
        lines.append(f"🏠 Remote: {'ja' if s.remote else 'nein'} · 🎓 Praktika: {'ja' if s.internships else 'nein'}")
    lines.append(
        f"🔔 {'Sofort' if s.digest_mode == 'sofort' else f'Top sofort, Rest um {s.digest_hour} Uhr'}"
        f" · ⏱️ alle {s.interval_minutes} Min, {s.active_from}–{s.active_to} Uhr"
    )
    return "\n".join(lines)


async def _send(context, chat_id: int, text: str, markup: Kb | None = None) -> None:
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _ask(context, chat_id: int, step: str) -> None:
    setup = context.user_data["setup"]
    setup["step"] = step
    text, markup = _question(step, setup["draft"], deps_of(context).categories)
    await _send(context, chat_id, text, markup)


def _changed(setup: dict, *names: str) -> None:
    setup.setdefault("changed", set()).update(names)


def _draft_from(s: UserSettings) -> UserSettings:
    return replace(s, categories=set(s.categories))


def _new_setup(draft: UserSettings, wizard: bool, first: bool, user_id: int) -> dict:
    return {"wizard": wizard, "draft": draft, "first": first, "step": None, "user_id": user_id}


async def cmd_start(update, context) -> None:
    deps = deps_of(context)
    uid = user_of(update)
    if uid is None:
        return
    if not deps.registry.is_user(uid):
        code = (context.args or [None])[0]
        name = getattr(update.effective_user, "first_name", None)
        if not code or not deps.registry.redeem(code, uid, datetime.now(UTC), name=name):
            await reply(update, "🔒 Dieser Bot ist privat. Bitte um einen neuen Einladungslink.")
            return
        try:
            await _send(context, deps.admin_id, f"👋 Eine neue Person ({uid}) hat deine Einladung angenommen.")
        except Exception:  # noqa: BLE001 – die Einrichtung der neuen Person geht trotzdem weiter
            log.warning("Admin nicht benachrichtigt")
    sp = deps.space(uid)
    current = sp.store.load_settings()
    context.user_data["setup"] = _new_setup(_draft_from(current), wizard=True, first=not current.onboarded,
                                            user_id=uid)
    chat = update.effective_chat.id
    await _send(context, chat, "👋 Hallo! Ich frage dich kurz ein paar Dinge, dann suche ich los.")
    await _ask(context, chat, STEPS[current.art][0])


async def cmd_einstellungen(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    draft = _draft_from(sp.store.load_settings())
    context.user_data["setup"] = _new_setup(draft, wizard=False, first=False, user_id=sp.user_id)
    rows = [[Btn(label, callback_data=f"menu:{key}")] for key, label in MENU
            if draft.art == "werkstudent" or key not in WERKSTUDENT_ONLY]
    await _send(context, update.effective_chat.id, "⚙️ Was möchtest du ändern?", Kb(rows))


async def _advance(context, chat_id: int) -> None:
    setup = context.user_data["setup"]
    if setup["wizard"]:
        steps = STEPS[setup["draft"].art]
        idx = steps.index(setup["step"]) + 1 if setup["step"] in steps else len(steps)
        if idx < len(steps):
            await _ask(context, chat_id, steps[idx])
            return
    await _finish(context, chat_id)


async def _finish(context, chat_id: int) -> None:
    deps = deps_of(context)
    setup = context.user_data.pop("setup")
    sp = deps.space(setup["user_id"])
    draft: UserSettings = setup["draft"]
    # Nur die beantworteten Felder übernehmen – der Entwurf kann veraltet sein (z. B. /pause seitdem).
    current = sp.store.load_settings()
    for name in setup.get("changed", set()):
        setattr(current, name, getattr(draft, name))
    current.onboarded = True
    sp.store.save_settings(current)
    await _send(context, chat_id, summary(current, deps.categories))
    if setup["first"]:
        await _send(context, chat_id, "🔎 Erste Suche läuft – das kann ein paar Minuten dauern …")
        await run_and_send(context, sp.user_id)


async def on_text(update, context) -> None:
    sp = space_of(update, context)
    if sp is None:
        return
    setup = context.user_data.get("setup")
    if not setup or setup.get("step") != "ort" or update.message is None:
        return
    place = (update.message.text or "").strip()
    chat = update.effective_chat.id
    coords = await sp.geocoder.locate(place) if place else None
    if coords is None:
        await _send(context, chat, "Ort nicht gefunden, bitte nochmal.")
        return
    draft = setup["draft"]
    draft.location, (draft.lat, draft.lon) = place, coords
    _changed(setup, "location", "lat", "lon")
    await _advance(context, chat)


def _switch_art(draft: UserSettings, art: str, categories) -> None:
    """Neue Suchart → Bereiche auf deren Standard setzen; Remote/Praktika gibt es nur für Werkstudenten."""
    if art == draft.art:
        return
    draft.art = art
    draft.categories = {c.key for c in _categories_for(art, categories) if c.default_on}
    if art != "werkstudent":
        draft.remote = draft.internships = False


async def on_button(update, context) -> None:
    deps = deps_of(context)
    query = update.callback_query
    sp = space_of(update, context)
    if query is None or sp is None:
        return
    chat = update.effective_chat.id
    kind, _, rest = (query.data or "").partition(":")

    if kind == "menu":
        setup = context.user_data.get("setup")
        if setup is None or setup["wizard"]:
            context.user_data["setup"] = setup = _new_setup(
                _draft_from(sp.store.load_settings()), wizard=False, first=False, user_id=sp.user_id
            )
        if rest in WERKSTUDENT_ONLY and setup["draft"].art != "werkstudent":  # alter Menü-Button
            await query.answer("Nur bei Werkstudentenstellen")
            return
        await query.answer()
        await _ask(context, chat, rest)
        return

    setup = context.user_data.get("setup")
    if kind != "set" or setup is None:
        await query.answer("Bitte /einstellungen neu öffnen.")
        return
    field, _, value = rest.partition(":")
    draft: UserSettings = setup["draft"]

    if field == "cat":
        if value == "done":
            if not draft.categories:
                await query.answer("Bitte mindestens einen Bereich wählen.")
                return
            _changed(setup, "categories")
        else:
            draft.categories ^= {value}
            await query.answer()
            await query.edit_message_reply_markup(reply_markup=_cats_keyboard(draft, deps.categories))
            return
    elif field == "art":
        if value not in STEPS:
            await query.answer()
            return
        _switch_art(draft, value, deps.categories)
        _changed(setup, "art", "categories", "remote", "internships")
        if not setup["wizard"]:  # über /einstellungen: passende Bereiche gleich mit abfragen
            await query.answer()
            await query.edit_message_reply_markup(reply_markup=None)
            await _ask(context, chat, "cats")
            return
    elif field == "ort":
        draft.location, draft.lat, draft.lon = DEFAULT_PLACE
        _changed(setup, "location", "lat", "lon")
    elif field == "radius":
        draft.radius_km = int(value)
        _changed(setup, "radius_km")
    elif field == "remote":
        draft.remote = value == "1"
        _changed(setup, "remote")
    elif field == "intern":
        draft.internships = value == "1"
        _changed(setup, "internships")
    elif field == "mode":
        draft.digest_mode = "taeglich" if value == "taeglich" else "sofort"
        _changed(setup, "digest_mode")
    elif field == "interval":
        draft.interval_minutes = int(value)
        _changed(setup, "interval_minutes")
    elif field == "hours":
        start, _, end = value.partition("-")
        draft.active_from, draft.active_to = int(start), int(end)
        _changed(setup, "active_from", "active_to")
    elif field == "digest":
        draft.digest_hour = int(value)
        _changed(setup, "digest_hour")
    else:
        await query.answer()
        return

    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await _advance(context, chat)
