from pathlib import Path

import pytest

from werkstudent.modelle import Category, UserSettings
from werkstudent.quellen.basis import SourceBlocked
from werkstudent.quellen.indeed import IndeedSource, clean_location, is_blocked, parse_detail, parse_search

SEARCH = Path("tests/fixtures/indeed_search.html").read_text(encoding="utf-8")
CAPTCHA = Path("tests/fixtures/indeed_captcha.html").read_text(encoding="utf-8")
CLOUD = Category("cloud", "Cloud & DevOps", "☁️", True, ["Werkstudent Cloud"], ["cloud"])


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("werkstudent.quellen.indeed.polite_sleep", _noop)


def test_parse_search_finds_jobs():
    jobs = parse_search(SEARCH)
    assert len(jobs) >= 5
    assert all(j.title and j.company and j.location for j in jobs)
    assert all(j.url.startswith("https://de.indeed.com/viewjob?jk=") for j in jobs)
    assert len({j.source_id for j in jobs}) == len(jobs)
    assert jobs[0].location == "Düsseldorf"


def test_clean_location():
    assert clean_location("Hybrides Arbeiten in 40882 Ratingen") == ("Ratingen", False)
    assert clean_location("41460 Neuss") == ("Neuss", False)
    assert clean_location("Homeoffice in Düsseldorf") == ("Düsseldorf", True)
    assert clean_location("Homeoffice") == ("", True)


def test_parse_detail():
    html = '<html><body><div id="jobDescriptionText"><p>Du arbeitest mit Azure.</p></div></body></html>'
    assert parse_detail(html) == "Du arbeitest mit Azure."


def test_captcha_page_is_blocked():
    assert is_blocked(CAPTCHA) is True
    assert is_blocked(SEARCH) is False


class FakeBrowser:
    def __init__(self, html):
        self.html, self.calls = html, []

    async def fetch_html(self, url, wait_selector, timeout_s=20, return_on_timeout=False):
        self.calls.append((url, return_on_timeout))
        return self.html


async def test_search_raises_source_blocked_on_captcha():
    b = FakeBrowser(CAPTCHA)
    with pytest.raises(SourceBlocked):
        await IndeedSource(b).search(UserSettings(), [CLOUD])
    assert len(b.calls) == 1 and b.calls[0][1] is True


async def test_search_returns_jobs():
    jobs = await IndeedSource(FakeBrowser(SEARCH)).search(UserSettings(), [CLOUD])
    assert len(jobs) >= 5
