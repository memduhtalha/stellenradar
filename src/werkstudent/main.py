"""Einstiegspunkt: baut alles zusammen und startet den Telegram-Bot."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from werkstudent.bot import alle, befehle, einrichtung, personen, pruefen
from werkstudent.bot.befehle import ADMIN_COMMANDS, COMMANDS, Deps, UserSpace
from werkstudent.bot.lebenszeichen import startup_notice
from werkstudent.bot.zeitplan import schedule
from werkstudent.config import Env, load_categories, load_enabled_sources, load_scoring, load_title_excludes
from werkstudent.lauf import Runner
from werkstudent.quellen.arbeitsagentur import ArbeitsagenturSource
from werkstudent.quellen.ausbildungsportale import AusbildungDeSource, AzubiDeSource, AzubiyoSource
from werkstudent.quellen.browser import Browser
from werkstudent.quellen.firmen import FirmenSource, load_firmen
from werkstudent.quellen.indeed import IndeedSource
from werkstudent.quellen.linkedin import LinkedInSource
from werkstudent.quellen.stellenwerk import StellenwerkSource
from werkstudent.quellen.stepstone import StepStoneSource
from werkstudent.speicher.registry import Registry
from werkstudent.speicher.store import Store
from werkstudent.verarbeitung.geo import Geocoder

log = logging.getLogger("werkstudent")

CONFIG_DIR = Path("config")


async def register_commands(bot, admin_id: int) -> None:
    """Befehlsmenü in Telegram: für alle die normalen Befehle, für den Admin zusätzlich die Admin-Befehle."""
    await bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
    await bot.set_my_commands(
        [BotCommand(c, d) for c, d in COMMANDS + ADMIN_COMMANDS], scope=BotCommandScopeChat(admin_id)
    )


def user_db_path(env: Env, user_id: int) -> str:
    """Der Admin behält seine bisherige Datenbank, jede weitere Person bekommt eine eigene Datei."""
    if user_id == env.allowed_user_id:
        return env.db_path
    return str(Path(env.db_path).parent / "users" / f"{user_id}.db")


def build_application(env: Env) -> Application:
    categories = load_categories(CONFIG_DIR / "kategorien.yaml")
    scoring = load_scoring(CONFIG_DIR / "bewertung.yaml")
    title_excludes = load_title_excludes(CONFIG_DIR / "filter.yaml")
    firmen = load_firmen(CONFIG_DIR / "firmen.yaml")
    enabled = load_enabled_sources(CONFIG_DIR)
    log.info("Quellen aus: %s", ", ".join(sorted(k for k, v in enabled.items() if not v)) or "keine")
    registry = Registry(str(Path(env.db_path).parent / "registry.db"), admin_id=env.allowed_user_id)
    registry.init()
    client = httpx.AsyncClient(follow_redirects=True)
    browser = Browser(env.lightpanda_cdp_url)  # gemeinsam – der Browser arbeitet ohnehin eine Seite nach der anderen
    run_lock = asyncio.Lock()

    def make_space(user_id: int) -> UserSpace:
        store = Store(user_db_path(env, user_id))
        store.init()
        geocoder = Geocoder(store, client)
        sources = [  # pro Person eigene Quellen-Objekte (z. B. eigenes LinkedIn-Stundenlimit)
            ArbeitsagenturSource(client),
            StepStoneSource(browser),
            IndeedSource(browser),
            LinkedInSource(client),
            StellenwerkSource(client),
            AusbildungDeSource(client),  # nur Suchart Ausbildung
            AzubiyoSource(client),
            AzubiDeSource(client),
            FirmenSource(client, firmen),
        ]
        sources = [s for s in sources if enabled.get(s.name, True)]  # config/quellen.yaml
        runner = Runner(store, sources, categories, scoring, geocoder, title_excludes=title_excludes,
                        run_lock=run_lock)
        return UserSpace(user_id=user_id, store=store, runner=runner, geocoder=geocoder)

    async def post_init(app: Application) -> None:
        await register_commands(app.bot, env.allowed_user_id)
        await startup_notice(app.bot_data["deps"], app.bot, datetime.now(UTC))
        schedule(app)
        log.info("Bot gestartet")

    async def post_shutdown(app: Application) -> None:
        await browser.close()
        await client.aclose()

    app = (
        ApplicationBuilder()
        .token(env.telegram_token)
        .concurrent_updates(True)  # lange Suchläufe blockieren keine Button-Klicks
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    deps = Deps(registry=registry, categories=categories, make_space=make_space, data_dir=Path(env.db_path).parent)
    deps.healthcheck_url = env.healthcheck_url

    async def ping(url: str) -> None:
        await client.get(url, timeout=10)

    deps.ping = ping
    app.bot_data["deps"] = deps

    # Zugriff prüft jeder Handler selbst über die Nutzerliste (Personen kommen per Einladung dazu).
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", einrichtung.cmd_start, filters=private))
    app.add_handler(CommandHandler("einstellungen", einrichtung.cmd_einstellungen, filters=private))
    app.add_handler(CommandHandler("jetzt", befehle.cmd_jetzt, filters=private))
    app.add_handler(CommandHandler("status", befehle.cmd_status, filters=private))
    app.add_handler(CommandHandler("gemerkt", befehle.cmd_gemerkt, filters=private))
    app.add_handler(CommandHandler("alle", alle.cmd_alle, filters=private))
    app.add_handler(CommandHandler("pruefen", pruefen.cmd_pruefen, filters=private))
    app.add_handler(CallbackQueryHandler(pruefen.on_review_button, pattern=r"^rv:"))
    app.add_handler(CallbackQueryHandler(alle.on_alle_button, pattern=r"^al:"))
    app.add_handler(CommandHandler("pause", befehle.cmd_pause, filters=private))
    app.add_handler(CommandHandler("weiter", befehle.cmd_weiter, filters=private))
    app.add_handler(CommandHandler("hilfe", befehle.cmd_hilfe, filters=private))
    app.add_handler(CommandHandler("einladen", personen.cmd_einladen, filters=private))
    app.add_handler(CommandHandler("personen", personen.cmd_personen, filters=private))
    app.add_handler(CallbackQueryHandler(personen.on_person_button, pattern=r"^(rm|rmy|rmn):"))
    app.add_handler(CallbackQueryHandler(befehle.on_job_button, pattern=r"^(bm|ub|ubl|dz|dzy|dzn|ap|snz):"))
    app.add_handler(CallbackQueryHandler(einrichtung.on_button, pattern=r"^(set|menu):"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & private, einrichtung.on_text))
    return app


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = build_application(Env())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
