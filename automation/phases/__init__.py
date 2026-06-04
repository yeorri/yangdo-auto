"""Phase 레지스트리 — 기본 실행 순서.

순서: ①위택스 신고(가상계좌 지연 대비 먼저) ②홈택스 신고 ③홈택스 부속서류
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
    wetax_filing,
    hometax_filing,
    hometax_attach,
    hometax_docs,
    wetax_docs,
    hometax_napbu,
    wetax_napbu,
]

PHASE_BY_KEY = {p.KEY: p for p in ALL_PHASES}
