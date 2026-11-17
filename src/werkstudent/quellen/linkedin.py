"""Quelle: LinkedIn – nur die öffentliche Gast-Jobsuche, ohne Login, höchstens 1 Durchlauf pro Stunde."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from selectolax.lexbor import LexborHTMLParser

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import (
    BROWSER_USER_AGENT,
    SourceBlocked,
    SourceError,
    SourceSkipped,
    polite_sleep,
)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
MIN_GAP = timedelta(minutes=60)
BERLIN = ZoneInfo("Europe/Berlin")
_HEADERS = {"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"}


def _text(node, selector: str) -> str:
    n = node.css_first(selector)
    return n.text(deep=True, strip=True) if n else ""


def parse_search(html: str) -> list[Job]:
    tree = LexborHTMLParser(html)
    jobs: dict[str, Job] = {}
    for card in tree.css("div.base-card"):
        urn = card.attributes.get("data-entity-urn") or ""
        job_id = urn.rsplit(":", 1)[-1]
        link = card.css_first("a.base-card__full-link")
        if not job_id.isdigit() or link is None or job_id in jobs:
            continue
        time_node = card.css_first("time")
        posted = None
        if time_node and time_node.attributes.get("datetime"):
            try:
                posted = datetime.fromisoformat(time_node.attributes["datetime"]).replace(tzinfo=BERLIN)
            except ValueError:
                pass
        jobs[job_id] = Job(
            source="linkedin",
            source_id=job_id,
            title=_text(card, "h3.base-search-card__title"),
            company=_text(card, "h4.base-search-card__subtitle"),
            location=_text(card, "span.job-search-card__location"),
            url=(link.attributes.get("href") or "").split("?")[0],
            posted_at=posted,
        )
    return list(jobs.values())


class LinkedInSource:
    name = "linkedin"

    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        self._last_run: datetime | None = None

    async def _get(self, url: str, params: dict | None = None) -> str:
        try:
            r = await self._client.get(url, params=params, headers=_HEADERS, timeout=20)
        except httpx.HTTPError as e:
            raise SourceError(f"LinkedIn: {e}") from e
        if r.status_code in (429, 999):
            raise SourceBlocked(f"LinkedIn blockiert (HTTP {r.status_code})")
        if r.status_code >= 400:
            raise SourceError(f"LinkedIn: HTTP {r.status_code}")
        return r.text

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        now = now or datetime.now(UTC)
        if self._last_run and now - self._last_run < MIN_GAP:
            raise SourceSkipped("LinkedIn: letzter Durchlauf vor weniger als 60 Minuten")
        self._last_run = now
        queries: list[tuple[dict, bool]] = []
        for cat in categories:
            base = {"keywords": cat.search_terms[0], "f_TPR": "r604800", "start": 0}
            # distance erwartet Meilen
            queries.append(({**base, "location": settings.location, "distance": round(settings.radius_km / 1.609)}, False))
            if settings.remote:
                queries.append(({**base, "location": "Deutschland", "f_WT": "2"}, True))  # f_WT=2: remote
        found: dict[str, Job] = {}
        for i, (params, remote) in enumerate(queries):
            if i:
                await polite_sleep()
            for job in parse_search(await self._get(SEARCH_URL, params)):
                job.remote = remote
                if job.source_id in found:
                    found[job.source_id].remote |= remote
                else:
                    found[job.source_id] = job
        return list(found.values())

    async def fetch_detail(self, job: Job) -> str | None:
        html = await self._get(DETAIL_URL.format(id=job.source_id))
        node = LexborHTMLParser(html).css_first("div.show-more-less-html__markup")
        return node.text(deep=True, separator=" ", strip=True) if node else None
