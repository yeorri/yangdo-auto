# 홈택스 자동화 패턴 모음

종합소득세 신고도움서비스 자동 인쇄(`hometax-auto/`) 만들면서 쓴 패턴 정리.
양도세 신고 자동화 등 후속 홈택스 자동화 만들 때 참고용.

홈택스는 **WebSquare 프레임워크 + clipreport(인쇄 모듈) + 다중 iframe**으로 돼 있어서 일반 셀렉터만으로 안 풀리는 경우가 많음. 아래 패턴들은 거의 그대로 양도세에도 적용 가능.

---

## 0. 기술 스택 한눈에

| 영역 | 선택 | 이유 |
|---|---|---|
| 브라우저 자동화 | Playwright (Python async) | CDP attach + 영구 프로필 + iframe/popup 처리가 셀레늄보다 깔끔 |
| 로그인 처리 | 사용자가 직접 로그인 | 공인인증서/간편인증/생체인증을 코드로 풀려고 하지 말 것 |
| 메뉴 도달 | 사용자가 메뉴까지 직접 클릭 → 폼이 뜨면 자동 감지 | 홈택스 메뉴는 동적 메뉴라 자동 클릭이 깨지기 쉬움 |
| 인쇄 | Chromium `--kiosk-printing` + sticky settings | 인쇄 다이얼로그 안 띄우고 바로 출력 |
| PDF 저장 | OS 인쇄 다이얼로그 → pywin32로 파일명 자동 입력 | "Save as PDF"를 chromium default printer로 박아두고 다이얼로그만 자동 |
| GUI | Tkinter + queue 패턴 | 표준 라이브러리, PyInstaller 친화적 |
| 패키징 | PyInstaller onedir + Chromium 번들 | onefile은 chromium 풀 때 매번 압축 풀어서 느림 |
| 업데이트 | GitHub raw `version.json` + 알림만 | 자동 설치는 복잡도 대비 가치 낮음 |

---

## 1. Playwright — 영구 프로필 + CDP attach 흐름

홈택스는 로그인이 까다로워서 **봇이 로그인을 시도하면 안 됨**. 대신:

1. Chromium을 사용자 프로필로 띄움 (`launch_persistent_context`)
2. 사용자가 직접 로그인 + 메뉴 클릭 → 작업 페이지 도달
3. 우리 코드는 작업 페이지의 폼이 뜨는지 polling으로 감지
4. 폼 잡히면 그때부터 자동화 시작

### 핵심 코드

```python
from playwright.async_api import async_playwright

PROFILE_DIR = Path.home() / ".hometax_profile"   # 로그인 캐시 유지용
WAIT_FORM_TIMEOUT_SEC = 600                       # 사용자가 로그인+메뉴까지 10분 줌

async def launch(pw):
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",  # 봇 감지 회피
            "--kiosk-printing",   # 인쇄 다이얼로그 안 뜸 (3절 참고)
        ],
        viewport=None,            # 창 크기 자유롭게
        accept_downloads=True,
    )
    return ctx

async def setup_context(ctx, dialog_msgs: list):
    """alert/confirm 자동 수락 + 메시지 기록."""
    async def on_dialog(d):
        dialog_msgs.append(d.message)
        try:
            await d.accept()
        except Exception:
            pass
    for page in ctx.pages:
        page.on("dialog", on_dialog)
    ctx.on("page", lambda p: p.on("dialog", on_dialog))
```

### 폼 감지 — polling

```python
async def find_form(ctx):
    """모든 page/frame 순회해서 작업 폼(주민번호 입력칸 등)이 보이는지."""
    for page in ctx.pages:
        for frame in page.frames:
            try:
                front = frame.locator(RRN_FRONT_SEL).first
                if await front.count() > 0 and await front.is_visible():
                    return page, frame
            except Exception:
                continue
    return None, None

async def wait_for_form(ctx, timeout_sec: int):
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        page, scope = await find_form(ctx)
        if scope is not None:
            return page, scope
        await asyncio.sleep(1.0)
    return None, None
```

**노하우**:
- `frame.locator(sel).first.is_visible()` 호출 자체가 frame이 detach되면 throw → try/except 필수
- 1초 polling이 적당. 0.3초로 줄이면 CPU 튀고 사용자도 안 좋아함
- 사용자 안내 메시지 ("로그인 + 메뉴 클릭 후 자동 시작") 반드시 띄울 것

---

## 2. WebSquare iframe / 동적 메뉴 진입

홈택스 모든 작업 페이지는 iframe 안에 들어 있고, 메뉴는 자바스크립트로 동적 생성. 한 페이지 안에서 메뉴 → 서브메뉴 → 작업 폼까지 가는 동안 iframe이 여러 번 갈아끼워짐.

### 안 풀리는 것
- top page의 메뉴 라벨로 직접 클릭 (`page.click("text=종합소득세")`)
- 새 iframe 들어가자마자 selector 호출 — 아직 자식 frame이 만들어지지 않음

### 풀리는 패턴

```python
async def click_menu_path(page, *labels):
    """홈택스 좌측 메뉴를 순서대로 클릭. 라벨 텍스트가 visible 될 때까지 wait."""
    for label in labels:
        loc = page.locator(f"text={label}").first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.click()
        await asyncio.sleep(0.8)   # 메뉴 펼침 애니메이션
```

**노하우**:
- 메뉴 라벨이 두 군데 (사이드바 + breadcrumb)에 있는 경우 많음 → `.first` 항상 붙이기
- `text=` 부분일치 매칭이 위험하면 `text="정확한 라벨"` 완전일치로
- 메뉴 클릭은 사용자에게 맡기는 게 가장 안전 — "메뉴까지 도달하시면 자동 시작합니다" 안내

---

## 3. Chromium 자동 인쇄 (`--kiosk-printing` + sticky settings)

`--kiosk-printing` 옵션 주면 `Ctrl+P` 또는 `window.print()`가 다이얼로그 없이 바로 기본 프린터로 출력.
**기본 프린터를 "Microsoft Print to PDF"로 박아두면 → 다이얼로그 한 번만 뜸 (파일명 입력)**, 그 외엔 즉시 인쇄.

### Chrome 기본 프린터 sticky 설정

```python
import json

def _ensure_pdf_sticky_settings(profile_dir: Path, save_dir: Path):
    """Chrome Preferences 파일에 PDF 프린터를 default로 박음."""
    prefs_path = profile_dir / "Default" / "Preferences"
    prefs = json.loads(prefs_path.read_text(encoding="utf-8")) if prefs_path.exists() else {}
    prefs.setdefault("printing", {}).setdefault("print_preview_sticky_settings", {})
    sticky = {
        "version": 2,
        "recentDestinations": [{
            "id": "Microsoft Print to PDF",
            "origin": "local",
            "account": "",
            "capabilities": "",
            "displayName": "Microsoft Print to PDF",
            "extensionId": "",
            "extensionName": "",
            "icon": "",
        }],
        "selectedDestinationId": "Microsoft Print to PDF",
    }
    prefs["printing"]["print_preview_sticky_settings"]["appState"] = json.dumps(sticky)
    prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
```

**중요**:
- Chrome이 실행 중일 때 Preferences를 수정하면 종료 시 덮어써짐 → **먼저 Chromium 종료 → prefs 수정 → 다시 launch**
- 일반 인쇄 모드로 돌릴 땐 sticky settings를 지워야 함 (`_clear_pdf_sticky_settings`)

### 인쇄 트리거 (홈택스 WebSquare 한정)

홈택스 인쇄 버튼은 `clipreport` 모듈을 새 창으로 띄움. 새 창 안의 인쇄 함수를 JS로 직접 호출:

```python
async def trigger_print_in_clipreport(popup):
    # 1) 데이터 로드 완료까지 대기 (progress hidden 또는 totalCount > 0)
    await popup.wait_for_function("""() => {
        const totalEl = document.querySelector('[id^="re_totalCountNumber"]');
        const progEl = document.querySelector('[id^="re_progressImg"]');
        const m = totalEl && (totalEl.value || '').match(/\\/\\s*(\\d+)/);
        const totalLoaded = !!(m && parseInt(m[1]) > 0);
        const progHidden = progEl && getComputedStyle(progEl).display === 'none';
        return totalLoaded || progHidden;
    }""", timeout=180000)

    # 2) printWindowView() → 인쇄 layer 활성화
    key = await popup.evaluate("""() => {
        const map = window.m_reportHashMap;
        const k = Object.keys(map)[0];
        map[k].printWindowView();
        return k;
    }""")

    # 3) mRe_printExportInfo() → 실제 인쇄 명령
    await popup.wait_for_timeout(800)
    await popup.evaluate(f"window.m_reportHashMap['{key}'].mRe_printExportInfo()")
```

---

## 4. ⚠ Race condition — modal-not-ready 패턴

WebSquare의 가장 큰 함정. **모달/팝업이 시각적으로는 떴어도 내부 hashMap/element는 아직 미준비**인 상태가 있음. 그 순간 evaluate 호출하면:

```
Page.evaluate: TypeError: Cannot read properties of undefined (reading 'check3Dom')
```

이런 식의 에러가 뜸. 32명 처리하면 한두 명에서 재현, 100명이면 더.

### 해결 — JS 안에서 존재 체크 + retry

```python
# 좋은 패턴: 안전 체크를 JS evaluate 안으로 밀어넣음
print_ok = False
for attempt in range(3):
    await popup.wait_for_timeout(800 if attempt == 0 else 1500)
    try:
        state = await popup.evaluate(f"""() => {{
            const map = window.m_reportHashMap;
            if (!map) return 'no_map';
            const r = map['{key}'];
            if (!r) return 'no_entry';
            if (typeof r.mRe_printExportInfo !== 'function') return 'no_fn';
            r.mRe_printExportInfo();
            return 'ok';
        }}""")
        if state == 'ok':
            print_ok = True
            break
        log(f"[!] 미준비 상태: {state}, attempt {attempt+1}")
    except Exception as e:
        log(f"[!] evaluate 실패 (attempt {attempt+1}): {str(e)[:120]}")
```

### Per-row try/except + popup 정리 보장

한 행이 throw하면 popup이 열린 채 남아서 **다음 행 click이 30초 timeout** 나는 cascade가 자주 발생. `finally`에서 popup 무조건 닫기:

```python
popup = None
try:
    async with ctx.expect_page(timeout=15000) as info:
        await cells.nth(i).click()
    popup = await info.value

    try:
        ok_row = await _do_print(popup)
    except Exception as e:
        log(f"[!] 처리 에러: {e}")
        ok_row = False

    if ok_row:
        printed += 1
    else:
        notes.append(f"행 {i+1} 인쇄 실패")
finally:
    if popup and not popup.is_closed():
        try: await popup.close()
        except Exception: pass
```

**핵심**: 한 행 에러가 다음 행으로 전파되지 않게 격리. 노이즈는 reason에 기록해서 결과 엑셀에서 확인.

---

## 5. 다이얼로그 / 팝업 / 그리드 안정화

### 5-1. JS dialog (alert/confirm)
```python
async def on_dialog(d):
    dialog_msgs.append(d.message)  # "기장수임이 아닙니다" 같은 메시지 캡처
    await d.accept()
page.on("dialog", on_dialog)
```

이 메시지로 **"수임 안된 사람"** 같은 카테고리를 검출 가능:
```python
joined = " ".join(dialog_msgs)
if any(k in joined for k in ["기장수임", "신고대리", "조회할 수 없"]):
    return {"status": "수임아님", ...}
```

### 5-2. 새 창 popup
```python
async with ctx.expect_page(timeout=15000) as info:
    await some_button.click()
popup = await info.value
```

이 패턴은 click이 새 창을 만들 때마다 항상 사용. timeout 안 잡히면 popup 미생성 = 클릭이 다른 동작이었거나 차단됨.

### 5-3. 그리드 로딩 안정화 (idle detection)
홈택스 그리드는 데이터가 흘러들어오는 동안 row 수가 계속 변함. **N초 동안 안 변하면 안정**으로 간주:

```python
async def wait_grid_stable(scope, tbody_sel: str, idle_sec=1.2, timeout_sec=20):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_sec
    last_count = -1
    last_change = loop.time()
    while loop.time() < deadline:
        current = await count_rows(scope, tbody_sel)
        if current != last_count:
            last_count = current
            last_change = loop.time()
        elif loop.time() - last_change >= idle_sec:
            return max(last_count, 0)
        await asyncio.sleep(0.2)
    return max(last_count, 0)
```

### 5-4. 인쇄 큐 백프레셔
연속 30+ 건 인쇄하면 Windows 인쇄 큐 폭주. spooler 큐 수 보고 임계치 넘으면 대기:

```python
import subprocess

def get_print_queue_count() -> int:
    """PowerShell로 인쇄 큐 작업 수 카운트."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-PrintJob -ComputerName . -ErrorAction SilentlyContinue | Measure-Object).Count"],
            text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,   # cmd 검은 창 안 뜸
        ).strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return 0

async def wait_print_queue_below(limit=10, log=print):
    while get_print_queue_count() >= limit:
        log("[i] 인쇄 큐 대기 중...")
        await asyncio.sleep(2.0)
```

---

## 6. PDF 저장 — OS 다이얼로그 자동 채우기 (pywin32)

Chrome의 "Microsoft Print to PDF"로 출력하면 **"다른 이름으로 저장"** 다이얼로그가 뜸. 이걸 보이지 않게 잡아서 파일명 입력하고 OK 클릭:

```python
import re
import time
from pathlib import Path
from pywinauto import findwindows, Application
import win32gui, win32con

# 한국어 Windows: "다른 이름으로 프린터 출력 저장" 또는 "다음 이름으로 ..."
SAVE_DIALOG_TITLE_RE = r"다(른|음) 이름으로.*저장"
WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
IDOK = 1

def fill_and_save(target_path: Path, timeout_sec=30.0, log=print) -> tuple[bool, str]:
    """다이얼로그 잡아서 파일명 set + OK 클릭. 파일 생성까지 확인."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    start_ts = time.time()
    deadline = start_ts + timeout_sec

    # 1) 다이얼로그 등장 대기
    dlg_handle = None
    while time.time() < deadline:
        handles = findwindows.find_windows(title_re=SAVE_DIALOG_TITLE_RE)
        if handles:
            dlg_handle = handles[0]
            break
        time.sleep(0.3)
    if not dlg_handle:
        return False, "다이얼로그 미등장"

    # 2) Edit 컨트롤 찾기 (ComboBoxEx32 > ComboBox > Edit 트리 깊이 탐색)
    app = Application(backend="win32").connect(handle=dlg_handle)
    dlg = app.window(handle=dlg_handle)
    edit = None
    try:
        combo_ex = dlg.child_window(class_name="ComboBoxEx32").wrapper_object()
        combo = combo_ex.child_window(class_name="ComboBox").wrapper_object()
        edit = combo.child_window(class_name="Edit").wrapper_object()
    except Exception:
        # fallback: 다이얼로그 직속 Edit
        try:
            edit = dlg.child_window(class_name="Edit").wrapper_object()
        except Exception:
            pass

    # 3) WM_SETTEXT로 파일명 set
    if edit:
        win32gui.SendMessageTimeout(
            edit.handle, WM_SETTEXT, 0, str(target_path),
            win32con.SMTO_NORMAL, 1000,
        )
        time.sleep(0.3)

    # 4) IDOK 메시지로 저장 (BM_CLICK도 가능)
    win32gui.SendMessage(dlg_handle, WM_COMMAND, IDOK, 0)

    # 5) 덮어쓰기 다이얼로그 처리 ("이미 있음. 바꿀까요?")
    time.sleep(0.5)
    confirm_handles = findwindows.find_windows(title_re=r".*확인.*")
    for h in confirm_handles:
        try:
            confirm = Application(backend="win32").connect(handle=h).window(handle=h)
            yes_btn = confirm.child_window(title="예(&Y)").wrapper_object()
            yes_btn.click()
            log("덮어쓰기 다이얼로그 '예' 자동 클릭")
            break
        except Exception:
            continue

    # 6) ⚠ 파일 생성 검증 (mtime) — false-positive 차단
    end = time.time() + 10
    while time.time() < end:
        if target_path.exists() and target_path.stat().st_mtime >= start_ts - 1:
            return True, ""
        time.sleep(0.2)
    return False, "OK 보냈으나 파일이 생성되지 않음"
```

### 핵심 함정들

1. **다이얼로그 제목 — Windows 버전마다 미묘하게 다름**
   - "다른 이름으로 저장" vs "다른 이름으로 프린터 출력 저장" vs "다음 이름으로..."
   - 정규식으로 느슨하게: `r"다(른|음) 이름으로.*저장"`

2. **Edit 컨트롤이 ComboBoxEx32 안에 깊이 박혀 있음**
   - 다이얼로그 직속 Edit 찾으면 빈 컨트롤이라 안 채워짐
   - `ComboBoxEx32 > ComboBox > Edit` 트리 깊이 따라가야 함

3. **mtime 검증 필수**
   - IDOK 보냈다고 파일이 생성됐다는 보장 X
   - "성공"이라고 결과 엑셀에 기록했는데 실제 파일이 없는 false-positive 발생 → 검증 안 하면 사용자 신뢰 박살

4. **포커스 빼앗김 — 사용자가 다른 작업하면 다이얼로그 잡힘이 깨짐**
   - 백그라운드 메시지(WM_SETTEXT/WM_COMMAND)는 포커스 무관해서 비교적 안전
   - 그래도 `SendInput`/`keys.send_keys` 같이 키보드 시뮬레이션은 절대 쓰지 말 것

5. **다이얼로그 hide 시도 → 실패**
   - `ShowWindow(SW_HIDE)`로 숨기면 OK 메시지가 안 먹는 경우 있음
   - 안 숨기고 짧게 뜨고 사라지는 게 가장 안정적

---

## 7. Tkinter GUI ↔ async automation 통신

automation은 `asyncio` 기반인데 Tkinter는 자체 mainloop. **하나의 프로세스에서 두 loop를 공존시키는 패턴**:

```python
import asyncio, queue, threading
import tkinter as tk

class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()    # automation → GUI 메시지 큐
        self.worker_thread = None
        self.loop = None               # worker thread의 asyncio loop
        self.root.after(100, self._poll)

    def _start_work(self):
        """버튼 클릭 핸들러. background thread에서 asyncio.run 돌림."""
        def emit(kind, **kwargs):
            self.events.put({"kind": kind, **kwargs})

        async def main():
            await run_batch(..., emit=emit)
            emit("done")

        def thread_target():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(main())
            finally:
                self.loop.close()

        self.worker_thread = threading.Thread(target=thread_target, daemon=True)
        self.worker_thread.start()

    def _poll(self):
        """100ms마다 큐 비우면서 GUI 업데이트."""
        try:
            while True:
                evt = self.events.get_nowait()
                if evt["kind"] == "log":
                    self.log_text.insert("end", evt["text"] + "\n")
                    self.log_text.see("end")
                elif evt["kind"] == "progress":
                    self.progress["value"] = evt["pct"]
                elif evt["kind"] == "done":
                    self._on_done()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)
```

**노하우**:
- `messagebox` 호출은 항상 main thread에서. worker에서 띄우면 mainloop 꼬여서 root이 destroy됨
  → worker 안에서 띄우고 싶을 땐 `self.root.after(0, lambda: messagebox.show...(...))`
- `daemon=True` 필수 — 사용자가 X 눌렀을 때 worker도 같이 죽음
- 작업 중간에 사용자가 "중지" 누르면 `asyncio.CancelledError`로 worker 깨우는 패턴:
  ```python
  def stop(self):
      if self.loop:
          asyncio.run_coroutine_threadsafe(self._cancel(), self.loop)
  async def _cancel(self):
      for task in asyncio.all_tasks(self.loop):
          task.cancel()
  ```

---

## 8. PyInstaller 패키징

### onedir vs onefile
- **onedir 추천**. onefile은 실행 시마다 압축을 푸는데 Chromium 600MB라 매번 5초 이상 걸림.
- onedir는 폴더 통째로 배포 (zip 압축하면 250MB 정도).

### 핵심 spec 설정

```python
# hometax_auto.spec
from PyInstaller.utils.hooks import collect_all

# Playwright 모든 리소스 자동 수집
datas, binaries, hiddenimports = collect_all("playwright")

# Chromium 번들 — %LOCALAPPDATA%\ms-playwright 폴더 통째로 포함
import os
from pathlib import Path
_pw_cache = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
for sub in _pw_cache.iterdir():
    if sub.is_dir() and (sub.name.startswith("chromium-") or sub.name.startswith("ffmpeg")):
        datas.append((str(sub), f"ms-playwright/{sub.name}"))
        # ⚠ chromium_headless_shell은 GUI 모드에서 안 쓰므로 제외 (300MB 절감)

a = Analysis(
    ["gui.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports + ["automation", "automation_paystub", "updater"],
)
```

### runtime — 번들된 chromium 경로 알려주기

PyInstaller frozen 상태에서는 `LOCALAPPDATA\ms-playwright`가 아니라 `_MEIPASS/ms-playwright`에 있음:

```python
import os, sys
from pathlib import Path

def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent

# Playwright에게 우리가 번들한 chromium 위치 알려줌
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_resource_dir() / "ms-playwright")
```

이 라인은 **playwright import 전에** 실행돼야 함.

### console 안 띄우기 + 아이콘
```python
exe = EXE(
    pyz, a.scripts, [],
    name="앱이름",
    console=False,           # cmd 창 안 뜸 (GUI 전용)
    icon="icon.ico",
)
```

### 빌드 스크립트 (build.bat)
```bat
@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m pip install "pyinstaller>=6.0"
python -m playwright install chromium
if exist build rd /s /q build
if exist dist rd /s /q dist
pyinstaller --noconfirm myapp.spec
pause
```

`pause` 없으면 더블클릭 시 창 바로 꺼져서 에러 안 보임.

---

## 9. GitHub 기반 업데이트 알림 (수동 설치)

자동 설치는 onedir 폴더 교체 + 헬퍼 프로세스 + 재시작 등 복잡도 크니까, **알림 + 다운로드 페이지 열어주기**만 자동:

```python
# updater.py
import json, threading, urllib.request

CURRENT_VERSION = "1.2.0"
GITHUB_USER = "yourname"
GITHUB_REPO = "your-releases-repo"
UPDATE_CHECK_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/version.json"

def _parse_version(v: str) -> tuple:
    try: return tuple(int(x) for x in v.strip().split("."))
    except: return (0,)

def _check_sync() -> dict | None:
    try:
        req = urllib.request.Request(UPDATE_CHECK_URL,
                                      headers={"User-Agent": "MyApp-UpdateCheck"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    latest = (data.get("version") or "").strip()
    if not latest or _parse_version(latest) <= _parse_version(CURRENT_VERSION):
        return None
    return {"latest": latest, "current": CURRENT_VERSION,
            "download_url": data.get("download_url", ""),
            "notes": data.get("notes", "")}

def check_async(callback):
    def _run():
        info = _check_sync()
        if info:
            try: callback(info)
            except Exception: pass
    threading.Thread(target=_run, daemon=True).start()
```

### GUI에서 사용
```python
# App.__init__ 끝부분
self.root.after(800, lambda: updater.check_async(self._on_update_available))

def _on_update_available(self, info):
    # background thread에서 호출되니 main thread로 디스패치
    self.root.after(0, lambda: self._prompt_update(info))

def _prompt_update(self, info):
    body = f"새 버전 v{info['latest']}이 있습니다.\n현재: v{info['current']}\n\n다운로드 페이지를 열까요?"
    if messagebox.askyesno("업데이트", body, parent=self.root):
        webbrowser.open(info["download_url"])
```

### version.json 포맷
```json
{
  "version": "1.3.0",
  "download_url": "https://github.com/USER/REPO/releases/latest",
  "notes": "변경 내역 한두 줄"
}
```

### 운영 흐름
1. 새 버전 빌드 → zip → GitHub Releases에 업로드
2. repo의 `version.json` "version" 값 갱신 → commit
3. 사용자가 앱 켜면 알림 → "예" → 브라우저로 Releases 페이지 열림 → 사용자가 zip 받고 압축 풀어서 폴더 교체

---

## 10. 결과 기록 — 엑셀 출력 패턴

자동화는 **결과 엑셀**이 가장 중요. 사용자가 "32명 처리됐다는데 실제로 뭐가 됐지?"를 한눈에 보고 싶어함:

```python
import openpyxl

def write_result_row(ws, row_idx: int, result: dict):
    """C: 결과, D: 사유, E~G: 단계별 인쇄 수, H: 처리시각"""
    ws.cell(row_idx, 3).value = result["status"]      # 성공 / 부분실패 / 에러 / 수임아님
    ws.cell(row_idx, 4).value = result["reason"]      # 짧고 구체적인 이유
    ws.cell(row_idx, 5).value = result.get("step1_count", 0)
    ws.cell(row_idx, 6).value = result.get("step2_count", 0)
    ws.cell(row_idx, 7).value = result.get("step3_count", 0)
    ws.cell(row_idx, 8).value = datetime.now().isoformat(timespec="seconds")
```

**노하우**:
- **매 행마다 `wb.save()` 호출** — 중간에 크래시해도 그때까지 결과 남음
- 결과 파일은 입력 파일 옆에 `{원본}_결과.xlsx`. 같은 이름 있으면 `_2`, `_3` 자동 증가
- status는 4종으로 분류: 성공 / 수임아님(=대상 아님) / 부분실패(=일부만 됨) / 에러
- reason은 200자 제한. 길면 잘림
- "지급 3(근로 1, 기타 2)" 같이 **상세 통계 inline 포함** → 사용자가 결과 보고 바로 판단

---

## 11. 양도세 신고 자동화 — 시작 전 체크리스트

홈택스에서 **양도소득세 신고도움자료 / 양도세 신고서 자동화** 만들 때 고려할 것들:

1. **메뉴 경로 확인**: `세무대리/납세관리 > 신고대리 > 양도세 신고도움자료` (대상 메뉴 정확히 찾기)
2. **clipreport 사용 여부**: 종소세는 `m_reportHashMap`이라는 clipreport 모듈을 썼음. 양도세도 같으면 [3절](#3-chromium-자동-인쇄---kiosk-printing--sticky-settings)·[4절](#4--race-condition--modal-not-ready-패턴) 그대로 재사용
3. **iframe 구조**: WebSquare는 동일하지만 frame 깊이가 다를 수 있음 — `find_form()` 시 모든 frame 순회 패턴 유지
4. **다이얼로그 메시지**: 양도세는 "거주자/비거주자", "토지/건물/주식" 등 다른 분기. dialog_msgs 패턴 매칭 새로 작성
5. **신고서 작성 자동화는 더 위험**: 신고도움자료 **조회/인쇄**까지만 자동화하고, 실제 신고서 작성은 사람이 하도록. 잘못 제출하면 가산세
6. **테스트 케이스**: 양도건이 0건인 사람 / 1건 / 여러 건 / 비거주자 / 1세대1주택 비과세 등 5~6 패턴 확보 후 진행

### 코드 재사용 추천
양도세 프로젝트도 `automation.py + automation_xxx.py + gui.py + pdf_save.py + updater.py` 동일 구조. 종소세의 `automation.py`에서 다음 함수들은 **거의 그대로** 가져다 쓰면 됨:

| 함수 | 위치 | 재사용 가치 |
|---|---|---|
| `launch` / `setup_context` / `wait_for_form` / `find_form` | `automation.py` | 100% — 브라우저 attach 흐름 |
| `parse_rrn` / `get_unused_path` / `wait_print_queue_below` | `automation.py` | 100% — 유틸 |
| `_ensure_pdf_sticky_settings` / `_clear_pdf_sticky_settings` | `automation.py` | 100% — Chrome PDF 설정 |
| `_print_clipreport_popup` | `automation_paystub.py` | 100% — clipreport 인쇄 (양도세도 clipreport면) |
| `fill_and_save` 등 | `pdf_save.py` | 100% — PDF 다이얼로그 자동화 |
| `App.__init__` 골조 / `_poll` / queue 패턴 | `gui.py` | 90% — UI는 새로 그리되 통신 패턴 동일 |
| `updater.py` 전체 | `updater.py` | 100% — URL/repo만 양도세용으로 교체 |

새로 작성해야 하는 것:
- 양도세 메뉴 selector / 결과 row 추출 selector
- 양도건별 인쇄 로직 (`step_capital_gains_print` 같은)
- 결과 엑셀 컬럼 정의 (양도건수, 양도가액 등을 기록할지)

---

## 12. 디버깅 도구 — 다이얼로그 진단 스크립트

PDF 다이얼로그가 새 Windows 버전에서 안 잡힐 때, **현재 떠있는 윈도우 목록을 출력**:

```python
# diag_dialogs.py — 다이얼로그 떠있는 상태에서 실행
from pywinauto import findwindows, Application

print("=== win32 backend — visible 윈도우 전체 ===")
handles = findwindows.find_windows(visible_only=True)
for h in handles[:30]:
    try:
        app = Application(backend="win32").connect(handle=h, timeout=1)
        w = app.window(handle=h)
        title = w.window_text()
        if title:
            print(f"  handle={h:8d}  class='{w.class_name()}'  title='{title}'")
    except Exception:
        pass

print("\n=== title에 '저장' 포함된 윈도우 ===")
handles = findwindows.find_windows(title_re=r".*저장.*")
for h in handles:
    app = Application(backend="win32").connect(handle=h, timeout=1)
    w = app.window(handle=h)
    print(f"  class='{w.class_name()}'  title='{w.window_text()}'")
```

원본은 [`hometax-auto/diag_dialogs.py`](../diag_dialogs.py) 참고.

---

## 마지막 — 개발할 때 명심할 것

1. **로그를 풍부하게**. 사용자가 결과 안 좋으면 로그 보내달라고 해야 디버깅 가능. `[i]`, `[v]`, `[!]` 같은 prefix로 단계별 가독성 ↑
2. **결과 엑셀은 매 행 저장**. 중간에 죽어도 손해 최소화
3. **race condition은 항상 있음**. 첫 100명 잘 되도 200명에서 터질 수 있음. retry + try/except 기본
4. **사용자의 PC 환경은 통제 불가**. 한국어 Windows / 영어 Windows, Win10/11, 사무용/가정용 다 다름. 한 사람만 잘 되면 안 됨
5. **인쇄/다이얼로그는 OS 의존성 큼**. 다른 사람이 쓰는 첫 빌드는 반드시 그 사람 PC에서 직접 점검
6. **Win11 + OneDrive 폴더는 함정**. 한글 경로, 동기화 lock, 권한 등 자잘한 문제 많음. PDF 저장 경로 안내 시 OneDrive 권하지 말 것

---

## 원본 파일 인덱스 (코드 직접 참고)

| 파일 | 핵심 내용 |
|---|---|
| [`automation.py`](../automation.py) | launch / setup / wait_for_form / process_full / run_batch / sticky settings |
| [`automation_paystub.py`](../automation_paystub.py) | step_paystub_print / step_brief_print / _print_clipreport_popup / race retry |
| [`pdf_save.py`](../pdf_save.py) | fill_and_save / 다이얼로그 자동 채우기 / mtime 검증 / 덮어쓰기 처리 |
| [`gui.py`](../gui.py) | Tkinter App / Notebook tabs / queue 통신 / 업데이트 알림 hook |
| [`updater.py`](../updater.py) | GitHub raw fetch / 버전 비교 / 백그라운드 체크 |
| [`hometax_auto.spec`](../hometax_auto.spec) | PyInstaller spec / Chromium 번들 |
| [`build.bat`](../build.bat) | 빌드 자동화 |
| [`diag_dialogs.py`](../diag_dialogs.py) | 다이얼로그 진단 도구 |
