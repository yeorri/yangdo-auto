"""공용 유틸 — 주민번호 파싱, WebSquare 다층 클릭 등.

reference/AUTOMATION_PATTERNS.md 참고. parse_rrn 등은 종소세 프로젝트에서 검증됨.
"""
from __future__ import annotations

import asyncio
import re


def normalize_rrn(s: str) -> str:
    """하이픈/공백 제거한 숫자만. '000000-0000000' → '0000000000000'."""
    return re.sub(r"\D", "", s or "")


def parse_rrn(s: str) -> tuple[str, str]:
    """주민번호를 (앞6, 뒤7)로. 13자리가 아니면 ValueError."""
    digits = normalize_rrn(s)
    if len(digits) != 13:
        raise ValueError(f"주민번호 13자리가 아님: {s!r}")
    return digits[:6], digits[6:]


async def websquare_click(scope, comp_id: str, log=print) -> bool:
    """홈택스 WebSquare 컴포넌트 클릭 — 다층 전략.

    일반 Playwright click이 안 먹는 경우가 많아 아래 순서로 시도:
      1) WebSquare API: getComponentById(id).trigger('onclick')
      2) Playwright 일반 click (id로)
      3) JS dispatchEvent

    하나라도 성공하면 True.
    """
    # 1) WebSquare API 직접 호출
    try:
        ok = await scope.evaluate(
            """(id) => {
                if (window.WebSquare && WebSquare.util) {
                    const c = WebSquare.util.getComponentById(id);
                    if (c && c.trigger) { c.trigger('onclick'); return true; }
                }
                return false;
            }""",
            comp_id,
        )
        if ok:
            return True
    except Exception as e:
        log(f"[!] websquare api click 실패({comp_id}): {str(e)[:80]}")

    # 2) 일반 click
    try:
        loc = scope.locator(f"#{comp_id}").first
        if await loc.count() > 0:
            await loc.click(timeout=5000)
            return True
    except Exception as e:
        log(f"[!] 일반 click 실패({comp_id}): {str(e)[:80]}")

    # 3) JS dispatchEvent
    try:
        ok = await scope.evaluate(
            """(id) => {
                const el = document.getElementById(id);
                if (!el) return false;
                el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                return true;
            }""",
            comp_id,
        )
        return bool(ok)
    except Exception as e:
        log(f"[!] dispatchEvent click 실패({comp_id}): {str(e)[:80]}")

    return False


async def wait_grid_stable(scope, tbody_sel: str, idle_sec: float = 1.2,
                           timeout_sec: float = 20) -> int:
    """그리드 row 수가 idle_sec 동안 안 변하면 안정으로 보고 row 수 반환."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_sec
    last_count, last_change = -1, loop.time()
    while loop.time() < deadline:
        try:
            current = await scope.locator(f"{tbody_sel} tr").count()
        except Exception:
            current = last_count
        if current != last_count:
            last_count, last_change = current, loop.time()
        elif loop.time() - last_change >= idle_sec:
            return max(last_count, 0)
        await asyncio.sleep(0.2)
    return max(last_count, 0)
