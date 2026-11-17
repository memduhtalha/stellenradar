"""Lebenszeichen: „Wieder da“-Hinweis nach längerer Pause und optionaler externer Wächter-Ping."""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from werkstudent.bot.befehle import Deps, UserSpace
from werkstudent.bot.lebenszeichen import maybe_ping, startup_notice
from werkstudent.config import load_categories
from werkstudent.speicher.registry import Registry
from werkstudent.speicher.store import Store

from .fakes import FakeBot

ME = 1000
B = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=B)


@pytest.fixture
def deps():
    reg = Registry(":memory:", admin_id=ME)
    reg.init()

    def space(uid):
        store = Store(":memory:")
        store.init()
        return UserSpace(user_id=uid, store=store, runner=None, geocoder=None)

    return Deps(registry=reg, categories=load_categories(Path("config/kategorien.yaml")), make_space=space)


def _onboard(deps, last_run):
    store = deps.space(ME).store
    s = store.load_settings()
    s.onboarded = True
    store.save_settings(s)
    if last_run:
        store.set_last_successful_run(last_run)


async def test_alive_mark_beats_last_search(deps):
    from werkstudent.bot.lebenszeichen import mark_alive
    _onboard(deps, NOW - timedelta(hours=30))  # Suchen schlugen lange fehl …
    mark_alive(deps, NOW - timedelta(minutes=5))  # … aber der Bot lief
    bot = FakeBot()
    await startup_notice(deps, bot, NOW)
    assert bot.sent == []


async def test_startup_after_long_pause_tells_admin(deps):
    _onboard(deps, NOW - timedelta(hours=30))
    bot = FakeBot()
    await startup_notice(deps, bot, NOW)
    (msg,) = bot.sent
    assert msg.chat_id == ME and "30 Std" in msg.text and "hole" in msg.text


async def test_startup_after_short_pause_is_quiet(deps):
    _onboard(deps, NOW - timedelta(hours=2))
    bot = FakeBot()
    await startup_notice(deps, bot, NOW)
    assert bot.sent == []


async def test_startup_before_first_run_is_quiet(deps):
    _onboard(deps, None)
    bot = FakeBot()
    await startup_notice(deps, bot, NOW)
    assert bot.sent == []


async def test_ping_every_ten_minutes_when_configured(deps):
    calls = []

    async def ping(url):
        calls.append(url)

    deps.healthcheck_url = "https://hc-ping.com/abc"
    deps.ping = ping
    await maybe_ping(deps, NOW)
    await maybe_ping(deps, NOW + timedelta(minutes=5))
    await maybe_ping(deps, NOW + timedelta(minutes=11))
    assert calls == ["https://hc-ping.com/abc", "https://hc-ping.com/abc"]


async def test_no_ping_without_url(deps):
    calls = []

    async def ping(url):
        calls.append(url)

    deps.ping = ping
    await maybe_ping(deps, NOW)
    assert calls == []


async def test_ping_failure_does_not_raise(deps):
    async def ping(url):
        raise RuntimeError("kein Netz")

    deps.healthcheck_url = "https://hc-ping.com/abc"
    deps.ping = ping
    await maybe_ping(deps, NOW)  # darf den Bot nicht stören
