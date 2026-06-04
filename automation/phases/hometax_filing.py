"""Phase: 홈택스 양도소득세 파일변환신고.

라이브 검증된 흐름까지 자동 수행:
  메뉴 내비게이션 → 파일 주입(KUpload, set_input_files) → 파일검증하기
  → 종전내역 모달 처리 → 검증 완료 대기.
제출([제출하러 가기]→[전자파일제출하기])은 실제·비가역 신고라 별도 단계에서 확인 후 구현.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .base import Inputs, PhaseResult

KEY = "hometax_filing"
LABEL = "홈택스 양도세 파일변환신고"
SITE = "홈택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    if not inp.hometax_convert_file or not Path(inp.hometax_convert_file).exists():
        res.reason = "홈택스 변환파일 경로가 없거나 파일이 없음"
        log(f"[!] {res.reason}: {inp.hometax_convert_file}")
        return res

    page = B.find_page(ctx, "hometax.go.kr")
    if page is None:
        res.reason = "홈택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    # 1) 메뉴 → 파일변환신고 화면
    if not await H.navigate_to_file_convert(page, log):
        res.reason = "메뉴 내비게이션 실패"
        return res
    await H.handle_prev_record_modal(page, log)  # 진입 시 모달이 떠 있으면 처리

    # 2) 파일 주입 (KUpload)
    if not await H.inject_convert_file(page, inp.hometax_convert_file, log):
        res.reason = "파일 주입 실패"
        return res

    # 3) 파일검증하기 → 모달 처리 → 검증 완료 대기
    status = await H.verify_and_wait(page, log)
    if status != "완료":
        res.reason = f"검증 미완료({status})"
        return res

    if not inp.auto_submit:
        log("[i] (홈택스) 검증 완료. auto_submit=False → 제출은 사람이 직접.")
        res.ok = True
        res.reason = "검증완료(수동제출 모드)"
        return res

    # 4) 제출하러 가기 → 전자파일 제출하기 → 제출확인 → 접수증 '닫기' (실제·비가역)
    ok = await H.submit_filing(page, log)
    res.ok = ok
    res.reason = "제출 완료" if ok else "제출 실패"
    return res
