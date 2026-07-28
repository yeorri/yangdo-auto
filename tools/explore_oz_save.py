"""위택스 OZ 뷰어에도 '다운로드 저장' 경로가 있는지 정찰.

홈택스(clipreport)는 pdfDownLoad()로 전환 완료. 위택스는 OZ Report 엔진(ozhJsonviewers.oz)
이라 API가 다름 — 저장/export 함수·버튼이 있는지 확인하고, 있으면 다운로드 가로채기 테스트.

실행:  python tools/explore_oz_save.py <성명>
결과:  oz_dump.txt + _dl_test/ (받은 파일 시그니처 판정)
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

OUT = ROOT / "oz_dump.txt"
DL = ROOT / "_dl_test"


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


async def dump_oz(oz, f):
    """OZ 뷰어의 저장/export 관련 전역 객체·함수·버튼 덤프."""
    for fi, fr in enumerate(oz.frames):
        try:
            d = await fr.evaluate("""() => {
                const out = {url: location.href.slice(0, 80), globals: [], objs: {}, btns: [], imgs: []};
                // 전역 함수 중 저장/내보내기 관련
                for (const p in window) {
                    try {
                        const v = window[p];
                        if (typeof v === 'function' && /save|export|down|pdf|print/i.test(p))
                            out.globals.push(p);
                        // OZ 뷰어 객체 후보
                        else if (v && typeof v === 'object'
                                 && /viewer|oz|report/i.test(p) && p.length < 30) {
                            const ms = [];
                            for (const m in v) {
                                try { if (typeof v[m] === 'function'
                                    && /save|export|down|pdf|print/i.test(m)) ms.push(m); } catch(e) {}
                            }
                            if (ms.length) out.objs[p] = ms.slice(0, 40);
                        }
                    } catch(e) {}
                }
                const vis = el => { const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0; };
                for (const el of document.querySelectorAll('button, a, input[type=button], div[onclick]')) {
                    if (!vis(el)) continue;
                    const t = ((el.innerText || el.value || el.title || '') + '').trim().slice(0, 20);
                    const oc = (el.getAttribute('onclick') || '').slice(0, 70);
                    if (t || oc) out.btns.push({t, id: el.id,
                        cls: (el.className || '').toString().slice(0, 40), oc});
                }
                for (const el of document.querySelectorAll('img')) {
                    if (!vis(el)) continue;
                    out.imgs.push({src: (el.src || '').split('/').pop().slice(0, 40),
                                   alt: el.alt || '', title: el.title || '', id: el.id});
                }
                return out;
            }""")
        except Exception:
            continue
        if not (d["globals"] or d["objs"] or d["btns"] or d["imgs"]):
            continue
        f.write(f"\n--- frame[{fi}] {d['url']}\n")
        f.write(f"[전역 저장관련 함수] {d['globals'][:40]}\n")
        for k, v in d["objs"].items():
            f.write(f"[객체 {k}] {v}\n")
        f.write("[보이는 버튼]\n")
        for b in d["btns"][:30]:
            f.write(f"  '{b['t']}' id={b['id']} cls={b['cls']} onclick={b['oc']}\n")
        f.write("[아이콘]\n")
        for i in d["imgs"][:25]:
            f.write(f"  {i['src']} alt='{i['alt']}' title='{i['title']}' id={i['id']}\n")
    f.flush()


async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not name:
        print("사용법: python tools/explore_oz_save.py <성명>")
        return
    OUT.write_text("위택스 OZ 저장 정찰\n", encoding="utf-8")
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

        # 신고서(openReport, 'Y' 없음) 창 열기
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
            print(f"[!] OZ 창 열기 실패: {str(e)[:80]}"); await ctx.close(); return
        await oz.wait_for_timeout(3500)
        print(f"[i] OZ 창: {oz.url[:70]}")

        with OUT.open("a", encoding="utf-8") as f:
            f.write(f"OZ url: {oz.url[:100]}\n")
            await dump_oz(oz, f)

            # 저장/내보내기 버튼이 있으면 클릭해 다운로드 시도
            print("[i] 저장/내보내기 버튼 탐색 후 클릭 시도")
            target = DL / "oz_test.bin"
            try:
                async with oz.expect_download(timeout=20000) as dl:
                    r = await oz.evaluate("""() => {
                        const vis = el => { const b = el.getBoundingClientRect();
                            return b.width > 0 && b.height > 0; };
                        for (const el of document.querySelectorAll(
                                'button, a, input[type=button], img, div[onclick]')) {
                            if (!vis(el)) continue;
                            const s = ((el.innerText || '') + (el.value || '') + (el.title || '')
                                     + (el.alt || '') + (el.id || '') + (el.className || '')).toLowerCase();
                            if (/save|저장|export|내보내|down|다운/.test(s)) {
                                el.click(); return 'clicked:' + s.slice(0, 50);
                            }
                        }
                        return 'no-button';
                    }""")
                    print(f"    js결과: {r}")
                d = await dl.value
                await d.save_as(str(target))
                msg = f"[OZ 다운로드 OK] suggested={d.suggested_filename} / {target.stat().st_size}b / {sig(target)}"
                print(f"  {msg}"); f.write(msg + "\n")
            except Exception as e:
                msg = f"[OZ 다운로드 실패] {str(e)[:140]}"
                print(f"  {msg}"); f.write(msg + "\n")

        print(f"\n[i] 결과: {OUT}")
        print("[i] 25초 후 종료 (화면에서 OZ 뷰어 확인 가능)")
        await asyncio.sleep(25)
        await ctx.close()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
