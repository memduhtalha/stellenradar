"""Speichert eine echte Seite als Test-Fixture.

Aufruf: python scripts/fixture_aufnehmen.py <url> <wait_selector> <ausgabe.html> [cdp_url]
"""
import asyncio
import sys
from pathlib import Path

from werkstudent.quellen.browser import Browser


async def main() -> None:
    url, selector, out = sys.argv[1:4]
    cdp = sys.argv[4] if len(sys.argv) > 4 else "ws://127.0.0.1:9222"
    b = Browser(cdp)
    try:
        html = await b.fetch_html(url, selector, timeout_s=30, return_on_timeout=True)
    finally:
        await b.close()
    Path(out).write_text(html, encoding="utf-8")
    print(f"{out}: {len(html)} Zeichen über {b.last_engine}")


asyncio.run(main())
