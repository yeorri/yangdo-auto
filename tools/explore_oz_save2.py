"""위택스 OZ 뷰어 심층 정찰 — 툴바 아이콘 스크린샷 + OZ API 전수 조사.

1차: 텍스트 없는 base64 아이콘뿐이라 버튼을 못 찾음. 전역에 saveAs/_OZCPDFDocCmd 존재.
2차: (a)뷰어 스크린샷으로 툴바를 눈으로 확인 (b)OZ 전역 객체/함수 전수 덤프
     (c)saveAs 등 소스 확인 (d)툴바 아이콘 요소 좌표·클래스 덤프 후 클릭 시도.

실행:  python tools/explore_oz_save2.py <성명>
결과:  oz_dump2.txt + oz_viewer.png(툴바 확인용) + _dl_test/
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
from automation import wetax as W

OUT = ROOT / "oz_dump2.txt"
SHOT = ROOT / "oz_viewer.png"
DL = ROOT / "_dl_test"


def sig(p: Path) -> str:
    try:
        b = p.read_bytes()[:4]
    except Exception:
        return "?"
    if b == b"%PDF":
        return "✅ PDF"
    if b[:2] == b"PK":
        return "zip계열"
    return f"? {b.hex()}"


async def wait_login(page, timeout=420):
    print("[i] 위택스 로그인 대기(최대 7분)", flush=True)
    for s in range(0, timeout, 2):
        try:
            if "로그아웃" in await page.locator("body").inner_text(timeout=2500):
                print(f"[v] 로그인 ({s}s)", flush=True)
                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


async def deep_dump(oz, f):
    """OZ 전역 객체/함수 전수 + 툴바 요소 상세."""
    d = await oz.evaluate("""() => {
        const out = {globalObjs: {}, funcs: {}, toolbar: []};
        // 전역 객체 전수 — 이름 패턴 없이, 저장/내보내기 메서드를 가진 객체 찾기
        for (const p in window) {
            try {
                const v = window[p];
                if (!v || typeof v !== 'object' || p.length > 40) continue;
                const ms = [];
                for (const m in v) {
                    try { if (typeof v[m] === 'function'
                        && /save|export|down|pdf|print|file/i.test(m)) ms.push(m); } catch(e) {}
                }
                if (ms.length) out.globalObjs[p] = ms.slice(0, 30);
            } catch(e) {}
        }
        // 주요 전역 함수 소스
        for (const n of ['saveAs', 'print', '_OZCPDFDocCmd', '_OZCPDFPageCmd',
                         'OZViewer', 'getOZViewer', 'OZExport']) {
            try { if (typeof window[n] === 'function')
                out.funcs[n] = window[n].toString().replace(/\\s+/g, ' ').slice(0, 260); } catch(e) {}
        }
        // 툴바: 클릭 가능한 요소 전부(좌표·클래스·부모 포함)
        const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.top < 200; };
        for (const el of document.querySelectorAll('*')) {
            if (!vis(el)) continue;
            const r = el.getBoundingClientRect();
            if (r.width > 60 || r.height > 60) continue;   // 아이콘 크기만
            const st = getComputedStyle(el);
            if (st.cursor !== 'pointer' && el.tagName !== 'IMG' && !el.onclick) continue;
            out.toolbar.push({
                tag: el.tagName, id: el.id,
                cls: (el.className || '').toString().slice(0, 45),
                title: el.title || '', alt: el.alt || '',
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
                parentCls: (el.parentElement && el.parentElement.className || '').toString().slice(0, 40),
            });
        }
        return out;
    }""")
    f.write("\n===== OZ 전역 객체(저장관련 메서드 보유) =====\n")
    for k, v in d["globalObjs"].items():
        f.write(f"  {k}: {v}\n")
    f.write("\n===== 주요 함수 소스 =====\n")
    for k, v in d["funcs"].items():
        f.write(f"\n--- {k} ---\n{v}\n")
    f.write(f"\n===== 툴바 요소({len(d['toolbar'])}개) =====\n")
    for t in d["toolbar"][:40]:
        f.write(f"  <{t['tag']}> id={t['id']} cls={t['cls']} title='{t['title']}' "
                f"alt='{t['alt']}' @({t['x']},{t['y']}) {t['w']}x{t['h']} parent={t['parentCls']}\n")
    f.flush()
    return d


async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not name:
        print("사용법: python tools/explore_oz_save2.py <성명>")
        return
    OUT.write_text("위택스 OZ 심층 정찰\n", encoding="utf-8")
    DL.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        ctx = await B.launch(pw)
        msgs: list = []
        await B.setup_context(ctx, msgs)
        page = (await B.open_homepages(ctx, ["위택스"]))["위택스"]
        if not await wait_login(page):
            await ctx.close(); return

        if not await W.open_inquiry(page, print):
            print("[!] 신고내역 진입 실패"); await ctx.close(); return
        if not await W._expand_taxpayer(page, name, print):
            print("[!] 출력물 보기 실패"); await ctx.close(); return
        try:
            async with ctx.expect_page(timeout=15000) as info:
                await page.evaluate("""() => {
                    for (const a of document.querySelectorAll('a')) {
                        const oc = a.getAttribute('onclick') || '';
                        if (oc.includes('openReport') && !oc.includes("'Y'")) { a.click(); return; }
                    }
                }""")
            oz = await info.value
        except Exception as e:
            print(f"[!] OZ 창 실패: {str(e)[:80]}"); await ctx.close(); return
        await oz.wait_for_timeout(4000)

        try:
            await oz.screenshot(path=str(SHOT))
            print(f"[i] 스크린샷: {SHOT.name}")
        except Exception as e:
            print(f"[!] 스크린샷 실패: {str(e)[:60]}")

        with OUT.open("a", encoding="utf-8") as f:
            d = await deep_dump(oz, f)
            print(f"[i] 저장관련 전역객체: {list(d['globalObjs'])[:8]}")
            print(f"[i] 툴바 요소 {len(d['toolbar'])}개")

            # ── 0) JS API 직접 호출 시도 (버튼 클릭보다 안정적) ──
            # OZ HTML5 뷰어의 export/save API 후보들을 순서대로 호출해 다운로드 유발 확인.
            js_ok = False
            js_target = DL / "oz_js.bin"
            probe = await oz.evaluate("""() => {
                // 뷰어 인스턴스 후보와 그 export 계열 메서드 수집
                const res = {cands: []};
                const push = (path, obj) => {
                    const ms = [];
                    for (const m in obj) {
                        try { if (typeof obj[m] === 'function'
                            && /export|save|pdf|down/i.test(m)) ms.push(m); } catch(e) {}
                    }
                    if (ms.length) res.cands.push({path, methods: ms.slice(0, 25)});
                };
                for (const p in window) {
                    try {
                        const v = window[p];
                        if (v && typeof v === 'object' && p.length < 40) push(p, v);
                        else if (typeof v === 'function' && /oz|viewer/i.test(p)) {
                            res.cands.push({path: p + '()', methods: ['<function>']});
                        }
                    } catch(e) {}
                }
                return res;
            }""")
            f.write(f"\n[JS API 후보] {probe}\n")
            print(f"[i] JS API 후보: {[c['path'] for c in probe.get('cands', [])][:10]}")

            for expr, tag in [
                ("window.saveAs && typeof OZViewer!=='undefined' "
                 "&& OZViewer.Export && OZViewer.Export('pdf')", "OZViewer.Export"),
                ("typeof OZViewer!=='undefined' && OZViewer.SaveAsPDF && OZViewer.SaveAsPDF()",
                 "OZViewer.SaveAsPDF"),
                ("typeof _OZCPDFDocCmd==='function' && _OZCPDFDocCmd()", "_OZCPDFDocCmd"),
            ]:
                try:
                    async with oz.expect_download(timeout=8000) as dlj:
                        r = await oz.evaluate(f"() => {{ try {{ return String({expr}); }}"
                                              f" catch(e) {{ return 'ERR ' + e.message; }} }}")
                        print(f"    [{tag}] js결과: {str(r)[:60]}")
                    dj = await dlj.value
                    await dj.save_as(str(js_target))
                    msg = (f"[JS {tag} 다운로드 OK] suggested={dj.suggested_filename} / "
                           f"{js_target.stat().st_size}b / {sig(js_target)}")
                    print(f"  {msg}"); f.write(msg + "\n"); js_ok = True
                    break
                except Exception:
                    f.write(f"[JS {tag}] 다운로드 없음\n")
            if js_ok:
                print("[v] JS 직접 호출로 저장 가능 — 버튼 클릭 불필요")
                print(f"\n[i] 결과: {OUT}")
                await asyncio.sleep(20)
                await ctx.close()
                return

            # 툴바 맨 왼쪽 = 저장(디스크) 아이콘 (스크린샷 확인). 그 옆이 인쇄라 절대 누르지 않음.
            tb = sorted(d["toolbar"], key=lambda t: (t["y"] // 20, t["x"]))
            if not tb:
                print("[!] 툴바 요소를 못 찾음"); return
            save_btn = tb[0]
            print(f"[i] 저장 아이콘 후보: <{save_btn['tag']}> cls={save_btn['cls']} "
                  f"@({save_btn['x']},{save_btn['y']})")
            f.write(f"\n[저장 아이콘 후보] {save_btn}\n")

            # 좌표 클릭(아이콘 중앙) — DOM 셀렉터가 불안정해 마우스 클릭이 확실
            cx = save_btn["x"] + save_btn["w"] / 2
            cy = save_btn["y"] + save_btn["h"] / 2
            target = DL / "oz_save.bin"
            got = False
            try:
                async with oz.expect_download(timeout=15000) as dl:
                    await oz.mouse.click(cx, cy)
                    print(f"[i] 저장 아이콘 클릭 @({cx:.0f},{cy:.0f}) — 즉시 다운로드 대기")
                d = await dl.value
                await d.save_as(str(target))
                msg = (f"[즉시 다운로드 OK] suggested={d.suggested_filename} / "
                       f"{target.stat().st_size}b / {sig(target)}")
                print(f"  {msg}"); f.write(msg + "\n"); got = True
            except Exception:
                print("[i] 즉시 다운로드 없음 — 저장 옵션 패널이 열렸는지 확인")

            if not got:
                await oz.wait_for_timeout(1500)
                try:
                    await oz.screenshot(path=str(ROOT / "oz_save_panel.png"))
                    print("[i] 패널 스크린샷: oz_save_panel.png")
                except Exception:
                    pass
                # 패널 DOM 덤프
                panel = await oz.evaluate("""() => {
                    const vis = el => { const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0; };
                    const sels = [], btns = [], inputs = [];
                    for (const s of document.querySelectorAll('select')) {
                        if (!vis(s)) continue;
                        sels.push({id: s.id, value: s.value,
                            options: [...s.options].map(o => o.value + '|' + o.text).slice(0, 15)});
                    }
                    for (const b of document.querySelectorAll('button, a, input[type=button]')) {
                        if (!vis(b)) continue;
                        const t = ((b.innerText || b.value || '') + '').trim().slice(0, 20);
                        if (t) btns.push({t, id: b.id, cls: (b.className||'').toString().slice(0,40)});
                    }
                    for (const i of document.querySelectorAll('input')) {
                        if (!vis(i)) continue;
                        inputs.push({id: i.id, type: i.type, value: (i.value||'').slice(0,25)});
                    }
                    return {sels, btns, inputs};
                }""")
                f.write(f"\n[저장 패널] {panel}\n")
                print(f"[i] 패널 select: {panel['sels']}")
                print(f"[i] 패널 버튼: {[b['t'] for b in panel['btns']][:12]}")
                # PDF 선택 후 확인/저장 클릭 시도
                try:
                    async with oz.expect_download(timeout=20000) as dl2:
                        r = await oz.evaluate("""() => {
                            for (const s of document.querySelectorAll('select')) {
                                const o = [...s.options].find(x => /pdf/i.test(x.value + x.text));
                                if (o) { s.value = o.value;
                                    s.dispatchEvent(new Event('change', {bubbles: true})); break; }
                            }
                            const vis = el => { const r = el.getBoundingClientRect();
                                return r.width > 0 && r.height > 0; };
                            for (const b of document.querySelectorAll('button, a, input[type=button]')) {
                                if (!vis(b)) continue;
                                const t = ((b.innerText || b.value || '') + '').trim();
                                if (t === '저장' || t === '확인' || t === 'OK') { b.click(); return 'clicked:' + t; }
                            }
                            return 'no-btn';
                        }""")
                        print(f"    js결과: {r}")
                    d2 = await dl2.value
                    await d2.save_as(str(target))
                    msg = (f"[패널 저장 OK] suggested={d2.suggested_filename} / "
                           f"{target.stat().st_size}b / {sig(target)}")
                    print(f"  {msg}"); f.write(msg + "\n")
                except Exception as e:
                    msg = f"[패널 저장 실패] {str(e)[:120]}"
                    print(f"  {msg}"); f.write(msg + "\n")

        print(f"\n[i] 결과: {OUT}")
        print("[i] 30초 후 종료")
        await asyncio.sleep(30)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
