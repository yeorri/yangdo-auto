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


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    out_dir = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")
    page = B.find_page(ctx, "wetax.go.kr")
    if page is None:
        res.reason = "위택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res

    await _wait(int(inp.napbu_wait_sec or 0), emit, stop_check)
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
