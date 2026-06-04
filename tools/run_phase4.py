"""홈택스 출력 검증 — 접수증·신고서(hometax_docs) + 납부서(hometax_napbu) 호출.

실행:  python tools/run_phase4.py <주민번호13>
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
from automation.phases import hometax_docs, hometax_napbu
from automation.phases.base import Inputs

SAVE_DIR = r""   # PDF 저장 폴더
NAME = ""   # 신고인 성명


async def wait_login(page, timeout=420):
    print("[i] 홈택스 로그인 대기(최대 7분)")
    for sec in range(0, timeout, 2):
        try:
            body = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        if "로그아웃" in body:
            print(f"[v] 로그인 ({sec}s)"); return True
        await asyncio.sleep(2)
    return False


async def main():
    rrn = sys.argv[1] if len(sys.argv) > 1 else ""

    B.ensure_pdf_sticky_settings()
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        page = (await B.open_homepages(ctx, ["홈택스"]))["홈택스"]
        if not await wait_login(page):
            print("[!] 로그인 미감지"); await ctx.close(); return

        inp = Inputs(
            name_label=NAME,
            seller_rrn=rrn,
            output_dir=SAVE_DIR,
            output_mode="pdf",
            disclose_personal_info=True,
            include_name=True,   # 공동명의 등 → 파일명에 이름 포함
        )

        def emit(kind, **kw):
            if kind == "log":
                print(kw.get("text", ""))

        for mod in (hometax_docs, hometax_napbu):
            res = await mod.run(ctx, inp, emit)
            print(f"[결과] {mod.LABEL}: ok={res.ok} reason={res.reason}")
            print(f"  저장된 파일: {res.outputs}")
        print("[i] 저장 폴더:")
        for f in sorted(Path(SAVE_DIR).glob("*.pdf")):
            print(f"  - {f.name} ({f.stat().st_size}b)")

        print("[i] 8초 후 종료")
        await page.wait_for_timeout(8000)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
