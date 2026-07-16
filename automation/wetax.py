"""위택스 지방소득세 양도소득분 회계파일신고 — 내비게이션 + 단계 (라이브 검증됨).

검증된 흐름:
  로그인(수동) → (직접 URL B070301M10.do로 이동) → 키보드보안 팝업 닫기
  → .Y13/.Y11 파일 주입(set_input_files) → [다음] → 서식검증 완료
  → [제출] → '정상적으로 완료'.

홈택스와 달리 위택스는 실제 URL(.do)을 써서 직접 URL 이동이 가장 견고하다.
파일은 홈택스(.01)와 다른 별도 파일: 양도소득 예정신고 .Y13 / 확정신고 .Y11.
"""
from __future__ import annotations

import asyncio

from . import pdf_save

WETAX_FILING_URL = "https://www.wetax.go.kr/etr/lit/b0703/B070301M10.do"
WETAX_INQUIRY_URL = "https://www.wetax.go.kr/etr/lit/b0703/B070302M01.do"


async def _body(page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


async def close_popups(page, log=print) -> None:
    """키보드보안 등 안내 팝업 닫기 (best-effort)."""
    for txt in ["오늘하루 그만보기", "오늘 하루 그만보기", "닫기"]:
        try:
            loc = page.get_by_text(txt, exact=False)
            for i in range(await loc.count()):
                el = loc.nth(i)
                if await el.is_visible():
                    await el.click(timeout=2000)
                    await page.wait_for_timeout(400)
        except Exception:
            pass


async def navigate_to_filing(page, log=print) -> bool:
    """양도소득분 회계파일신고 화면으로 이동(직접 URL 우선, 메뉴 폴백)."""
    try:
        await page.goto(WETAX_FILING_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
    except Exception as e:
        log(f"[!] (위택스) goto 실패: {str(e)[:60]}")
    b = await _body(page)
    if "회계파일신고" not in b and "변환파일선택" not in b:
        # 폴백: 메뉴 클릭
        log("[i] (위택스) 직접 URL 미확인 → 메뉴(지방소득세) 폴백")
        try:
            await page.get_by_text("지방소득세", exact=True).first.click(timeout=8000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass
        b = await _body(page)
    if "회계파일신고" in b or "변환파일선택" in b:
        await close_popups(page, log)
        log("[v] (위택스) 양도소득분 회계파일신고 화면 도달")
        return True
    log("[!] (위택스) 회계파일신고 화면 도달 실패")
    return False


async def inject_file(page, file_path: str, log=print) -> bool:
    """숨은 input[type=file]에 파일 직접 주입 (홈택스와 동일)."""
    for fi, frame in enumerate(page.frames):
        try:
            inp = frame.locator("input[type=file]")
            if await inp.count() > 0:
                await inp.first.set_input_files(file_path, timeout=8000)
                log(f"[v] (위택스) 파일 주입: {file_path}")
                return True
        except Exception:
            continue
    log("[!] (위택스) input[type=file]를 못 찾음")
    return False


async def _confirm_modals(page, log=print, rounds: int = 3) -> None:
    """보이는 모달의 긍정 버튼(확인/예/제출) 클릭 (best-effort).

    프레임당 JS 한 번으로 탐색+클릭(요소별 await 왕복 제거 — 검증완료→제출 사이
    수 초 걸리던 텀의 주범).
    """
    for _ in range(rounds):
        clicked = False
        for frame in page.frames:
            try:
                clicked = await frame.evaluate("""() => {
                    const vis = el => { const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0; };
                    for (const win of document.querySelectorAll(
                            '.w2window, .modal, [role=dialog], .popup, .layer')) {
                        if (!vis(win)) continue;
                        for (const el of win.querySelectorAll(
                                'a, button, input[type=button], input[type=submit]')) {
                            if (!vis(el)) continue;
                            const t = ((el.innerText || el.value || '') + '').trim();
                            if (t === '확인' || t === '예' || t === '제출') {
                                el.click(); return true;
                            }
                        }
                    }
                    return false;
                }""")
            except Exception:
                continue
            if clicked:
                await page.wait_for_timeout(400)
                break
        if not clicked:
            break


async def next_and_verify(page, log=print, timeout: int = 90) -> bool:
    """[다음](버튼 텍스트 '다음 →') 클릭 → 서식검증 완료 대기."""
    clicked = False
    try:
        loc = page.get_by_text("다음", exact=False).last
        if await loc.count() and await loc.is_visible():
            await loc.click(timeout=6000)
            clicked = True
    except Exception:
        pass
    if not clicked:
        try:
            await page.get_by_role("button", name="다음", exact=False).first.click(timeout=6000)
        except Exception as e:
            log(f"[!] (위택스) '다음' 클릭 실패: {str(e)[:60]}")
            return False
    await page.wait_for_timeout(800)
    await _confirm_modals(page, log)
    # 0.5초 간격 폴링 — 2초 간격은 완료 후 헛대기가 김
    for i in range(timeout * 2):
        if "검증이 완료" in await _body(page):
            log(f"[v] (위택스) 서식검증 완료 ({i // 2}s)")
            return True
        await asyncio.sleep(0.5)
    log("[!] (위택스) 서식검증 완료 미확인")
    return False


async def submit_filing(page, log=print, timeout: int = 40) -> bool:
    """[제출] 클릭 → (확인모달) → '정상적으로 완료' 대기. ⚠ 실제·비가역."""
    clicked = False
    try:
        await page.get_by_role("button", name="제출", exact=True).first.click(timeout=6000)
        clicked = True
    except Exception:
        try:
            await page.get_by_text("제출", exact=True).last.click(timeout=6000)
            clicked = True
        except Exception as e:
            log(f"[!] (위택스) '제출' 클릭 실패: {str(e)[:60]}")
            return False
    await page.wait_for_timeout(600)
    await _confirm_modals(page, log)
    for i in range(timeout * 2):
        if "정상적으로 완료" in await _body(page):
            log(f"[v] (위택스) 제출 완료 ({i // 2}s)")
            return True
        await asyncio.sleep(0.5)
    log("[!] (위택스) '정상적으로 완료' 표시 미확인 — 화면 확인 필요")
    return clicked


# ─────────────────── 위택스 서류 PDF저장/출력 (Phase 5) ───────────────────

async def open_inquiry(page, log=print) -> bool:
    """양도소득분 신고내역(B070302M01) 직접 URL 이동."""
    try:
        await page.goto(WETAX_INQUIRY_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
    except Exception as e:
        log(f"[!] (위택스) 신고내역 goto 실패: {str(e)[:60]}")
        return False
    await close_popups(page, log)
    log("[v] (위택스) 양도소득분 신고내역 화면")
    return True


async def _expand_taxpayer(page, name: str, log=print) -> bool:
    """신고내역 목록에서 name 행의 '출력물 보기' 클릭 → 신고서/납부서 링크 펼침."""
    clicked = await page.evaluate("""(name) => {
        const anchors=[...document.querySelectorAll('a')].filter(a=>
            (a.id||'').startsWith('ui-id')||(a.title||'').includes('출력')||(a.textContent||'').includes('출력물'));
        for(const a of anchors){
            const row=a.closest('tr')||a.closest('li')||(a.parentElement&&a.parentElement.parentElement);
            if(row && (row.innerText||'').includes(name)){ a.click(); return true; }
        }
        return false;
    }""", name)
    await page.wait_for_timeout(2000)
    if not clicked:
        log(f"[!] (위택스) '{name}' 출력물 보기 못 찾음")
    return clicked


async def _click_text_js(scope, text: str) -> bool:
    return await scope.evaluate("""(text) => {
        for(const e of document.querySelectorAll('input,button,a,img')){
            const t=(e.value||e.title||e.getAttribute('alt')||e.innerText||'').trim();
            if(t===text){ e.click(); return true; }
        }
        return false;
    }""", text)


async def _oz_print(oz, target, log=print, save: bool = True) -> bool:
    """OZ 뷰어: [인쇄] → 인쇄옵션 [확인] → (save면) Microsoft Print to PDF 저장.

    고정 대기 대신 버튼 등장을 0.3초 간격 폴링 — 뷰어가 빨리 뜨면 그만큼 빨리 진행.
    """
    clicked = False
    for _ in range(17):   # 최대 ~5초
        if await _click_text_js(oz, "인쇄"):
            clicked = True
            break
        await oz.wait_for_timeout(300)
    if not clicked:
        log("  [!] (위택스) OZ 인쇄 버튼 못 찾음")
        return False
    for _ in range(17):   # 인쇄옵션 창 [확인] 등장 폴링 (최대 ~5초)
        if await _click_text_js(oz, "확인"):
            break
        await oz.wait_for_timeout(300)
    if not save:
        await oz.wait_for_timeout(2500)
        return True
    from pathlib import Path as _P
    _P(target).parent.mkdir(parents=True, exist_ok=True)
    target = pdf_save.prepare_target(target, log)   # 사전 삭제 → 덮어쓰기창·OneDrive 잠금 회피
    ok, err = await asyncio.to_thread(pdf_save.fill_and_save, target, 25.0, log)
    if not ok:
        log(f"  [!] (위택스) PDF 저장 실패: {err}")
    return ok


async def _fetch_due(page, name: str, log=print) -> str:
    """'출력물 보기' 앵커의 개별 데이터 행(closest tr)에서 납부기한 추출.

    (전체 tr 순회는 테이블 래퍼 tr이 먼저 잡혀 다른 행 날짜를 가져오는 버그가 있어 앵커 기준으로.)
    개별 행은 [신고일자, 납부기한]뿐이라 마지막 날짜 = 납부기한.
    """
    due_raw = await page.evaluate("""(name) => {
        const anchors=[...document.querySelectorAll('a')].filter(a=>
            (a.id||'').startsWith('ui-id')||(a.title||'').includes('출력')||(a.textContent||'').includes('출력물'));
        for(const a of anchors){
            const row=a.closest('tr');
            if(row && (row.innerText||'').includes(name)){
                const ds=(row.innerText.match(/20\\d\\d-\\d\\d-\\d\\d/g))||[];
                if(ds.length) return ds[ds.length-1];
            }
        }
        return '';
    }""", name)
    log(f"[i] (위택스) {name} 납부기한 fetch: {due_raw}")
    return pdf_save.fmt_due(due_raw)


async def _print_reports(ctx, page, pdf_dir, name: str, kinds: list, output_mode: str,
                         include_name: bool, log=print) -> dict:
    """신고내역 → name 출력물 보기 → kinds(신고서/납부서) OZ PDF저장/출력. {saved, failed}.

    파일명: [신고서]{이름}_지방세 / [납부서]{이름}_지방세_{납부기한}.
    """
    from pathlib import Path
    pdf_dir = Path(pdf_dir)
    save = (output_mode == "pdf")
    result = {"saved": [], "failed": []}

    if not await open_inquiry(page, log):
        return result
    due = await _fetch_due(page, name, log) if "납부서" in kinds else ""
    if not await _expand_taxpayer(page, name, log):
        result["failed"].append("출력물보기")
        return result

    specs = []
    if "신고서" in kinds:
        specs.append(("신고서", False, pdf_save.doc_name("신고서", ["지방세"], include_name, name)))
    if "납부서" in kinds:
        specs.append(("납부서", True, pdf_save.doc_name("납부서", ["지방세", due], include_name, name)))

    for kind, has_y, fname in specs:
        exists = await page.evaluate("""(hasY) => {
            for(const a of document.querySelectorAll('a')){
                const oc=a.getAttribute('onclick')||'';
                if(oc.includes('openReport')){ if(oc.includes("'Y'")===hasY) return true; }
            }
            return false;
        }""", has_y)
        if not exists:
            log(f"[i] (위택스) {kind} 없음 — 건너뜀")
            continue
        try:
            async with ctx.expect_page(timeout=10000) as info:
                await page.evaluate("""(hasY) => {
                    for(const a of document.querySelectorAll('a')){
                        const oc=a.getAttribute('onclick')||'';
                        if(oc.includes('openReport')){ if(oc.includes("'Y'")===hasY){ a.click(); return; } }
                    }
                }""", has_y)
            oz = await info.value
            await oz.wait_for_timeout(500)   # _oz_print가 인쇄 버튼 등장을 폴링
            tgt = pdf_dir / fname
            if await _oz_print(oz, tgt, log, save=save):
                result["saved"].append(fname)
                log(f"[v] (위택스) {kind} {'저장' if save else '출력'}: {fname}")
            else:
                result["failed"].append(kind)
            try:
                await oz.close()
            except Exception:
                pass
        except Exception as e:
            log(f"[!] (위택스) {kind} 실패: {str(e)[:60]}")
            result["failed"].append(kind)
        await page.wait_for_timeout(1500)
    return result


async def print_singo(ctx, page, pdf_dir, name: str, output_mode: str = "pdf",
                      include_name: bool = False, log=print) -> dict:
    """위택스 지방세 신고서만 출력(가상계좌 무관)."""
    return await _print_reports(ctx, page, pdf_dir, name, ["신고서"], output_mode, include_name, log)


async def print_napbu(ctx, page, pdf_dir, name: str, output_mode: str = "pdf",
                      include_name: bool = False, log=print) -> dict:
    """위택스 지방세 납부서(가상계좌)만 출력. 가상계좌 미생성/차손이면 링크 없어 건너뜀."""
    return await _print_reports(ctx, page, pdf_dir, name, ["납부서"], output_mode, include_name, log)
