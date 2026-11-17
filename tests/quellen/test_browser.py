import asyncio

import pytest

from werkstudent.quellen.basis import SourceError
from werkstudent.quellen.browser import Browser

# _fetch_cdp/_fetch_local liefern (html, selector_gefunden)


def _patch(monkeypatch, b, cdp, local):
    monkeypatch.setattr(b, "_fetch_cdp", cdp)
    monkeypatch.setattr(b, "_fetch_local", local)


async def test_fetch_html_falls_back_to_chromium(monkeypatch):
    b = Browser("ws://nowhere:9222")
    calls = []

    async def cdp(*a):
        calls.append("cdp")
        raise RuntimeError("connect failed")

    async def local(*a):
        calls.append("local")
        return "<html>ok</html>", True

    _patch(monkeypatch, b, cdp, local)
    assert await b.fetch_html("https://x", "body") == "<html>ok</html>"
    assert calls == ["cdp", "local"]
    assert b.last_engine == "chromium"


async def test_fetch_html_uses_lightpanda_when_it_works(monkeypatch):
    b = Browser("ws://nowhere:9222")

    async def cdp(*a):
        return "<html>lp</html>", True

    async def local(*a):
        raise AssertionError("fallback must not run")

    _patch(monkeypatch, b, cdp, local)
    assert await b.fetch_html("https://x", "body") == "<html>lp</html>"
    assert b.last_engine == "lightpanda"


async def test_incomplete_lightpanda_render_falls_back_even_with_return_on_timeout(monkeypatch):
    b = Browser("ws://nowhere:9222")

    async def cdp(*a):
        return "<html>halb</html>", False

    async def local(*a):
        return "<html>voll</html>", True

    _patch(monkeypatch, b, cdp, local)
    assert await b.fetch_html("https://x", "#cards", return_on_timeout=True) == "<html>voll</html>"
    assert b.last_engine == "chromium"


async def test_return_on_timeout_returns_page_when_both_miss_selector(monkeypatch):
    b = Browser("ws://nowhere:9222")

    async def cdp(*a):
        return "<html>lp</html>", False

    async def local(*a):
        return "<html>keine Treffer</html>", False

    _patch(monkeypatch, b, cdp, local)
    assert await b.fetch_html("https://x", "#cards", return_on_timeout=True) == "<html>keine Treffer</html>"
    with pytest.raises(SourceError):
        await b.fetch_html("https://x", "#cards")


async def test_hung_lightpanda_times_out_and_falls_back(monkeypatch):
    b = Browser("ws://nowhere:9222")

    async def cdp(*a):
        await asyncio.sleep(1000)

    async def local(*a):
        return "<html>ok</html>", True

    _patch(monkeypatch, b, cdp, local)
    assert await asyncio.wait_for(b.fetch_html("https://x", "body", timeout_s=0.01), 2) == "<html>ok</html>"


async def test_search_raises_on_both_browsers_failing(monkeypatch):
    b = Browser("ws://nowhere:9222")

    async def fail(*a):
        raise RuntimeError("nope")

    _patch(monkeypatch, b, fail, fail)
    with pytest.raises(SourceError):
        await b.fetch_html("https://x", "body")
