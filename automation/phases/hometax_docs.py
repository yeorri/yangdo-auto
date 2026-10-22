"""Phase: 홈택스 접수증·신고서 PDF저장/출력 (납부서 제외).

홈 리셋 → 신고/납부 → 양도소득세 → '신고내역 조회' → 주민번호 조회 → 접수번호 링크
→ 개인정보 공개여부 적용 → 접수증([접수증]) + 신고서 목록 각각([신고서]<목록명>).
납부서는 별도 phase(hometax_napbu)에서 — 위택스 가상계좌 대기와 분리하기 위함.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .base import Inputs, PhaseResult

KEY = "hometax_docs"
LABEL = "홈택스 접수증·신고서 출력"
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
    if not await H.open_receipt_docs(ctx, page, inp.seller_rrn, log):
        res.reason = "접수번호 링크 열기 실패"
        return res

    summary = await H.print_documents(
        ctx, page, out_dir, inp.name_label,
        disclose=inp.disclose_personal_info, output_mode=inp.output_mode,
        include_name=inp.include_name, log=log,
    )
    res.outputs = summary.get("saved", [])
    failed = summary.get("failed", [])
    verb = "저장" if inp.output_mode == "pdf" else "출력"
    # ⚠ 하나라도 실패하면 단계 실패다. 예전엔 일부만 저장돼도 ok=True였는데,
    #   그러면 병합 안전장치가 통과돼 서류가 빠진 병합본이 만들어지고 원본까지 지워진다
    #   (2026-10-22: 신고서 0건인데 '성공 / 1건 저장' → 접수증+지방세만 병합 → 원본 삭제).
    #   저장된 파일은 outputs에 그대로 남는다 — 실패 표시는 '다시 돌려라'는 신호일 뿐.
    if res.outputs and not failed:
        res.ok = True
        res.reason = f"{len(res.outputs)}건 {verb} 완료"
    elif res.outputs:
        res.reason = f"일부 실패 — {len(res.outputs)}건 {verb}, {len(failed)}건 실패: {failed}"
        log(f"[!] (홈택스) {res.reason}")
    else:
        res.reason = f"서류 {verb} 실패: {failed}"
    return res
