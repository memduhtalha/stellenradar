"""Quelle: Jobsuche-API der Bundesagentur für Arbeit (inoffiziell dokumentiert, v6)."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import SourceError, polite_sleep, unique_by_id

API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAIL_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"
API_KEY = "jobboerse-jobsuche"
BERLIN = ZoneInfo("Europe/Berlin")
PAGE_SIZE = 50
MAX_PAGES = 2


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=BERLIN)
    except ValueError:
        return None


def _to_job(item: dict) -> Job:
    locs = item.get("stellenlokationen") or [{}]
    loc = locs[0]
    adresse = loc.get("adresse") or {}
    ref = item["referenznummer"]
    return Job(
        source="arbeitsagentur",
        source_id=ref,
        title=item.get("stellenangebotsTitel", ""),
        company=item.get("firma", ""),
        location=adresse.get("ort", ""),
        url=DETAIL_URL.format(ref=ref),
        snippet=" ".join(item.get("alleBerufe") or []),
        posted_at=_parse_date(item.get("datumErsteVeroeffentlichung")),
        lat=loc.get("breite"),
        lon=loc.get("laenge"),
    )


class ArbeitsagenturSource:
    name = "arbeitsagentur"
    provides_details = False  # keine Detailseiten – unklare Stellen nicht in „Zum Prüfen“

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def _query(self, params: dict) -> list[Job]:
        jobs: list[Job] = []
        for page in range(1, MAX_PAGES + 1):
            try:
                r = await self._client.get(
                    API_URL,
                    params={**params, "size": PAGE_SIZE, "page": page},
                    headers={"X-API-Key": API_KEY},
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
            except (httpx.HTTPError, ValueError) as e:
                raise SourceError(f"Arbeitsagentur: {e}") from e
            items = data.get("ergebnisliste") or []
            jobs.extend(_to_job(i) for i in items if i.get("referenznummer"))
            if page * PAGE_SIZE >= int(data.get("maxErgebnisse") or 0):
                break
            await polite_sleep(1, 2)
        return jobs

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        if settings.art == "ausbildung":
            return await self._search_ausbildung(settings, categories)
        # Die API hat nur wenige Werkstudentenstellen – eine breite Suche, gefiltert wird lokal.
        base = {"was": "Werkstudent", "wo": settings.location, "umkreis": settings.radius_km, "veroeffentlichtseit": 14}
        jobs = await self._query({**base, "angebotsart": 1})
        if settings.internships:
            await polite_sleep(1, 2)
            jobs += await self._query({**base, "was": "Praktikum Informatik", "angebotsart": 34})
        return unique_by_id(jobs)

    async def _search_ausbildung(self, settings: UserSettings, categories: list[Category]) -> list[Job]:
        # angebotsart=4: Ausbildung/Duales Studium. „Ausbildung Immobilienkaufmann“ → was=„Immobilienkaufmann“
        terms: list[str] = []
        for c in categories:
            for t in c.search_terms:
                term = re.sub(r"^ausbildung\s+(zum\s+|zur\s+)?", "", t, flags=re.I).strip()
                if term and term not in terms:
                    terms.append(term)
        jobs: list[Job] = []
        for i, term in enumerate(terms):
            if i:
                await polite_sleep(1, 2)
            jobs += await self._query({"was": term, "wo": settings.location, "umkreis": settings.radius_km,
                                       "angebotsart": 4})
        for j in jobs:  # Titel heißen hier oft nur „Immobilienkaufmann/-frau“ – die Art ist trotzdem sicher
            j.kind_hint = "ausbildung"
        return unique_by_id(jobs)

    async def fetch_detail(self, job: Job) -> str | None:
        return None
