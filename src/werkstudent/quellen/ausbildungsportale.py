"""Quellen nur für die Suchart Ausbildung: ausbildung.de, AZUBIYO und azubi.de (serverseitig gerendert)."""
from __future__ import annotations

import re
from datetime import datetime

import httpx
from selectolax.lexbor import LexborHTMLParser

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import BROWSER_USER_AGENT, SourceError, SourceSkipped, polite_sleep

AUSBILDUNGDE_BASE = "https://www.ausbildung.de"
AUSBILDUNGDE_URL = f"{AUSBILDUNGDE_BASE}/suche/"
AZUBIYO_BASE = "https://www.azubiyo.de"
AZUBIYO_URL = f"{AZUBIYO_BASE}/stellenmarkt/"
AZUBIDE_BASE = "https://www.azubi.de"
AZUBIDE_RADII = [10, 30, 50, 100]
_HEADERS = {"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"}
_DATE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def portal_terms(categories: list[Category]) -> list[str]:
    """„Ausbildung Immobilienkaufmann“ → „Immobilienkaufmann“ – die Portale enthalten ohnehin nur Ausbildungen."""
    terms: list[str] = []
    for c in categories:
        for t in c.search_terms:
            term = re.sub(r"^ausbildung\s+(zum\s+|zur\s+)?", "", t, flags=re.I).strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def _text(node, selector: str) -> str:
    n = node.css_first(selector)
    return " ".join(n.text(deep=True, separator=" ", strip=True).split()) if n else ""


def _start_snippet(start: str) -> str:
    return f"Ausbildungsbeginn {start}" if start else ""


def parse_ausbildungde(html: str) -> list[Job]:
    jobs: dict[str, Job] = {}
    for card in LexborHTMLParser(html).css("article"):
        link = card.css_first('a[href^="/stellen/"]')
        if link is None:
            continue
        href = link.attributes.get("href") or ""
        source_id = href.rstrip("/").rsplit("-", 5)[-5:]  # UUID am Ende des Pfads
        source_id = "-".join(source_id)
        if source_id in jobs:
            continue
        company = re.sub(r"^bei\s*", "", _text(card, '[data-testid="jp-customer"]'))
        jobs[source_id] = Job(
            source="ausbildungde",
            source_id=source_id,
            title=_text(card, '[data-testid="jp-title"]'),
            company=company,
            location=_text(card, '[data-testid="jp-branches"]'),
            url=AUSBILDUNGDE_BASE + href,
            snippet=_start_snippet(_text(card, '[data-testid="jp-starting-at"]')),
        )
    return [j for j in jobs.values() if j.title]


def parse_azubiyo(html: str) -> list[Job]:
    jobs: dict[str, Job] = {}
    for card in LexborHTMLParser(html).css("div.job-search-job-offer-teaser"):
        link = card.css_first('a[href^="/stellenanzeigen/"]')
        if link is None:
            continue
        href = link.attributes.get("href") or ""
        source_id = href.rstrip("/").rsplit("_", 1)[-1]
        if source_id in jobs:
            continue
        details = [s.text(strip=True) for s in card.css("span.text-placeholder")]
        start = next((d for d in details if _DATE.fullmatch(d)), "")
        location = next((d for d in details if re.match(r"^\d{5}\s", d)), "")
        jobs[source_id] = Job(
            source="azubiyo",
            source_id=source_id,
            title=_text(card, "span.h3"),
            company=_text(card, "span.text-secondary"),
            location=location,
            url=AZUBIYO_BASE + href,
            snippet=_start_snippet(start),
        )
    return [j for j in jobs.values() if j.title]


class _PortalSource:
    name = ""
    provides_details = False  # keine Detailseiten – unklare Stellen nicht in „Zum Prüfen“

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def _get(self, url: str, params: dict) -> str:
        try:
            r = await self._client.get(url, params=params, headers=_HEADERS, timeout=20)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise SourceError(f"{self.name}: {e}") from e
        return r.text

    def _request(self, term: str, settings: UserSettings) -> tuple[str, dict]:
        raise NotImplementedError

    def _parse(self, html: str) -> list[Job]:
        raise NotImplementedError

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        if settings.art != "ausbildung":
            raise SourceSkipped(f"{self.name} hat nur Ausbildungsplätze")
        found: dict[str, Job] = {}
        for i, term in enumerate(portal_terms(categories)):
            if i:
                await polite_sleep(1, 3)
            url, params = self._request(term, settings)
            for job in self._parse(await self._get(url, params)):
                found.setdefault(job.source_id, job)
        return list(found.values())

    async def fetch_detail(self, job: Job) -> str | None:
        return None  # Titel und Ausbildungsbeginn reichen für die Entscheidung


class AusbildungDeSource(_PortalSource):
    name = "ausbildungde"

    def _request(self, term: str, settings: UserSettings) -> tuple[str, dict]:
        return AUSBILDUNGDE_URL, {"search": f"{term}|{settings.location}"}

    def _parse(self, html: str) -> list[Job]:
        return parse_ausbildungde(html)


class AzubiyoSource(_PortalSource):
    name = "azubiyo"

    def _request(self, term: str, settings: UserSettings) -> tuple[str, dict]:
        subject = re.sub(r"[^a-z0-9]+", "-", term.lower().translate(_UMLAUTE)).strip("-")
        return AZUBIYO_URL, {"subject": subject, "location": settings.location}

    def _parse(self, html: str) -> list[Job]:
        return parse_azubiyo(html)


# --- azubi.de -------------------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().translate(_UMLAUTE)).strip("-")


def azubide_url(term: str, location: str, radius_km: int) -> str:
    radius = next((r for r in AZUBIDE_RADII if r >= radius_km), AZUBIDE_RADII[-1])
    return f"{AZUBIDE_BASE}/beruf/ausbildung-{_slug(term)}/ausbildungsplaetze/stadt/{_slug(location)}?radius={radius}"


def parse_azubide(html: str) -> list[Job]:
    jobs: dict[str, Job] = {}
    for card in LexborHTMLParser(html).css("a"):
        href = card.attributes.get("href") or ""
        m = re.match(r"^/ausbildungsplatz/(\d+)", href)
        if not m or m.group(1) in jobs:
            continue
        spans = [" ".join(s.text(strip=True).split()) for s in card.css("span")]
        start = next((t for t in spans if _DATE.fullmatch(t)), "")
        # Standort steht als „47798Krefeld“ (PLZ und Ort in verschachtelten Spans)
        place = next((re.match(r"^(\d{5})\s*(\D.*)$", t) for t in spans if re.match(r"^\d{5}\s*\D", t)), None)
        location = f"{place.group(1)} {place.group(2)}" if place else ""
        jobs[m.group(1)] = Job(
            source="azubide",
            source_id=m.group(1),
            title=_text(card, "h2"),
            company=_text(card, "span.text-secondary"),
            location=location,
            url=AZUBIDE_BASE + href,
            snippet=_start_snippet(start),
        )
    return [j for j in jobs.values() if j.title]


class AzubiDeSource(_PortalSource):
    name = "azubide"

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        if settings.art != "ausbildung":
            raise SourceSkipped("azubi.de hat nur Ausbildungsplätze")
        found: dict[str, Job] = {}
        for i, term in enumerate(portal_terms(categories)):
            if i:
                await polite_sleep(1, 3)
            try:
                r = await self._client.get(azubide_url(term, settings.location, settings.radius_km),
                                           headers=_HEADERS, timeout=20)
            except httpx.HTTPError as e:
                raise SourceError(f"azubide: {e}") from e
            if r.status_code == 404:  # kein Berufsprofil unter diesem Begriff – kein Fehler
                continue
            if r.status_code >= 400:
                raise SourceError(f"azubide: HTTP {r.status_code}")
            for job in parse_azubide(r.text):
                found.setdefault(job.source_id, job)
        return list(found.values())
