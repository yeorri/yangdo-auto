"""파이프라인 — 브라우저 세션 유지 + 선택한 phase들을 순서대로 실행.

브라우저는 BrowserSession으로 GUI 수명 동안 유지된다: 첫 실행에서 launch+로그인하고,
실행이 끝나도 닫지 않아 다음 건을 재로그인 없이 이어서 처리할 수 있다.
phase는 서로 독립이라 한쪽 실패가 다음 phase를 자동으로 막지는 않는다(계속 진행, 결과만 기록).
(ingunbi_auto에서 검증된 세션 패턴)
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

SITE_SUB = {"홈택스": "hometax.go.kr", "위택스": "wetax.go.kr"}
# 여는 순서: 홈택스 먼저 → 위택스 나중(새 탭이 맨 앞 = 위택스부터 로그인 유도)
OPEN_ORDER = {"홈택스": 0, "위택스": 1}


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
    if not pdf_save.merge_pdfs(src, out_dir / out_name, log):
        return
    # 병합에 성공했을 때만 개별 원본 삭제(옵션). 납부서는 대상 아님 — 병합에 안 들어감.
    if not inp.delete_merged_sources:
        return
    removed = 0
    for p in src:
        try:
            Path(p).unlink()
            removed += 1
        except Exception as e:  # noqa: BLE001
            log(f"[!] 원본 삭제 실패: {Path(p).name} ({str(e)[:40]})")
    log(f"[i] 병합본만 남김 — 개별 접수증·신고서 {removed}개 삭제")


def ordered_selected(selected_keys: list[str]):
    """선택된 key를 기본 순서(ALL_PHASES)대로 정렬해 phase 모듈 리스트 반환."""
    sel = set(selected_keys)
    return [p for p in ALL_PHASES if p.KEY in sel]


async def wait_logins(site_pages: dict, emit: Emit,
                      stop_check: Callable[[], bool] | None = None,
                      timeout: int = 600) -> bool:
    """필요한 사이트가 '전부' 로그인될 때까지 대기(2초 polling, '로그아웃' 텍스트 감지).

    이미 로그인된 사이트(세션 유지)는 첫 폴링에서 즉시 통과한다.
    하나라도 로그인 전이면 phase를 시작하지 않는다. 모두 완료 시 True.
    """
    def log(m):
        emit("log", text=m)

    pending = dict(site_pages)  # 사이트명 -> Page
    if not pending:
        return True
    emit("status", text="로그인 확인 중…")
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    notified = False
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
        if not notified:
            log(f"[i] 로그인 대기 — {', '.join(pending)} 에 각각 로그인하세요. "
                f"(최대 {timeout // 60}분, 자동 감지)")
            notified = True
        await asyncio.sleep(2)
    log(f"[!] 로그인 미완료: {', '.join(pending)} — 시작하지 않습니다.")
    return False


class BrowserSession:
    """GUI 수명 동안 유지되는 브라우저 세션.

    - ensure(): (필요 시) launch + 필요한 사이트 탭 확보 + 로그인 대기
    - 실행 사이에 브라우저를 닫지 않아 재로그인이 필요 없다
    - 서류 처리 모드(pdf/print)가 바뀌면 프린터 sticky 재설정을 위해 재시작
    """

    def __init__(self):
        self.pw = None
        self.ctx = None
        self.dialog_msgs: list = []
        self.output_mode: str | None = None

    def _alive(self) -> bool:
        if self.ctx is None:
            return False
        try:
            return bool(self.ctx.pages)  # 사용자가 창을 닫았으면 False/예외
        except Exception:
            return False

    async def ensure(self, sites_needed: list[str], output_mode: str, emit: Emit,
                     stop_check: Callable[[], bool] | None = None) -> dict | None:
        """브라우저·탭·로그인 준비. 성공 시 {사이트명: Page}, 실패/중단 시 None."""
        def log(m):
            emit("log", text=m)

        if self._alive() and self.output_mode != output_mode:
            log("[i] 서류 처리 모드 변경 감지 — 프린터 설정을 위해 브라우저를 재시작합니다.")
            await self.close()

        if not self._alive():
            # 브라우저 시작 구간은 취소(즉시 중단)로부터 보호 — 도중에 끊기면
            # 브라우저 프로세스가 고아로 남아 프로필 잠금이 걸릴 수 있다.
            await asyncio.shield(self._startup(output_mode, log))

        # 필요한 사이트 탭 확보 — 이미 열려 있으면 재사용(로그인 유지)
        pages: dict = {}
        to_open: list[str] = []
        for site in sorted(sites_needed, key=lambda s: OPEN_ORDER.get(s, 99)):
            p = B.find_page(self.ctx, SITE_SUB.get(site, site))
            if p is None:
                to_open.append(site)
            else:
                pages[site] = p
        if to_open:
            opened = await B.open_homepages(self.ctx, to_open, log=log)
            pages.update(opened)

        if not await wait_logins(pages, emit, stop_check):
            return None
        return pages

    async def _startup(self, output_mode: str, log) -> None:
        """브라우저 실행 — 잔재 정리 + sticky 프린터 설정 + launch."""
        await self.close()
        # 인쇄 대상(sticky)은 launch 전에만 적용 가능 — 모드에 맞게 설정
        if output_mode == "pdf":
            B.ensure_pdf_sticky_settings()
        else:
            prn = B.default_printer_name()
            if prn:
                B.ensure_sticky_printer(prn)
                log(f"[i] 인쇄 대상: 기본 프린터 '{prn}'")
            else:
                log("[!] 기본 프린터 조회 실패 — 이전 인쇄 대상이 그대로 사용될 수 있음")
        self.pw = await async_playwright().start()
        self.ctx = await B.launch(self.pw)
        await B.setup_context(self.ctx, self.dialog_msgs)
        self.output_mode = output_mode
        log("[i] Chromium 실행됨.")

    async def close(self):
        try:
            if self.ctx:
                await self.ctx.close()
        except Exception:
            pass
        try:
            if self.pw:
                await self.pw.stop()
        except Exception:
            pass
        self.ctx = None
        self.pw = None
        self.output_mode = None


async def run_phases(session: BrowserSession, selected_keys: list[str], inp: Inputs,
                     emit: Emit, stop_check: Callable[[], bool] | None = None
                     ) -> list[PhaseResult]:
    """세션 브라우저에서 선택 phase들을 실행. 끝나도 브라우저는 유지."""
    def log(msg: str):
        emit("log", text=msg)

    phases = ordered_selected(selected_keys)
    if not phases:
        log("[!] 실행할 phase가 없습니다.")
        emit("done", results=[])
        return []

    if inp.output_dir:
        Path(inp.output_dir).mkdir(parents=True, exist_ok=True)

    sites_needed: list[str] = []
    for mod in phases:
        s = getattr(mod, "SITE", None)
        if s and s not in sites_needed:
            sites_needed.append(s)

    results: list[PhaseResult] = []
    pages = await session.ensure(sites_needed, inp.output_mode, emit, stop_check)
    if pages is None:
        emit("done", results=results)
        return results

    # 병합은 신고서류 출력(④홈택스 접수증·신고서, ⑤위택스 신고서)만 필요 → 마지막 신고서류
    # phase 직후에 수행(납부서 출력 ⑥⑦ 대기/중단과 무관하게 병합이 끝나 있도록).
    docs_keys = [p.KEY for p in phases if p.KEY in ("hometax_docs", "wetax_docs")]
    last_docs_key = docs_keys[-1] if docs_keys else None
    merged = False

    ctx = session.ctx
    for mod in phases:
        if stop_check and stop_check():
            log("[i] 중단됨.")
            break
        emit("phase", key=mod.KEY, status="run")
        log(f"[i] ===== {mod.LABEL} 시작 =====")
        try:
            res = await mod.run(ctx, inp, emit, stop_check=stop_check)
        except asyncio.CancelledError:
            raise   # 즉시 중단 — 취소는 위로 전파 (브라우저는 세션이 유지)
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

    log("[i] 전체 단계 종료 — 브라우저는 유지됩니다. 다음 건을 입력하고 다시 시작하세요.")
    emit("done", results=results)
    return results


def _person_emit(emit: Emit, idx: int) -> Emit:
    """사람 인덱스를 붙여 전달하는 emit 래퍼. run_phases가 내는 'done'은 삼킨다
    (배치 전체가 끝났을 때 한 번만 done을 보내야 하므로)."""
    def e(kind, **kw):
        if kind == "done":
            return
        emit(kind, person=idx, **kw)
    return e


async def run_batch(session: BrowserSession, jobs: list[tuple], emit: Emit,
                    stop_check: Callable[[], bool] | None = None) -> list:
    """여러 신고인을 순차 실행. 한 명이 실패해도 다음 사람은 계속 진행.

    jobs: [(Inputs, [phase_key, ...]), ...] — 신고인마다 실행할 단계가 다를 수 있다
          (완료된 단계는 GUI가 빼고 넘겨 실패분만 재시도되게 함).
    ⑦ 위택스 납부서(가상계좌 대기)는 **전원 나머지 단계를 끝낸 뒤 마지막에 몰아서** 한다.
    앞사람 가상계좌가 뒷사람 처리 중에 이미 생성돼 대기 시간이 거의 사라진다.
    """
    def log(m: str):
        emit("log", text=m)

    if not jobs:
        log("[!] 실행할 신고인이 없습니다.")
        emit("done", results=[])
        return []

    last_key = "wetax_napbu"
    defer_napbu = len(jobs) > 1 and any(last_key in keys for _inp, keys in jobs)

    out: list = [[] for _ in jobs]
    for idx, (inp, keys) in enumerate(jobs):
        if stop_check and stop_check():
            log("[i] 중단됨.")
            break
        main_keys = [k for k in keys if k != last_key] if defer_napbu else list(keys)
        who = inp.name_label or f"{idx + 1}번"
        if not main_keys:
            continue
        log(f"[i] ########## {who} ({idx + 1}/{len(jobs)}) ##########")
        emit("person", index=idx, status="run")
        try:
            res = await run_phases(session, main_keys, inp, _person_emit(emit, idx), stop_check)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log(f"[!] {who} 예외: {e}")
            res = []
        out[idx] = res
        ok = bool(res) and all(r.ok for r in res)
        emit("person", index=idx, status="ok" if ok else "fail")

    # 미뤄둔 위택스 납부서 — 전원 몰아서
    if defer_napbu and not (stop_check and stop_check()):
        log("[i] ########## 위택스 납부서 (전원) ##########")
        for idx, (inp, keys) in enumerate(jobs):
            if stop_check and stop_check():
                log("[i] 중단됨.")
                break
            if last_key not in keys:
                continue
            who = inp.name_label or f"{idx + 1}번"
            log(f"[i] ----- {who} 위택스 납부서 -----")
            try:
                res = await run_phases(session, [last_key], inp, _person_emit(emit, idx), stop_check)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log(f"[!] {who} 위택스 납부서 예외: {e}")
                res = []
            out[idx].extend(res)

    log("[i] 전체 신고인 종료 — 브라우저는 유지됩니다.")
    emit("done", results=out)
    return out


async def run_pipeline(selected_keys: list[str], inp: Inputs, emit: Emit,
                       stop_check: Callable[[], bool] | None = None) -> list[PhaseResult]:
    """1회성 실행(브라우저 종료까지) — 세션을 쓰지 않는 호출용 호환 래퍼."""
    session = BrowserSession()
    try:
        return await run_phases(session, selected_keys, inp, emit, stop_check)
    finally:
        await session.close()
