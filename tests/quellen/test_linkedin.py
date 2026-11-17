from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from werkstudent.modelle import Category, UserSettings
from werkstudent.quellen.basis import SourceBlocked, SourceSkipped
from werkstudent.quellen.linkedin import SEARCH_URL, LinkedInSource, parse_search

SEARCH = Path("tests/fixtures/linkedin_search.html").read_text(encoding="utf-8")
CLOUD = Category("cloud", "Cloud & DevOps", "☁️", True, ["Werkstudent Cloud", "Werkstudent DevOps"], ["cloud"])
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("werkstudent.quellen.linkedin.polite_sleep", _noop)


def test_parse_search_finds_jobs():
    jobs = parse_search(SEARCH)
    assert len(jobs) >= 5
    assert jobs[0].source_id == "4000000001"
    assert jobs[0].company == "Beispiel Consulting GmbH"
    assert all(j.url.startswith("https://") and "?" not in j.url for j in jobs)
    assert all(j.posted_at is not None for j in jobs)
    assert len({j.source_id for j in jobs}) == len(jobs)


@respx.mock
async def test_one_request_per_category_with_distance_in_miles():
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, text=SEARCH))
    async with httpx.AsyncClient() as c:
        await LinkedInSource(c).search(UserSettings(), [CLOUD], now=NOW)
    assert route.call_count == 1
    assert route.calls[0].request.url.params["distance"] == "16"
    assert route.calls[0].request.url.params["keywords"] == "Werkstudent Cloud"


@respx.mock
async def test_status_999_raises_blocked():
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(999))
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceBlocked):
            await LinkedInSource(c).search(UserSettings(), [CLOUD], now=NOW)


@respx.mock
async def test_skips_if_last_run_under_60_min():
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, text=SEARCH))
    async with httpx.AsyncClient() as c:
        src = LinkedInSource(c)
        await src.search(UserSettings(), [CLOUD], now=NOW)
        with pytest.raises(SourceSkipped):
            await src.search(UserSettings(), [CLOUD], now=NOW + timedelta(minutes=30))
        assert route.call_count == 1
        await src.search(UserSettings(), [CLOUD], now=NOW + timedelta(minutes=61))
        assert route.call_count == 2


@respx.mock
async def test_remote_adds_germany_remote_query():
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, text=SEARCH))
    async with httpx.AsyncClient() as c:
        jobs = await LinkedInSource(c).search(UserSettings(remote=True), [CLOUD], now=NOW)
    assert route.call_count == 2
    assert route.calls[1].request.url.params["f_WT"] == "2"
    assert all(j.remote for j in jobs)
