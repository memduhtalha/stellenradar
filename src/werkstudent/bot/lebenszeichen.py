"""Lebenszeichen: Ausfälle sichtbar machen.

- Beim Start: War der Bot lange aus (PC aus, Docker gestoppt), bekommt der Admin einen Hinweis.
- Optional: Ping an einen externen Wächter (z. B. healthchecks.io, kostenlos). Bleibt der Ping aus,
  meldet sich der Wächter – das kann der Bot selbst nicht, wenn er gar nicht läuft.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from werkstudent.bot.senden import send_text

log = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
PAUSE_NOTICE_AFTER = timedelta(hours=12)
PING_EVERY = timedelta(minutes=10)


def mark_alive(deps, now: datetime) -> None:
    deps.registry.set_meta("last_alive", now.isoformat())


async def startup_notice(deps, bot, now: datetime) -> None:
    alive = deps.registry.get_meta("last_alive")
    if alive:
        last = datetime.fromisoformat(alive)  # wann der Bot zuletzt lief – unabhängig vom Sucherfolg
    else:
        runs = [deps.space(uid).store.last_successful_run() for uid in deps.registry.users()]
        last = max(filter(None, runs), default=None)
    if last is None or now - last < PAUSE_NOTICE_AFTER:
        return
    hours = int((now - last).total_seconds() // 3600)
    since = last.astimezone(BERLIN).strftime("%d.%m. %H:%M")
    await send_text(
        bot,
        deps.admin_id,
        f"👋 Wieder da – ich war ca. {hours} Std. offline (zuletzt aktiv: {since}). "
        "Ich hole die Suche jetzt nach.",
    )


async def maybe_ping(deps, now: datetime) -> None:
    url = getattr(deps, "healthcheck_url", None)
    ping = getattr(deps, "ping", None)
    last = getattr(deps, "_last_ping", None)
    if not url or ping is None or (last and now - last < PING_EVERY):
        return
    deps._last_ping = now
    try:
        await ping(url)
    except Exception as e:  # noqa: BLE001 – der Wächter darf den Bot nie stören
        log.info("Wächter-Ping fehlgeschlagen: %s", e)
