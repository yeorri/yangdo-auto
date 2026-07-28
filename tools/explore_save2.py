"""clipreport 저장 2차 정찰 — PDF 형식 지정 + 파일명 지정 방법 확정.

1차 결과: exportView()로 저장 패널이 열리고 다운로드 가로채기도 성공했으나,
기본 형식이 Excel이라 .xls가 받아짐(suggested=신고접수증.xls).
→ 이번엔 (a)핵심 함수 소스 덤프로 인자 확인 (b)패널 DOM(형식 select/파일명 input)
   (c)pdfDownLoad() 직접 호출로 PDF 받기 시도까지.

실행:  python tools/explore_save2.py <주민번호13자리>
결과:  save_dump2.txt + _dl_test/ 에 받은 파일들(시그니처로 PDF 여부 판정)
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

OUT = ROOT / "save_dump2.txt"
DL = ROOT / "_dl_test"

FUNCS = ["exportView", "pdfDownLoad", "saveExportView", "saveExportFileInfo",
         "mRe_selectExportType", "setSaveFileName", "setDefaultSelectSaveOption",
         "submitSaveOption", "makeExportSaveOption", "mRe_selectSaveRange",
         "setSaveDirectPDFOption", "saveFileDownLoad", "setPDFDownloadLink"]


def sig(p: Path) -> str:
    try:
        b = p.read_bytes()[:4]
    except Exception:
        return "?"
    if b == b"%PDF":
        return "✅ PDF"
    if b == b"\xd0\xcf\x11\xe0":
        return "❌ xls(OLE)"
    if b[:2] == b"PK":
        return "❌ zip계열"
    return f"? {b.hex()}"


async def wait_login(page, timeout=420):
    print("[i] 홈택스 로그인 대기(최대 7분)", flush=True)
    for s in range(0, timeout, 2):
        try:
            if "로그아웃" in await page.locator("body").inner_text(timeout=2500):
                print(f"[v] 로그인 ({s}s)", flush=True)
                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


async def dump_funcs(scope, f):
    """핵심 함수 소스 앞부분 덤프 — 인자/동작 확인용."""
    src = await scope.evaluate("""(names) => {
        const m = window.m_reportHashMap; if (!m) return {};
        const k = Object.keys(m)[0]; if (!k) return {};
        const r = m[k]; const out = {};
        for (const n of names) {
            try { if (typeof r[n] === 'function')
                out[n] = r[n].toString().replace(/\\s+/g, ' ').slice(0, 320); }
            catch(e) { out[n] = 'ERR ' + e.message; }
        }
        return out;
    }""", FUNCS)
    f.write("\n===== 함수 소스(앞 320자) =====\n")
    for n in FUNCS:
        f.write(f"\n--- {n} ---\n{src.get(n, '(없음)')}\n")
    f.flush()


async def dump_panel(scope, f, label):
    """저장 패널 DOM — 형식 select의 option, 파일명 input 등."""
    d = await scope.evaluate("""() => {
        const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0; };
        const sels = [], inputs = [];
        for (const s of document.querySelectorAll('select')) {
            if (!vis(s)) continue;
            sels.push({id: s.id, name: s.name, value: s.value,
                       options: [...s.options].map(o => o.value + '|' + o.text).slice(0, 20)});
        }
        for (const i of document.querySelectorAll('input')) {
            if (!vis(i)) continue;
            inputs.push({id: i.id, name: i.name, type: i.type,
                         value: (i.value || '').slice(0, 30)});
        }
        return {sels, inputs};
    }""")
    f.write(f"\n===== 패널 DOM: {label} =====\n")
    for s in d.get("sels", []):
        f.write(f"SELECT id={s['id']} name={s['name']} value={s['value']}\n")
        for o in s["options"]:
            f.write(f"    option: {o}\n")
    for i in d.get("inputs", []):
        f.write(f"INPUT id={i['id']} name={i['name']} type={i['type']} value={i['value']}\n")
    f.flush()
    return d


async def try_pdf_download(page, scope, f, log, tag: str, js: str):
    """주어진 JS로 다운로드 시도 → 받은 파일 시그니처 판정."""
    target = DL / f"{tag}.bin"
    try:
        async with page.expect_download(timeout=25000) as dl:
            r = await scope.evaluate(js)
            log(f"    [{tag}] js결과: {r}")
        d = await dl.value
        await d.save_as(str(target))
        s = sig(target)
        msg = f"[{tag}] 다운로드 OK — suggested={d.suggested_filename} / {target.stat().st_size}b / {s}"
        log(f"  {msg}")
        f.write(msg + "\n")
        return s.startswith("✅")
    except Exception as e:
        msg = f"[{tag}] 실패: {str(e)[:120]}"
        log(f"  {msg}")
        f.write(msg + "\n")
        return False


async def probe_viewers(ctx, page, f, log):
    """신고서 뷰어(저장 버튼이 UI에 없는 창)에서도 저장 API가 살아있는지 확인.

    같은 clipreport 엔진이라 버튼만 숨겨져 있고 pdfDownLoad/exportView는 동작할 수 있음
    (API 목록에 setPrintExceptionSaveButtonVisible/setSaveOptionVisible 존재).
    """
    viewer = None
    for p in ctx.pages:
        try:
            if "신고서 목록" in await p.locator("body").inner_text(timeout=2000):
                viewer = p
                break
        except Exception:
            continue
    if viewer is None:
        f.write("\n[신고서 뷰어] 창을 못 찾음\n")
        log("[!] 신고서 뷰어 창 없음")
        return

    # 목록 첫 항목 클릭 → 신고서 리포트 로드
    items = await viewer.evaluate("""() => {
        const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0; };
        const out = [];
        for (const el of document.querySelectorAll('a, li')) {
            if (!vis(el)) continue;
            const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            if ((t.includes('계산서') || t.includes('명세서')) && t.length < 40
                && !out.includes(t)) out.push(t);
        }
        return out;
    }""")
    log(f"[i] 신고서 목록: {items}")
    if items:
        await H._click_text_in_frames(viewer, items[0])
        await viewer.wait_for_timeout(2500)

    sc2 = await H._clipreport_scope(viewer)
    if sc2 is None:
        f.write("\n[신고서 뷰어] m_reportHashMap 스코프 없음\n")
        log("[!] 신고서 뷰어 스코프 없음")
        return

    # 저장 API 존재 여부 + 저장 버튼 가시성
    info = await sc2.evaluate("""() => {
        const m = window.m_reportHashMap; const k = Object.keys(m)[0];
        const r = m[k]; const has = {};
        for (const n of ['exportView','pdfDownLoad','saveExportView',
                         'setSaveFileName','setPrintExceptionSaveButtonVisible',
                         'setSaveOptionVisible'])
            has[n] = typeof r[n] === 'function';
        const vis = el => { const b = el.getBoundingClientRect();
            return b.width > 0 && b.height > 0; };
        const btns = [];
        for (const el of document.querySelectorAll('button, a, input[type=button]')) {
            if (!vis(el)) continue;
            const t = ((el.innerText || el.value || el.title || '') + '').trim().slice(0, 20);
            if (t) btns.push(t);
        }
        return {has, btns: btns.slice(0, 15)};
    }""")
    f.write(f"\n===== 신고서 뷰어 =====\n저장API: {info['has']}\n보이는 버튼: {info['btns']}\n")
    log(f"[i] 신고서 뷰어 저장API: {info['has']}")
    log(f"[i] 신고서 뷰어 버튼: {info['btns']}")

    # 저장 버튼이 없어도 JS로 pdfDownLoad 직접 호출 시도
    log("[i] C) 신고서에서 pdfDownLoad() 직접 호출")
    ok = await try_pdf_download(viewer, sc2, f, log, "C_report_pdfDownLoad", """() => {
        const m = window.m_reportHashMap; const k = Object.keys(m)[0];
        try { m[k].pdfDownLoad(); return 'called'; } catch(e) { return 'ERR ' + e.message; }
    }""")
    if not ok:
        log("[i] D) 신고서에서 exportView() → PDF 선택 → 저장")
        await sc2.evaluate("""() => {
            const m = window.m_reportHashMap; const k = Object.keys(m)[0];
            try { m[k].exportView(); } catch(e) {}
        }""")
        await viewer.wait_for_timeout(1500)
        await dump_panel(sc2, f, "신고서 exportView 후")
        await try_pdf_download(viewer, sc2, f, log, "D_report_selectPdf", """() => {
            const m = window.m_reportHashMap; const k = Object.keys(m)[0]; const r = m[k];
            for (const s of document.querySelectorAll('select')) {
                const opt = [...s.options].find(o => /pdf/i.test(o.value + o.text));
                if (opt) { s.value = opt.value;
                    s.dispatchEvent(new Event('change', {bubbles: true}));
                    try { if (r.mRe_selectExportType) r.mRe_selectExportType(s); } catch(e) {}
                    break; }
            }
            const vis = el => { const b = el.getBoundingClientRect();
                return b.width > 0 && b.height > 0; };
            for (const el of document.querySelectorAll('button, a, input[type=button]')) {
                if (!vis(el)) continue;
                const t = ((el.innerText || el.value || '') + '').trim();
                if (t === '저장') { el.click(); return 'saved'; }
            }
            return 'no-save-btn';
        }""")


async def main():
    rrn = sys.argv[1] if len(sys.argv) > 1 else ""
    if len("".join(c for c in rrn if c.isdigit())) != 13:
        print("사용법: python tools/explore_save2.py <주민번호13자리>")
        return
    OUT.write_text("clipreport 저장 2차 정찰\n", encoding="utf-8")
    DL.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        page = (await B.open_homepages(ctx, ["홈택스"]))["홈택스"]
        if not await wait_login(page):
            await ctx.close(); return

        if not await H.navigate_to_inquiry(page, print):
            print("[!] 조회 진입 실패"); await ctx.close(); return
        if not await H.open_receipt_docs(ctx, page, rrn, print):
            print("[!] 접수번호 링크 실패"); await ctx.close(); return
        await H.set_disclosure(ctx, True, print)
        await page.wait_for_timeout(1500)

        report = next((p for p in ctx.pages if "clipreport" in (p.url or "")), None)
        if report is None:
            print("[!] clipreport 창 없음"); await ctx.close(); return
        await report.wait_for_timeout(1000)
        sc = await H._clipreport_scope(report)
        if sc is None:
            print("[!] 스코프 없음"); await ctx.close(); return

        with OUT.open("a", encoding="utf-8") as f:
            await dump_funcs(sc, f)
            await probe_viewers(ctx, page, f, print)

            # A) pdfDownLoad() 직접 호출 — 패널 없이 바로 PDF?
            print("[i] A) pdfDownLoad() 직접 호출")
            ok_a = await try_pdf_download(report, sc, f, print, "A_pdfDownLoad", """() => {
                const m = window.m_reportHashMap; const k = Object.keys(m)[0];
                try { m[k].pdfDownLoad(); return 'called'; } catch(e) { return 'ERR ' + e.message; }
            }""")

            # B) 패널 열고 형식 select를 pdf로 바꾼 뒤 저장
            if not ok_a:
                print("[i] B) exportView() → 형식 PDF 선택 → 저장")
                await sc.evaluate("""() => {
                    const m = window.m_reportHashMap; const k = Object.keys(m)[0];
                    try { m[k].exportView(); } catch(e) {}
                }""")
                await report.wait_for_timeout(1500)
                await dump_panel(sc, f, "exportView 후")
                await try_pdf_download(report, sc, f, print, "B_selectPdf", """() => {
                    const m = window.m_reportHashMap; const k = Object.keys(m)[0]; const r = m[k];
                    // 형식 select에서 pdf 선택 후 change 발화
                    for (const s of document.querySelectorAll('select')) {
                        const opt = [...s.options].find(o => /pdf/i.test(o.value + o.text));
                        if (opt) { s.value = opt.value;
                            s.dispatchEvent(new Event('change', {bubbles: true}));
                            try { if (r.mRe_selectExportType) r.mRe_selectExportType(s); } catch(e) {}
                            break; }
                    }
                    // 저장 버튼 클릭
                    const vis = el => { const b = el.getBoundingClientRect();
                        return b.width > 0 && b.height > 0; };
                    for (const el of document.querySelectorAll('button, a, input[type=button]')) {
                        if (!vis(el)) continue;
                        const t = ((el.innerText || el.value || '') + '').trim();
                        if (t === '저장') { el.click(); return 'saved'; }
                    }
                    return 'no-save-btn';
                }""")
                await report.wait_for_timeout(1500)
                # PDF 옵션 확인창이 뜨면 확인
                await dump_panel(sc, f, "저장 클릭 후")

        print(f"\n[i] 결과: {OUT}")
        print("[i] 받은 파일:")
        for p in sorted(DL.glob("*")):
            print(f"  - {p.name} ({p.stat().st_size}b) {sig(p)}")
        print("[i] 25초 후 종료 (화면 확인 가능)")
        await asyncio.sleep(25)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
