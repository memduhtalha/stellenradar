from pathlib import Path

import pytest

from werkstudent.modelle import Category, UserSettings
from werkstudent.quellen.basis import SourceError
from werkstudent.quellen.stepstone import StepStoneSource, parse_detail, parse_search, search_url

SEARCH = Path("tests/fixtures/stepstone_search.html").read_text(encoding="utf-8")
DETAIL = Path("tests/fixtures/stepstone_detail.html").read_text(encoding="utf-8")
CLOUD = Category("cloud", "Cloud & DevOps", "☁️", True, ["Werkstudent Cloud"], ["cloud"])


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("werkstudent.quellen.stepstone.polite_sleep", _noop)


def test_parse_search_finds_jobs():
    jobs = parse_search(SEARCH)
    assert len(jobs) >= 5
    assert all(j.title and j.company and j.location for j in jobs)
    assert all(j.url.startswith("https://www.stepstone.de/") for j in jobs)
    assert len({j.source_id for j in jobs}) == len(jobs)
    assert jobs[0].source_id == "10000001" and jobs[0].posted_at is not None


def test_parse_detail_returns_text():
    text = parse_detail(DETAIL)
    assert len(text) > 200 and "Kunden" in text


def test_search_url_format():
    assert search_url("Werkstudent Cloud", "Düsseldorf", 25) == \
        "https://www.stepstone.de/jobs/werkstudent-cloud/in-duesseldorf?radius=25&ag=age_7"


class FakeBrowser:
    def __init__(self, html=SEARCH, fail=False, fail_first=False):
        self.html, self.fail, self.fail_first, self.urls = html, fail, fail_first, []

    async def fetch_html(self, url, wait_selector, timeout_s=20, return_on_timeout=False):
        self.urls.append(url)
        if self.fail or (self.fail_first and len(self.urls) == 1):
            raise SourceError("kaputt")
        return self.html


TWO_TERMS = Category("cloud", "Cloud & DevOps", "☁️", True, ["Werkstudent Cloud", "Werkstudent DevOps"], ["cloud"])


async def test_one_failing_url_keeps_results_of_others():
    jobs = await StepStoneSource(FakeBrowser(fail_first=True)).search(UserSettings(), [TWO_TERMS])
    assert len(jobs) >= 5


async def test_empty_result_page_is_no_error():
    jobs = await StepStoneSource(FakeBrowser(html="<html><body>Keine Treffer</body></html>")).search(UserSettings(), [CLOUD])
    assert jobs == []


async def test_search_queries_each_term_and_dedupes():
    b = FakeBrowser()
    jobs = await StepStoneSource(b).search(UserSettings(), [CLOUD])
    assert len(b.urls) == 1
    assert len({j.source_id for j in jobs}) == len(jobs)


async def test_remote_adds_homeoffice_search_marked_remote():
    b = FakeBrowser()
    jobs = await StepStoneSource(b).search(UserSettings(remote=True), [CLOUD])
    assert any("in-homeoffice" in u for u in b.urls)
    assert any(j.remote for j in jobs)


async def test_search_raises_on_both_browsers_failing():
    with pytest.raises(SourceError):
        await StepStoneSource(FakeBrowser(fail=True)).search(UserSettings(), [CLOUD])
