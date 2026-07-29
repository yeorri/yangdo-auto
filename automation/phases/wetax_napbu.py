"""Phase: 위택스 지방세 납부서(가상계좌) PDF저장/출력.

⚠ 가상계좌는 신고 후 몇 분 지나야 생성됨 → 이 phase 시작 시 inp.napbu_wait_sec 만큼 대기
(중단 가능). 그 뒤 신고내역 → 출력물 보기 → 납부서(openReport 'Y') OZ 출력.
가상계좌 미생성/차손이면 납부서 링크 없어 0건 → '없음'으로 정상 처리(나중에 재실행 가능).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from .. import browser as B
from .. import wetax as W
from .base import Inputs, PhaseResult

KEY = "wetax_napbu"
LABEL = "위택스 납부서 출력"
SITE = "위택스"


async def _wait(sec: int, emit, stop_check) -> None:
    """가상계좌 생성 대기(1초 단위, 중단 가능). 10초마다 남은 시간 로그."""
    log = lambda m: emit("log", text=m)
    if sec <= 0:
        return
    log(f"[i] (위택스) 가상계좌 생성 대기 {sec}초…")
    for elapsed in range(sec):
        if stop_check and stop_check():
            log("[i] (위택스) 대기 중단됨")
            return
        if elapsed and elapsed % 10 == 0:
            log(f"    대기 {elapsed}/{sec}초")
        await asyncio.sleep(1)


async def _wait_napbu(sec: int, emit, stop_check, skip_check=None, extend_check=None) -> None:
    """가상계좌 생성 대기 — 사용자가 중간에 개입할 수 있다.

    가상계좌는 납부서 PDF '문서 안'에 인쇄되는 값이라 프로그램이 생성 여부를 알 수 없다
    (링크·버튼은 신고 즉시 생김). 그래서 시간으로 기다리되:
      - skip_check()가 True → 남은 시간을 버리고 '즉시 출력'(사용자가 눈으로 확인한 경우)
      - extend_check()가 True → 그만큼 시간을 더 기다림(아직 안 뜬 경우)
    """
    log = lambda m: emit("log", text=m)
    total = max(0, int(sec or 0))
    if total <= 0:
        return
    log(f"[i] (위택스) 가상계좌 생성 대기 {total}초 — "
        f"이미 떴으면 [지금 출력], 더 필요하면 [+1분]을 누르세요")
    emit("napbu_wait", state="start", total=total)
    elapsed = 0
    try:
        while elapsed < total:
            if stop_check and stop_check():
                log("[i] (위택스) 대기 중단됨")
                return
            if skip_check and skip_check():
                log(f"[v] (위택스) 사용자 요청 — 대기 건너뛰고 즉시 출력 ({elapsed}초 경과)")
                return
            if extend_check:
                more = extend_check()
                if more:
                    total += more
                    log(f"[i] (위택스) 대기 {more}초 연장 → 총 {total}초")
            await asyncio.sleep(1)
            elapsed += 1
            if elapsed % 10 == 0:
                log(f"    대기 {elapsed}/{total}초")
                emit("napbu_wait", state="tick", elapsed=elapsed, total=total)
    finally:
        emit("napbu_wait", state="end")


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    out_dir = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")
    page = B.find_page(ctx, "wetax.go.kr")
    if page is None:
        res.reason = "위택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res

    await _wait_napbu(int(inp.napbu_wait_sec or 0), emit, stop_check,
                      skip_check=getattr(inp, "napbu_skip_check", None),
                      extend_check=getattr(inp, "napbu_extend_check", None))
    if stop_check and stop_check():
        res.reason = "중단됨"
        return res
    await page.bring_to_front()

    summary = await W.print_napbu(
        ctx, page, out_dir, inp.name_label, output_mode=inp.output_mode,
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
        res.ok = True  # 가상계좌 미생성/차손 — 없음(나중에 재실행 가능)
        res.reason = "납부서 없음(가상계좌 미생성/차손) — 나중에 재실행 가능"
    return res
