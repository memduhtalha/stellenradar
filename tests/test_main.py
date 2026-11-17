from telegram.ext import CallbackQueryHandler, CommandHandler

from werkstudent.config import Env
from werkstudent.main import build_application


def test_build_application_registers_all_handlers(tmp_path):
    env = Env(telegram_token="123456:TEST", allowed_user_id=1000, db_path=str(tmp_path / "jobs.db"))
    app = build_application(env)
    handlers = [h for group in app.handlers.values() for h in group]
    commands = {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands}
    assert commands == {"start", "einstellungen", "jetzt", "status", "gemerkt", "pause", "weiter", "hilfe", "einladen", "personen", "alle", "pruefen"}
    patterns = {h.pattern.pattern for h in handlers if isinstance(h, CallbackQueryHandler)}
    assert patterns == {r"^(bm|ub|ubl|dz|dzy|dzn|ap|snz):", r"^(set|menu):", r"^(rm|rmy|rmn):", r"^al:", r"^rv:"}
    deps = app.bot_data["deps"]
    assert deps.registry.admin_id == 1000
    assert deps.space(1000).store is not deps.space(2000).store


async def test_einladen_is_in_menu_only_for_admin():
    from werkstudent.main import register_commands

    class Bot:
        def __init__(self):
            self.calls = []

        async def set_my_commands(self, commands, scope=None):
            self.calls.append(([c.command for c in commands], scope))

    bot = Bot()
    await register_commands(bot, admin_id=1000)
    everyone = next(cmds for cmds, scope in bot.calls if scope is None)
    admin = next((cmds, scope) for cmds, scope in bot.calls if scope is not None)
    assert "einladen" not in everyone
    assert "einladen" in admin[0] and admin[1].chat_id == 1000


async def test_admin_menu_has_admin_commands():
    from werkstudent.main import register_commands

    class Bot:
        def __init__(self):
            self.calls = []

        async def set_my_commands(self, commands, scope=None):
            self.calls.append(([c.command for c in commands], scope))

    bot = Bot()
    await register_commands(bot, admin_id=1000)
    everyone = next(cmds for cmds, scope in bot.calls if scope is None)
    admin_cmds, scope = next((c, s) for c, s in bot.calls if s is not None)
    assert "einladen" not in everyone and "personen" not in everyone
    assert {"einladen", "personen"} <= set(admin_cmds) and scope.chat_id == 1000



def test_disabled_sources_are_not_used(tmp_path, monkeypatch):
    import werkstudent.main as m
    monkeypatch.setattr(m, "load_enabled_sources", lambda *a, **k: {"stepstone": False, "indeed": False})
    env = Env(telegram_token="123456:TEST", allowed_user_id=1000, db_path=str(tmp_path / "jobs.db"))
    names = [s.name for s in build_application(env).bot_data["deps"].space(1000).runner._sources]
    assert "stepstone" not in names and "indeed" not in names and "arbeitsagentur" in names
