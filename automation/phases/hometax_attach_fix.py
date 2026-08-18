"""Phase: 홈택스 부속서류 수정 — 기존 제출분을 지우고 다시 제출.

계산이 틀렸거나 엉뚱한 서류를 냈을 때 쓴다. 제출 절차 자체는 ③과 같고, 앞에
'기존 제출분 삭제'가 붙는 것만 다르다.

흐름(라이브 절차 그대로):
  홈 리셋 → 신고/납부 → 양도소득세 → '신고 부속·증빙서류 제출' 모달
  → 양도인 주민번호 입력 → 조회
  → [첨부하기] 자리에 뜬 **[제출내역보기]** → 제출목록 모달
  → 선택 라디오 체크 → [선택한 부속서류 삭제] → '정상 삭제' 확인 (남은 게 없을 때까지 반복)
  → 모달 닫기 → **③과 완전히 동일한 제출 과정을 처음부터** 다시 수행.

⚠ 삭제만 하고 끝나면 부속서류가 없는 신고건이 남는다 → 이 phase는 삭제와 재제출을
  한 덩어리로 수행한다(삭제 단독 실행은 만들지 않음). 재제출은 hometax_attach.run을
  그대로 호출해 ③의 검증된 경로(조회 안정화 후 주입·재주입·등록 확인)를 재사용한다.
"""
from __future__ import annotations

from .. import browser as B
from .. import hometax as H
from . import hometax_attach
from .base import Inputs, PhaseResult

KEY = "hometax_attach_fix"
LABEL = "홈택스 부속서류 수정"
SITE = "홈택스"
# 기존 제출분을 지우는 되돌릴 수 없는 단계 → GUI에서 기본 꺼짐. 필요할 때만 켠다.
DEFAULT_ON = False


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

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

    # ── 1단계: 기존 제출분 삭제 ──
    if not await H.navigate_to_attach(page, log):
        res.reason = "부속서류 화면 진입 실패"
        return res
    removed = 0
    if await H.open_submitted_list(page, inp.seller_rrn, log):
        removed = await H.delete_submitted_attachments(page, log)
        if removed < 0:
            res.reason = "기존 부속서류 삭제 실패 — 재제출하지 않음"
            log(f"[!] (홈택스) {res.reason} (지금 제출하면 기존 서류와 섞인다)")
            return res
    if removed == 0:
        log("[i] (홈택스) 삭제할 기존 부속서류 없음 — 제출만 진행")

    if stop_check and stop_check():
        res.reason = "중단됨"
        return res

    # ── 2단계: ③과 동일한 제출 (검증된 경로 그대로 재사용) ──
    log("[i] (홈택스) 기존 제출분 정리 완료 — 부속서류 제출을 처음부터 다시 진행")
    sub = await hometax_attach.run(ctx, inp, emit, stop_check=stop_check)
    res.ok = sub.ok
    res.outputs = sub.outputs
    if sub.ok:
        res.reason = (f"기존 {removed}건 삭제 후 재제출 완료" if removed
                      else f"{sub.reason} (삭제 대상 없음)")
    else:
        res.reason = f"삭제 {removed}건 후 재제출 실패 — {sub.reason}"
        log("[!] (홈택스) 기존 부속서류는 지워졌으나 재제출이 실패했다 — "
            "홈택스에서 직접 제출하거나 이 단계를 다시 실행할 것")
    return res
