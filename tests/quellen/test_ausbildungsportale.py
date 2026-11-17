from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from werkstudent.modelle import Category, UserSettings
from werkstudent.quellen.ausbildungsportale import (
    AUSBILDUNGDE_URL,
    AZUBIYO_URL,
    AusbildungDeSource,
    AzubiyoSource,
    parse_ausbildungde,
    parse_azubiyo,
    portal_terms,
)
from werkstudent.quellen.basis import SourceError, SourceSkipped

ADE = Path("tests/fixtures/ausbildungde_search.html").read_text(encoding="utf-8")
AZY = Path("tests/fixtures/azubiyo_search.html").read_text(encoding="utf-8")
IMMO = Category("immobilien", "Immobilienkaufmann/-frau", "🏠", True,
                ["Ausbildung Immobilienkaufmann", "Ausbildung Immobilien"], ["immobilien"], art="ausbildung")
SETTINGS = UserSettings(art="ausbildung", categories={"immobilien"}, location="Nettetal", radius_km=25)
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("werkstudent.quellen.ausbildungsportale.polite_sleep", _noop)


def test_portal_terms():
    assert portal_terms([IMMO]) == ["Immobilienkaufmann", "Immobilien"]


def test_parse_ausbildungde():
    jobs = parse_ausbildungde(ADE)
    assert len(jobs) == 10 and len({j.source_id for j in jobs}) == 10
    j = next(j for j in jobs if "Rheinblick" in j.company)
    assert j.source == "ausbildungde"
    assert j.title == "Ausbildung Immobilienkauffrau/-mann (m/w/d)"
    assert j.company == "Rheinblick Versicherung AG"  # ohne „bei“
    assert j.location == "41460 Neuss"
    assert "01.08.2027" in j.snippet
    assert j.url.startswith("https://www.ausbildung.de/stellen/")


def test_parse_azubiyo():
    jobs = parse_azubiyo(AZY)
    assert len(jobs) == 15 and len({j.source_id for j in jobs}) == 15
    j = next(j for j in jobs if "Musterwohnen" in j.company)
    assert j.source == "azubiyo"
    assert j.title.startswith("Ausbildung Immobilienkaufmann/-frau")
    assert j.location == "47798 Krefeld"
    assert "01.08.2027" in j.snippet
    assert j.url.startswith("https://www.azubiyo.de/stellenanzeigen/")


@respx.mock
async def test_ausbildungde_search_params():
    route = respx.get(AUSBILDUNGDE_URL).mock(return_value=httpx.Response(200, text=ADE))
    async with httpx.AsyncClient() as c:
        jobs = await AusbildungDeSource(c).search(SETTINGS, [IMMO], now=NOW)
    assert route.call_count == 2
    assert route.calls[0].request.url.params["search"] == "Immobilienkaufmann|Nettetal"
    assert len(jobs) == 10


@respx.mock
async def test_azubiyo_search_params():
    route = respx.get(AZUBIYO_URL).mock(return_value=httpx.Response(200, text=AZY))
    async with httpx.AsyncClient() as c:
        await AzubiyoSource(c).search(SETTINGS, [IMMO], now=NOW)
    params = route.calls[0].request.url.params
    assert (params["subject"], params["location"]) == ("immobilienkaufmann", "Nettetal")


async def test_skipped_for_werkstudent():
    async with httpx.AsyncClient() as c:
        for src in (AusbildungDeSource(c), AzubiyoSource(c)):
            with pytest.raises(SourceSkipped):
                await src.search(UserSettings(), [IMMO], now=NOW)


@respx.mock
async def test_http_error_raises_source_error():
    respx.get(AZUBIYO_URL).mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError):
            await AzubiyoSource(c).search(SETTINGS, [IMMO], now=NOW)
