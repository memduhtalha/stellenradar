from datetime import UTC, datetime
from pathlib import Path

from telegram.error import BadRequest, NetworkError, RetryAfter

from werkstudent.bot.senden import send_jobs
from werkstudent.config import load_categories
from werkstudent.lauf import RunResult
from werkstudent.modelle import Job, ProcessedJob

from .fakes import FakeBot

CATS = {c.key: c for c in load_categories(Path("config/kategorien.yaml"))}
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def _res(n, warnings=(), backlog=None):
    items = []
    for i in range(n):
        job = Job(source="stepstone", source_id=str(i), title=f"Werkstudent Cloud {i}", company="F", location="D", url="u")
        items.append((i, ProcessedJob(job=job, kind="werkstudent", categories=["cloud"], distance_km=1, score=7,
                                      is_top=True, dedupe_key=str(i))))
    return RunResult(to_send=items, backlog_total=backlog, warnings=list(warnings))


class Sleeps:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


async def test_send_jobs_retries_after_flood_limit():
    bot = FakeBot(fail_on={1: RetryAfter(3)})
    sleep = Sleeps()
    await send_jobs(bot, 42, _res(3), CATS, NOW, sleep=sleep)
    assert [m.text.split("\n")[1] for m in bot.sent] == [f"<b>Werkstudent Cloud {i}</b>" for i in range(3)]
    assert 3 in sleep.calls


async def test_send_jobs_continues_after_other_error():
    bot = FakeBot(fail_on={0: BadRequest("kaputt")})
    failed = await send_jobs(bot, 42, _res(3), CATS, NOW, sleep=Sleeps())
    assert len(bot.sent) == 2
    assert failed == [0]


async def test_network_error_is_retried():
    bot = FakeBot(fail_on={0: NetworkError("weg")})
    failed = await send_jobs(bot, 42, _res(1), CATS, NOW, sleep=Sleeps())
    assert len(bot.sent) == 1 and failed == []


async def test_persistent_network_error_reports_failed_ids():
    bot = FakeBot(fail_on={0: NetworkError("a"), 1: NetworkError("b"), 2: NetworkError("c")})
    failed = await send_jobs(bot, 42, _res(2), CATS, NOW, sleep=Sleeps())
    assert failed == [0] and len(bot.sent) == 1


async def test_send_order_warnings_intro_jobs():
    bot = FakeBot()
    await send_jobs(bot, 42, _res(2, warnings=["⚠️ Indeed"], backlog=30), CATS, NOW, sleep=Sleeps())
    texts = [m.text for m in bot.sent]
    assert texts[0] == "⚠️ Indeed"
    assert texts[1].startswith("📦 Rückstau: 30")
    assert "Werkstudent Cloud 0" in texts[2]
    assert all(m.chat_id == 42 for m in bot.sent)
