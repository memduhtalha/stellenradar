"""Ergebnisse eines Laufs an Telegram schicken – mit Rücksicht auf das Flood-Limit."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError

from werkstudent.bot.nachrichten import format_backlog_intro, format_job
from werkstudent.lauf import RunResult
from werkstudent.modelle import Category

log = logging.getLogger(__name__)

PAUSE_S = 1.1
MAX_ATTEMPTS = 3


def _seconds(value) -> float:
    return value.total_seconds() if isinstance(value, timedelta) else float(value)


async def send_text(bot, chat_id: int, text: str, sleep=asyncio.sleep, **kwargs) -> bool:
    for _ in range(MAX_ATTEMPTS):
        try:
            await bot.send_message(
                chat_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kwargs
            )
            return True
        except RetryAfter as e:
            await sleep(_seconds(e.retry_after))
        except BadRequest as e:  # Unterklasse von NetworkError, ein neuer Versuch hilft nicht
            log.warning("Nachricht abgelehnt: %s", e)
            return False
        except NetworkError as e:  # inkl. TimedOut – kurz warten und erneut versuchen
            log.info("Netzwerkfehler beim Senden: %s", e)
            await sleep(2)
        except TelegramError as e:
            log.warning("Nachricht nicht gesendet: %s", e)
            return False
    log.warning("Nachricht nach %d Versuchen aufgegeben", MAX_ATTEMPTS)
    return False


async def send_jobs(
    bot,
    chat_id: int,
    result: RunResult,
    categories: dict[str, Category],
    now: datetime,
    sleep=asyncio.sleep,
) -> list[int]:
    """Schickt Warnungen, Rückstau-Info und Stellen. Gibt die IDs der nicht zugestellten Stellen zurück."""
    for w in result.warnings:
        await send_text(bot, chat_id, w, sleep)
    if result.backlog_total is not None and result.to_send:
        await send_text(bot, chat_id, format_backlog_intro(result.backlog_total), sleep)
    failed: list[int] = []
    for i, (job_id, p) in enumerate(result.to_send):
        if i:
            await sleep(PAUSE_S)
        text, markup = format_job(job_id, p, categories, now)
        if not await send_text(bot, chat_id, text, sleep, reply_markup=markup):
            failed.append(job_id)
    return failed
