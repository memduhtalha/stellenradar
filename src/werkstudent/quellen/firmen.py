"""Quelle: Karriereseiten einzelner Firmen (nur Suchart Ausbildung).

Viele Wohnungsunternehmen schreiben Ausbildungsplätze nur auf der eigenen Seite aus – oft früh.
Der Bot sucht dort nach Überschriften/Links wie „Ausbildung zum/zur …“ oder „… (m/w/d)“.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
import yaml
from selectolax.lexbor import LexborHTMLParser

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import BROWSER_USER_AGENT, SourceError, SourceSkipped, polite_sleep

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"}
_MONTHS = "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
_DATE = rf"\d{{1,2}}\.\s*(?:{_MONTHS})\s*20\d{{2}}|\d{{1,2}}\.\d{{1,2}}\.20\d{{2}}"
_DATE_RE = re.compile(_DATE)
_DEADLINE_RE = re.compile(rf"(?:bewerbungsschluss|bewerbungsfrist|bis spätestens|bis zum|bis)\s*:?\s*({_DATE})", re.I)
# „Ausbildung zum/zur/als …“, „Azubi …“, „Auszubildende …“ oder eine Geschlechterangabe wie „(m/w/d)“
_TRAINING = re.compile(r"ausbildung|azubi|auszubildend", re.I)
_JOB_TITLE = re.compile(
    r"ausbildung\s+(?:zum|zur|zur/zum|zum/zur|als)\b|\bazubi\b|auszubildende|\((?:[mwd]\s*/\s*){2}[mwdx]\)", re.I
)


@dataclass(frozen=True)
class Firma:
    name: str
    ort: str
    url: str


def load_firmen(path: Path) -> list[Firma]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [Firma(name=f["name"], ort=f["ort"], url=f["url"]) for f in raw]


def extract_dates(text: str) -> tuple[str | None, str | None]:
    """(Ausbildungsbeginn, Bewerbungsfrist) aus dem Seitentext – None, wenn nicht gefunden."""
    deadline = _DEADLINE_RE.search(text)
    start = next(
        (m for m in _DATE_RE.finditer(text) if not deadline or m.start() != deadline.start(1)),
        None,
    )
    return (start.group(0) if start else None, deadline.group(1) if deadline else None)


def _matches_category(text: str, active: list[Category]) -> bool:
    low = text.lower()
    return any(k in low for c in active for k in c.keywords)


def parse_firmenseite(html: str, firma: Firma, active: list[Category]) -> list[Job]:
    tree = LexborHTMLParser(html)
    body = tree.body
    page_text = body.text(separator=" ", strip=True) if body else ""
    start, deadline = extract_dates(page_text)
    snippet = " · ".join(
        part for part in [f"Ausbildungsbeginn {start}" if start else "", f"Bewerbung bis {deadline}" if deadline else ""]
        if part
    )
    jobs: dict[str, Job] = {}
    for node in tree.css("h1, h2, h3, h4, a"):
        title = " ".join(node.text(separator=" ", strip=True).split())
        if not (10 <= len(title) <= 160) or not _TRAINING.search(title) or not _JOB_TITLE.search(title):
            continue
        if not _matches_category(title, active):
            continue
        href = node.attributes.get("href") if node.tag == "a" else None
        url = urljoin(firma.url, href) if href and not href.startswith(("#", "mailto:", "tel:")) else firma.url
        key = title.lower()
        if key in jobs:
            continue
        jobs[key] = Job(
            source="firmen",
            source_id=hashlib.sha1(f"{firma.url}|{key}".encode()).hexdigest()[:16],
            title=title,
            company=firma.name,
            location=firma.ort,
            url=url,
            snippet=snippet,
        )
    return list(jobs.values())


class FirmenSource:
    name = "firmen"
    provides_details = False  # keine Detailseiten – unklare Stellen nicht in „Zum Prüfen“

    def __init__(self, client: httpx.AsyncClient, firmen: list[Firma]):
        self._client = client
        self._firmen = firmen

    async def search(
        self, settings: UserSettings, categories: list[Category], now: datetime | None = None
    ) -> list[Job]:
        if settings.art != "ausbildung":
            raise SourceSkipped("Firmenseiten werden nur bei der Suche nach Ausbildungsplätzen geprüft")
        jobs: list[Job] = []
        failed = 0
        for i, firma in enumerate(self._firmen):
            if i:
                await polite_sleep(1, 3)
            try:
                r = await self._client.get(firma.url, headers=_HEADERS, timeout=20)
                r.raise_for_status()
            except httpx.HTTPError as e:  # eine kaputte Firmenseite darf die anderen nicht stoppen
                log.info("Firmenseite %s nicht ladbar: %s", firma.url, e)
                failed += 1
                continue
            jobs += parse_firmenseite(r.text, firma, categories)
        if self._firmen and failed == len(self._firmen):
            raise SourceError("Keine Firmenseite erreichbar")
        return jobs

    async def fetch_detail(self, job: Job) -> str | None:
        return None
