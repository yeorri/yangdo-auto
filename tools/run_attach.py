"""Phase 3 단독 — 테스트 건 부속서류 제출 (검증/진단용, 재제출 가능).

홈택스 로그인 후 자동 진행. 새 검증 로직(첨부 등록 확인 + 완료 메시지 검증) 동작 확인용.

실행:  python tools/run_attach.py
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
from automation.phases import hometax_attach
from automation.phases.base import Inputs

RRN = ""   # 양도인 주민번호 13자리
ATTACH = r""   # 부속서류 폴더


async def wait_login(page, timeout=420):
    print("[i] 홈택스 로그인 대기(최대 7분)")
    for sec in range(0, timeout, 2):
        try:
            if "로그아웃" in await page.locator("body").inner_text(timeout=2500):
                print(f"[v] 로그인 ({sec}s)")
                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    print("[!] 로그인 미완료")
    return False


async def main():
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        pages = await B.open_homepages(ctx, ["홈택스"])
        if not await wait_login(pages["홈택스"]):
            await ctx.close(); return

        inp = Inputs(name_label="", seller_rrn=RRN, attach_folder=ATTACH, auto_submit=True)

        def emit(kind, **kw):
            if kind == "log":
                print(kw.get("text", ""))

        print(f"\n===== {hometax_attach.LABEL} =====")
        res = await hometax_attach.run(ctx, inp, emit)
        print(f"\n[결과] ok={res.ok} / {res.reason}")
        print("[i] 10초 후 종료")
        await pages["홈택스"].wait_for_timeout(10000)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
