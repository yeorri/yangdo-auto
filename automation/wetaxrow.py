"""위택스 신고내역에서 '이 신고건의 줄'을 고른다.

위택스 목록에는 접수번호가 없다. 줄마다 보이는 것은(2026-11-18 라이브 확인):
    [N행, 납세자명, 신고일자, 관할자치단체, 금액, 진행상태, 납부기한, 납부여부, 출력물 보기, 신고구분]
최근 신고가 위에 온다. 예전엔 '이름이 들어간 첫 줄'을 골라서, 같은 사람 신고건이 둘이면
먼저 신고한 건의 납부서 자리에 나중 건의 납부서가 저장됐다.

고르는 순서(사용자와 정한 규칙):
  1) 이름 칸이 정확히 같은 줄 가운데 진행상태가 '신고완료'인 줄만 본다.
  2) 변환파일 이름에서 양도연월을 알면, 그 달 양도분의 지방세 납부기한(양도월+4개월 말일,
     휴일이면 며칠 밀림)에 해당하는 줄만 남긴다. 같은 달에 판 건은 납부기한이 같고,
     한 사람이 같은 달 양도분을 따로따로 신고할 일은 거의 없으므로 대부분 여기서 한 줄이 된다.
  3) 이번 실행에서 신고했으면 → 남은 줄 중 위에서 pick번째(내 신고 뒤에 같은 이름·같은 양도월로
     신고된 건수). 고른 줄의 신고일자가 오늘이 아니면 순서가 어긋난 것이므로 멈춘다.
     신고하지 않았으면(출력만) → 남은 줄이 하나일 때만 진행, 여럿이면 멈춘다.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

# 같은 이름 줄 목록. k = '출력물 보기' 링크들 가운데 몇 번째인지(클릭할 때 쓴다).
_ROWS_JS = r"""(name) => {
  const anchors = [...document.querySelectorAll('a')].filter(a =>
      (a.id || '').startsWith('ui-id') || (a.title || '').includes('출력') || (a.textContent || '').includes('출력물'));
  const out = [], seen = new Set();
  anchors.forEach((a, k) => {
    const tr = a.closest('tr');
    if (!tr || seen.has(tr)) return;
    const tds = [...tr.children].map(td => (td.innerText || '').replace(/\s+/g, ' ').trim());
    const exact = tds.includes(name);
    if (!exact && !(tr.innerText || '').includes(name)) return;
    seen.add(tr);
    const dates = (tr.innerText || '').match(/20\d\d-\d\d-\d\d/g) || [];
    out.push({k, exact, done: tds.includes('신고완료'),
              filed: dates[0] || '', due: dates.length > 1 ? dates[dates.length - 1] : '',
              amount: tds.find(t => /원$/.test(t)) || '',
              tip: a.getAttribute('data-tooltip-content') || ''});
  });
  return out;
}"""

_CLICK_JS = r"""(k) => {
  const anchors = [...document.querySelectorAll('a')].filter(a =>
      (a.id || '').startsWith('ui-id') || (a.title || '').includes('출력') || (a.textContent || '').includes('출력물'));
  if (!anchors[k]) return false;
  anchors[k].click();
  return true;
}"""


def due_window(trade_ym: str):
    """양도연월 'YYYYMM' → 지방세 납부기한이 들어올 범위(ISO 문자열 2개). 모르면 None.

    부동산 예정신고: 양도세 기한 = 양도월 말일부터 2개월, 지방세는 거기서 2개월 더.
    즉 양도월+4개월의 말일이고, 휴일이면 다음 평일로 밀린다(예: 9월 양도 → 1/31(일) → 2/1,
    10월 양도 → 2/28(일)·3/1(공휴일) → 3/2). 공휴일 달력을 두는 대신 말일부터 열흘을 본다.
    """
    if not (trade_ym and len(trade_ym) == 6 and trade_ym.isdigit()):
        return None
    y, m = int(trade_ym[:4]), int(trade_ym[4:])
    if not 1 <= m <= 12:
        return None
    y, m = y + (m + 3) // 12, (m + 3) % 12 + 1
    last = date(y, m, calendar.monthrange(y, m)[1])
    return last.isoformat(), (last + timedelta(days=10)).isoformat()


def _desc(r: dict) -> str:
    return f"신고일자 {r['filed'] or '?'} · {r['amount'] or '?'} · 납부기한 {r['due'] or '?'}"


def choose(rows: list, name: str, pick, trade_ym: str = "", today: str = ""):
    """줄 고르기(순수 함수 — 화면 없이 시험 가능). 반환: (고른 줄 | None, 설명 문구)."""
    today = today or date.today().isoformat()
    same = [r for r in rows if r.get("exact")] or list(rows)
    if not same:
        return None, f"'{name}' 신고건을 신고내역에서 찾지 못함"
    cand = [r for r in same if r.get("done")] or same
    note = ""
    win = due_window(trade_ym)
    if win:
        by_due = [r for r in cand if r.get("due") and win[0] <= r["due"] <= win[1]]
        if by_due:
            if len(by_due) < len(cand):
                note = f", 양도월 {trade_ym[:4]}-{trade_ym[4:]} 납부기한으로 {len(cand)}건 중 {len(by_due)}건"
            cand = by_due
    listing = " / ".join(_desc(r) for r in cand)
    if pick is None:        # 이번 실행에서 신고하지 않음
        if len(cand) == 1:
            return cand[0], f"{_desc(cand[0])}{note}"
        return None, (f"'{name}' 신고건이 {len(cand)}건이라 어느 건인지 알 수 없음 — {listing}. "
                      f"위택스에서 직접 출력하세요")
    if pick >= len(cand):
        return None, f"'{name}' 신고건이 {len(cand)}건뿐인데 위에서 {pick + 1}번째를 찾으려 함 — {listing}"
    r = cand[pick]
    if r.get("filed") != today:
        return None, (f"고른 줄의 신고일자({r.get('filed') or '?'})가 오늘({today})이 아님 — "
                      f"신고 순서와 화면 순서가 어긋났을 수 있어 멈춤. {listing}")
    where = f" (같은 이름 {len(cand)}건 중 위에서 {pick + 1}번째)" if len(cand) > 1 else ""
    return r, f"{_desc(r)}{where}{note}"


def same_due_memo(rows: list, name: str, row: dict) -> str:
    """고른 줄과 **납부기한이 같은** 같은 사람 신고건이 더 있으면 알림 문구(없으면 '').

    납부기한이 같다 = 같은 달 양도분이다. 같은 달 양도분이 따로따로 신고돼 있는 건 드문 일이라,
    대개 ①앞 신고를 지워야 하는데 남아 있거나(다시 신고한 경우) ②두 건을 합쳐 다시 신고해야
    하는 경우다. 프로그램은 신고 순서로 줄을 골라 그대로 진행하지만, 사람이 확인해야 한다.
    """
    if not row.get("due"):
        return ""
    same = [r for r in rows if r.get("exact")] or list(rows)
    same = [r for r in same if r.get("done")] or same
    twins = [r for r in same if r.get("due") == row["due"]]
    if len(twins) < 2:
        return ""
    return (f"'{name}' 신고건 중 납부기한이 같은({row['due']}) 건이 {len(twins)}건 있습니다 — "
            + " / ".join(_desc(r) for r in twins)
            + ". 같은 달 양도분이 따로 신고된 상태입니다. 앞 신고를 지워야 하는지, "
              "합산해서 다시 신고해야 하는지 확인하세요")


async def pick_and_expand(page, name: str, pick, trade_ym: str = "", log=print):
    """신고내역에서 이 신고건의 줄을 골라 '출력물 보기'를 누른다. 반환: 고른 줄(dict) | None.

    목록이 늦게 그려질 수 있어 같은 이름 줄이 보일 때까지 폴링한다(최대 ~10초).
    """
    rows: list = []
    for _ in range(25):
        try:
            rows = await page.evaluate(_ROWS_JS, name)
        except Exception:
            rows = []
        if rows:
            break
        await page.wait_for_timeout(400)
    row, msg = choose(rows, name, pick, trade_ym)
    if row is None:
        log(f"[!] (위택스) {msg}")
        return None
    log(f"[i] (위택스) {name} 신고건 선택: {msg}")
    memo = same_due_memo(rows, name, row)
    if memo:
        log(f"[!] (위택스) ⚠ 확인 필요 — {memo}")
    row["memo"] = memo
    try:
        ok = await page.evaluate(_CLICK_JS, row["k"])
    except Exception:
        ok = False
    if not ok:
        log(f"[!] (위택스) '{name}' 출력물 보기를 누르지 못함")
        return None
    await page.wait_for_timeout(1500)
    return row
