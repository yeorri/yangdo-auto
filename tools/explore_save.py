"""clipreport 뷰어 '저장(내려받기)' 경로 정찰 + 다운로드 가로채기 검증.

목적: Windows 저장 다이얼로그(pywinauto) 없이 PDF를 받는 방식으로 전환 가능한지 확인.
  뷰어 좌상단 저장 아이콘 → [파일형식: PDF 저장(*.pdf)] 패널 → [저장] → 브라우저 다운로드
  → Playwright가 가로채 원하는 경로에 저장(accept_downloads=True).

이 스크립트는 신고가 이미 접수된 상태에서 실행한다(신고 phase는 건드리지 않음):
  홈택스 로그인 대기 → 신고내역 조회(주민번호) → 접수번호 링크 → 접수증/신고서 뷰어
  → (1) 저장 관련 JS API/버튼 덤프  (2) 저장 클릭 → 다운로드 가로채기 실제 테스트

실행:  python tools/explore_save.py <주민번호13자리>
결과:  save_dump.txt (PII 없음: 함수명/버튼명만) + 다운로드 성공 시 저장 경로 출력
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright

from automation import browser as B
from automation import hometax as H

OUT = ROOT / "save_dump.txt"
DL_DIR = ROOT / "_dl_test"


async def wait_login(page, timeout=420):
    print("[i] 홈택스 로그인 대기(최대 7분)", flush=True)
    for sec in range(0, timeout, 2):
        try:
            if "로그아웃" in await page.locator("body").inner_text(timeout=2500):
                print(f"[v] 로그인 ({sec}s)", flush=True)
                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


async def dump_scope(scope, f, label: str):
    """clipreport 스코프에서 저장/내보내기 관련 API·버튼 덤프."""
    data = await scope.evaluate("""() => {
        const out = {api: [], winApi: [], buttons: [], imgs: []};
        const m = window.m_reportHashMap;
        if (m) {
            const k = Object.keys(m)[0];
            if (k) {
                const r = m[k];
                // 리포트 객체의 저장/내보내기 관련 메서드
                for (const p in r) {
                    try { if (typeof r[p] === 'function'
                        && /save|export|down|pdf|file/i.test(p)) out.api.push(p); } catch(e){}
                }
                out.key = k;
            }
        }
        // 전역 함수 중 저장 관련
        for (const p in window) {
            try { if (typeof window[p] === 'function'
                && /save|export|down|pdf/i.test(p)) out.winApi.push(p); } catch(e){}
        }
        const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0; };
        for (const el of document.querySelectorAll('button, a, input[type=button], div[onclick], span[onclick]')) {
            if (!vis(el)) continue;
            const t = ((el.innerText || el.value || el.title || '') + '').trim().slice(0, 24);
            const cls = (el.className || '').toString().slice(0, 50);
            const oc = (el.getAttribute('onclick') || '').slice(0, 60);
            if (t || cls || oc) out.buttons.push({t, id: el.id, cls, oc});
        }
        for (const el of document.querySelectorAll('img')) {
            if (!vis(el)) continue;
            out.imgs.push({src: (el.src || '').split('/').pop().slice(0, 40),
                           alt: el.alt || '', id: el.id,
                           oc: (el.getAttribute('onclick') || '').slice(0, 60)});
        }
        return out;
    }""")
    f.write(f"\n===== {label} =====\n")
    f.write(f"reportKey: {data.get('key')}\n")
    f.write(f"[리포트 객체 저장관련 메서드]\n  {data.get('api')}\n")
    f.write(f"[전역 저장관련 함수]\n  {data.get('winApi')}\n")
    f.write("[보이는 버튼]\n")
    for b in data.get("buttons", [])[:40]:
        f.write(f"  '{b['t']}' id={b['id']} cls={b['cls']} onclick={b['oc']}\n")
    f.write("[보이는 아이콘(img)]\n")
    for i in data.get("imgs", [])[:30]:
        f.write(f"  {i['src']} alt='{i['alt']}' id={i['id']} onclick={i['oc']}\n")
    f.flush()
    return data


async def try_save_flow(page, scope, f, log=print):
    """저장 아이콘 클릭 → 패널 덤프 → [저장] 클릭 → 다운로드 가로채기 테스트."""
    # 1) 저장 아이콘/함수 실행 시도 — API 우선, 없으면 아이콘 클릭
    opened = await scope.evaluate("""() => {
        const m = window.m_reportHashMap; if (!m) return 'no-map';
        const k = Object.keys(m)[0]; if (!k) return 'no-key';
        const r = m[k];
        // 저장 패널을 여는 후보 메서드들 순서대로 시도
        for (const name of ['saveWindowView','exportWindowView','mRe_saveExportInfo',
                            'saveView','exportView','mRe_exportInfo']) {
            if (typeof r[name] === 'function') {
                try { r[name](); return 'called:' + name; } catch(e) { return 'err:'+name+':'+e.message; }
            }
        }
        return 'no-method';
    }""")
    f.write(f"\n[저장 패널 열기 시도] {opened}\n")
    log(f"[i] 저장 패널 열기: {opened}")
    if str(opened).startswith("no-"):
        # 폴백: 저장 아이콘 클릭 (좌상단 디스크 아이콘)
        clicked = await scope.evaluate("""() => {
            const vis = el => { const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0; };
            for (const el of document.querySelectorAll('img, button, a, div')) {
                if (!vis(el)) continue;
                const s = ((el.src||'') + (el.className||'') + (el.id||'')
                          + (el.title||'') + (el.alt||'')).toLowerCase();
                if (/save|down|export|디스크/.test(s)) { el.click(); return s.slice(0,60); }
            }
            return '';
        }""")
        f.write(f"[아이콘 클릭 폴백] {clicked}\n")
        log(f"[i] 아이콘 클릭 폴백: {clicked}")
    await page.wait_for_timeout(1500)

    # 2) 저장 패널 구조 덤프
    await dump_scope(scope, f, "저장 패널 열린 후")

    # 3) [저장] 버튼 클릭 + 다운로드 가로채기
    DL_DIR.mkdir(exist_ok=True)
    target = DL_DIR / "테스트저장.pdf"
    try:
        async with page.expect_download(timeout=30000) as dl:
            await scope.evaluate("""() => {
                const vis = el => { const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0; };
                for (const el of document.querySelectorAll('button, a, input[type=button]')) {
                    if (!vis(el)) continue;
                    const t = ((el.innerText || el.value || '') + '').trim();
                    if (t === '저장') { el.click(); return true; }
                }
                return false;
            }""")
        d = await dl.value
        await d.save_as(str(target))
        size = target.stat().st_size if target.exists() else 0
        f.write(f"\n[다운로드 성공] {target.name} ({size}b) suggested={d.suggested_filename}\n")
        log(f"[v] 다운로드 가로채기 성공: {target} ({size}b)")
        return True
    except Exception as e:
        f.write(f"\n[다운로드 실패] {str(e)[:200]}\n")
        log(f"[!] 다운로드 실패: {str(e)[:120]}")
        return False


async def main():
    rrn = sys.argv[1] if len(sys.argv) > 1 else ""
    if len(("".join(c for c in rrn if c.isdigit()))) != 13:
        print("사용법: python tools/explore_save.py <주민번호13자리>")
        return

    OUT.write_text("clipreport 저장(내려받기) 정찰\n", encoding="utf-8")
    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        page = (await B.open_homepages(ctx, ["홈택스"]))["홈택스"]
        if not await wait_login(page):
            await ctx.close(); return

        if not await H.navigate_to_inquiry(page, print):
            print("[!] 신고내역 조회 진입 실패"); await ctx.close(); return
        if not await H.open_receipt_docs(ctx, page, rrn, print):
            print("[!] 접수번호 링크 실패"); await ctx.close(); return
        await H.set_disclosure(ctx, True, print)
        await page.wait_for_timeout(1500)

        with OUT.open("a", encoding="utf-8") as f:
            # 접수증 창(clipreport.do)에서 정찰
            report = next((p for p in ctx.pages if "clipreport" in (p.url or "")), None)
            if report is None:
                print("[!] clipreport 창을 못 찾음")
            else:
                await report.wait_for_timeout(1000)
                sc = await H._clipreport_scope(report)
                if sc is None:
                    print("[!] m_reportHashMap 스코프 없음")
                else:
                    await dump_scope(sc, f, "접수증 뷰어 초기 상태")
                    # scope가 frame이면 page는 report
                    await try_save_flow(report, sc, f, print)

        print(f"\n[i] 결과: {OUT}")
        print("[i] 30초 후 종료 (화면에서 저장 패널 확인 가능)")
        await asyncio.sleep(30)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
