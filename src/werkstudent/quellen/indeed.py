"""Quelle: Indeed. Bei Captcha/Bot-Schutz wird die Quelle übersprungen – nie umgangen."""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode

from selectolax.lexbor import LexborHTMLParser

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import SourceBlocked, polite_sleep
from werkstudent.quellen.browser import Browser

BASE = "https://de.indeed.com"
CARDS = "#mosaic-provider-jobcards"
_BLOCK_TITLES = ("just a moment", "security check", "hcaptcha", "sicherheitsüberprüfung", "blocked")
_LOCATION_PREFIX = re.compile(r"^(hybrides arbeiten|teilweise homeoffice|homeoffice|remote)(\s+in)?\s*", re.I)
_REMOTE_PREFIX = re.compile(r"^(homeoffice|remote)\b", re.I)
_PLZ = re.compile(r"\b\d{5}\b")


def search_url(term: str, location: str | None, radius_km: int) -> str:
    params = {"q": term, "fromage": 7}
    if location:
        params.update(l=location, radius=radius_km)
    return f"{BASE}/jobs?{urlencode(params)}"


def clean_location(raw: str) -> tuple[str, bool]:
    """„Hybrides Arbeiten in 40882 Ratingen“ → („Ratingen“, False); „Homeoffice in X“ → („X“, True)."""
    remote = bool(_REMOTE_PREFIX.match(raw.strip()))
    loc = _LOCATION_PREFIX.sub("", raw.strip())
    loc = _PLZ.sub("", loc)
    return re.sub(r"\s+", " ", loc).strip(" ,"), remote


def is_blocked(html: str) -> bool:
    tree = LexborHTMLParser(html)
    title = tree.css_first("title")
    if title and any(t in title.text().lower() for t in _BLOCK_TITLES):
        return True
    if tree.css_first(CARDS) is not None:
        return False
    return tree.css_first('.cf-challenge, #challenge-running, [class*="captcha"], iframe[src*="captcha"]') is not None


def parse_search(html: str) -> list[Job]:
    tree = LexborHTMLParser(html)
    jobs: dict[str, Job] = {}
    for card in tree.css(".job_seen_beacon"):
        link = card.css_first("a[data-jk]")
        if link is None:
            continue
        jk = link.attributes.get("data-jk") or ""
        if not jk or jk in jobs:
            continue
        company = card.css_first('[data-testid="company-name"]')
        loc_node = card.css_first('[data-testid="text-location"]')
        location, remote = clean_location(loc_node.text(strip=True) if loc_node else "")
        jobs[jk] = Job(
            source="indeed",
            source_id=jk,
            title=link.text(deep=True, strip=True),
            company=company.text(strip=True) if company else "",
            location=location,
            url=f"{BASE}/viewjob?jk={jk}",
            remote=remote,
        )
    return list(jobs.values())


def parse_detail(html: str) -> str:
    node = LexborHTMLParser(html).css_first("#jobDescriptionText")
    return node.text(deep=True, separator=" ", strip=True) if node else ""


class IndeedSource:
    name = "indeed"

    def __init__(self, browser: Browser):
        self._browser = browser

    async def _fetch(self, url: str) -> list[Job]:
        html = await self._browser.fetch_html(url, CARDS, return_on_timeout=True)
        if is_blocked(html):
            raise SourceBlocked("Indeed zeigt eine Captcha-/Sperrseite")
        return parse_search(html)

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        urls = [search_url(t, settings.location, settings.radius_km) for c in categories for t in c.search_terms]
        remote_urls = (
            [search_url(t, "Homeoffice", settings.radius_km) for c in categories for t in c.search_terms[:1]]
            if settings.remote
            else []
        )
        found: dict[str, Job] = {}
        for i, (url, remote) in enumerate([(u, False) for u in urls] + [(u, True) for u in remote_urls]):
            if i:
                await polite_sleep()
            for job in await self._fetch(url):
                job.remote |= remote
                if job.source_id in found:
                    found[job.source_id].remote |= job.remote
                else:
                    found[job.source_id] = job
        return list(found.values())

    async def fetch_detail(self, job: Job) -> str | None:
        html = await self._browser.fetch_html(job.url, "#jobDescriptionText", return_on_timeout=True)
        if is_blocked(html):
            raise SourceBlocked("Indeed zeigt eine Captcha-/Sperrseite")
        return parse_detail(html) or None
