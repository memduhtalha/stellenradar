"""Gemeinsame Schnittstelle aller Quellen."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Protocol

from werkstudent.modelle import Category, Job, UserSettings

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


class SourceError(Exception):
    """Quelle hat nicht funktioniert (Netzwerk, Format, Browser …)."""


class SourceBlocked(SourceError):
    """Quelle zeigt Captcha oder Bot-Schutz – wird nicht umgangen."""


class SourceSkipped(Exception):
    """Quelle setzt diesen Lauf bewusst aus (z. B. Stundenlimit) – zählt nicht als Ausfall."""


class Source(Protocol):
    name: str

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]: ...

    async def fetch_detail(self, job: Job) -> str | None: ...


async def polite_sleep(min_s: float = 2, max_s: float = 5) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


def unique_by_id(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    out: list[Job] = []
    for j in jobs:
        if j.source_id not in seen:
            seen.add(j.source_id)
            out.append(j)
    return out
