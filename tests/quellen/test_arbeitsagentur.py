import json
from pathlib import Path

import httpx
import pytest
import respx

from werkstudent.modelle import UserSettings
from werkstudent.quellen.arbeitsagentur import API_URL, ArbeitsagenturSource
from werkstudent.quellen.basis import SourceError

FIXTURE = json.loads(Path("tests/fixtures/arbeitsagentur_search.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("werkstudent.quellen.arbeitsagentur.polite_sleep", _noop)


@respx.mock
async def test_maps_fields():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    async with httpx.AsyncClient() as c:
        jobs = await ArbeitsagenturSource(c).search(UserSettings(), [])
    first = FIXTURE["ergebnisliste"][0]
    j = jobs[0]
    assert j.source == "arbeitsagentur"
    assert j.source_id == first["referenznummer"]
    assert j.title == first["stellenangebotsTitel"]
    assert j.company == first["firma"]
    assert j.location == first["stellenlokationen"][0]["adresse"]["ort"]
    assert (j.lat, j.lon) == (first["stellenlokationen"][0]["breite"], first["stellenlokationen"][0]["laenge"])
    assert j.url.startswith("https://www.arbeitsagentur.de/jobsuche/jobdetail/")
    assert j.posted_at is not None and j.posted_at.tzinfo is not None
    assert len(jobs) == 3


@respx.mock
async def test_sends_api_key_and_params():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    async with httpx.AsyncClient() as c:
        await ArbeitsagenturSource(c).search(UserSettings(), [])
    req = route.calls[0].request
    assert req.headers["X-API-Key"] == "jobboerse-jobsuche"
    assert req.url.params["umkreis"] == "25"
    assert req.url.params["wo"] == "Düsseldorf"
    assert req.url.params["angebotsart"] == "1"


@respx.mock
async def test_internships_adds_angebotsart_34():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    async with httpx.AsyncClient() as c:
        await ArbeitsagenturSource(c).search(UserSettings(internships=True), [])
    assert "34" in [call.request.url.params["angebotsart"] for call in route.calls]


@respx.mock
async def test_empty_result_without_list_key():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json={"maxErgebnisse": 0}))
    async with httpx.AsyncClient() as c:
        assert await ArbeitsagenturSource(c).search(UserSettings(), []) == []


@respx.mock
async def test_http_500_raises_source_error():
    respx.get(API_URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError):
            await ArbeitsagenturSource(c).search(UserSettings(), [])


from werkstudent.modelle import Category

IMMO = Category("immobilien", "Immobilienkaufmann/-frau", "🏠", True,
                ["Ausbildung Immobilienkaufmann", "Ausbildung Immobilien"], ["immobilien"], art="ausbildung")


@respx.mock
async def test_ausbildung_uses_angebotsart_4_and_terms():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    async with httpx.AsyncClient() as c:
        await ArbeitsagenturSource(c).search(UserSettings(art="ausbildung", location="Nettetal"), [IMMO])
    params = [call.request.url.params for call in route.calls]
    assert {p["angebotsart"] for p in params} == {"4"}
    assert [p["was"] for p in params] == ["Immobilienkaufmann", "Immobilien"]
    assert params[0]["wo"] == "Nettetal"


@respx.mock
async def test_ausbildung_jobs_are_marked_as_ausbildung():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    async with httpx.AsyncClient() as c:
        jobs = await ArbeitsagenturSource(c).search(UserSettings(art="ausbildung", location="Nettetal"), [IMMO])
    assert jobs and all(j.kind_hint == "ausbildung" for j in jobs)
