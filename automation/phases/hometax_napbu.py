"""Phase: 홈택스 납부서 PDF저장/출력.

홈 리셋 → 신고/납부 → 양도소득세 → '신고내역 조회' → 주민번호 조회
→ 납부서 [보기] → 납부서 목록 → 각 납부서(분납 N건) PDF. 차손/무납부서면 0건(성공 처리).
접수증·신고서 출력(hometax_docs)과 분리 — 위택스 가상계좌 대기 동안 막히지 않게.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .base import Inputs, PhaseResult

KEY = "hometax_napbu"
LABEL = "홈택스 납부서 출력"
SITE = "홈택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    if not inp.seller_rrn or len(inp.seller_rrn.replace("-", "")) != 13:
        res.reason = "양도인 주민번호(13자리) 필요"
        log(f"[!] {res.reason}")
        return res
    out_dir = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")

    page = B.find_page(ctx, "hometax.go.kr")
    if page is None:
        res.reason = "홈택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    if not await H.navigate_to_inquiry(page, log):
        res.reason = "신고내역 조회 화면 진입 실패"
        return res
    if not await H.query_inquiry(page, inp.seller_rrn, log):
        res.reason = "주민번호 조회 실패"
        return res

    summary = await H.print_napbu(
        ctx, page, out_dir, label=inp.name_label, output_mode=inp.output_mode,
        include_name=inp.include_name, log=log,
    )
    res.outputs = summary.get("saved", [])
    failed = summary.get("failed", [])
    verb = "저장" if inp.output_mode == "pdf" else "출력"
    if failed:
        res.ok = bool(res.outputs)
        res.reason = f"{len(res.outputs)}건 {verb}, {len(failed)}건 실패: {failed}"
    elif res.outputs:
        res.ok = True
        res.reason = f"납부서 {len(res.outputs)}건 {verb} 완료"
    else:
        res.ok = True  # 차손/무납부서 — 정상(없음)
        res.reason = "납부서 없음(차손 등) — 건너뜀"
    return res
