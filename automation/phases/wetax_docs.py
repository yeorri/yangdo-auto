"""Phase: 위택스 지방세 신고서 PDF저장/출력 (납부서 제외).

양도소득분 신고내역(직접 URL) → name 행 '출력물 보기' → 신고서(openReport) OZ 뷰어
→ [인쇄]→[확인] → PDF저장/출력. 납부서(가상계좌)는 별도 phase(wetax_napbu)에서.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import wetax as W
from .base import Inputs, PhaseResult

KEY = "wetax_docs"
LABEL = "위택스 신고서 출력"
SITE = "위택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    out_dir = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")
    page = B.find_page(ctx, "wetax.go.kr")
    if page is None:
        res.reason = "위택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    summary = await W.print_singo(
        ctx, page, out_dir, inp.name_label, output_mode=inp.output_mode,
        pick=inp.wetax_pick, trade_ym=inp.wetax_trade_ym,
        include_name=inp.include_name, log=log,
    )
    res.outputs = summary.get("saved", [])
    failed = summary.get("failed", [])
    verb = "저장" if inp.output_mode == "pdf" else "출력"
    if res.outputs and not failed:
        res.ok = True
        res.reason = f"{len(res.outputs)}건 {verb} 완료"
    elif res.outputs:
        # 일부만 저장돼도 실패 — ok=True면 병합이 서류 빠진 채 진행된다(hometax_docs와 동일).
        res.reason = f"일부 실패 — {len(res.outputs)}건 {verb}, {len(failed)}건 실패: {failed}"
        log(f"[!] (위택스) {res.reason}")
    else:
        res.reason = f"위택스 신고서 {verb} 실패: {failed}"
    if summary.get("memo"):
        # 진행은 했지만 사람이 확인할 것이 있다 — 결과 줄에도 남겨 로그 끝에서 다시 보이게.
        res.reason += " / ⚠ 납부기한이 같은 신고건이 또 있음(로그 확인)"
    return res
