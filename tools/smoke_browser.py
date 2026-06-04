"""스모크 테스트 — 영구 프로필 Chromium이 뜨고 홈택스가 로드되는지 확인.

실행:  python tools/smoke_browser.py
GUI와 동시에 실행하지 말 것(.profile 잠금 충돌).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright

from automation import browser as B


async def main():
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        pages = await B.open_homepages(ctx, ["홈택스"])
        page = pages["홈택스"]
        await page.wait_for_timeout(4000)
        print("URL  :", page.url)
        print("TITLE:", await page.title())
        shot = Path(__file__).resolve().parent.parent / "smoke_hometax.png"
        await page.screenshot(path=str(shot))
        print("SCREENSHOT:", shot)
        await ctx.close()
        print("OK: 브라우저 정상 실행/종료")


if __name__ == "__main__":
    asyncio.run(main())
