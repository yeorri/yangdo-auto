"""파이프라인 — 선택한 phase들을 한 브라우저에서 순서대로 실행.

GUI가 실행할 phase key 목록(selected_keys)과 Inputs를 넘긴다.
phase는 서로 독립이라 한쪽 실패가 다음 phase를 자동으로 막지는 않는다(계속 진행, 결과만 기록).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from playwright.async_api import async_playwright

from . import browser as B
from . import pdf_save
from .phases import ALL_PHASES, PHASE_BY_KEY
from .phases.base import Inputs, PhaseResult

Emit = Callable[..., None]


def _merge_documents(results: list[PhaseResult], inp: Inputs, log) -> None:
    """접수증 → 홈택스 양도세 신고서들(저장 순서) → 지방세 신고서 순으로 병합.

    파일명: [접수증&신고서]{이름}.pdf (이름은 include_name일 때만). 개별 원본은 보존.
    """
    def outputs_of(key: str) -> list[str]:
        for r in results:
            if r.key == key:
                return r.outputs or []
        return []

    ht = outputs_of("hometax_docs")    # [접수증].., [신고서]..
    wt = outputs_of("wetax_docs")      # [신고서]..지방세
    receipt = [f for f in ht if f.startswith("[접수증]")]
    ht_reports = [f for f in ht if f.startswith("[신고서]")]   # 저장 순서 유지
    wt_reports = [f for f in wt if f.startswith("[신고서]")]   # 지방세 신고서
    ordered = receipt + ht_reports + wt_reports
    if len(ordered) < 2:
        log(f"[i] 병합 대상 부족({len(ordered)}개) — 병합 생략")
        return
    out_dir = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")
    src = [str(out_dir / f) for f in ordered]
    out_name = pdf_save.doc_name("접수증&신고서", [], inp.include_name, inp.name_label)
    log(f"[i] 병합 순서: {' + '.join(ordered)} → {out_name}")
    pdf_save.merge_pdfs(src, out_dir / out_name, log)


def ordered_selected(selected_keys: list[str]):
    """선택된 key를 기본 순서(ALL_PHASES)대로 정렬해 phase 모듈 리스트 반환."""
    sel = set(selected_keys)
    return [p for p in ALL_PHASES if p.KEY in sel]


async def wait_logins(site_pages: dict, emit: Emit,
                      stop_check: Callable[[], bool] | None = None,
                      timeout: int = 600) -> bool:
    """필요한 사이트가 '전부' 로그인될 때까지 대기(2초 polling, ' 로그아웃' 텍스트 감지).

    하나라도 로그인 전이면 phase를 시작하지 않는다(위택스 로그인 중에 홈택스 phase로
    넘어가버리는 문제 방지). 모두 완료 시 True, 중단/타임아웃 시 False.
    """
    def log(m):
        emit("log", text=m)

    pending = dict(site_pages)  # 사이트명 -> Page
    if not pending:
        return True
    emit("status", text="로그인 대기 중…")
    log(f"[i] 로그인 대기 — {', '.join(pending)} 에 각각 로그인하세요. (최대 {timeout // 60}분, 자동 감지)")
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while pending and loop.time() < deadline:
        if stop_check and stop_check():
            log("[i] 로그인 대기 중단됨.")
            return False
        for site, page in list(pending.items()):
            try:
                body = await page.locator("body").inner_text(timeout=2500)
            except Exception:
                body = ""
            if "로그아웃" in body:
                del pending[site]
                log(f"[v] {site} 로그인 확인")
        if not pending:
            log("[v] 모든 사이트 로그인 완료 — 자동 진행 시작")
            emit("status", text="실행 중…")
            return True
        await asyncio.sleep(2)
    log(f"[!] 로그인 미완료: {', '.join(pending)} — 시작하지 않습니다.")
    return False


async def run_pipeline(selected_keys: list[str], inp: Inputs, emit: Emit,
                       stop_check: Callable[[], bool] | None = None) -> list[PhaseResult]:
    def log(msg: str):
        emit("log", text=msg)

    phases = ordered_selected(selected_keys)
    if not phases:
        log("[!] 실행할 phase가 없습니다.")
        return []

    # PDF 저장 모드면 launch 전에 기본 프린터를 'Microsoft Print to PDF'로 박음
    if inp.output_mode == "pdf":
        B.ensure_pdf_sticky_settings()
    if inp.output_dir:
        Path(inp.output_dir).mkdir(parents=True, exist_ok=True)

    results: list[PhaseResult] = []
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        dialog_msgs: list = []
        await B.setup_context(ctx, dialog_msgs)

        # 선택한 phase가 쓰는 사이트(홈택스/위택스)만 홈페이지를 연다.
        sites_needed: list[str] = []
        for mod in phases:
            s = getattr(mod, "SITE", None)
            if s and s not in sites_needed:
                sites_needed.append(s)
        # 여는 순서: 홈택스 먼저 → 위택스 나중(새 탭이 맨 앞). 위택스부터 로그인하도록 자연 유도.
        # (phase 실행 순서와 무관 — 위택스 신고가 먼저 실행되는 건 그대로.)
        OPEN_ORDER = {"홈택스": 0, "위택스": 1}
        sites_needed.sort(key=lambda s: OPEN_ORDER.get(s, 99))
        site_pages = await B.open_homepages(ctx, sites_needed, log=log)
        log(f"[i] Chromium 실행됨 ({', '.join(sites_needed)}).")

        # 필요한 사이트가 전부 로그인될 때까지 대기 후 phase 시작.
        logins_ok = await wait_logins(site_pages, emit, stop_check)

        # 병합은 신고서류 출력(④홈택스 접수증·신고서, ⑤위택스 신고서)만 필요 → 마지막 신고서류
        # phase 직후에 수행(납부서 출력 ⑥⑦ 대기/중단과 무관하게 병합이 끝나 있도록).
        docs_keys = [p.KEY for p in phases if p.KEY in ("hometax_docs", "wetax_docs")]
        last_docs_key = docs_keys[-1] if docs_keys else None
        merged = False

        for mod in (phases if logins_ok else []):
            if stop_check and stop_check():
                log("[i] 중단됨.")
                break
            emit("phase", key=mod.KEY, status="run")
            log(f"[i] ===== {mod.LABEL} 시작 =====")
            try:
                res = await mod.run(ctx, inp, emit, stop_check=stop_check)
            except Exception as e:  # noqa: BLE001
                res = PhaseResult(mod.KEY, mod.LABEL, ok=False, reason=f"예외: {e}")
                log(f"[!] {mod.LABEL} 예외: {e}")
            results.append(res)
            emit("phase", key=mod.KEY, status="ok" if res.ok else "fail")
            tail = (f" / 접수 {res.receipt_no}" if res.receipt_no else "") + \
                   (f" / {res.reason}" if res.reason else "")
            log(f"[v] {mod.LABEL}: {'성공' if res.ok else '실패'}{tail}")

            # 마지막 신고서류 phase 직후 병합(납부서 phase 전에). 순서: 접수증→홈택스 신고서들→지방세 신고서.
            if not merged and mod.KEY == last_docs_key and inp.merge_docs \
                    and inp.output_mode == "pdf":
                _merge_documents(results, inp, log)
                merged = True

        # 모든 단계 종료 후에도 브라우저를 닫지 않고 유지 — 사용자가 화면을 보고
        # 로그인/확인할 수 있게. 창을 닫거나 '중단'을 누르면 종료.
        log("[i] 단계 종료. 브라우저 창을 닫거나 '중단'을 누르면 정리됩니다.")
        while not (stop_check and stop_check()):
            if not ctx.pages:
                break
            await asyncio.sleep(0.5)

    emit("done", results=results)
    return results
