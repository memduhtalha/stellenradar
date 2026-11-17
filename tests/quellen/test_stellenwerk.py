from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from werkstudent.modelle import Category, Job, UserSettings
from werkstudent.quellen.basis import SourceError
from werkstudent.quellen.stellenwerk import (
    SEARCH_URL,
    StellenwerkSource,
    parse_age,
    parse_detail,
    parse_search,
    query_terms,
)

SEARCH = Path("tests/fixtures/stellenwerk_search.html").read_text(encoding="utf-8")
DETAIL = Path("tests/fixtures/stellenwerk_detail.html").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
CLOUD = Category("cloud", "Cloud & DevOps", "☁️", True, ["Werkstudent Cloud", "Werkstudent DevOps"], ["cloud"])


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("werkstudent.quellen.stellenwerk.polite_sleep", _noop)


def test_parse_search_finds_jobs():
    jobs = parse_search(SEARCH, NOW)
    assert len(jobs) == 10
    assert all(j.source == "stellenwerk" and j.title and j.company for j in jobs)
    assert all(j.url.startswith("https://www.stellenwerk.de/duesseldorf/") for j in jobs)
    assert len({j.source_id for j in jobs}) == 10
    robot = next(j for j in jobs if j.source_id == "200001")
    assert robot.title == "Werkstudent Robotik gesucht !"
    assert robot.company == "Musterrobotik GmbH"
    assert robot.location.startswith("Herne")
    assert robot.posted_at == NOW - timedelta(days=5)


def test_multi_city_location_prefers_duesseldorf():
    consultant = next(j for j in parse_search(SEARCH, NOW) if "Consultant" in j.title)
    assert consultant.location == "Düsseldorf"


def test_parse_age():
    assert parse_age("vor 5 Tagen", NOW) == NOW - timedelta(days=5)
    assert parse_age("vor 1 Tag", NOW) == NOW - timedelta(days=1)
    assert parse_age("vor 3 Stunden", NOW) == NOW - timedelta(hours=3)
    assert parse_age("heute", NOW) == NOW
    assert parse_age("gestern", NOW) == NOW - timedelta(days=1)
    assert parse_age("irgendwann", NOW) is None


def test_parse_detail_uses_json_ld():
    text = parse_detail(DETAIL)
    assert "Automatisierungen" in text and "<p>" not in text and "&nbsp;" not in text


def test_query_terms_strip_werkstudent_and_add_informatik():
    assert query_terms([CLOUD]) == ["Informatik", "Cloud", "DevOps"]


@respx.mock
async def test_search_queries_each_term_and_dedupes():
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, text=SEARCH))
    async with httpx.AsyncClient() as c:
        jobs = await StellenwerkSource(c).search(UserSettings(), [CLOUD], now=NOW)
    assert route.call_count == 3
    assert route.calls[1].request.url.params["_q"] == "Cloud"
    assert len(jobs) == 10


@respx.mock
async def test_http_error_raises_source_error():
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError):
            await StellenwerkSource(c).search(UserSettings(), [CLOUD], now=NOW)


@respx.mock
async def test_fetch_detail():
    job = Job(source="stellenwerk", source_id="278163", title="t", company="c", location="l",
              url="https://www.stellenwerk.de/duesseldorf/x-261012-278163")
    respx.get(job.url).mock(return_value=httpx.Response(200, text=DETAIL))
    async with httpx.AsyncClient() as c:
        assert "Automatisierungen" in await StellenwerkSource(c).fetch_detail(job)


async def test_skipped_for_ausbildung():
    from werkstudent.quellen.basis import SourceSkipped
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceSkipped):
            await StellenwerkSource(c).search(UserSettings(art="ausbildung"), [CLOUD], now=NOW)
