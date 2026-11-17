"""Quelle: Stellenwerk Düsseldorf – Jobportal von HHU und Hochschule Düsseldorf (serverseitig gerendert, kein Browser)."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from html import unescape

import httpx
from selectolax.lexbor import LexborHTMLParser

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import BROWSER_USER_AGENT, SourceError, SourceSkipped, polite_sleep

BASE = "https://www.stellenwerk.de"
SEARCH_URL = f"{BASE}/duesseldorf"
_JOB_HREF = re.compile(r"^/duesseldorf/.*-\d{6}-(\d+)\s*$")
_AGE = re.compile(r"vor\s+(\d+)\s+(stunde|stunden|tag|tagen|woche|wochen|monat|monaten)", re.I)
_UNITS = {"stunde": "hours", "tag": "days", "woche": "weeks"}
_HEADERS = {"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"}
HOME_CITY = "Düsseldorf"


def query_terms(categories: list[Category]) -> list[str]:
    """„Werkstudent Cloud“ → „Cloud“: Stellenwerk verknüpft Wörter mit UND, das würde zu viel ausschließen."""
    terms = ["Informatik"]
    for c in categories:
        for t in c.search_terms:
            term = re.sub(r"^werkstudent\s+", "", t, flags=re.I).strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def parse_age(text: str, now: datetime) -> datetime | None:
    t = text.strip().lower()
    if t == "heute":
        return now
    if t == "gestern":
        return now - timedelta(days=1)
    m = _AGE.search(t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith("monat"):
        return now - timedelta(days=30 * n)
    key = next(k for k in _UNITS if unit.startswith(k))
    return now - timedelta(**{_UNITS[key]: n})


def _location(raw: str) -> str:
    # Mehrere Städte („Berlin, Düsseldorf, …“) → Düsseldorf bevorzugen, sonst die erste Angabe.
    return HOME_CITY if HOME_CITY.lower() in raw.lower() else raw.strip()


def parse_search(html: str, now: datetime) -> list[Job]:
    tree = LexborHTMLParser(html)
    jobs: dict[str, Job] = {}
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        m = _JOB_HREF.match(href)
        if not m or m.group(1) in jobs:
            continue
        paragraphs = [p for p in a.css("p") if p.text(strip=True)]
        if len(paragraphs) < 2:
            continue
        title = paragraphs[0].text(separator=" ", strip=True)
        company, _, location = paragraphs[1].text(separator="|", strip=True).partition("|·|")
        age = parse_age(paragraphs[-1].text(strip=True), now) if len(paragraphs) > 2 else None
        badges = " ".join(s.text(strip=True) for s in a.css("span"))
        jobs[m.group(1)] = Job(
            source="stellenwerk",
            source_id=m.group(1),
            title=title,
            company=company.replace("|", " ").strip(),
            location=_location(location.replace("|", " ")),
            url=BASE + href.strip(),
            snippet=badges,
            posted_at=age,
        )
    return list(jobs.values())


def parse_detail(html: str) -> str:
    for script in LexborHTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("description"):
            text = LexborHTMLParser(f"<div>{data['description']}</div>").body.text(separator=" ", strip=True)
            return re.sub(r"\s+", " ", unescape(text).replace("\xa0", " ")).strip()
    return ""


class StellenwerkSource:
    name = "stellenwerk"

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def _get(self, url: str, params: dict | None = None) -> str:
        try:
            r = await self._client.get(url, params=params, headers=_HEADERS, timeout=20)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise SourceError(f"Stellenwerk: {e}") from e
        return r.text

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        if settings.art != "werkstudent":
            raise SourceSkipped("Stellenwerk ist ein Portal für Studierendenjobs")
        now = now or datetime.now(UTC)
        found: dict[str, Job] = {}
        for i, term in enumerate(query_terms(categories)):
            if i:
                await polite_sleep(1, 3)
            for job in parse_search(await self._get(SEARCH_URL, {"_q": term}), now):
                found.setdefault(job.source_id, job)
        return list(found.values())

    async def fetch_detail(self, job: Job) -> str | None:
        return parse_detail(await self._get(job.url)) or None
