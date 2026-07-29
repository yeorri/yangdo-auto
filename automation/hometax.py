"""홈택스 양도소득세 파일변환신고 — 메뉴 내비게이션 + 화면 셀렉터.

검증된 경로(라이브 확인):
  (로그인) → 신고/납부[호버] → 양도소득세[클릭] → 파일변환신고 카드[클릭] → 전자파일변환 화면

화면 공식 변환순서:
  [파일선택] → [파일검증하기] → (암호화 시 비밀번호 입력) → 검증결과 확인
  → [제출하러 가기]/[전자파일제출하기] → '일괄접수증' 확인 → [신고내역 조회(접수증·납부서)]

⚠ WebSquare 숫자 id는 매번 바뀌므로(동적) 텍스트 기반 셀렉터를 쓴다.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from . import pdf_save
from .browser import HOMETAX_URL

# 접수번호 패턴 (예: 212-2026-2-505316384006)
RECEIPT_NO_RE = re.compile(r"\d{3}-\d{4}-\d-\d{3,}")
# clipreport 리포트 데이터 로딩 완료 감지 JS
_CLIPREPORT_LOADED = """() => {
    const t = document.querySelector('[id^="re_totalCountNumber"]');
    const p = document.querySelector('[id^="re_progressImg"]');
    const m = t && (t.value||'').match(/\\/\\s*(\\d+)/);
    return (m && parseInt(m[1])>0) || (p && getComputedStyle(p).display==='none');
}"""


async def _click_first_visible(locator, timeout: int = 4000) -> bool:
    """locator 중 보이는 첫 요소를 클릭. 성공하면 True."""
    n = await locator.count()
    for i in range(n):
        try:
            el = locator.nth(i)
            if await el.is_visible():
                await el.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


async def _open_and_click_submenu(page, parent_text: str, child_text: str,
                                  log=print, attempts: int = 5) -> bool:
    """메가메뉴: parent를 호버(필요시 클릭)해 드롭다운을 열고 child를 클릭. 재시도 포함.

    홈택스 메뉴는 호버로 열릴 때도, 클릭해야 열릴 때도 있고 클릭 시 페이지가 이동하며
    드롭다운이 닫히는 레이스가 있어 불안정 → child가 보일 때까지 재시도.
    """
    parent = page.get_by_text(parent_text, exact=True).first
    child = page.get_by_text(child_text, exact=True)
    # 페이지(WebSquare 메뉴)가 렌더될 때까지 parent가 보이길 먼저 기다린다(goto 직후 레이스 방지).
    try:
        await parent.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(600)
    except Exception:
        log(f"  [!] (홈택스) '{parent_text}' 메뉴가 안 보임(렌더 지연?)")
    for a in range(attempts):
        try:
            await parent.hover(timeout=8000)
        except Exception:
            pass
        await page.wait_for_timeout(800)
        if await _click_first_visible(child):
            return True
        # 호버로 안 열리면 parent 클릭으로 펼침 시도
        try:
            await parent.click(timeout=5000)
            await page.wait_for_timeout(1200)
        except Exception:
            pass
        if await _click_first_visible(child):
            return True
        log(f"  ... (홈택스) '{child_text}' 진입 재시도 {a + 1}/{attempts}")
        await page.wait_for_timeout(1000)
    return False


async def reset_to_home(page, log=print) -> None:
    """phase 시작용 하드 리셋 — 홈택스 홈으로 goto.

    goto는 DOM·모달·오버레이 잔재를 통째로 날려, 앞 phase의 끝 상태와 무관하게
    깨끗한 상태에서 시작하게 한다(배치/독립 실행 동일). 로그인 세션은 유지됨.
    """
    try:
        await page.goto(HOMETAX_URL, wait_until="domcontentloaded", timeout=30000)
        # 뒤따르는 메뉴 진입(_open_and_click_submenu)이 parent 가시성 대기(15s)를
        # 따로 하므로 여기선 짧은 안정화만. (속도 최적화 — vat 패턴)
        await page.wait_for_timeout(600)
    except Exception as e:
        log(f"[!] (홈택스) 홈 리셋 실패: {str(e)[:60]}")


async def navigate_to_file_convert(page, log=print) -> bool:
    """어떤 화면에 있든: 홈으로 리셋 → 신고/납부→양도소득세→파일변환신고(재시도 견고화)."""
    await reset_to_home(page, log)
    log("[i] (홈택스) 신고/납부 → 양도소득세 → 파일변환신고")
    if not await _open_and_click_submenu(page, "신고/납부", "양도소득세", log):
        log("[!] (홈택스) 양도소득세 메뉴 진입 실패")
        return False
    await page.wait_for_timeout(1500)
    # 양도세 신고 화면의 '파일변환신고' 카드 클릭 (재시도)
    for a in range(3):
        try:
            await page.get_by_text("파일변환신고", exact=True).first.click(timeout=8000)
            await page.wait_for_timeout(2500)
            log("[v] (홈택스) 전자파일변환 화면 도달")
            return True
        except Exception as e:
            log(f"  ... (홈택스) 파일변환신고 클릭 재시도 {a + 1}/3: {str(e)[:50]}")
            await page.wait_for_timeout(1000)
    log("[!] (홈택스) 파일변환신고 카드 클릭 실패")
    return False


# 파일변환신고 화면의 버튼/링크 텍스트 (id가 아니라 텍스트로 잡음)
BTN_FILE_SELECT = "파일선택"
BTN_VERIFY = "파일검증하기"
BTN_GO_SUBMIT = "제출하러 가기"
BTN_SUBMIT = "전자파일 제출하기"     # 공백 포함(라이브 확인)
LINK_RECEIPT = "신고내역 조회(접수증·납부서)"
LINK_ATTACH = "신고 부속·증빙서류 제출"

HOMETAX_MAIN_URL = HOMETAX_URL


async def inject_convert_file(page, file_path: str, log=print) -> bool:
    """KUpload 대응: 숨은 input[type=file]에 파일을 직접 주입(라이브 검증됨).

    filechooser/OS 다이얼로그 없이 set_input_files로 바로 꽂힌다.
    """
    for fi, frame in enumerate(page.frames):
        try:
            inp = frame.locator("input[type=file]")
            if await inp.count() > 0:
                await inp.first.set_input_files(file_path, timeout=8000)
                log(f"[v] (홈택스) 파일 주입 성공: {file_path}")
                return True
        except Exception as e:
            log(f"[!] (홈택스) 파일 주입 실패(frame {fi}): {str(e)[:70]}")
    log("[!] (홈택스) input[type=file]를 찾지 못함")
    return False


async def handle_prev_record_modal(page, log=print) -> bool:
    """'이미 검증된 자료가 존재합니다. 다시 하시겠습니까?' 모달 → '확인'.

    종전 신고내역이 있을 때만 뜬다(없으면 안 뜸). 닫기/취소는 누르지 않는다.
    """
    for frame in page.frames:
        try:
            wins = frame.locator(".w2window")
            for i in range(await wins.count()):
                win = wins.nth(i)
                if not await win.is_visible():
                    continue
                btns = win.locator("a, button, input[type=button], input[type=submit]")
                for b in range(await btns.count()):
                    el = btns.nth(b)
                    if not await el.is_visible():
                        continue
                    t = (await el.inner_text()).strip() or (await el.get_attribute("value") or "")
                    if t == "확인" or (("확인" in t or "예" in t) and "닫기" not in t):
                        await el.click()
                        log(f"[i] (홈택스) 종전내역 모달 '{t}' 클릭")
                        await page.wait_for_timeout(1000)
                        return True
        except Exception:
            continue
    return False


async def verify_and_wait(page, log=print, timeout: int = 150) -> str:
    """파일검증하기 클릭 → 종전내역 모달 처리 → '검증 중' 오버레이가 사라질 때까지 대기.

    반환: "완료" | "시간초과". (오류/정상 판정은 호출측에서 화면 파싱.)
    """
    try:
        await page.get_by_text(BTN_VERIFY, exact=True).first.click(timeout=8000)
        await page.wait_for_timeout(1200)
    except Exception as e:
        log(f"[!] (홈택스) 파일검증하기 클릭 실패: {str(e)[:80]}")
        return "시간초과"
    await handle_prev_record_modal(page, log)
    # 검증이 시작될 시간을 준다. ⚠ 이 대기가 없으면 이전 신고인 화면의 잔재('제출하러 가기'
    # 버튼은 검증 전에도 존재)를 보고 0초 만에 '검증 완료'로 오판해, 엉뚱한 화면에서
    # 제출까지 진행되는 사고가 난다(라이브에서 실제 발생).
    await page.wait_for_timeout(2500)

    # '검증 중입니다' 오버레이가 사라지고 결과 영역이 보이면 완료.
    seen_validating = False
    for sec in range(0, timeout, 2):
        try:
            body = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        validating = "검증 중입니다" in body or "검증중입니다" in body
        if validating:
            seen_validating = True
        elif "내용검증" in body:
            # 오버레이 없음 + 검증 결과 영역 존재 = 완료
            # ('제출하러 가기'는 검증 전에도 있으므로 완료 신호로 쓰지 않는다)
            log(f"[v] (홈택스) 검증 완료 ({sec}s)")
            return "완료"
        if sec % 10 == 0:
            log(f"  ... (홈택스) 검증 대기 ({sec}s)")
        await asyncio.sleep(2)
    return "시간초과"


async def _click_modal_confirm(page, must_contain: str, log=print,
                               timeout: float = 4.0) -> bool:
    """텍스트에 must_contain이 든 보이는 WebSquare 모달의 '확인'을 클릭.

    프레임당 JS 한 번으로 탐색+클릭(요소별 await 왕복 제거 — 수 초 → 수십 ms).
    ⚠ 모달은 조금 늦게 뜰 수 있어 등장을 폴링한다. 1회만 확인하면 놓치고, 그 모달이
      화면을 덮은 채 남아 다음 클릭이 전부 실패한다(부속서류 '첨부하기' 타임아웃의 원인).
      모달이 아예 없는 경우도 정상이므로 timeout 후 False를 돌려준다.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        if await _try_click_modal_confirm(page, must_contain):
            log(f"[i] (홈택스) 모달 '확인' ({must_contain})")
            await page.wait_for_timeout(400)
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.3)


async def _try_click_modal_confirm(page, must_contain: str) -> bool:
    """모달 '확인'을 1회 탐색·클릭(폴링은 호출측 담당)."""
    for frame in page.frames:
        try:
            clicked = await frame.evaluate("""(mustContain) => {
                const vis = el => { const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0; };
                for (const win of document.querySelectorAll('.w2window')) {
                    if (!vis(win)) continue;
                    const txt = win.innerText || '';
                    if (mustContain && !txt.includes(mustContain)) continue;
                    for (const el of win.querySelectorAll(
                            'a, button, input[type=button], input[type=submit]')) {
                        if (!vis(el)) continue;
                        const t = ((el.innerText || el.value || '') + '').trim();
                        if (t === '확인') { el.click(); return true; }
                    }
                }
                return false;
            }""", must_contain)
        except Exception:
            continue
        if clicked:
            return True
    return False


async def _wait_receipt_modal(page, log=print, timeout: int = 25) -> bool:
    """접수증 모달이 뜰 때까지 대기. 등장 = 제출 성공 신호.

    닫지 않고 화면에 남겨 둔다 — 다음 phase가 reset_to_home로 정리하고,
    사용자는 접수증 화면으로 제출 성공을 눈으로 확인할 수 있다(phase 시작-리셋 원칙).
    """
    for _ in range(timeout):
        for frame in page.frames:
            try:
                wins = frame.locator(".w2window")
                for i in range(await wins.count()):
                    win = wins.nth(i)
                    if not await win.is_visible():
                        continue
                    txt = await win.inner_text()
                    if "접수증" in txt or "접수내용" in txt or "접수 되었습니다" in txt:
                        log("[v] (홈택스) 접수증 확인 — 제출 완료 (화면 유지)")
                        return True
            except Exception:
                continue
        await page.wait_for_timeout(1000)
    return False


async def check_and_save_warnings(page, out_dir=None, log=print) -> int:
    """검증결과내역의 '오류납세자수(확인납세자수)'를 보고 경고(오류 아님)를 처리.

    화면에 `0(1)`처럼 표시되면 오류 0건 / 경고 1건. 경고는 제출을 막지 않지만 확인이
    필요하므로, 경고내역을 열어 엑셀로 내려받고(out_dir 지정 시) 모달을 닫는다.
    반환: 경고 건수(없으면 0).
    """
    info = await page.evaluate("""() => {
        const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0; };
        for (const a of document.querySelectorAll('a, span, td')) {
            if (!vis(a)) continue;
            const m = ((a.innerText || '') + '').trim().match(/^(\\d+)\\((\\d+)\\)$/);
            if (m) return {text: m[0], err: +m[1], warn: +m[2]};
        }
        return null;
    }""")
    if not info or not info.get("warn"):
        return 0
    n = info["warn"]
    log(f"[i] (홈택스) 내용검증 경고 {n}건 (오류 {info['err']}건) — 경고내역 확인")
    # 1) 오류/경고 링크 클릭 → '내용검증(경고/안내)' 모달
    await page.evaluate("""(txt) => {
        const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0; };
        for (const a of document.querySelectorAll('a, span, td')) {
            if (vis(a) && ((a.innerText || '') + '').trim() === txt) { a.click(); return; }
        }
    }""", info["text"])
    await page.wait_for_timeout(1500)
    # 2) [경고내역] 클릭 → '신고서 오류내역 조회' 상세
    for label in ("경고내역", "오류내역"):
        if await _click_btn_by_text(page, label):
            break
    await page.wait_for_timeout(1500)
    # 3) 엑셀 내려받기 — 어떤 경고였는지 기록으로 남긴다
    if out_dir:
        from pathlib import Path as _P
        d = _P(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        try:
            async with page.expect_download(timeout=20000) as dli:
                await _click_btn_by_text(page, "엑셀 내려받기")
            dl = await dli.value
            tgt = d / f"[경고내역]{_P(dl.suggested_filename).name}"
            await dl.save_as(str(tgt))
            log(f"[i] (홈택스) 경고내역 저장: {tgt.name}")
        except Exception as e:  # noqa: BLE001
            log(f"[i] (홈택스) 경고내역 엑셀 저장 실패(계속): {str(e)[:60]}")
    # 4) 모달 닫기(상세 → 목록 순서로 최대 3번)
    for _ in range(3):
        if not await _click_btn_by_text(page, "닫기"):
            break
        await page.wait_for_timeout(600)
    return n


async def _click_btn_by_text(page, text: str) -> bool:
    """보이는 버튼/링크 중 텍스트가 정확히 일치하는 첫 요소를 JS로 클릭."""
    return await page.evaluate("""(txt) => {
        const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0; };
        for (const el of document.querySelectorAll('a, button, input[type=button], input[type=submit]')) {
            if (!vis(el)) continue;
            const t = ((el.innerText || el.value || '') + '').trim();
            if (t === txt) { el.click(); return true; }
        }
        return false;
    }""", text)


async def submit_filing(page, log=print) -> bool:
    """검증완료 화면 → [제출하러 가기] → [전자파일 제출하기] → 제출확인 → 접수증 등장 확인.

    ⚠ 실제·비가역 제출. 접수증 모달 등장 = 제출 성공(닫지 않고 화면에 남겨 둠).
    """
    try:
        await page.get_by_text(BTN_GO_SUBMIT, exact=True).first.click(timeout=8000)
        await page.wait_for_timeout(2500)
    except Exception as e:
        log(f"[!] (홈택스) '제출하러 가기' 실패: {str(e)[:80]}")
        return False
    # ⚠ 경고(오류 아님)가 있으면 '(경고/안내) 메시지가 있습니다' 알림이 떠 제출 화면으로
    #   넘어가지 않는다. [확인]=경고내역 보기 / [취소]=그대로 제출 → 여기선 [취소].
    #   (경고내역은 앞서 check_and_save_warnings에서 이미 저장해 둔다.)
    try:
        body = await page.locator("body").inner_text(timeout=2500)
    except Exception:
        body = ""
    if "경고" in body and ("확인이 필요한" in body or "메시지가 있습니다" in body):
        if await _click_btn_by_text(page, "취소"):
            log("[i] (홈택스) 경고 안내 — [취소]로 그대로 제출 진행")
            await page.wait_for_timeout(2000)
    try:
        await page.get_by_text(BTN_SUBMIT, exact=True).first.click(timeout=8000)
    except Exception as e:
        log(f"[!] (홈택스) '{BTN_SUBMIT}' 실패: {str(e)[:80]}")
        return False
    await page.wait_for_timeout(1500)
    # 제출 확인 모달('정상 변환된 신고서를 제출합니다') 확인
    await _click_modal_confirm(page, must_contain="제출", log=log)
    # 접수증 모달 등장 = 제출 성공. 닫지 않고 그대로 둔다(다음 phase가 리셋).
    if await _wait_receipt_modal(page, log):
        return True
    # ⚠ 예전엔 여기서도 True를 돌려줬는데, 실제로 제출이 안 된 경우(엉뚱한 화면에서 제출
    # 시도 등)까지 성공으로 보고돼 뒷 단계가 줄줄이 헛돌았다 → 실패로 처리한다.
    log("[!] (홈택스) 접수증 미확인 — 제출 실패로 처리(화면 확인 필요)")
    return False


# ─────────────────── 부속·증빙서류 제출 (Phase 3) ───────────────────

async def _fill_rrn(page, rrn: str, log=print) -> bool:
    """주민번호 입력 — 앞자리(text maxlength 6) + 뒷자리(password maxlength 7)."""
    digits = "".join(c for c in (rrn or "") if c.isdigit())
    if len(digits) != 13:
        log(f"[!] (홈택스) 주민번호 13자리 아님: {len(digits)}")
        return False
    front, back = digits[:6], digits[6:]
    # 모달·입력칸이 늦게 렌더될 수 있어 등장할 때까지 폴링(1회 순회는 놓치는 원인)
    for _ in range(20):        # 최대 ~8초
        for frame in page.frames:
            try:
                f6 = frame.locator("input[maxlength='6']")
                b7 = frame.locator("input[maxlength='7']")
                f6v = [f6.nth(i) for i in range(await f6.count()) if await f6.nth(i).is_visible()]
                b7v = [b7.nth(i) for i in range(await b7.count()) if await b7.nth(i).is_visible()]
                if f6v and b7v:
                    await f6v[0].fill(front)
                    await b7v[0].fill(back)
                    log(f"[i] (홈택스) 주민번호 입력 {front}-*******")
                    return True
            except Exception:
                continue
        await page.wait_for_timeout(400)
    log("[!] (홈택스) 주민번호 입력칸 못 찾음")
    return False


async def navigate_to_attach(page, log=print) -> bool:
    """홈 리셋 → 신고/납부 → 양도소득세 → '신고 부속·증빙서류 제출' 모달 열기."""
    await reset_to_home(page, log)
    if not await _open_and_click_submenu(page, "신고/납부", "양도소득세", log):
        log("[!] (홈택스) 양도소득세 진입 실패")
        return False
    await page.wait_for_timeout(1500)
    for label in ["신고 부속·증빙서류 제출", "부속·증빙서류 제출", "부속·증빙서류"]:
        try:
            loc = page.get_by_text(label, exact=False).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=5000)
                await page.wait_for_timeout(2500)
                log("[v] (홈택스) 부속·증빙서류 제출 모달 열림")
                return True
        except Exception:
            continue
    log("[!] (홈택스) 부속서류 제출 링크 못 찾음")
    return False


async def query_and_open_attach(ctx, page, rrn: str, log=print):
    """주민번호 조회 → 조회완료 알림 닫기 → '첨부하기'(새 팝업) → 팝업 page 반환(없으면 None)."""
    if not await _fill_rrn(page, rrn, log):
        return None
    await page.wait_for_timeout(400)
    try:
        await page.get_by_role("button", name="조회").first.click(timeout=5000)
    except Exception:
        try:
            await page.get_by_text("조회", exact=True).last.click(timeout=5000)
        except Exception as e:
            log(f"[!] (홈택스) 조회 클릭 실패: {str(e)[:60]}")
            return None
    # 조회 완료 알림 — 뜰 때까지 폴링(고정 대기 대신). 모달이 남아 있으면 아래 클릭이 막힌다.
    await page.wait_for_timeout(600)
    await _click_modal_confirm(page, must_contain="완료", log=log, timeout=8.0)
    try:
        # '첨부하기'는 조회 결과 행이 그려진 뒤에 나타난다 — locator가 자동 대기(12초)
        async with ctx.expect_page(timeout=15000) as info:
            await page.get_by_text("첨부하기", exact=True).first.click(timeout=12000)
        popup = await info.value
        # 고정 2초 대신 문서 로드까지 대기(느린 PC에서 내용이 늦게 뜨는 경우 대비).
        # 파일 입력칸 자체는 attach_files_and_submit이 다시 폴링한다.
        try:
            await popup.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        await popup.wait_for_timeout(600)
        log("[v] (홈택스) 부속서류 첨부 팝업 열림")
        return popup
    except Exception as e:
        log(f"[!] (홈택스) 첨부하기/새 창 실패: {str(e)[:80]}")
        return None


async def _popup_body(popup) -> str:
    """팝업의 모든 frame 텍스트 합치기(진단/검증용)."""
    parts = []
    for frame in popup.frames:
        try:
            parts.append(await frame.locator("body").inner_text(timeout=2000))
        except Exception:
            continue
    return "\n".join(parts)


async def _click_btn_in_popup(popup, texts: tuple, log=print) -> bool:
    """팝업 내 보이는 버튼/링크 중 텍스트가 texts와 정확히 일치하는 첫 요소 클릭."""
    for frame in popup.frames:
        try:
            els = frame.locator("a, button, input[type=button], input[type=submit]")
            for i in range(await els.count()):
                el = els.nth(i)
                if not await el.is_visible():
                    continue
                t = ((await el.inner_text()) or (await el.get_attribute("value")) or "").strip()
                if t in texts:
                    await el.click(timeout=4000)
                    return True
        except Exception:
            continue
    return False


async def attach_files_and_submit(popup, files: list, log=print, auto_submit: bool = True,
                                  parent=None) -> bool:
    """첨부 팝업에서 파일 주입(multiple) → 등록 확인 → '부속서류 제출하기' → 완료 검증.

    ⚠ 빈 제출 방지: 제출 전 첨부 파일명이 목록에 등록됐는지(N/M) 확인.
    완료 판정(오탐 방지): 성공 알림은 팝업/부모 페이지 어느 쪽에 뜰지 몰라 둘 다 듣고,
    팝업이 닫히면 성공으로 본다. 명시적 '없음' 경고만 실패로 보고, 신호가 끝내 없으면
    (등록은 됐으니) 실패가 아니라 '확인 권장'으로 통과시킨다.
    """
    # JS alert/confirm 메시지 기록(자동수락은 ctx 핸들러가 담당). 팝업+부모 둘 다 듣는다.
    dmsgs: list = []
    popup.on("dialog", lambda d: dmsgs.append(d.message))
    if parent is not None:
        try:
            parent.on("dialog", lambda d: dmsgs.append(d.message))
        except Exception:
            pass

    # ⚠ 팝업이 떠도 그 안의 파일 입력칸은 늦게 렌더된다. 프레임을 '한 번만' 순회하면
    #   아직 없는 상태를 보고 즉시 실패 → 호출측이 팝업을 닫아, 화면상 '창이 떴다가
    #   첨부 없이 꺼지는' 증상이 된다(라이브에서 실제 발생) → 등장할 때까지 폴링.
    injected = False
    for _ in range(30):                 # 최대 ~12초
        found_input = False
        for frame in popup.frames:
            try:
                fin = frame.locator("input[type=file]")
                if await fin.count() > 0:
                    found_input = True
                    await fin.first.set_input_files(files, timeout=15000)
                    injected = True
                    break
            except Exception as e:
                # 입력칸은 찾았는데 주입이 실패 = 파일 자체 문제(경로/권한/클라우드).
                # 재시도해도 소용없으므로 즉시 중단하고 원인을 남긴다.
                log(f"[!] (홈택스) 부속서류 주입 실패: {str(e)[:100]}")
                return False
        if injected or found_input:
            break
        await popup.wait_for_timeout(400)
    if not injected:
        log("[!] (홈택스) 첨부 팝업에 파일 입력칸이 나타나지 않음(12초 대기)")
        return False
    # 첨부 등록 확인: 파일명이 전부 목록에 보일 때까지 폴링(다건은 렌더가 늦음).
    # ⚠ 목록의 표시 이름은 픽셀 폭 기준 말줄임(…)이라 파일마다 잘리는 위치가 다르고
    # 공백도 달라질 수 있음 → 공백 제거 후 프리픽스를 12→10→8→6자로 줄여가며 매칭.
    # (고정 12자 매칭은 10개 다 올라갔는데 9/10으로 오집계했음)
    names = [Path(f).name for f in files]

    def _norm(s: str) -> str:
        return "".join(s.split())

    keys = [_norm(n) for n in names]

    def _count(body: str) -> int:
        b = _norm(body)
        found = 0
        for k in keys:
            for ln in (12, 10, 8, 6):
                if k[:ln] in b:
                    found += 1
                    break
        return found

    # 전부 보이면 즉시 진행. 일부가 끝내 매칭 안 되는 경우(말줄임이 12자보다 짧게
    # 잘리는 파일명 등)를 위해 '개수가 1.5초간 안 늘면' 등록 완료로 보고 진행 —
    # 안 그러면 30회(15초)를 꽉 채우는 헛대기가 됨.
    registered = 0
    prev, stable = -1, 0
    for _ in range(30):
        await popup.wait_for_timeout(500)
        registered = _count(await _popup_body(popup))
        if registered >= len(names):
            break
        if registered > 0 and registered == prev:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        prev = registered
    if registered == 0:
        if await _click_btn_in_popup(popup, ("첨부", "추가", "등록", "파일추가", "올리기"), log):
            await popup.wait_for_timeout(1500)
            registered = _count(await _popup_body(popup))
    log(f"[i] (홈택스) 첨부 등록 확인: {registered}/{len(names)}개 (목록 표시 기준)")
    if 0 < registered < len(names):
        # 진단: 어떤 파일명이 목록에서 매칭 안 됐는지 — 오집계 원인 규명용.
        b = _norm(await _popup_body(popup))
        missing = [n for n, k in zip(names, keys)
                   if not any(k[:ln] in b for ln in (12, 10, 8, 6))]
        if missing:
            log(f"[i] (홈택스) 목록에서 매칭 안 된 파일명: {missing}")
    if registered == 0:
        log("[!] (홈택스) 첨부 파일이 목록에 등록되지 않음 — 제출 중단(빈 제출 방지)")
        return False
    log(f"[v] (홈택스) 부속서류 {len(files)}개 첨부 (목록 확인 {registered})")

    if not auto_submit:
        log("[i] (홈택스) 첨부까지 완료(수동 제출 모드)")
        return True

    if not await _click_btn_in_popup(popup, ("부속서류 제출하기", "제출하기", "제출"), log):
        log("[!] (홈택스) '부속서류 제출하기' 버튼 못 찾음")
        return False
    await popup.wait_for_timeout(1500)
    # 제출 확인 모달(있으면) 확인/예 클릭 — JS confirm이면 ctx 핸들러가 자동수락.
    await _click_btn_in_popup(popup, ("확인", "예", "제출"), log)

    # 완료 검증: 신호 = (성공 알림) | (팝업 닫힘) | (부모 페이지 '제출완료').
    # 실제 업로드는 제출 클릭 후 로딩바 창에서 진행됨 — 업로드가 보이는 동안은
    # 계속 대기(quiet 리셋), 조용해진 뒤 25초까지만 추가 대기. 전체 한도 5분.
    # 실패 신호는 '없음' 계열 dialog만(본문 텍스트는 오탐 가능해 제외).
    success = empty = closed = False
    upload_seen = False
    quiet = total = 0
    while total < 300 and quiet < 25:
        try:
            await popup.wait_for_timeout(1000)
        except Exception:
            await asyncio.sleep(1)
        total += 1
        dialog_blob = " ".join(dmsgs)
        # 실패: '첨부파일이 없습니다' 등은 dialog로만 판단(본문의 무관한 '없음' 오탐 방지).
        if any(k in dialog_blob for k in ("없습니다", "선택된 파일", "첨부파일이")):
            empty = True
            break
        # 성공 알림(팝업/부모 어디든)
        if (("제출" in dialog_blob and ("되었" in dialog_blob or "완료" in dialog_blob))
                or "정상적으로" in dialog_blob or "접수되었" in dialog_blob):
            success = True
            break
        # 팝업이 닫혔으면 = 제출 성공 신호
        if popup.is_closed():
            closed = True
            break
        # 업로드 로딩바(progress 요소/'업로드 중' 문구)가 보이면 계속 대기
        uploading = False
        for fr in popup.frames:
            try:
                uploading = await fr.evaluate("""() => {
                    const vis = el => { const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0; };
                    for (const el of document.querySelectorAll(
                            '[class*="progress"],[id*="progress"],[class*="loading"],[id*="loading"]'))
                        if (vis(el)) return true;
                    return /업로드\\s*중|전송\\s*중|송신\\s*중|처리\\s*중/.test(
                        (document.body && document.body.innerText) || '');
                }""")
            except Exception:
                continue
            if uploading:
                break
        if uploading:
            if not upload_seen:
                log("[i] (홈택스) 첨부파일 업로드 진행 중 — 완료까지 대기…")
                upload_seen = True
            quiet = 0
        else:
            quiet += 1
        # 부모 페이지 본문에 '제출완료' 상태가 보이면 성공
        if parent is not None:
            try:
                pbody = await parent.locator("body").inner_text(timeout=1500)
                if "제출완료" in pbody or "정상적으로 제출" in pbody:
                    success = True
                    break
            except Exception:
                pass
    if dmsgs:
        log(f"[i] (홈택스) 제출 응답: {' / '.join(m[:50] for m in dmsgs[-3:])}")
    if empty:
        log("[!] (홈택스) 첨부파일 없음 경고 — 실제 제출 안 됨")
        return False
    if success:
        log("[v] (홈택스) 부속서류 제출 완료 (확인됨)")
        return True
    if closed:
        log("[v] (홈택스) 제출 후 첨부창 닫힘 — 제출 완료로 간주")
        return True
    # 등록은 확인됐고 오류 알림도 없음 → 실패로 단정하지 않고 통과(화면 확인 권장).
    log("[i] (홈택스) 완료 메시지 미확인이나 오류도 없음 — 제출된 것으로 처리(화면 확인 권장)")
    return True


# ─────────────────── 서류 PDF저장/출력 (Phase 4) ───────────────────

LINK_RECEIPT_INQUIRY = "신고내역 조회(접수증·납부서)"


async def navigate_to_inquiry(page, log=print) -> bool:
    """홈 리셋 → 신고/납부 → 양도소득세 → '신고내역 조회(접수증·납부서)' 모달."""
    await reset_to_home(page, log)
    if not await _open_and_click_submenu(page, "신고/납부", "양도소득세", log):
        log("[!] (홈택스) 양도소득세 진입 실패")
        return False
    await page.wait_for_timeout(1500)
    for label in [LINK_RECEIPT_INQUIRY, "신고내역 조회", "접수증·납부서"]:
        try:
            loc = page.get_by_text(label, exact=False).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=5000)
                await page.wait_for_timeout(2500)
                log("[v] (홈택스) 신고내역 조회 모달 열림")
                return True
        except Exception:
            continue
    log("[!] (홈택스) 신고내역 조회 링크 못 찾음")
    return False


async def _fill_inquiry_rrn(page, rrn: str, log=print) -> bool:
    """신고내역 조회 모달: 단일 password 칸(사업자/주민번호, maxlength 20)에 주민번호 13자리."""
    digits = "".join(c for c in (rrn or "") if c.isdigit())
    for frame in page.frames:
        try:
            pwl = frame.locator("input[type=password]")
            for i in range(await pwl.count()):
                el = pwl.nth(i)
                if not await el.is_visible():
                    continue
                ml = await el.get_attribute("maxlength")
                if ml is None or int(ml) >= 13:
                    await el.fill(digits)
                    return True
        except Exception:
            continue
    log("[!] (홈택스) 조회 주민번호 칸 못 찾음")
    return False


async def query_inquiry(page, rrn: str, log=print) -> bool:
    """신고내역 조회 모달: 주민번호 입력 → 조회 → 조회완료 알림 확인.

    (접수번호 링크는 누르지 않음 — 납부서 출력은 이 모달의 '납부서 보기'만 필요.)
    """
    if not await _fill_inquiry_rrn(page, rrn, log):
        return False
    await page.wait_for_timeout(400)
    try:
        await page.get_by_role("button", name="조회").first.click(timeout=5000)
    except Exception:
        try:
            await page.get_by_text("조회", exact=True).last.click(timeout=5000)
        except Exception as e:
            log(f"[!] (홈택스) 조회 클릭 실패: {str(e)[:60]}")
            return False
    await page.wait_for_timeout(2500)
    await _click_modal_confirm(page, must_contain="완료", log=log)
    await page.wait_for_timeout(1000)
    return True


async def open_receipt_docs(ctx, page, rrn: str, log=print) -> bool:
    """주민번호 조회 → 접수번호 링크 클릭(접수증/신고서/공개여부 창들 오픈)."""
    if not await query_inquiry(page, rrn, log):
        return False
    try:
        await page.get_by_text(RECEIPT_NO_RE).first.click(timeout=6000)
    except Exception as e:
        log(f"[!] (홈택스) 접수번호 링크 클릭 실패: {str(e)[:60]}")
        return False
    await page.wait_for_timeout(4000)
    log("[v] (홈택스) 접수번호 링크 클릭 — 접수증/신고서 창 열림")
    return True


async def set_disclosure(ctx, disclose: bool = True, log=print) -> bool:
    """'신고서 보기 개인정보 공개여부' 팝업: 공개/비공개 선택 + [적용].

    ⚠ '개인정보…' 문구는 신고서 보기 창에도 있어서, 조건에 맞는 '첫 창 하나'만 보면
      엉뚱한 창을 잡고 [적용]을 못 찾은 채 끝난다(실제 실패 원인).
      → 모든 창 × 모든 프레임을 돌며 [적용]을 찾을 때까지 시도하고, 그 전체를 폴링한다.
      놓치면 서류가 마스킹(주민번호 ***)된 채 저장되므로 중요.
    """
    target = "개인정보 공개" if disclose else "개인정보 비공개"
    radio_js = """(want) => {
        const norm = s => (s || '').replace(/\s+/g, '');
        for (const inp of document.querySelectorAll('input[type=radio]')) {
            let txt = '';
            if (inp.id) {
                const l = document.querySelector('label[for="' + inp.id + '"]');
                if (l) txt = l.innerText || '';
            }
            if (!txt && inp.parentElement) txt = inp.parentElement.innerText || '';
            if (norm(txt).includes(norm(want))) {
                inp.click();
                if (!inp.checked) inp.checked = true;
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }
        }
        return false;
    }"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + 12.0
    while True:
        for page in list(ctx.pages):
            for frame in page.frames:
                try:
                    await frame.evaluate(radio_js, target)   # 1) 라디오 선택
                except Exception:
                    pass
                try:
                    # 2) [적용] — 모든 요소를 보는 get_by_text가 검증된 방식
                    #    (태그를 한정한 JS 탐색은 span/div 버튼을 놓친다)
                    aply = frame.get_by_text("적용", exact=True).first
                    if await aply.count() and await aply.is_visible():
                        await aply.click(timeout=3000)
                        log(f"[i] (홈택스) 개인정보 {('공개' if disclose else '비공개')} 적용")
                        await page.wait_for_timeout(800)
                        return True
                except Exception:
                    continue
        if loop.time() >= deadline:
            break
        await asyncio.sleep(0.5)
    log("[!] (홈택스) 개인정보 공개여부 [적용] 클릭 실패")
    return False


async def wait_page(ctx, pred, timeout: float = 15.0, interval: float = 0.4):
    """조건(pred)에 맞는 page가 나타날 때까지 폴링. 없으면 None.

    ⚠ 창을 '한 번만' 찾으면 느린 PC·네트워크에서 아직 안 뜬 창을 놓쳐 그대로 실패한다
    (라이브에서 실제 발생) — 출력 관련 창 탐색은 반드시 이 함수를 쓸 것.
    """
    import inspect
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        for p in list(ctx.pages):
            try:
                r = pred(p)
                # ⚠ pred는 동기(lambda)일 수도, async일 수도 있다. 동기 결과를 await 하면
                #   TypeError가 나고 except에 삼켜져 '영원히 못 찾음'이 된다(실제 버그였음).
                if inspect.isawaitable(r):
                    r = await r
                if r:
                    return p
            except Exception:
                continue
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(interval)


async def _clipreport_scope(window, timeout: float = 12.0):
    """window 또는 그 자식 frame 중 m_reportHashMap을 가진 scope 반환.

    뷰어 스크립트가 늦게 초기화될 수 있어 등장할 때까지 폴링한다(1회 확인은 실패 원인).
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            if await window.evaluate("() => !!window.m_reportHashMap"):
                return window
        except Exception:
            pass
        for frame in window.frames:
            try:
                if await frame.evaluate("() => !!window.m_reportHashMap"):
                    return frame
            except Exception:
                continue
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(0.4)


async def _clipreport_save_pdf(page, scope, target, log=print) -> bool:
    """clipreport 리포트를 pdfDownLoad()로 내려받아 target에 저장.

    ⭐ Windows 저장 다이얼로그(pywinauto) 없이 브라우저 다운로드로 받는다 →
    다른 프로그램(양도박사·세무사랑) 쓰는 중에도 포커스를 뺏지 않아 안전하고 빠름.
    신고서 뷰어는 저장 버튼이 UI에 숨겨져 있을 뿐 pdfDownLoad는 살아있다(정찰 확인).
    받은 파일이 진짜 PDF(%PDF)인지 시그니처까지 검증.
    """
    try:
        await scope.wait_for_function(_CLIPREPORT_LOADED, timeout=30000)
    except Exception:
        log("  [!] (홈택스) clipreport 데이터 로드 대기 시간초과(계속)")
    target.parent.mkdir(parents=True, exist_ok=True)
    # 데이터 로드 신호가 이전 리포트 것일 수 있어(목록에서 다음 신고서를 막 클릭한 직후)
    # 짧게 안정화. 이게 없으면 첫 신고서에서 다운로드가 시작되지 않고 타임아웃 났다.
    await scope.wait_for_timeout(700)
    try:
        # 1차 실패 시 한 번 더 시도 — 뷰어가 아직 준비 안 됐던 경우를 구제(타임아웃 단축).
        for attempt in (1, 2):
            try:
                async with page.expect_download(timeout=25000) as dl:
                    r = await scope.evaluate("""() => {
                        const m = window.m_reportHashMap; if(!m) return 'no-map';
                        const k = Object.keys(m)[0]; if(!k) return 'no-key';
                        try { m[k].pdfDownLoad(); return 'ok'; }
                        catch(e) { return 'ERR ' + e.message; }
                    }""")
                    if not isinstance(r, str) or r != "ok":
                        log(f"  [!] (홈택스) pdfDownLoad 호출 실패: {r}")
                        return False
                break
            except Exception:
                if attempt == 2:
                    raise
                log("  [i] (홈택스) 다운로드 미시작 — 재시도")
                await scope.wait_for_timeout(1500)
        d = await dl.value
        await d.save_as(str(target))
    except Exception as e:
        log(f"  [!] (홈택스) PDF 다운로드 실패: {str(e)[:80]}")
        return False
    try:
        if target.read_bytes()[:4] != b"%PDF":
            log(f"  [!] (홈택스) 받은 파일이 PDF가 아님: {target.name}")
            return False
    except Exception:
        return False
    log(f"    PDF: ✓ 다운로드 저장 ({target.name})")
    return True


async def _clipreport_print(scope, target, log=print, save: bool = True,
                            expect_layer: bool | None = None, page=None) -> bool:
    """clipreport 인쇄 → (save=True) PDF 저장 / (save=False) 기본 프린터로 출력.

    데이터 로드 → printWindowView() → (인쇄방식 레이어가 뜨면 change 발화로 PDF DOM 초기화
    + mRe_printExportInfo) → save면 fill_and_save. 레이어 없으면(접수증) printWindowView가 곧 인쇄.
    expect_layer: True=레이어 확실(신고서) / False=레이어 없음(접수증, 폴링 스킵) / None=모름(폴링).
    page: 주면 PDF 저장 시 pdfDownLoad() 다운로드 방식을 먼저 시도(다이얼로그 없음).
    """
    # ⭐ PDF 저장은 다운로드 방식 우선 — Windows 다이얼로그가 없어 다른 프로그램 사용 중에도
    # 안전하고, 텍스트가 살아있는 PDF가 나온다. 실패 시에만 기존 인쇄 방식으로 폴백.
    if save and page is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tgt = pdf_save.prepare_target(target, log)
        if await _clipreport_save_pdf(page, scope, tgt, log):
            return True
        log("  [i] (홈택스) 다운로드 저장 실패 — 인쇄 방식으로 폴백")
    try:
        await scope.wait_for_function(_CLIPREPORT_LOADED, timeout=30000)
    except Exception:
        log("  [!] (홈택스) clipreport 데이터 로드 대기 시간초과(계속)")
    await scope.wait_for_timeout(300)
    key = await scope.evaluate("""() => {
        const m=window.m_reportHashMap; if(!m)return null;
        const k=Object.keys(m)[0]; if(!k)return null;
        try{m[k].printWindowView();}catch(e){return '__ERR__'+e.message;} return k;
    }""")
    if not key or (isinstance(key, str) and key.startswith("__ERR__")):
        log(f"  [!] (홈택스) printWindowView 실패: {key}")
        return False
    # 인쇄방식 레이어 등장을 폴링(고정 1500ms 대신) — 접수증(expect_layer=False)은 스킵.
    if expect_layer is not False:
        try:
            await scope.wait_for_function(
                "() => !!document.querySelector('[id^=\"re_printType1\"]')", timeout=4000)
        except Exception:
            pass   # 레이어 없는 유형(접수증류) — 아래 evaluate가 null 반환
    # 인쇄방식 레이어(신고서)면: change 발화 → mRe_selectPrintRange(1) → mRe_printExportInfo
    layer_key = await scope.evaluate("""() => {
        const sel = document.querySelector('[id^="re_printType1"]');
        if(!sel) return null;
        const k = sel.id.replace('re_printType1','');
        sel.value='pdf'; sel.dispatchEvent(new Event('change',{bubbles:true}));
        const r = window.m_reportHashMap[k];
        try{ if(r.mRe_selectPrintRange) r.mRe_selectPrintRange(1); }catch(e){}
        return k;
    }""")
    if layer_key:
        await scope.wait_for_timeout(1200)
        await scope.evaluate(f"""() => {{
            try{{ window.m_reportHashMap['{layer_key}'].mRe_printExportInfo(); }}catch(e){{}}
        }}""")
    if not save:
        # 출력 모드: 기본 프린터로 바로 출력됨(kiosk). 저장 다이얼로그 없음.
        await scope.wait_for_timeout(2500)
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    target = pdf_save.prepare_target(target, log)   # 사전 삭제 → 덮어쓰기창·OneDrive 잠금 회피
    ok, err = await asyncio.to_thread(pdf_save.fill_and_save, target, 25.0, log)
    if not ok:
        log(f"  [!] (홈택스) PDF 저장 실패: {err}")
    return ok


async def print_documents(ctx, page, pdf_dir, label: str, disclose: bool = True,
                          output_mode: str = "pdf", include_name: bool = False, log=print) -> dict:
    """접수번호 링크로 열린 접수증 + 신고서 목록을 PDF저장/출력. 반환: {saved:[...], failed:[...]}.

    호출 전 open_receipt_docs로 창들이 열려 있어야 함. output_mode 'print'면 기본 프린터로 출력.
    """
    from pathlib import Path
    pdf_dir = Path(pdf_dir)
    save = (output_mode == "pdf")
    result = {"saved": [], "failed": []}

    # ⚠ 공개여부를 적용하지 못하면 서류가 기본값(비공개=주민번호 ***)으로 저장된다.
    #   조용히 넘어가면 마스킹된 서류를 받게 되므로 눈에 띄게 경고한다.
    if not await set_disclosure(ctx, disclose, log):
        log("[!] (홈택스) 개인정보 공개여부 미적용 — 서류가 마스킹될 수 있습니다(확인 필요)")
    await page.wait_for_timeout(1200)

    # 접수증 (clipreport.do 최상위 창) — 창이 뜰 때까지 대기(1회 탐색은 놓칠 수 있음)
    report = await wait_page(ctx, lambda p: "clipreport" in (p.url or ""), timeout=15)
    if report is None:
        log("[!] (홈택스) 접수증 창(clipreport)이 뜨지 않음")
        result["failed"].append("[접수증]")
    if report:
        await report.wait_for_timeout(400)   # _clipreport_print가 데이터 로드를 따로 대기
        sc = await _clipreport_scope(report)
        tgt = pdf_dir / pdf_save.doc_name("접수증", [], include_name, label)
        if sc and await _clipreport_print(sc, tgt, log, save=save, expect_layer=False,
                                          page=report):
            result["saved"].append(tgt.name)
            log(f"[v] (홈택스) 접수증 {'저장' if save else '출력'}: {tgt.name}")
        else:
            result["failed"].append("[접수증]")
        try:
            await report.close()
        except Exception:
            pass
    await page.wait_for_timeout(1000)

    # 신고서 보기 뷰어 — 창이 뜰 때까지 대기
    async def _is_viewer(p):
        return "신고서 목록" in await p.locator("body").inner_text(timeout=2000)

    viewer = await wait_page(ctx, _is_viewer, timeout=15)
    if viewer is None:
        log("[!] (홈택스) 신고서 보기 뷰어 없음")
        return result

    # 신고서 목록 수집 — 프레임당 JS 한 번(요소별 await 왕복 제거), 목록 렌더까지 폴링.
    items: list = []
    for _ in range(12):   # 최대 ~6초
        for frame in viewer.frames:
            try:
                found = await frame.evaluate("""() => {
                    const vis = el => { const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0; };
                    const out = [];
                    for (const el of document.querySelectorAll('a, li')) {
                        if (!vis(el)) continue;
                        const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                        if ((t.includes('계산서') || t.includes('명세서'))
                                && t.length < 40 && !out.includes(t)) out.push(t);
                    }
                    return out;
                }""")
            except Exception:
                continue
            for t in found:
                if t not in items:
                    items.append(t)
        if items:
            break
        await viewer.wait_for_timeout(500)
    log(f"[i] (홈택스) 신고서 {len(items)}건: {items}")
    for it in items:
        if not await _click_text_in_frames(viewer, it):
            log(f"  [!] 목록 클릭 실패: {it}")
            continue
        await viewer.wait_for_timeout(800)   # _clipreport_print가 데이터 로드를 따로 대기
        sc = await _clipreport_scope(viewer)
        if sc is None:
            result["failed"].append(it)
            continue
        fname = pdf_save.doc_name("신고서", [it], include_name, label)
        tgt = pdf_dir / fname
        if await _clipreport_print(sc, tgt, log, save=save, expect_layer=True, page=viewer):
            result["saved"].append(fname)
            log(f"[v] (홈택스) 신고서 {'저장' if save else '출력'}: {fname}")
        else:
            result["failed"].append(it)
    return result


async def _click_text_in_frames(window, text: str) -> bool:
    for frame in window.frames:
        try:
            loc = frame.get_by_text(text, exact=True).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


async def print_napbu(ctx, page, pdf_dir, label: str = "", output_mode: str = "pdf",
                      include_name: bool = False, log=print) -> dict:
    """신고내역 모달의 납부서 [보기] → 납부서 목록 팝업 → 각 납부서(프린트 아이콘) PDF저장/출력.

    납부서는 분납 시 여러 건. img[alt='납부서'](btn_print.png) 클릭 → 납부서 clipreport 창.
    파일명: [납부서]{이름}_양도소득세_{납부기한}.pdf (납부기한은 목록 표에서 fetch).
    납부할금액 0/기한경과면 목록에 안 뜸 → 0건이면 빈 결과(차손 등).
    """
    from pathlib import Path
    pdf_dir = Path(pdf_dir)
    save = (output_mode == "pdf")
    result = {"saved": [], "failed": []}

    await page.bring_to_front()
    # 신고내역 행엔 접수증 보기 + 납부서 보기. 차손이면 납부서 보기가 없어 보기 버튼이 1개뿐 →
    # .last가 접수증 보기를 누르는 오작동 발생. 보기 버튼이 2개 이상일 때만 마지막(=납부서)을 누른다.
    bogi = page.get_by_text("보기", exact=True)
    vis = []
    try:
        for i in range(await bogi.count()):
            if await bogi.nth(i).is_visible():
                vis.append(i)
    except Exception:
        pass
    if len(vis) < 2:
        log("[i] (홈택스) 납부서 보기 없음(차손/무납부서) — 건너뜀")
        return result
    try:
        await bogi.nth(vis[-1]).click(timeout=5000)
    except Exception as e:
        log(f"[!] (홈택스) 납부서 보기 클릭 실패: {str(e)[:60]}")
        return result
    await page.wait_for_timeout(2500)

    icons = page.locator("img[alt='납부서']")
    try:
        n = await icons.count()
    except Exception:
        n = 0
    # 각 납부서 아이콘의 행에서 납부기한(YYYY-MM-DD) 추출
    dues = await page.evaluate("""() => {
        const out=[];
        document.querySelectorAll("img[alt='납부서']").forEach(img=>{
            const row=img.closest('tr'); let d='';
            if(row){ const m=(row.innerText||'').match(/20\\d\\d-\\d\\d-\\d\\d/); if(m) d=m[0]; }
            out.push(d);
        });
        return out;
    }""")
    log(f"[i] (홈택스) 납부서 {n}건 (납부기한 {dues})")
    for i in range(n):
        try:
            # ⚠ WebSquare는 같은 popupID 창을 재사용한다 → 이미 열린 clipreport 창이
            #   있으면 '새 page 이벤트'가 발생하지 않아 expect_page가 타임아웃난다
            #   ('새 창 없음 ≠ 팝업 없음'). 그 경우 기존 창을 찾아서 쓴다.
            before = set(ctx.pages)
            win = None
            try:
                async with ctx.expect_page(timeout=10000) as info:
                    await page.locator("img[alt='납부서']").nth(i).click(timeout=8000)
                win = await info.value
            except Exception:
                win = await wait_page(
                    ctx, lambda p: "clipreport" in (p.url or "") and p not in before, timeout=3)
                if win is None:   # 재사용된 창(이미 before에 있던 것)까지 허용
                    win = await wait_page(
                        ctx, lambda p: "clipreport" in (p.url or ""), timeout=3)
                if win is None:
                    raise RuntimeError("납부서 창을 찾지 못함(새 창·재사용 창 모두 없음)")
                log("  [i] (홈택스) 새 창 대신 기존 납부서 창 재사용")
            await win.wait_for_timeout(800)
            sc = await _clipreport_scope(win)
            due = pdf_save.fmt_due(dues[i] if i < len(dues) else "")
            tgt = pdf_dir / pdf_save.doc_name("납부서", ["양도소득세", due], include_name, label)
            if sc and await _clipreport_print(sc, tgt, log, save=save, page=win):
                result["saved"].append(tgt.name)
                log(f"[v] (홈택스) 납부서 {'저장' if save else '출력'}: {tgt.name}")
            else:
                result["failed"].append(f"납부서{i + 1}")
            try:
                await win.close()
            except Exception:
                pass
        except Exception as e:
            log(f"[!] (홈택스) 납부서{i + 1} 실패: {str(e)[:70]}")
            result["failed"].append(f"납부서{i + 1}")
    # 납부서 목록 팝업 닫기
    try:
        await page.get_by_text("닫기", exact=True).last.click(timeout=3000)
    except Exception:
        pass
    return result
