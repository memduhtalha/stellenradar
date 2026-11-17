from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from werkstudent.bot.zeitplan import is_active, next_run_at
from werkstudent.modelle import UserSettings

B = ZoneInfo("Europe/Berlin")
S = UserSettings()


def test_is_active_window():
    assert is_active(datetime(2026, 11, 3, 7, 0, tzinfo=B), S)
    assert not is_active(datetime(2026, 11, 3, 22, 0, tzinfo=B), S)
    assert not is_active(datetime(2026, 11, 3, 6, 59, tzinfo=B), S)


def test_next_run_catches_up_after_downtime():
    now = datetime(2026, 11, 3, 9, 30, tzinfo=B)
    assert next_run_at(datetime(2026, 11, 2, 15, 0, tzinfo=B), now, S) == now


def test_next_run_first_time_is_now_if_active():
    now = datetime(2026, 11, 3, 9, 30, tzinfo=B)
    assert next_run_at(None, now, S) == now


def test_next_run_outside_window_moves_to_morning():
    last = datetime(2026, 11, 3, 21, 30, tzinfo=B)
    assert next_run_at(last, last + timedelta(minutes=5), S) == datetime(2026, 11, 4, 7, 0, tzinfo=B)


def test_next_run_at_night_waits_for_morning():
    now = datetime(2026, 11, 4, 3, 0, tzinfo=B)
    assert next_run_at(datetime(2026, 11, 3, 21, 0, tzinfo=B), now, S) == datetime(2026, 11, 4, 7, 0, tzinfo=B)


def test_next_run_normal():
    assert next_run_at(datetime(2026, 11, 3, 10, 0, tzinfo=B), datetime(2026, 11, 3, 10, 20, tzinfo=B), S) == \
        datetime(2026, 11, 3, 11, 0, tzinfo=B)


from datetime import date

from werkstudent.bot.zeitplan import digest_due


def test_digest_due_after_hour_once_per_day():
    s = UserSettings(digest_hour=18)
    assert digest_due(datetime(2026, 11, 3, 18, 5, tzinfo=B), s, None)
    assert not digest_due(datetime(2026, 11, 3, 17, 59, tzinfo=B), s, None)
    assert not digest_due(datetime(2026, 11, 3, 18, 30, tzinfo=B), s, date(2026, 11, 3))
    assert digest_due(datetime(2026, 11, 4, 19, 0, tzinfo=B), s, date(2026, 11, 3))
