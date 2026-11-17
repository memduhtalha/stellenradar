"""Telegram-Texte (HTML) und Buttons – reine Funktionen."""
from __future__ import annotations

import re
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from werkstudent.lauf import SOURCE_NAMES
from werkstudent.modelle import Category, ProcessedJob
from werkstudent.speicher.store import SourceState

BERLIN = ZoneInfo("Europe/Berlin")
MAX_LEN = 4096


def source_label(name: str) -> str:
    return SOURCE_NAMES.get(name, name)


def _age(posted: datetime, now: datetime) -> str:
    hours = int((now - posted).total_seconds() // 3600)
    if hours < 24:
        return f"vor {max(hours, 1)} Std."
    days = hours // 24
    return "vor 1 Tag" if days == 1 else f"vor {days} Tagen"


def job_buttons(job_id: int, bookmarked: bool = False) -> InlineKeyboardMarkup:
    bookmark = (
        InlineKeyboardButton("✅ Gemerkt", callback_data=f"ub:{job_id}")
        if bookmarked
        else InlineKeyboardButton("⭐ Merken", callback_data=f"bm:{job_id}")
    )
    return InlineKeyboardMarkup([[bookmark, InlineKeyboardButton("👎 Uninteressant", callback_data=f"dz:{job_id}")]])


def format_job(
    job_id: int, p: ProcessedJob, categories: dict[str, Category], now: datetime, bookmarked: bool = False
) -> tuple[str, InlineKeyboardMarkup]:
    j = p.job
    tags = [f"{categories[k].emoji} {categories[k].label}" for k in p.categories if k in categories]
    if p.kind == "ausbildung":
        tags.append("🎓 Ausbildung")
    if p.kind == "praktikum":
        tags.append("🎓 Praktikum/Abschlussarbeit")
    if j.remote:
        tags.append("🏠 Remote")
    head = ("🔥 " if p.is_top else "") + " · ".join(tags)

    place = f"📍 {escape(j.location or 'Ort unbekannt')}"
    if p.distance_km is not None:
        place += f" ({round(p.distance_km)} km)"

    meta = f"Quelle: {source_label(j.source)}"
    if p.also_on:
        meta += f" (auch auf: {', '.join(source_label(s) for s, _ in p.also_on)})"
    if j.posted_at is not None:
        meta = f"📅 {_age(j.posted_at, now)} · {meta}"

    links = [f'🔗 <a href="{escape(j.url)}">Zur Anzeige</a>']
    links += [f'<a href="{escape(u)}">{source_label(s)}</a>' for s, u in p.also_on]

    lines = [
        escape(head),
        f"<b>{escape(j.title)}</b>",
        f"🏢 {escape(j.company or 'Firma unbekannt')} · {place}",
        meta,
    ]
    if dates := _training_dates(j.snippet):
        lines.append(escape(dates))
    if p.is_top and (excerpt := _excerpt(j.description or j.snippet)):
        lines.append(f"<i>{escape(excerpt)}</i>")
    lines.append(" · ".join(links))
    return "\n".join(lines), job_buttons(job_id, bookmarked)


def _training_dates(snippet: str) -> str | None:
    """„Ausbildungsbeginn … · Bewerbung bis …“ aus dem Vorschautext als eigene Zeile."""
    start = re.search(r"Ausbildungsbeginn ([^·]+?)\s*(?:·|$)", snippet or "")
    deadline = re.search(r"Bewerbung bis ([\d.]+)", snippet or "")
    parts = [f"🗓️ Beginn {start.group(1)}" if start else "", f"⏳ Bewerbung bis {deadline.group(1)}" if deadline else ""]
    return " · ".join(p for p in parts if p) or None


EXCERPT_MIN = 40
EXCERPT_MAX = 200


def _excerpt(text: str | None) -> str | None:
    """Kurzer Ausschnitt aus der Beschreibung, damit man nicht jede Anzeige öffnen muss."""
    t = " ".join((text or "").split())
    if len(t) < EXCERPT_MIN:
        return None
    if len(t) <= EXCERPT_MAX:
        return t
    return t[:EXCERPT_MAX].rsplit(" ", 1)[0] + " …"


def format_backlog_intro(total: int) -> str:
    return f"📦 Rückstau: {total} neue Stellen – hier die Top 10."


def _split(header: str, lines: list[str]) -> list[str]:
    messages: list[str] = []
    current = header
    for line in lines:
        if len(current) + 1 + len(line) > MAX_LEN:
            messages.append(current)
            current = line
        else:
            current = f"{current}\n{line}"
    messages.append(current)
    return messages


def format_job_line(p: ProcessedJob) -> str:
    j = p.job
    return f'• <a href="{escape(j.url)}">{escape(j.title)}</a> – {escape(j.company)}, {escape(j.location)}'


def format_digest(items: list[ProcessedJob]) -> list[str]:
    if not items:
        return []
    return _split(f"🗓️ <b>Tageszusammenfassung:</b> {len(items)} weitere Stellen", [format_job_line(p) for p in items])


MAX_BOOKMARK_CARDS = 20


def format_bookmarks_header(total: int) -> str:
    noun = "Stelle" if total == 1 else "Stellen"
    text = f"⭐ <b>Merkliste</b> – {total} {noun}"
    if total > MAX_BOOKMARK_CARDS:
        text += f" (hier die {MAX_BOOKMARK_CARDS} zuletzt gemerkten)"
    return text


def format_bookmark_card(
    job_id: int,
    p: ProcessedJob,
    categories: dict[str, Category],
    saved_at: datetime,
    applied_at: datetime | None = None,
    offline_days: int | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    j = p.job
    place = f"📍 {escape(j.location or 'Ort unbekannt')}"
    if p.distance_km is not None:
        place += f" ({round(p.distance_km)} km)"
    tags = " · ".join(f"{categories[k].emoji} {categories[k].label}" for k in p.categories if k in categories)
    lines = [
        f"<b>{escape(j.title)}</b>",
        f"🏢 {escape(j.company or 'Firma unbekannt')}",
        place,
        f"{escape(tags)}" if tags else "",
        (f"✅ beworben am {applied_at.astimezone(BERLIN).strftime('%d.%m.')}" if applied_at
         else f"⭐ gemerkt am {saved_at.astimezone(BERLIN).strftime('%d.%m.')}") + f" · {source_label(j.source)}",
        f"⚠️ seit {offline_days} Tagen nicht mehr in den Suchergebnissen – evtl. abgelaufen" if offline_days else "",
    ]
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 Zur Anzeige", url=j.url),
        InlineKeyboardButton("🗑️ Entfernen", callback_data=f"ubl:{job_id}"),
    ]])
    return "\n".join(line for line in lines if line), markup


def format_reminder(job_id: int, p: ProcessedJob, missing: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    j = p.job
    text = "\n".join([
        "⏰ <b>Erinnerung</b> – diese Stelle hast du dir gemerkt:",
        f"<b>{escape(j.title)}</b>",
        f"🏢 {escape(j.company or 'Firma unbekannt')} · 📍 {escape(j.location or 'Ort unbekannt')}",
        *(["⚠️ Taucht nicht mehr in den Suchergebnissen auf – kurz prüfen, ob sie noch online ist."] if missing else []),
        "Schon beworben?",
    ])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Beworben", callback_data=f"ap:{job_id}"),
         InlineKeyboardButton("⏰ In 3 Tagen", callback_data=f"snz:{job_id}")],
        [InlineKeyboardButton("🔗 Zur Anzeige", url=j.url)],
    ])
    return text, markup


def format_weekly(stats: dict) -> str:
    lines = ["📅 <b>Wochenrückblick</b>", f"🆕 {stats['neu']} neue passende Stellen"]
    if stats["quellen"]:
        lines.append("   " + " · ".join(f"{source_label(s)} {n}" for s, n in stats["quellen"].items()))
    lines.append(f"⭐ {stats['gemerkt_offen']} gemerkte Stellen ohne Bewerbung")
    lines.append(f"✅ {stats['beworben']} Bewerbungen diese Woche")
    if stats["gemerkt_offen"]:
        lines.append("\nTipp: /gemerkt zeigt deine Merkliste.")
    return "\n".join(lines)


def format_person(user_id: int, name: str | None, settings, is_admin: bool) -> tuple[str, InlineKeyboardMarkup | None]:
    who = escape(name) if name else f"Person {user_id}"
    art = "Ausbildung" if settings.art == "ausbildung" else "Werkstudent"
    state = (f"{art} · {escape(settings.location)} · {settings.radius_km} km" if settings.onboarded
             else "noch nicht eingerichtet")
    text = f"👤 <b>{who}</b>{' (du)' if is_admin else ''}\n{state}"
    if is_admin:
        return text, None
    return text, InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Entfernen", callback_data=f"rm:{user_id}")]])


def remove_confirm_buttons(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑️ Ja, entfernen", callback_data=f"rmy:{user_id}"),
        InlineKeyboardButton("↩️ Abbrechen", callback_data=f"rmn:{user_id}"),
    ]])


def dismiss_confirm_buttons(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👎 Ja, ausblenden", callback_data=f"dzy:{job_id}"),
        InlineKeyboardButton("↩️ Abbrechen", callback_data=f"dzn:{job_id}"),
    ]])


def _time(t: datetime | None) -> str:
    return t.astimezone(BERLIN).strftime("%d.%m. %H:%M") if t else "–"


def format_status(
    states: dict[str, SourceState],
    counts: dict[str, int | str],
    last_run: datetime | None,
    next_run: datetime | None,
    paused: bool,
) -> str:
    lines = [
        "📊 <b>Status</b>",
        f"Letzter erfolgreicher Lauf: {_time(last_run)}",
        f"Nächster Lauf: {_time(next_run)}",
    ]
    if paused:
        lines.append("⏸️ Benachrichtigungen pausiert – /weiter zum Fortsetzen")
    lines.append("")
    for name in sorted(set(states) | set(counts)):
        st = states.get(name, SourceState())
        count = counts.get(name)
        if isinstance(count, int) and st.consecutive_failures == 0:
            icon, info = "✅", f"{count} Treffer"
        elif count == "pausiert":
            icon, info = "⏳", "diesmal ausgesetzt (Stundenlimit)"
        elif st.consecutive_failures:
            icon = "⛔" if count == "blockiert" else "⚠️"
            info = f"{count if isinstance(count, str) else 'keine Treffer'} – {st.consecutive_failures}× in Folge"
        else:
            icon, info = "▫️", "noch nicht gelaufen"
        lines.append(f"{icon} {source_label(name)}: {escape(str(info))} (zuletzt ok: {_time(st.last_ok_at)})")
    return "\n".join(lines)


# --- /alle -------------------------------------------------------------------------------------

ALLE_PAGE_SIZE = 10
ALLE_COUNTS = [10, 25, 50, 0]  # 0 = alle


def alle_count_question() -> tuple[str, InlineKeyboardMarkup]:
    labels = {0: "Alle"}
    row = [InlineKeyboardButton(labels.get(n, str(n)), callback_data=f"al:n:{n}") for n in ALLE_COUNTS]
    return (
        "📋 <b>Alle aktuellen Stellen</b>\nIch suche jetzt live auf allen Portalen – auch Stellen, "
        "die du schon bekommen hast.\n\nWie viele möchtest du sehen (die besten zuerst)?",
        InlineKeyboardMarkup([row]),
    )


def _alle_line(n: int, p: ProcessedJob, is_new: bool, bookmarked: bool, applied: bool) -> str:
    j = p.job
    marks = "".join([
        "🆕 " if is_new else "",
        "🔥 " if p.is_top else "",
        "✅ " if applied else ("⭐ " if bookmarked else ""),
    ])
    place = escape(j.location or "Ort unbekannt")
    if p.distance_km is not None:
        place += f" ({round(p.distance_km)} km)"
    return (f"{n}. {marks}<b>{escape(j.title)}</b>\n"
            f"    {escape(j.company or 'Firma unbekannt')} · {place} · {source_label(j.source)}")


def format_alle_page(
    entries: list[tuple[int, ProcessedJob, bool]],
    page: int,
    total_found: int,
    new_count: int,
    searched_at: datetime,
    bookmarked: set[int],
    applied: set[int],
) -> tuple[str, InlineKeyboardMarkup]:
    """Eine Seite der Liste. entries = die angezeigten Stellen (bereits auf die gewählte Anzahl gekürzt)."""
    pages = max(1, -(-len(entries) // ALLE_PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    start = page * ALLE_PAGE_SIZE
    chunk = entries[start:start + ALLE_PAGE_SIZE]

    head = f"📋 <b>Aktuelle Stellen</b> – {total_found} gefunden"
    if new_count:
        head += f", davon {new_count} neu 🆕"
    if len(entries) < total_found:
        head += f" · die besten {len(entries)}"
    head += f"\nStand: {searched_at.astimezone(BERLIN).strftime('%d.%m. %H:%M')} · Seite {page + 1}/{pages}"
    if not entries:
        return head + "\n\nGerade keine passenden Stellen online.", InlineKeyboardMarkup([])

    lines = [_alle_line(start + i + 1, p, new, jid in bookmarked, jid in applied)
             for i, (jid, p, new) in enumerate(chunk)]
    numbers = [InlineKeyboardButton(str(start + i + 1), callback_data=f"al:j:{start + i}") for i in range(len(chunk))]
    rows = [numbers[:5], numbers[5:]] if len(numbers) > 5 else [numbers]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Zurück", callback_data=f"al:p:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Weiter ▶️", callback_data=f"al:p:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("📄 Als Datei", callback_data="al:f")])
    hint = "\n\nTippe auf eine Nummer für Link, ⭐ und 👎."
    return head + "\n\n" + "\n".join(lines) + hint, InlineKeyboardMarkup([r for r in rows if r])


def alle_html(entries: list[tuple[int, ProcessedJob, bool]], searched_at: datetime) -> bytes:
    """Ganze Liste als eine HTML-Datei – am Handy öffnen, Links anklickbar, durchsuchbar."""
    rows = []
    for n, (_, p, new) in enumerate(entries, 1):
        j = p.job
        dist = f"{round(p.distance_km)} km" if p.distance_km is not None else ""
        rows.append(
            f"<tr><td>{n}</td><td>{'🆕 ' if new else ''}{'🔥 ' if p.is_top else ''}"
            f'<a href="{escape(j.url)}">{escape(j.title)}</a></td>'
            f"<td>{escape(j.company)}</td><td>{escape(j.location)}</td><td>{dist}</td>"
            f"<td>{source_label(j.source)}</td></tr>"
        )
    stand = searched_at.astimezone(BERLIN).strftime("%d.%m.%Y %H:%M")
    html = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Aktuelle Stellen</title>
<style>body{{font-family:system-ui,sans-serif;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:6px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}a{{color:#0b57d0}}</style>
</head><body><h1>Aktuelle Stellen ({len(entries)})</h1><p>Stand: {stand}</p>
<table><tr><th>#</th><th>Stelle</th><th>Firma</th><th>Ort</th><th>Entf.</th><th>Quelle</th></tr>
{''.join(rows)}</table></body></html>"""
    return html.encode("utf-8")
