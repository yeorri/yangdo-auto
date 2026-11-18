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
from .. import rowpick as R
from .base import Inputs, PhaseResult

KEY = "hometax_attach"
LABEL = "홈택스 부속서류 제출"
SITE = "홈택스"

# 홈택스가 부속서류 파일명에 허용하지 않는 문자 — 제출 시 알림 원문 그대로:
#   '파일명에 특수문자는 들어갈 수 없습니다. [ !*!=?/|:;@#$%^& ]'
# 하나라도 걸리면 **제출 전체가 거부**된다(그 파일만 빠지는 게 아님, 2026-11 임혜성 건 '&').
# 공백·괄호·쉼표·하이픈·밑줄은 과거 제출 성공 이력이 있어 허용으로 본다.
FORBIDDEN_CHARS = "!*=?/|:;@#$%^&"


def bad_attach_names(folder) -> list[tuple[str, str]]:
    """폴더에서 홈택스가 거부할 파일명 목록 [(파일명, 걸린 문자들)]. 문제 없으면 [].

    GUI가 폴더를 고르는 즉시 이걸로 검사해 [시작]을 막고, 실행 시에도 다시 확인한다
    (같은 기준을 두 곳에서 쓰도록 여기 한 곳에 둔다).
    """
    try:
        names = [p.name for p in Path(folder).iterdir() if p.is_file()]
    except Exception:
        return []
    out = []
    for n in names:
        hit = "".join(c for c in FORBIDDEN_CHARS if c in n)
        if hit:
            out.append((n, hit))
    return out


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

    # 파일명 금지문자 — 홈택스에 들어가기 전에 거른다(GUI가 먼저 막지만, 시작 후 폴더가 바뀐
    # 경우를 위해 실행 시에도 확인). 걸리면 제출 전체가 거부되므로 첨부를 시도하지 않는다.
    named = bad_attach_names(folder)
    if named:
        res.reason = ("파일명에 홈택스 금지문자 — "
                      + ", ".join(f"{n}({c})" for n, c in named[:3])
                      + (f" 외 {len(named) - 3}개" if len(named) > 3 else ""))
        log(f"[!] (홈택스) {res.reason}")
        log(f"[i] (홈택스) 사용할 수 없는 문자: {' '.join(FORBIDDEN_CHARS)} — 이름을 고친 뒤 다시 실행하세요.")
        return res

    # ⚠ OneDrive '파일 온디맨드'는 목록엔 보여도 로컬에 실체가 없어 열 때 WinError 2가 난다.
    #   주입 전에 실제로 읽히는지 확인해, 어떤 파일이 문제인지 로그로 남긴다.
    bad = []
    for f in files:
        try:
            with open(f, "rb") as fh:
                fh.read(1)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{Path(f).name} ({type(e).__name__})")
    if bad:
        res.reason = f"열 수 없는 파일 {len(bad)}개 — 첨부 중단"
        log(f"[!] {res.reason}: {', '.join(bad[:5])}")
        log("[i] OneDrive 등 클라우드 폴더면 해당 파일을 '이 장치에 항상 유지'로 받아두세요.")
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

    # 이미 제출된 건인지 먼저 본다 — 조회 결과의 [첨부하기] 자리에 [제출내역보기]가 뜬다.
    # ⚠ 이 확인이 없으면 이미 제출된 건에서 [첨부하기]를 못 찾아 정체불명의 실패로 끝난다.
    if not await H.query_attach(page, inp.seller_rrn, log):
        res.reason = "조회 실패"
        return res
    # 어느 신고건인가 — 같은 사람 신고건이 여러 줄일 수 있다. 접수번호를 정하지 못하면 멈춘다
    # (다른 건에 첨부하거나, [수정]으로 다른 건의 부속서류를 지우는 것보다 멈추는 게 낫다).
    rc = await R.resolve(page, inp.hometax_receipt_no, inp.hometax_filed_now, log, screen="부속서류")
    if not rc:
        res.reason = "어느 신고건인지 특정하지 못함 — 첨부하지 않음"
        return res
    inp.hometax_receipt_no = rc
    removed = 0
    state = await H.attach_state(page, rc)
    if state == "":
        res.reason = f"접수번호 {rc} 줄에서 [첨부하기]·[제출내역보기]를 찾지 못함"
        log(f"[!] (홈택스) {res.reason}")
        return res
    if state == "submitted":
        if not inp.replace_attachments:
            res.reason = "이미 부속서류가 제출된 건 — [수정]을 켜고 다시 실행하세요"
            log(f"[!] (홈택스) {res.reason} (접수번호 {rc})")
            log("[i] (홈택스) 기존 제출분을 임의로 지우지 않았습니다.")
            return res
        log(f"[i] (홈택스) 이미 제출된 건(접수번호 {rc}) — 기존 제출분을 지우고 다시 제출합니다(수정)")
        if not await H.open_submitted_list(page, log, receipt_no=rc):
            res.reason = "제출내역 열기 실패 — 재제출하지 않음"
            return res
        # 지우기 직전 한 번 더 — 열린 제출목록이 정말 이 접수번호 것인지 모달의 '신고서접수번호'로 확인
        if not await H.submitted_list_is_for(page, rc):
            res.reason = f"열린 제출목록이 접수번호 {rc} 것인지 확인하지 못함 — 삭제하지 않음"
            log(f"[!] (홈택스) {res.reason}")
            return res
        removed = await H.delete_submitted_attachments(page, log)
        if removed < 0:
            res.reason = "기존 부속서류 삭제 실패 — 재제출하지 않음"
            log(f"[!] (홈택스) {res.reason} (지금 제출하면 기존 서류와 섞인다)")
            return res
        # 전부 지우면 목록이 [첨부하기]로 돌아온다 → 처음부터 평소 경로를 탄다.
        if stop_check and stop_check():
            res.reason = "중단됨"
            return res
        if not await H.navigate_to_attach(page, log):
            res.reason = "삭제 후 부속서류 화면 재진입 실패"
            return res

    popup = await H.query_and_open_attach(ctx, page, inp.seller_rrn, log, receipt_no=rc)
    if popup is None:
        res.reason = "조회/첨부 팝업 열기 실패"
        return res
    ok = await H.attach_files_and_submit(popup, files, log, auto_submit=inp.auto_submit,
                                         parent=page, dump_dir=inp.output_dir)
    try:
        if not popup.is_closed():
            await popup.close()
    except Exception:
        pass

    res.ok = ok
    fixed = f"기존 {removed}건 삭제 후 " if removed else ""
    if ok and inp.auto_submit:
        res.reason = f"{fixed}부속서류 {len(files)}개 제출 완료"
    elif ok:
        res.reason = f"{fixed}부속서류 {len(files)}개 첨부완료(수동제출)"
    else:
        res.reason = f"{fixed}부속서류 제출 실패" if removed else "부속서류 제출 실패"
        if removed:
            log("[!] (홈택스) 기존 부속서류는 지워졌으나 재제출이 실패했다 — "
                "홈택스에서 직접 제출하거나 이 단계를 다시 실행할 것")
    return res
