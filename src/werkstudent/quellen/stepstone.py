"""Quelle: StepStone (gerendert über Lightpanda, Fallback Chromium)."""
from __future__ import annotations

import re
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import SourceError, polite_sleep
from werkstudent.quellen.browser import Browser

BASE = "https://www.stepstone.de"
CARD = 'article[data-at="job-item"]'
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().translate(_UMLAUTE)).strip("-")


def search_url(term: str, location: str, radius_km: int) -> str:
    return f"{BASE}/jobs/{slug(term)}/in-{slug(location)}?radius={radius_km}&ag=age_7"


def _text(node, selector: str) -> str:
    n = node.css_first(selector)
    return n.text(deep=True, separator=" ", strip=True) if n else ""


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_search(html: str) -> list[Job]:
    tree = LexborHTMLParser(html)
    jobs: dict[str, Job] = {}
    for card in tree.css(CARD):
        source_id = (card.attributes.get("id") or "").removeprefix("job-item-")
        link = card.css_first('a[data-at="job-item-title"]')
        if not source_id or link is None or source_id in jobs:
            continue
        href = link.attributes.get("href") or ""
        if href.startswith("/"):
            href = BASE + href
        time_node = card.css_first("time")
        jobs[source_id] = Job(
            source="stepstone",
            source_id=source_id,
            title=link.text(deep=True, strip=True),
            company=_text(card, '[data-at="job-item-company-name"]'),
            location=_text(card, '[data-at="job-item-location"]'),
            url=href.split("?")[0],
            snippet=_text(card, '[data-at="jobcard-content"]'),
            posted_at=_parse_time(time_node.attributes.get("datetime") if time_node else None),
        )
    return list(jobs.values())


def parse_detail(html: str) -> str:
    node = LexborHTMLParser(html).css_first('[data-at="job-ad-content"]')
    return node.text(deep=True, separator=" ", strip=True) if node else ""


class StepStoneSource:
    name = "stepstone"

    def __init__(self, browser: Browser):
        self._browser = browser

    async def _fetch(self, url: str) -> list[Job]:
        # Seiten ohne Treffer haben keine Karten → trotzdem zurückgeben statt Fehler.
        html = await self._browser.fetch_html(url, CARD, return_on_timeout=True)
        return parse_search(html)

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        found: dict[str, Job] = {}
        urls = [search_url(t, settings.location, settings.radius_km) for c in categories for t in c.search_terms]
        remote_urls = (
            [search_url(t, "Homeoffice", settings.radius_km) for c in categories for t in c.search_terms[:1]]
            if settings.remote
            else []
        )
        plan = [(u, False) for u in urls] + [(u, True) for u in remote_urls]
        errors: list[SourceError] = []
        for i, (url, remote) in enumerate(plan):
            if i:
                await polite_sleep()
            try:
                jobs = await self._fetch(url)
            except SourceError as e:  # eine kaputte Suchseite darf die anderen nicht mitreißen
                errors.append(e)
                continue
            for job in jobs:
                if remote:
                    job.remote = True
                if job.source_id in found:
                    found[job.source_id].remote |= job.remote
                else:
                    found[job.source_id] = job
        if plan and len(errors) == len(plan):
            raise errors[0]
        return list(found.values())

    async def fetch_detail(self, job: Job) -> str | None:
        html = await self._browser.fetch_html(job.url, '[data-at="job-ad-content"]')
        return parse_detail(html) or None
