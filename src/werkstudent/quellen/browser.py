"""Seiten mit JavaScript rendern: zuerst Lightpanda (CDP), sonst lokales Headless-Chromium."""
from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from werkstudent.quellen.basis import BROWSER_USER_AGENT, SourceError

log = logging.getLogger(__name__)


class Browser:
    def __init__(self, cdp_url: str):
        self._cdp_url = cdp_url
        self._pw = None
        self._local = None
        self._lock = asyncio.Lock()
        self.last_engine: str | None = None

    async def _playwright(self):
        if self._pw is None:
            self._pw = await async_playwright().start()
        return self._pw

    @staticmethod
    async def _load(context, url: str, wait_selector: str, timeout_s: float) -> tuple[str, bool]:
        """Gibt (HTML, ob der Selektor erschienen ist) zurück."""
        page = await context.new_page()
        try:
            await page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(wait_selector, timeout=timeout_s * 1000)
                found = True
            except PlaywrightTimeout:
                found = False
            return await page.content(), found
        finally:
            await page.close()

    async def _fetch_cdp(self, url: str, wait_selector: str, timeout_s: float) -> tuple[str, bool]:
        pw = await self._playwright()
        # Lightpanda: pro Aufruf frisch verbinden, das ist robuster als eine lange offene Sitzung.
        browser = await pw.chromium.connect_over_cdp(self._cdp_url, timeout=timeout_s * 1000)
        try:
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            return await self._load(context, url, wait_selector, timeout_s)
        finally:
            await browser.close()

    async def _fetch_local(self, url: str, wait_selector: str, timeout_s: float) -> tuple[str, bool]:
        pw = await self._playwright()
        if self._local is None or not self._local.is_connected():
            self._local = await pw.chromium.launch(headless=True)
        context = await self._local.new_context(user_agent=BROWSER_USER_AGENT, locale="de-DE")
        try:
            return await self._load(context, url, wait_selector, timeout_s)
        finally:
            await context.close()

    async def fetch_html(
        self, url: str, wait_selector: str, timeout_s: float = 20, return_on_timeout: bool = False
    ) -> str:
        """Lädt die Seite. Erscheint der Selektor bei Lightpanda nicht, wird Chromium versucht.

        return_on_timeout: Erscheint er auch dort nicht, wird die Seite trotzdem zurückgegeben
        (z. B. Captcha- oder „keine Treffer“-Seite), statt einen Fehler auszulösen.
        """
        # Gesamt-Timeout je Versuch, damit ein hängender Browser nicht den ganzen Lauf blockiert.
        limit = timeout_s * 3
        fallback_html: str | None = None
        async with self._lock:
            for engine, fetch in (("lightpanda", self._fetch_cdp), ("chromium", self._fetch_local)):
                try:
                    html, found = await asyncio.wait_for(fetch(url, wait_selector, timeout_s), limit)
                except Exception as e:  # noqa: BLE001 – jeder Fehler führt zum nächsten Browser
                    log.info("%s fehlgeschlagen für %s (%s)", engine, url, e)
                    continue
                if found:
                    self.last_engine = engine
                    if engine == "chromium":
                        log.info("Chromium-Fallback genutzt für %s", url)
                    return html
                log.info("%s: Selektor %r nicht gefunden auf %s", engine, wait_selector, url)
                fallback_html, self.last_engine = html, engine
            if return_on_timeout and fallback_html is not None:
                return fallback_html
            raise SourceError(f"Seite nicht ladbar oder unvollständig: {url}")

    async def close(self) -> None:
        try:
            if self._local is not None:
                await self._local.close()
            if self._pw is not None:
                await self._pw.stop()
        except PlaywrightError:
            pass
        self._local = None
        self._pw = None
