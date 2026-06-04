"""Phase: 위택스 지방소득세 양도소득분 회계파일신고.

라이브 검증된 흐름: 직접 URL 이동 → 팝업닫기 → 파일주입(.Y13/.Y11)
→ [다음] → 서식검증 완료 → [제출] → 정상 완료.
(기본 순서상 첫 번째 — 지방세 납부서 가상계좌가 늦게 떠서 먼저 돌리는 게 유리.)
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import wetax as W
from .base import Inputs, PhaseResult

KEY = "wetax_filing"
LABEL = "위택스 지방세 파일변환신고"
SITE = "위택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    if not inp.wetax_convert_file or not Path(inp.wetax_convert_file).exists():
        res.reason = "위택스 변환파일 경로가 없거나 파일이 없음"
        log(f"[!] {res.reason}: {inp.wetax_convert_file}")
        return res

    page = B.find_page(ctx, "wetax.go.kr")
    if page is None:
        res.reason = "위택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    if not await W.navigate_to_filing(page, log):
        res.reason = "회계파일신고 화면 도달 실패"
        return res
    if not await W.inject_file(page, inp.wetax_convert_file, log):
        res.reason = "파일 주입 실패"
        return res
    if not await W.next_and_verify(page, log):
        res.reason = "서식검증 미완료"
        return res

    if not inp.auto_submit:
        log("[i] (위택스) 서식검증 완료. auto_submit=False → 제출은 사람이 직접.")
        res.ok = True
        res.reason = "검증완료(수동제출 모드)"
        return res

    ok = await W.submit_filing(page, log)
    res.ok = ok
    res.reason = "제출 완료" if ok else "제출 실패"
    return res
