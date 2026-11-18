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
from .. import rowpick as R
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

    # 3-0) 내용검증 '오류'면 여기서 끝 — 제출 단계로 넘어가지 않는다.
    #      ('완료'는 검증이 끝났다는 뜻일 뿐, 오류여도 완료 문구가 뜬다.)
    if await H.content_check_error(page):
        res.reason = ("내용검증 오류 — 전자제출 불가. 홈택스 화면의 [오류자료]로 내용을 확인하고 "
                      "양도박사에서 고쳐 변환파일을 다시 만드세요")
        log(f"[!] (홈택스) {res.reason}")
        return res

    # 3-1) 내용검증 경고(오류 아님) 확인 — 있으면 경고내역을 엑셀로 받아 두고 모달을 닫는다.
    #      (제출은 막히지 않지만 나중에 무슨 경고였는지 알아야 하므로 기록으로 남김)
    try:
        warns = await H.check_and_save_warnings(page, inp.output_dir or None, log)
        if warns:
            res.reason = f"경고 {warns}건(확인 필요) / "
    except Exception as e:  # noqa: BLE001
        log(f"[i] (홈택스) 경고 확인 중 예외(계속): {str(e)[:60]}")

    if not inp.auto_submit:
        log("[i] (홈택스) 검증 완료. auto_submit=False → 제출은 사람이 직접.")
        res.ok = True
        res.reason = "검증완료(수동제출 모드)"
        return res

    # 4) 제출하러 가기 → 전자파일 제출하기 → 제출확인 → 접수증 '닫기' (실제·비가역)
    ok = await H.submit_filing(page, log)
    res.ok = ok
    res.reason = (res.reason or "") + ("제출 완료" if ok else "제출 실패")
    if ok:
        # 접수번호를 남긴다 — 뒤 단계(부속서류·접수증·납부서)가 '이 신고건의 줄'만 고르는 열쇠.
        # 같은 사람 신고건이 조회 화면에 여러 줄 뜰 수 있어 위치로는 고를 수 없다.
        rc = await R.read_from_modals(page)
        if not rc:
            # 접수증 화면에서 못 읽었으면 지금 바로 신고내역에서 '접수일시가 가장 늦은 줄'을 본다.
            # 방금 신고했으니 지금 이 순간엔 그 줄이 확실히 이번 건이다(나중엔 장담 못 한다).
            try:
                if await H.navigate_to_inquiry(page, log) and await H.query_inquiry(page, inp.seller_rrn, log):
                    rc = await R.resolve(page, "", True, log)
            except Exception as e:  # noqa: BLE001
                log(f"[i] (홈택스) 접수번호 확인 중 예외(계속): {str(e)[:60]}")
        if rc:
            res.receipt_no = rc
            log(f"[i] (홈택스) 접수번호 {rc}")
        else:
            log("[i] (홈택스) 접수번호를 확인하지 못함 — 뒤 단계는 신고건이 한 줄일 때만 진행합니다")
    return res
