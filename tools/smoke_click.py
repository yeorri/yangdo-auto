"""클릭 테스트 — 홈택스 '신고/납부' 메뉴가 자동으로 눌러지는지 + 양도소득세가 보이는지.

영구 프로필을 재실행하므로 로그인 세션이 유지되면 로그인 상태로 뜬다.
GUI/다른 Chromium이 떠 있으면 .profile 잠금 충돌 → 먼저 닫을 것.

실행:  python tools/smoke_click.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright

from automation import browser as B


async def any_visible(locator) -> bool:
    n = await locator.count()
    for i in range(n):
        try:
            if await locator.nth(i).is_visible():
                return True
        except Exception:
            pass
    return False


async def main():
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        pages = await B.open_homepages(ctx, ["홈택스"])
        page = pages["홈택스"]
        await page.wait_for_timeout(4000)

        print("URL:", page.url)
        body = await page.locator("body").inner_text()
        print("로그인 상태(로그아웃 버튼 보임):", "로그아웃" in body)

        # 사용자가 준 id가 그대로 존재하는지(동적 id 여부 점검)
        gid = "#mf_wfHeader_hdGroup919"
        print(f"고정 id {gid} 존재:", await page.locator(gid).count())

        menu = page.get_by_text("신고/납부", exact=True).first
        print("'신고/납부' 메뉴 발견 수:", await page.get_by_text("신고/납부", exact=True).count())

        ygd = page.get_by_text("양도소득세", exact=True)
        print("클릭 전 양도소득세 보임:", await any_visible(ygd))

        # 메뉴 호버 후 클릭 (드롭다운 펼침)
        try:
            await menu.hover()
            await page.wait_for_timeout(800)
        except Exception as e:
            print("hover 실패:", str(e)[:80])
        try:
            await menu.click(timeout=5000)
        except Exception as e:
            print("click 실패:", str(e)[:80])
        await page.wait_for_timeout(1500)

        print("클릭 후 양도소득세 보임:", await any_visible(ygd))
        shot = Path(__file__).resolve().parent.parent / "smoke_click.png"
        await page.screenshot(path=str(shot))
        print("SCREENSHOT:", shot)
        await page.wait_for_timeout(2000)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
