"""위택스 출력 검증 — 신고서(wetax_docs) + 납부서(wetax_napbu) 호출.

실행:  python tools/run_phase5.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright

from automation import browser as B
from automation.phases import wetax_docs, wetax_napbu
from automation.phases.base import Inputs

SAVE = r""   # PDF 저장 폴더
NAME = ""   # 신고인 성명


async def wait_login(page, timeout=480):
    print("[i] 위택스 로그인 대기(최대 8분)", flush=True)
    for sec in range(0, timeout, 2):
        try:
            if "로그아웃" in await page.locator("body").inner_text(timeout=2500):
                print(f"[v] 로그인 ({sec}s)", flush=True); return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


async def main():
    B.ensure_pdf_sticky_settings()
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        page = (await B.open_homepages(ctx, ["위택스"]))["위택스"]
        if not await wait_login(page):
            await ctx.close(); return

        inp = Inputs(name_label=NAME, output_dir=SAVE, output_mode="pdf", include_name=True,
                     napbu_wait_sec=0)  # 테스트라 대기 없이

        def emit(kind, **kw):
            if kind == "log":
                print(kw.get("text", ""), flush=True)

        for mod in (wetax_docs, wetax_napbu):
            res = await mod.run(ctx, inp, emit)
            print(f"[결과] {mod.LABEL}: ok={res.ok} reason={res.reason}", flush=True)
            print(f"  저장: {res.outputs}", flush=True)

        await page.wait_for_timeout(8000)
        await ctx.close()
        print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
