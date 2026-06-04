"""Stage1 — 테스트 건 ①위택스 신고 ②홈택스 신고 ③부속서류 제출 (실제 phase 코드).

위택스+홈택스 둘 다 로그인 후 자동 진행. ⚠ 실제 제출(재신고 가능).

실행:  python tools/run_submit.py
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
from automation.phases import wetax_filing, hometax_filing, hometax_attach
from automation.phases.base import Inputs

# ↓ 본인 테스트 데이터로 채워서 사용 (실제 PII는 커밋하지 말 것)
HT_FILE = r""   # 홈택스 양도세 변환파일 *.01
WT_FILE = r""   # 위택스 지방세 변환파일 *.Y13
RRN = ""        # 양도인 주민번호 13자리
ATTACH = r""    # 부속서류 폴더
SAVE = r""      # PDF 저장 폴더


async def wait_both_login(wt_page, ht_page, timeout=600):
    print("[i] 위택스 + 홈택스 둘 다 로그인해 주세요. (최대 10분)")
    done_wt = done_ht = False
    for sec in range(0, timeout, 2):
        if not done_wt:
            try:
                if "로그아웃" in await wt_page.locator("body").inner_text(timeout=2500):
                    done_wt = True; print(f"[v] 위택스 로그인 ({sec}s)")
            except Exception:
                pass
        if not done_ht:
            try:
                if "로그아웃" in await ht_page.locator("body").inner_text(timeout=2500):
                    done_ht = True; print(f"[v] 홈택스 로그인 ({sec}s)")
            except Exception:
                pass
        if done_wt and done_ht:
            return True
        await asyncio.sleep(2)
    print(f"[!] 로그인 미완료 (위택스={done_wt}, 홈택스={done_ht})")
    return done_wt and done_ht


async def main():
    B.ensure_pdf_sticky_settings()
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        pages = await B.open_homepages(ctx, ["위택스", "홈택스"])
        wt_page, ht_page = pages["위택스"], pages["홈택스"]

        if not await wait_both_login(wt_page, ht_page):
            await ctx.close(); return

        inp = Inputs(
            name_label="",
            wetax_convert_file=WT_FILE,
            hometax_convert_file=HT_FILE,
            seller_rrn=RRN,
            attach_folder=ATTACH,
            output_dir=SAVE,
            auto_submit=True,
        )

        def emit(kind, **kw):
            if kind == "log":
                print(kw.get("text", ""))

        for mod in (wetax_filing, hometax_filing, hometax_attach):
            print(f"\n===== {mod.LABEL} =====")
            try:
                res = await mod.run(ctx, inp, emit)
                print(f"[결과] {mod.LABEL}: ok={res.ok} / {res.reason}")
            except Exception as e:
                print(f"[!] {mod.LABEL} 예외: {e}")

        print("\n[i] 20초 후 종료")
        await ht_page.wait_for_timeout(20000)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
