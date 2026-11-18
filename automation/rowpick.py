"""홈택스 조회 결과에서 '이 신고건의 줄'을 고른다 — 위치(첫 줄·마지막 버튼)로 고르지 않는다.

왜: 주민번호로 조회하면 같은 사람의 신고건이 여러 줄 뜰 수 있다(같은 달에 두 채를 판 경우,
조회 기간 안에 예전 신고가 있는 경우). 예전 코드는 단계마다 다른 가정으로 줄을 골랐다 —
접수증은 '첫 접수번호 링크', 납부서는 '화면의 마지막 [보기]', 부속서류는 '첫 [첨부하기]'.
줄이 하나일 땐 다 맞지만 둘이 되면 서로 다른 줄을 집는다(2026-11-18 정미희 건: 2번 신고의
납부서로 1번 신고 것이 저장되고, 부속서류는 1번 건의 [제출내역보기]를 보고 '이미 제출됨'으로 오판).

화면 구조(2026-11-18 라이브 확인, 신고내역 조회):
  한 신고건 = 표의 한 줄(tr). 접수번호 전체가 <a> 텍스트로 들어 있고, 같은 tr 안에
  접수일시와 [보기] 버튼 2개(앞=접수증, 뒤=납부서)가 있다. 최근 신고가 위.
→ 접수번호가 든 tr을 찾고, **그 tr 안에서만** 버튼을 찾는다.
  부속서류 조회 화면도 같은 방식(접수번호가 든 tr의 [첨부하기]/[제출내역보기]).

누를 요소에는 data-yd-pick 표시를 달고, 클릭은 Playwright가 한다(새 창이 열리는 클릭은
실제 클릭이어야 expect_page로 잡힌다).
"""
from __future__ import annotations

import re

RECEIPT_RE = re.compile(r"\d{3}-\d{4}-\d-\d{6,}")
PICK = '[data-yd-pick="1"]'

# 조회 결과의 줄 목록: [{receipt, when, labels}]  (화면에 보이는 순서 = 위에서부터)
_ROWS_JS = r"""() => {
  const re = /\d{3}-\d{4}-\d-\d{6,}/;
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const own = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const lab = el => ((el.innerText || el.value || '') + '').trim();
  const rows = [], seen = new Set();
  for (const el of document.querySelectorAll('a, nobr, span, td, div')) {
    const m = own(el).match(re);
    if (!m || !vis(el)) continue;
    const tr = el.closest('tr');
    if (!tr || seen.has(tr)) continue;
    seen.add(tr);
    const txt = (tr.innerText || '').replace(/\s+/g, ' ');
    rows.push({receipt: m[0],
               when: (txt.match(/20\d\d-\d\d-\d\d \d\d:\d\d:\d\d/) || [''])[0],
               labels: [...tr.querySelectorAll('a, button, input[type=button]')].filter(vis).map(lab)
                         .filter(t => t && t.length <= 8)});
  }
  return rows;
}"""

# 접수번호 줄 안의 요소에 표시를 단다. 반환: 'ok' | 'norow'(그 접수번호 줄 없음) | 'nobtn'(줄은 있는데 그 버튼 없음)
_MARK_JS = r"""(arg) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const own = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const lab = el => ((el.innerText || el.value || '') + '').trim();
  document.querySelectorAll('[data-yd-pick]').forEach(e => e.removeAttribute('data-yd-pick'));
  let cell = null;
  for (const el of document.querySelectorAll('a, nobr, span, td, div')) {
    if (vis(el) && own(el).includes(arg.receipt)) { cell = el; break; }
  }
  const tr = cell && cell.closest('tr');
  if (!tr) return 'norow';
  const btns = t => [...tr.querySelectorAll('a, button, input[type=button]')].filter(e => vis(e) && lab(e) === t);
  let target = null;
  if (arg.kind === 'receipt') target = cell;
  else if (arg.kind === 'napbu') {          // [보기] 2개 = 접수증·납부서. 1개뿐이면 납부서 없음(차손)
    const b = btns('보기'); target = b.length >= 2 ? b[b.length - 1] : null;
  } else target = btns(arg.kind)[0] || null;  // '첨부하기' / '제출내역보기'
  if (!target) return 'nobtn';
  target.setAttribute('data-yd-pick', '1');
  return 'ok';
}"""


async def rows(page) -> list:
    try:
        return await page.evaluate(_ROWS_JS)
    except Exception:
        return []


async def wait_rows(page, timeout: float = 8.0) -> list:
    """조회 결과 줄이 그려질 때까지 폴링(한 번만 보면 빈 표를 보고 오판한다)."""
    r: list = []
    for _ in range(int(timeout / 0.4)):
        r = await rows(page)
        if r:
            return r
        await page.wait_for_timeout(400)
    return r


async def resolve(page, receipt_no: str, filed_now: bool, log=print, screen: str = "신고내역") -> str:
    """이번에 다룰 신고건의 접수번호를 정한다. 정하지 못하면 '' — 호출측은 **멈춰야 한다**
    (다른 신고건의 서류를 뽑거나 다른 건의 부속서류를 지우는 것보다 멈추는 게 낫다).

      1) 접수번호를 알고 있으면(신고 직후 읽었거나 신고 기록에 있음) 그 줄. 없으면 멈춤.
      2) 줄이 하나면 그 줄.
      3) 이번 실행에서 방금 신고했으면 접수일시가 가장 늦은 줄.
      4) 그 밖(여러 줄인데 어느 건인지 모름)은 멈춤.
    """
    rs = await wait_rows(page)
    if not rs:
        log(f"[!] (홈택스) {screen} 조회 결과에 신고건이 없음")
        return ""
    have = [r["receipt"] for r in rs]
    if receipt_no:
        if receipt_no in have:
            if len(rs) > 1:
                log(f"[i] (홈택스) 신고건 {len(rs)}건 중 접수번호 {receipt_no} 줄을 사용")
            return receipt_no
        log(f"[!] (홈택스) 접수번호 {receipt_no} 줄이 {screen} 조회 결과에 없음 (조회된 접수번호: {', '.join(have)})")
        return ""
    if len(rs) == 1:
        return have[0]
    if filed_now and all(r["when"] for r in rs):
        newest = max(rs, key=lambda r: r["when"])
        log(f"[i] (홈택스) 신고건 {len(rs)}건 중 방금 신고한 건(접수일시 {newest['when']}) "
            f"접수번호 {newest['receipt']} 줄을 사용")
        return newest["receipt"]
    desc = ", ".join(f"{r['receipt']}({r['when'] or '접수일시 미상'})" for r in rs)
    log(f"[!] (홈택스) 이 주민번호로 신고건이 {len(rs)}건 조회되어 어느 건인지 알 수 없음 — {desc}")
    log("[i] (홈택스) 이 프로그램으로 신고한 건이면 그때 쓴 홈택스 변환파일을 지정하면 접수번호를 찾아냅니다. "
        "아니면 홈택스에서 직접 처리하세요.")
    return ""


async def mark(page, receipt_no: str, kind: str) -> str:
    """접수번호 줄의 요소에 표시를 단다(kind: 'receipt' | 'napbu' | '첨부하기' | '제출내역보기').
    반환 'ok'면 page.locator(PICK)로 클릭한다."""
    try:
        return await page.evaluate(_MARK_JS, {"receipt": receipt_no, "kind": kind})
    except Exception:
        return "norow"


async def labels_of(page, receipt_no: str) -> list:
    """그 접수번호 줄에 보이는 버튼 글자들(없으면 [])."""
    for r in await rows(page):
        if r["receipt"] == receipt_no:
            return r["labels"]
    return []


async def read_from_modals(page) -> str:
    """보이는 모달(.w2window) 글에서 접수번호를 읽는다 — 신고 직후 접수증 화면용. 없으면 ''."""
    for frame in page.frames:
        try:
            txt = await frame.evaluate(r"""() => [...document.querySelectorAll('.w2window')]
                .filter(w => { const r = w.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
                .map(w => w.innerText || '').join('\n')""")
        except Exception:
            continue
        m = RECEIPT_RE.search(txt or "")
        if m:
            return m.group(0)
    return ""
