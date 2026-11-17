"""Entfernungen und Geocoding."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from werkstudent.speicher.store import Store

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "werkstudent-scraper/0.1 (privater Job-Alarm)"


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


class Geocoder:
    """Ortsname → Koordinaten, mit SQLite-Cache und höchstens 1 Anfrage/s an Nominatim."""

    def __init__(self, store: Store, client: httpx.AsyncClient):
        self._store = store
        self._client = client
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def locate(self, place: str) -> tuple[float, float] | None:
        key = place.strip().lower()
        if not key:
            return None
        cached = self._store.geocache_get(key)
        if cached:
            return cached
        async with self._lock:
            wait = 1.0 - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
            try:
                r = await self._client.get(
                    NOMINATIM_URL,
                    params={"format": "json", "countrycodes": "de", "limit": 1, "q": place},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10,
                )
                r.raise_for_status()
                hits = r.json()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("Geocoding für %r fehlgeschlagen: %s", place, e)
                return None
        if not hits:
            return None
        lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
        self._store.geocache_put(key, lat, lon)
        return lat, lon
