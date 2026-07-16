"""Phase: 홈택스 부속·증빙서류 제출.

라이브 검증된 흐름:
  홈 리셋 → 신고/납부 → 양도소득세 → '신고 부속·증빙서류 제출' 모달
  → 양도인 주민번호(6+7) 입력 → 조회 → 조회완료 알림 확인
  → 신고건 행의 '첨부하기'(새 팝업) → 폴더 내 파일 전부 주입(multiple)
  → '부속서류 제출하기' → 확인.

전제: inp.seller_rrn(양도인 주민번호 13자리), inp.attach_folder(폴더, 안의 파일 전부 첨부).
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .base import Inputs, PhaseResult

KEY = "hometax_attach"
LABEL = "홈택스 부속서류 제출"
SITE = "홈택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    folder = Path(inp.attach_folder) if inp.attach_folder else None
    if not folder or not folder.is_dir():
        res.reason = "부속서류 폴더 미지정/없음"
        log(f"[!] {res.reason}: {inp.attach_folder}")
        return res

    # 자연 정렬(숫자 인식): 0,1,2,…,10,11 순. 문자열 정렬은 0,1,10,11,…,2 로 올라가
    # 제출내역 순서가 뒤죽박죽이 됨.
    import re as _re

    def _natkey(p: Path):
        return [int(t) if t.isdigit() else t.lower()
                for t in _re.split(r"(\d+)", p.name)]

    files = [str(p) for p in sorted(folder.iterdir(), key=_natkey) if p.is_file()]
    if not files:
        res.reason = "폴더에 첨부할 파일 없음"
        log(f"[!] {res.reason}")
        return res
    if not inp.seller_rrn or len(inp.seller_rrn.replace("-", "")) != 13:
        res.reason = "양도인 주민번호(13자리) 필요"
        log(f"[!] {res.reason}")
        return res

    page = B.find_page(ctx, "hometax.go.kr")
    if page is None:
        res.reason = "홈택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    if not await H.navigate_to_attach(page, log):
        res.reason = "부속서류 화면 진입 실패"
        return res
    popup = await H.query_and_open_attach(ctx, page, inp.seller_rrn, log)
    if popup is None:
        res.reason = "조회/첨부 팝업 열기 실패"
        return res
    ok = await H.attach_files_and_submit(popup, files, log, auto_submit=inp.auto_submit, parent=page)
    try:
        if not popup.is_closed():
            await popup.close()
    except Exception:
        pass

    res.ok = ok
    if ok and inp.auto_submit:
        res.reason = f"부속서류 {len(files)}개 제출 완료"
    elif ok:
        res.reason = f"부속서류 {len(files)}개 첨부완료(수동제출)"
    else:
        res.reason = "부속서류 제출 실패"
    return res
