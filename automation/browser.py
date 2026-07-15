"""브라우저 토대 — Playwright 영구 프로필 Chromium 실행 + 로그인 대기.

이 모듈은 incometax_printing(검증된 종소세 프로젝트)의 launch/setup_context/
find_form/wait_for_form 패턴을 거의 그대로 가져온 것이다. 홈택스 로그인이 까다로워
봇이 로그인을 시도하면 안 되므로, 사용자가 직접 로그인 + 메뉴 진입하도록 두고
작업 폼이 뜨는지 polling으로 감지한다.

참고: reference/AUTOMATION_PATTERNS.md 1절·2절
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import BrowserContext, Page


def app_data_dir() -> Path:
    """쓰기 가능한 앱 데이터 폴더.

    - 개발(소스 실행): 프로젝트 폴더(기존과 동일).
    - 배포(frozen exe): %LOCALAPPDATA%\\YangdoAuto (exe 내부는 쓰기 불가/임시이므로).
    """
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "YangdoAuto"
    else:
        base = Path(__file__).resolve().parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base


# 로그인 세션 캐시 폴더. 첫 실행에서 로그인하면 이후엔 자동 유지된다.
PROFILE_DIR = app_data_dir() / ".profile"

HOMETAX_URL = "https://www.hometax.go.kr"
WETAX_URL = "https://www.wetax.go.kr"


async def launch(pw) -> BrowserContext:
    """영구 프로필로 Chromium 실행. 사용자가 로그인한 세션이 .profile 에 보존된다.

    --kiosk-printing: 인쇄 다이얼로그 없이 바로 기본 프린터로 출력
    (기본 프린터를 'Microsoft Print to PDF'로 박아두면 접수증 PDF 자동 저장).
    호출 전에 ensure_pdf_sticky_settings()를 먼저 실행해 둘 것.
    """
    PROFILE_DIR.mkdir(exist_ok=True)
    return await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        no_viewport=True,
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",  # 봇 감지 회피
            "--kiosk-printing",
        ],
        accept_downloads=True,
    )


def ensure_sticky_printer(printer: str, profile_dir: Path = PROFILE_DIR) -> bool:
    """Chrome Preferences의 인쇄 대상(sticky)을 printer로 박는다.

    --kiosk-printing은 OS 기본 프린터가 아니라 이 sticky 값으로 인쇄한다 →
    PDF 모드가 남긴 'Microsoft Print to PDF'가 출력(인쇄) 모드에서도 그대로 쓰여
    종이 대신 저장 다이얼로그가 뜨는 버그를 막으려면, 모드에 맞는 대상을
    launch 전에 항상 명시해야 한다.
    ⚠ Chromium 실행 중에 고치면 종료 시 덮어써짐 → 반드시 launch 전에 호출.
    reference/AUTOMATION_PATTERNS.md 3절.
    """
    prefs_path = profile_dir / "Default" / "Preferences"
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8")) if prefs_path.exists() else {}
    except Exception:
        prefs = {}
    sticky = {
        "version": 2,
        "recentDestinations": [{
            "id": printer, "origin": "local", "account": "",
            "capabilities": "", "displayName": printer,
            "extensionId": "", "extensionName": "", "icon": "",
        }],
        "selectedDestinationId": printer,
    }
    prefs.setdefault("printing", {}).setdefault("print_preview_sticky_settings", {})
    prefs["printing"]["print_preview_sticky_settings"]["appState"] = json.dumps(sticky)
    try:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def ensure_pdf_sticky_settings(profile_dir: Path = PROFILE_DIR) -> bool:
    """PDF 저장 모드용 — 인쇄 대상을 'Microsoft Print to PDF'로."""
    return ensure_sticky_printer("Microsoft Print to PDF", profile_dir)


def default_printer_name() -> str:
    """Windows 기본 프린터 이름. 실패 시 ''."""
    try:
        import win32print
        return win32print.GetDefaultPrinter() or ""
    except Exception:
        return ""


def attach_dialog_handler(page: Page, msgs: list) -> None:
    """JS alert/confirm 자동 수락 + 메시지 기록.

    기록된 메시지로 '거주자/비거주자', '이미 검증된 자료' 등 분기를 검출할 수 있다.
    """
    async def on_dialog(d):
        msgs.append(d.message)
        try:
            await d.accept()
        except Exception:
            pass

    # Playwright Python은 async 이벤트 핸들러를 그대로 await 해 준다.
    page.on("dialog", on_dialog)


SITE_URLS = {"홈택스": HOMETAX_URL, "위택스": WETAX_URL}


def find_page(ctx: BrowserContext, url_substr: str):
    """ctx의 열린 page 중 url에 substr가 든 첫 page. 없으면 None."""
    for p in ctx.pages:
        if url_substr in (p.url or ""):
            return p
    return None


async def setup_context(ctx: BrowserContext, dialog_msgs: list) -> None:
    """모든 page에 dialog 핸들러 부착. (홈페이지 이동은 open_homepages가 담당)"""
    for p in ctx.pages:
        attach_dialog_handler(p, dialog_msgs)
    ctx.on("page", lambda p: attach_dialog_handler(p, dialog_msgs))


async def open_homepages(ctx: BrowserContext, sites: list[str], log=print) -> dict[str, Page]:
    """필요한 사이트(홈택스/위택스) 홈페이지만 각각 탭으로 연다.

    첫 사이트는 빈 첫 페이지를 재사용, 나머지는 새 탭. 반환: {사이트명: Page}.
    """
    pages: dict[str, Page] = {}
    for i, site in enumerate(sites):
        url = SITE_URLS.get(site)
        if not url:
            continue
        if i == 0 and ctx.pages:
            page = ctx.pages[0]
        else:
            page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            log(f"[i] {site} 홈페이지 열림")
        except Exception as e:
            log(f"[!] {site} 이동 실패: {str(e)[:80]}")
        pages[site] = page
    # 마지막에 연 사이트(보통 위택스)를 맨 앞으로 — 사용자가 그 사이트부터 로그인하도록 유도.
    if sites:
        last = pages.get(sites[-1])
        if last is not None:
            try:
                await last.bring_to_front()
            except Exception:
                pass
    return pages


async def find_visible(ctx: BrowserContext, selector: str):
    """모든 page/frame 순회해서 selector가 보이는 (page, frame)을 반환.

    frame이 detach되면 호출 자체가 throw하므로 try/except 필수.
    """
    for page in ctx.pages:
        for frame in page.frames:
            try:
                loc = frame.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    return page, frame
            except Exception:
                continue
    return None, None


async def wait_for(ctx: BrowserContext, selector: str, timeout_sec: int, log=print):
    """selector가 보일 때까지 1초 polling. (page, frame) 또는 (None, None)."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_sec
    while loop.time() < deadline:
        page, scope = await find_visible(ctx, selector)
        if scope is not None:
            return page, scope
        await asyncio.sleep(1.0)
    return None, None
