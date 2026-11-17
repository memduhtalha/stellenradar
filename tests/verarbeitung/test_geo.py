import pytest

from werkstudent.verarbeitung.geo import haversine_km


def test_haversine_duesseldorf_koeln():
    assert haversine_km((51.2277, 6.7735), (50.9375, 6.9603)) == pytest.approx(34, abs=2)


import httpx
import respx

from werkstudent.speicher.store import Store
from werkstudent.verarbeitung.geo import Geocoder

NOMINATIM = "https://nominatim.openstreetmap.org/search"


@respx.mock
async def test_geocoder_uses_cache():
    store = Store(":memory:"); store.init()
    store.geocache_put("neuss", 51.2, 6.69)
    route = respx.get(NOMINATIM).mock(return_value=httpx.Response(200, json=[]))
    async with httpx.AsyncClient() as client:
        assert await Geocoder(store, client).locate("Neuss") == (51.2, 6.69)
    assert route.call_count == 0


@respx.mock
async def test_geocoder_stores_result():
    store = Store(":memory:"); store.init()
    respx.get(NOMINATIM).mock(return_value=httpx.Response(200, json=[{"lat": "51.3", "lon": "6.85"}]))
    async with httpx.AsyncClient() as client:
        assert await Geocoder(store, client).locate("Ratingen") == (51.3, 6.85)
    assert store.geocache_get("ratingen") == (51.3, 6.85)


@respx.mock
async def test_geocoder_returns_none_on_error():
    store = Store(":memory:"); store.init()
    respx.get(NOMINATIM).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        assert await Geocoder(store, client).locate("Nirgendwo") is None
