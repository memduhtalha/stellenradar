from datetime import UTC, datetime, timedelta

import pytest

from werkstudent.speicher.registry import Registry

NOW = datetime(2026, 11, 3, 20, tzinfo=UTC)
ADMIN = 1000


@pytest.fixture
def reg():
    r = Registry(":memory:", admin_id=ADMIN)
    r.init()
    return r


def test_admin_is_user_from_start(reg):
    assert reg.users() == [ADMIN]
    assert reg.is_user(ADMIN) and not reg.is_user(2000)


def test_invite_can_be_redeemed_once(reg):
    code = reg.create_invite(NOW)
    assert len(code) >= 8
    assert reg.redeem(code, 2000, NOW + timedelta(hours=1))
    assert reg.is_user(2000)
    assert not reg.redeem(code, 3000, NOW + timedelta(hours=2))  # schon benutzt
    assert not reg.is_user(3000)


def test_invite_expires_after_24h(reg):
    code = reg.create_invite(NOW)
    assert not reg.redeem(code, 2000, NOW + timedelta(hours=25))
    assert not reg.is_user(2000)


def test_unknown_code_rejected(reg):
    assert not reg.redeem("falsch", 2000, NOW)


def test_codes_are_unique(reg):
    assert len({reg.create_invite(NOW) for _ in range(20)}) == 20


def test_existing_user_redeeming_keeps_code_unused(reg):
    code = reg.create_invite(NOW)
    assert reg.redeem(code, ADMIN, NOW)  # bereits Nutzer – kein Fehler …
    assert reg.redeem(code, 2000, NOW)   # … und der Code bleibt für die eingeladene Person gültig
