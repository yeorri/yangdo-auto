"""Phase 레지스트리 — 기본 실행 순서.

순서: ①홈택스 신고 ②위택스 신고 ③홈택스 부속서류(수정=기존 제출분 삭제 후 재제출은 Inputs.replace_attachments 옵션)
      ⚠ 신고는 **홈택스(양도세)가 먼저**다(2026-10-29 변경). 신고가 실패하면 전체를 멈추는데
        (pipeline.FILING_KEYS), 흔한 실패인 양도세 내용검증 오류가 위택스 뒤에 나면 이미
        지방세가 접수된 반쪽 상태가 남는다. 홈택스를 먼저 하면 아무것도 접수되기 전에 멈춘다.
        예전엔 위택스가 먼저였다(가상계좌 생성 시간을 벌려고) — 늦어지는 건 홈택스 신고
        한 번(10~30초)뿐이고 ⑦ 대기엔 [지금 출력]/[+1분]이 있어 실익이 작았다.
      ④홈택스 접수증·신고서 출력 ⑤위택스 신고서 출력
      ⑥홈택스 납부서 출력 ⑦위택스 납부서 출력(가상계좌 대기 후).
서류 출력과 납부서 출력을 분리 — 위택스 가상계좌 생성 지연이 신고서 출력/병합을
막지 않게. 차손 등 납부서 없는 건은 ⑥⑦을 끄거나 켜도 0건으로 정상 종료.
각 phase 모듈은 KEY / LABEL / async run(ctx, inp, emit, stop_check) 인터페이스를 따른다.
"""
from __future__ import annotations

from . import (
    hometax_attach,
    hometax_docs,
    hometax_filing,
    hometax_napbu,
    wetax_docs,
    wetax_filing,
    wetax_napbu,
)

# 기본 순서 (GUI에서 순서 변경/토글 가능)
ALL_PHASES = [
    hometax_filing,
    wetax_filing,
    hometax_attach,
    hometax_docs,
    wetax_docs,
    hometax_napbu,
    wetax_napbu,
]

PHASE_BY_KEY = {p.KEY: p for p in ALL_PHASES}
