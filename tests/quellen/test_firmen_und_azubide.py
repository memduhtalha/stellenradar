from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from werkstudent.modelle import Category, UserSettings
from werkstudent.quellen.ausbildungsportale import AzubiDeSource, azubide_url, parse_azubide
from werkstudent.quellen.basis import SourceSkipped
from werkstudent.quellen.firmen import Firma, FirmenSource, extract_dates, load_firmen, parse_firmenseite

AZD = Path("tests/fixtures/azubide_search.html").read_text(encoding="utf-8")
FIRMA = Path("tests/fixtures/firma_beispiel.html").read_text(encoding="utf-8")
IMMO = Category("immobilien", "Immobilienkaufmann/-frau", "🏠", True,
                ["Ausbildung Immobilienkaufmann", "Ausbildung Immobilien"],
                ["immobilienkaufmann", "immobilienkauffrau", "immobilien"], art="ausbildung")
SETTINGS = UserSettings(art="ausbildung", categories={"immobilien"}, location="Nettetal", radius_km=40)
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
WOHNSTAETTE = Firma("Musterwohnen Krefeld AG", "Krefeld", "https://musterwohnen.example/karriere/ausbildung")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("werkstudent.quellen.ausbildungsportale.polite_sleep", _noop)
    monkeypatch.setattr("werkstudent.quellen.firmen.polite_sleep", _noop)


# --- azubi.de -----------------------------------------------------------------------------------


def test_azubide_url_rounds_radius_up():
    assert azubide_url("Immobilienkaufmann", "Nettetal", 40) == \
        "https://www.azubi.de/beruf/ausbildung-immobilienkaufmann/ausbildungsplaetze/stadt/nettetal?radius=50"
    assert azubide_url("Immobilienkaufmann", "Mönchengladbach", 25).endswith("/stadt/moenchengladbach?radius=30")
    assert azubide_url("X", "Y", 200).endswith("radius=100")


def test_parse_azubide():
    jobs = parse_azubide(AZD)
    assert len(jobs) == 3 and len({j.source_id for j in jobs}) == 3
    j = jobs[0]
    assert j.source == "azubide" and j.source_id == "90000001"
    assert j.title == "Ausbildung Immobilienkaufmann/-frau (m/w/d) in Krefeld 2027"
    assert j.company == "Musterwohnen Krefeld AG"
    assert j.location == "47798 Krefeld"
    assert "01.08.2027" in j.snippet
    assert j.url == ("https://www.azubi.de/ausbildungsplatz/"
                     "90000001-s-ausbildung-immobilienkaufmann-frau-m-w-d-in-krefeld-2027")


@respx.mock
async def test_azubide_unknown_profession_page_is_empty_not_error():
    respx.get(url__startswith="https://www.azubi.de/beruf/ausbildung-immobilienkaufmann/").mock(
        return_value=httpx.Response(200, text=AZD))
    respx.get(url__startswith="https://www.azubi.de/beruf/ausbildung-immobilien/").mock(
        return_value=httpx.Response(404))
    async with httpx.AsyncClient() as c:
        jobs = await AzubiDeSource(c).search(SETTINGS, [IMMO], now=NOW)
    assert len(jobs) == 3


async def test_azubide_skipped_for_werkstudent():
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceSkipped):
            await AzubiDeSource(c).search(UserSettings(), [IMMO], now=NOW)


# --- Firmen-Karriereseiten -------------------------------------------------------------------------


def test_extract_dates():
    text = "Am 1. August 2027 geht es los … Bitte sende sie bis zum 29.12.2026 per E-Mail."
    assert extract_dates(text) == ("1. August 2027", "29.12.2026")
    assert extract_dates("Beginn: 01.08.2027, Bewerbungsschluss: 15.01.2027") == ("01.08.2027", "15.01.2027")
    assert extract_dates("Nichts davon") == (None, None)


def test_parse_firmenseite_finds_training_heading_only():
    jobs = parse_firmenseite(FIRMA, WOHNSTAETTE, [IMMO])
    assert [j.title for j in jobs] == ["Ausbildung zur/zum Immobilienkauffrau/-mann (m/w/d)"]
    j = jobs[0]
    assert j.source == "firmen" and j.company == "Musterwohnen Krefeld AG" and j.location == "Krefeld"
    assert j.url == WOHNSTAETTE.url
    assert "Ausbildungsbeginn 1. August 2027" in j.snippet and "Bewerbung bis 29.12.2026" in j.snippet


def test_parse_firmenseite_without_training():
    assert parse_firmenseite("<html><body><h2>Sachbearbeiter (m/w/d)</h2></body></html>", WOHNSTAETTE, [IMMO]) == []


def test_load_firmen_config():
    firmen = load_firmen(Path("config/firmen.yaml"))
    assert any(f.name.startswith("Wohnstätte") and f.ort == "Krefeld" for f in firmen)


@respx.mock
async def test_firmen_source_fetches_each_page_and_survives_errors():
    respx.get(WOHNSTAETTE.url).mock(return_value=httpx.Response(200, text=FIRMA))
    respx.get("https://kaputt.example/jobs").mock(return_value=httpx.Response(500))
    firmen = [WOHNSTAETTE, Firma("Kaputt AG", "Viersen", "https://kaputt.example/jobs")]
    async with httpx.AsyncClient() as c:
        jobs = await FirmenSource(c, firmen).search(SETTINGS, [IMMO], now=NOW)
    assert [j.company for j in jobs] == ["Musterwohnen Krefeld AG"]


async def test_firmen_skipped_for_werkstudent():
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceSkipped):
            await FirmenSource(c, [WOHNSTAETTE]).search(UserSettings(), [IMMO], now=NOW)
