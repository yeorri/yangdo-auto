"""양도소득세 홈택스+위택스 신고 자동화 — Tkinter GUI (모던 테마).

phase를 각각 켜고(선택 실행) 전부 켜서(연속 실행) 돌릴 수 있다. 기본 순서는 레지스트리 순.
순수 Tkinter Canvas로 그린 커스텀 테마(외부 의존성 없음): 다크 헤더 + 화이트 카드 +
인디고 액센트, iOS식 토글 스위치, 둥근 버튼, 상태 pill, 콘솔형 로그.

실행:  python gui.py
"""
from __future__ import annotations

import os
import sys

# 배포(frozen exe)에서 Chromium 위치 결정 — 어떤 playwright import보다 먼저.
# 동봉 폴더가 있으면 그걸 쓰고(구버전 풀번들 하위호환), 없으면 Playwright 기본 위치
# (%LOCALAPPDATA%\ms-playwright)를 사용 — 첫 실행 때 browser_setup이 자동 설치한다.
if getattr(sys, "frozen", False):
    _base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    _bundled = os.path.join(_base, "playwright-browsers")
    if os.path.isdir(_bundled):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _bundled)
    else:
        # ⚠ playwright-python은 frozen(exe)이면 드라이버에 PLAYWRIGHT_BROWSERS_PATH='0'
        # (= exe 내부 .local-browsers)을 강제 주입한다(_transport.py) → 분리 배포에선
        # 공용 위치(ms-playwright)를 명시해 선점해야 브라우저를 찾는다.
        os.environ.setdefault(
            "PLAYWRIGHT_BROWSERS_PATH",
            os.path.join(os.environ.get("LOCALAPPDATA")
                         or os.path.expanduser("~\\AppData\\Local"), "ms-playwright"))

import asyncio
import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import browser_setup
import updater
from automation import ALL_PHASES, BrowserSession, Inputs, run_batch
from automation import ersfile
from automation.browser import app_data_dir

# 사용자 설정(변환파일 폴더 등) — 개발: 프로젝트 폴더 / 배포: %LOCALAPPDATA%\YangdoAuto
SETTINGS_PATH = app_data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(d: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        pass

# ─────────────────────────── 디자인 토큰 ───────────────────────────
FONT = "Malgun Gothic"        # 한글 선명
MONO = "Consolas"
BG = "#F1F5F9"                # slate-100  (앱 배경)
CARD = "#FFFFFF"              # 카드
HEAD = "#0F172A"              # slate-900  (헤더)
INK = "#0F172A"              # 본문 텍스트
MUTE = "#64748B"             # 보조 텍스트
BORDER = "#E2E8F0"           # 테두리
ACCENT = "#6366F1"           # indigo-500
ACCENT_DK = "#4F46E5"        # hover
ACCENT_SOFT = "#EEF2FF"
TRACK = "#CBD5E1"            # 토글 off
CONSOLE_BG = "#0B1220"
CONSOLE_FG = "#E2E8F0"

SITE_BADGE = {
    "홈택스": ("#DBEAFE", "#1D4ED8"),
    "위택스": ("#DCFCE7", "#15803D"),
}


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Canvas에 둥근 사각형(smooth polygon)."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


# ─────────────────────────── 커스텀 위젯 ───────────────────────────
class Toggle(tk.Canvas):
    """iOS식 토글 스위치 (BooleanVar 바인딩)."""

    def __init__(self, parent, variable: tk.BooleanVar, bg, command=None):
        super().__init__(parent, width=46, height=26, bg=bg, highlightthickness=0, bd=0)
        self.var = variable
        self.command = command
        self.bind("<Button-1>", self._click)
        self.configure(cursor="hand2")
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        round_rect(self, 2, 3, 44, 23, 10, fill=ACCENT if on else TRACK, outline="")
        x = 26 if on else 4
        self.create_oval(x, 5, x + 16, 21, fill="#FFFFFF", outline="")

    def _click(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()


class RButton(tk.Canvas):
    """둥근 버튼 (primary / ghost / mini) + hover."""

    def __init__(self, parent, text, command, *, kind="primary", bg,
                 width=128, height=44, font=None):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
        self.text, self.command, self.kind = text, command, kind
        self.w, self.h = width, height
        self.font = font or (FONT, 11, "bold")
        self._hover = False
        self.enabled = True
        self.configure(cursor="hand2")
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _on_click(self, _e):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, b: bool):
        if b == self.enabled:
            return
        self.enabled = b
        self.configure(cursor="hand2" if b else "arrow")
        self._draw()

    def _set(self, h):
        if not self.enabled:
            return
        self._hover = h
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.w, self.h
        if self.kind == "primary":
            if not self.enabled:
                fill = "#CBD5E1"
            else:
                fill = ACCENT_DK if self._hover else ACCENT
            round_rect(self, 1, 1, w - 1, h - 1, 13, fill=fill, outline="")
            fg = "#FFFFFF" if self.enabled else "#EEF2F8"
        elif self.kind == "ghost":
            round_rect(self, 1, 1, w - 1, h - 1, 13, fill="#F8FAFC" if self._hover else CARD,
                       outline=BORDER, width=1)
            fg = INK
        else:  # mini
            round_rect(self, 1, 1, w - 1, h - 1, 9, fill=ACCENT_SOFT if self._hover else "#F1F5F9", outline="")
            fg = ACCENT
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font)


class Segmented(tk.Canvas):
    """2지 세그먼트 컨트롤 (StringVar)."""

    def __init__(self, parent, variable: tk.StringVar, options, bg, width=190, height=36):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
        self.var = variable
        self.options = options  # [(value,label),(value,label)]
        self.w, self.h = width, height
        self.configure(cursor="hand2")
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.w, self.h
        round_rect(self, 1, 1, w - 1, h - 1, 11, fill="#F1F5F9", outline=BORDER, width=1)
        half = w / 2
        for i, (val, label) in enumerate(self.options):
            sel = self.var.get() == val
            cx = half * i + half / 2
            if sel:
                x1 = half * i + 3
                round_rect(self, x1, 3, x1 + half - 6, h - 3, 9, fill=ACCENT, outline="")
            self.create_text(cx, h / 2, text=label, fill="#FFFFFF" if sel else MUTE,
                             font=(FONT, 9, "bold"))

    def _click(self, e):
        self.var.set(self.options[0][0] if e.x < self.w / 2 else self.options[1][0])


class CellPill(tk.Canvas):
    """실행 단계 × 신고인 셀 — 체크(실행 여부) + 상태(대기/진행/완료/실패)를 한 칸에.

    클릭하면 실행 여부가 토글된다. 완료되면 호출부가 체크를 자동으로 풀어,
    '시작'을 다시 누르면 실패·미완료분만 재시도된다(재제출 방지).
    """

    STYLES = {   # status -> (라벨, 배경, 글자)
        "idle": ("대기", "#EEF2FF", "#4F46E5"),
        "run": ("진행", "#FEF3C7", "#B45309"),
        "ok": ("완료", "#DCFCE7", "#15803D"),
        "fail": ("실패", "#FEE2E2", "#B91C1C"),
    }

    def __init__(self, parent, var: tk.BooleanVar, bg, width=62, height=22):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.var = var
        self.w, self.h = width, height
        self.status = "idle"
        self.enabled = True          # 행(단계) 토글이 꺼지면 False
        self.configure(cursor="hand2")
        self.bind("<Button-1>", self._click)
        # 위젯이 파괴돼도 var는 살아남으므로(재생성 시 재사용) trace를 반드시 떼어낸다.
        self._trace = self.var.trace_add("write", lambda *a: self._draw())
        self.bind("<Destroy>", self._on_destroy)
        self._draw()

    def _on_destroy(self, _e=None):
        try:
            self.var.trace_remove("write", self._trace)
        except Exception:
            pass

    def _click(self, _e):
        if self.enabled:
            self.var.set(not self.var.get())

    def set_status(self, status: str):
        self.status = status
        self._draw()

    def set_enabled(self, b: bool):
        self.enabled = b
        self.configure(cursor="hand2" if b else "arrow")
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        label, fill, fg = self.STYLES.get(self.status, self.STYLES["idle"])
        if not self.enabled:                 # 단계 자체가 꺼짐
            fill, fg, label = "#F1F5F9", "#94A3B8", "꺼짐"
        elif not on and self.status in ("idle", "ok"):
            fill, fg, label = "#F8FAFC", "#94A3B8", "제외"
        round_rect(self, 1, 1, self.w - 1, self.h - 1, 8, fill=fill, outline="")
        mark = "☑" if (on and self.enabled) else "☐"
        self.create_text(12, self.h / 2, text=mark, fill=fg, font=(FONT, 8))
        self.create_text(self.w / 2 + 6, self.h / 2, text=label, fill=fg,
                         font=(FONT, 8, "bold"))


class Pill(tk.Canvas):
    """상태 pill (대기/진행/완료/실패)."""

    STYLES = {
        "idle": ("대기", "#F1F5F9", "#64748B"),
        "run": ("진행 중", "#FEF3C7", "#B45309"),
        "ok": ("완료", "#DCFCE7", "#15803D"),
        "fail": ("실패", "#FEE2E2", "#B91C1C"),
    }

    def __init__(self, parent, bg):
        super().__init__(parent, width=64, height=24, bg=bg, highlightthickness=0, bd=0)
        self.set("idle")

    def set(self, status):
        t, fill, fg = self.STYLES.get(status, self.STYLES["idle"])
        self.delete("all")
        round_rect(self, 1, 1, 63, 23, 11, fill=fill, outline="")
        self.create_text(32, 12, text=t, fill=fg, font=(FONT, 8, "bold"))


class PersonPicker(tk.Toplevel):
    """[신고인 선택] 창 — 변환파일 폴더를 스캔해 신고건을 최근순으로 보여주고 체크 선택.

    파일이 한쪽만 있는 건(홈✓ 위✗)도 선택 가능 — 선택 후 해당 칸에서 직접 지정하거나
    그 단계를 끄고 진행할 수 있게(사용자 결정).
    """

    def __init__(self, master, folder: str, on_pick):
        super().__init__(master)
        self.title("신고인 선택")
        self.configure(bg=BG)
        self.geometry("640x520")
        self.transient(master)
        self.grab_set()
        self.on_pick = on_pick
        self.folder = folder or ""
        self.vars: list = []
        self.rows: list = []

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text="변환파일 폴더", bg=BG, fg=INK, font=(FONT, 10)).pack(side="left")
        self.var_folder = tk.StringVar(value=self.folder)
        tk.Entry(top, textvariable=self.var_folder, font=(FONT, 9), bg="#FFFFFF", fg=MUTE,
                 relief="flat", highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left", fill="x", expand=True, padx=8, ipady=4)
        RButton(top, "변경", self._change_folder, kind="mini", bg=BG,
                width=54, height=30, font=(FONT, 9, "bold")).pack(side="left")

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=16)
        tk.Label(head, text="최근에 만든 변환파일이 위에 옵니다. 신고할 분을 체크하세요.",
                 bg=BG, fg=MUTE, font=(FONT, 8)).pack(anchor="w", pady=(0, 6))

        # 목록(스크롤)
        wrap = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16)
        cv = tk.Canvas(wrap, bg=CARD, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=cv.yview)
        self.list_frame = tk.Frame(cv, bg=CARD)
        win = cv.create_window((0, 0), window=self.list_frame, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.list_frame.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))

        btm = tk.Frame(self, bg=BG)
        btm.pack(fill="x", padx=16, pady=12)
        self.count_var = tk.StringVar(value="")
        tk.Label(btm, textvariable=self.count_var, bg=BG, fg=MUTE, font=(FONT, 9)).pack(side="left")
        self.ok_btn = RButton(btm, "선택", self._confirm, kind="primary", bg=BG, width=110)
        self.ok_btn.pack(side="right")
        RButton(btm, "취소", self.destroy, kind="ghost", bg=BG, width=90).pack(side="right", padx=8)

        self._reload()

    def _change_folder(self):
        p = filedialog.askdirectory(title="변환파일 폴더 선택", parent=self)
        if p:
            self.folder = p
            self.var_folder.set(p)
            self._reload()

    def _reload(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.vars.clear()
        self.rows = ersfile.scan_folder(self.folder) if self.folder else []
        if not self.rows:
            tk.Label(self.list_frame, text="변환파일이 없습니다. 폴더를 확인해 주세요.",
                     bg=CARD, fg=MUTE, font=(FONT, 9)).pack(pady=24)
            self._refresh_count()
            return
        # 헤더
        hd = tk.Frame(self.list_frame, bg=CARD)
        hd.pack(fill="x", padx=10, pady=(8, 2))
        for txt, w in (("", 3), ("성명", 8), ("양도연월", 9), ("자산", 7),
                       ("홈택스", 6), ("위택스", 6), ("만든 시각", 12)):
            tk.Label(hd, text=txt, width=w, anchor="w", bg=CARD, fg=MUTE,
                     font=(FONT, 8, "bold")).pack(side="left")
        for r in self.rows:
            row = tk.Frame(self.list_frame, bg=CARD)
            row.pack(fill="x", padx=10, pady=1)
            v = tk.BooleanVar(value=False)
            v.trace_add("write", lambda *a: self._refresh_count())
            self.vars.append(v)
            tk.Checkbutton(row, variable=v, bg=CARD, activebackground=CARD,
                           highlightthickness=0, bd=0).pack(side="left")
            def cell(text, w, fg=INK, bold=False):
                tk.Label(row, text=text, width=w, anchor="w", bg=CARD, fg=fg,
                         font=(FONT, 9, "bold" if bold else "normal")).pack(side="left")
            cell(r["name"] or "?", 8, bold=True)
            cell(r["trade_ym"] or "-", 9)
            cell(r["asset"] or "-", 7)
            cell("있음" if r["hometax"] else "없음", 6,
                 fg="#15803D" if r["hometax"] else "#B91C1C")
            cell("있음" if r["wetax"] else "없음", 6,
                 fg="#15803D" if r["wetax"] else "#B91C1C")
            t = datetime.fromtimestamp(r["mtime"]).strftime("%m-%d %H:%M") if r["mtime"] else "-"
            cell(t, 12, fg=MUTE)
        self._refresh_count()

    def _refresh_count(self):
        n = sum(1 for v in self.vars if v.get())
        self.count_var.set(f"{n}명 선택됨" if n else "선택된 신고인이 없습니다")
        try:
            self.ok_btn.set_enabled(n > 0)
        except Exception:
            pass

    def _confirm(self):
        picked = [r for r, v in zip(self.rows, self.vars) if v.get()]
        if not picked:
            return
        self.on_pick(picked, self.folder)
        self.destroy()


# ─────────────────────────── 앱 ───────────────────────────
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("양도소득세 신고 자동화")
        root.geometry("1120x1000")
        root.minsize(1000, 820)
        root.configure(bg=BG)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Vertical.TScrollbar", background=TRACK, troughcolor=BG,
                        bordercolor=BG, arrowcolor=MUTE, relief="flat")

        self.events: queue.Queue = queue.Queue()
        self.session_loop: asyncio.AbstractEventLoop | None = None
        self.session: BrowserSession | None = None
        self._run_fut = None   # 실행 중인 asyncio task — 중단 시 즉시 취소용
        self._busy = False
        self._stop = False
        self._phase_vars: dict[str, tk.BooleanVar] = {}
        self._phase_pills: dict[str, Pill] = {}

        # 검증(_missing)이 참조하므로 _build_ui 전에 설정.
        self._browsers_ready = browser_setup.browsers_ready()
        self._settings = load_settings()
        self.people: list[dict] = []
        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll)
        updater.check_async(self._on_update_available)
        if not self._browsers_ready:
            self._install_browsers_async()

    def _ensure_session(self):
        """세션 루프 스레드 + BrowserSession 준비(최초 1회)."""
        if self.session_loop is not None:
            return
        self.session_loop = asyncio.new_event_loop()
        threading.Thread(target=self.session_loop.run_forever, daemon=True).start()
        self.session = BrowserSession()

    def _on_close(self):
        """창 닫기 — 세션 브라우저 정리 후 종료."""
        try:
            if self.session_loop is not None and self.session is not None:
                fut = asyncio.run_coroutine_threadsafe(self.session.close(), self.session_loop)
                fut.result(timeout=5)
        except Exception:
            pass
        self.root.destroy()

    def _install_browsers_async(self):
        """첫 실행: Chromium 자동 다운로드(~150MB). 완료까지 시작 버튼 비활성."""
        self._append_log("[i] 첫 실행 준비 — 브라우저 구성요소(약 150MB)를 다운로드합니다. "
                         "인터넷 연결이 필요하며 몇 분 걸릴 수 있습니다…")

        def worker():
            ok = browser_setup.install_browsers(
                lambda m: self.events.put({"kind": "log", "text": m}))
            # 완료 메시지도 같은 큐로 — 다운로드 로그와 순서가 어긋나지 않게(FIFO)
            if ok:
                self.events.put({"kind": "log",
                                 "text": "[v] 브라우저 준비 완료 — 이제 시작할 수 있습니다."})

            def fin():
                self._browsers_ready = ok
                self._refresh_validation()
                if not ok:
                    messagebox.showerror(
                        "설치 실패",
                        "브라우저 구성요소 다운로드에 실패했습니다.\n"
                        "인터넷 연결을 확인한 뒤 프로그램을 다시 실행해주세요.")
            self.root.after(0, fin)

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_available(self, info: dict):
        """새 버전 알림 — background thread에서 호출되므로 Tk 조작은 after로 디스패치."""
        def ask():
            msg = (f"새 버전 v{info['latest']}이 있습니다. (현재 v{info['current']})\n\n"
                   + (f"{info['notes']}\n\n" if info.get("notes") else "")
                   + "다운로드 페이지를 열까요?")
            if messagebox.askyesno("업데이트 알림", msg):
                import webbrowser
                webbrowser.open(info["download_url"])
        try:
            self.root.after(0, ask)
        except Exception:
            pass

    # ── UI ──
    def _build_ui(self):
        # 헤더
        head = tk.Frame(self.root, bg=HEAD)
        head.pack(fill="x", side="top")
        hin = tk.Frame(head, bg=HEAD)
        hin.pack(fill="x", padx=24, pady=(18, 16))
        tk.Label(hin, text="양도소득세 신고 자동화", bg=HEAD, fg="#FFFFFF",
                 font=(FONT, 18, "bold")).pack(anchor="w")
        tk.Label(hin, text="홈택스 · 위택스   |   파일변환 신고 → 부속서류 제출 → 서류 PDF·출력",
                 bg=HEAD, fg="#94A3B8", font=(FONT, 9)).pack(anchor="w", pady=(3, 0))
        tk.Frame(self.root, bg=ACCENT, height=3).pack(fill="x", side="top")

        # 푸터(버튼) — 하단 고정
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", side="bottom", padx=20, pady=(8, 14))
        self.start_btn = RButton(footer, "▶  시작", self._start, kind="primary", bg=BG, width=130)
        self.start_btn.pack(side="left")
        RButton(footer, "■  중단", self._stop_clicked, kind="ghost", bg=BG, width=110).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="대기 중")
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=MUTE,
                 font=(FONT, 9)).pack(side="right", pady=4)
        self.hint_var = tk.StringVar()
        tk.Label(footer, textvariable=self.hint_var, bg=BG, fg="#B45309",
                 font=(FONT, 9), wraplength=420, justify="left").pack(side="left", padx=14)

        # 로그 — 푸터 위 고정
        logwrap = tk.Frame(self.root, bg=BG)
        logwrap.pack(fill="x", side="bottom", padx=20, pady=(0, 0))
        tk.Label(logwrap, text="실행 로그", bg=BG, fg=MUTE, font=(FONT, 9, "bold")).pack(anchor="w", pady=(0, 4))
        lt = tk.Frame(logwrap, bg=CONSOLE_BG, highlightbackground=BORDER, highlightthickness=1)
        lt.pack(fill="both")
        self.log_text = tk.Text(lt, height=6, wrap="word", bg=CONSOLE_BG, fg=CONSOLE_FG,
                                relief="flat", font=(MONO, 9), insertbackground=CONSOLE_FG,
                                padx=12, pady=8, borderwidth=0)
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(lt, orient="vertical", command=self.log_text.yview)
        lsb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.tag_config("ok", foreground="#4ADE80")
        self.log_text.tag_config("fail", foreground="#F87171")
        self.log_text.tag_config("info", foreground="#7DD3FC")
        self.log_text.tag_config("accent", foreground="#A5B4FC")

        # 중앙 — 스크롤 영역
        scroll = tk.Frame(self.root, bg=BG)
        scroll.pack(fill="both", expand=True, side="top")
        canvas = tk.Canvas(scroll, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        # 위: [실행 단계 | 옵션] 같은 높이로 나란히. 아래: [입력 정보] 전체 폭(긴 경로 잘 보이게).
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1, uniform="t")
        top.columnconfigure(1, weight=1, uniform="t")
        top.rowconfigure(0, weight=1)
        tl = tk.Frame(top, bg=BG)
        tl.grid(row=0, column=0, sticky="nsew", padx=(20, 8))
        tr = tk.Frame(top, bg=BG)
        tr.grid(row=0, column=1, sticky="nsew", padx=(8, 20))
        self._build_phase_card(tl, expand=True)
        self._build_option_card(tr, expand=True)

        bottom = tk.Frame(body, bg=BG)
        bottom.pack(fill="x", padx=20)
        self._build_input_card(bottom)
        self._setup_validation()

    def _card(self, parent, title, subtitle=None, expand=False, ret_head=False):
        fill = "both" if expand else "x"
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill=fill, expand=expand, padx=0, pady=(12, 0))
        c = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        c.pack(fill=fill, expand=expand)
        head = tk.Frame(c, bg=CARD)
        head.pack(fill="x", padx=16, pady=(11, 4))
        tk.Label(head, text=title, bg=CARD, fg=INK, font=(FONT, 11, "bold")).pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=CARD, fg=MUTE, font=(FONT, 8)).pack(side="left", padx=(8, 0))
        return (c, head) if ret_head else c

    def _build_phase_card(self, parent, expand=False):
        c = self._card(parent, "실행 단계", "단계 토글 = 전원 · 칸 클릭 = 그 사람만", expand=expand)
        # 신고인 헤더(이름) — 사람이 바뀔 때마다 다시 그림
        self._matrix_head = tk.Frame(c, bg=CARD)
        self._matrix_head.pack(fill="x", padx=16, pady=(0, 2))
        self._cells: dict = {}          # (phase_key, person_idx) -> CellPill
        self._cell_vars: dict = {}      # (phase_key, person_idx) -> BooleanVar
        self._phase_rows: dict = {}     # phase_key -> 셀이 들어갈 프레임

        for i, mod in enumerate(ALL_PHASES, 1):
            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", padx=16, pady=2)
            var = tk.BooleanVar(value=True)
            self._phase_vars[mod.KEY] = var
            var.trace_add("write", lambda *a, k=mod.KEY: self._sync_row_enabled(k))
            Toggle(row, var, CARD).pack(side="left")
            site = getattr(mod, "SITE", "")
            if site in SITE_BADGE:
                bgc, fgc = SITE_BADGE[site]
                tk.Label(row, text=site, bg=bgc, fg=fgc, font=(FONT, 8, "bold"),
                         padx=6, pady=1).pack(side="left", padx=(10, 6))
            tk.Label(row, text=f"{i}. {mod.LABEL}", bg=CARD, fg=INK,
                     font=(FONT, 9)).pack(side="left")
            holder = tk.Frame(row, bg=CARD)
            holder.pack(side="right")
            self._phase_rows[mod.KEY] = holder
        tk.Frame(c, bg=CARD, height=6).pack()

    def _render_phase_matrix(self):
        """신고인 수에 맞춰 단계×신고인 셀을 다시 그린다(사람 추가/삭제 시 호출)."""
        if not hasattr(self, "_phase_rows"):
            return
        active = [pv for pv in self.people if not self._is_blank(pv)]
        n = max(1, len(active))
        # 헤더(이름)
        for w in self._matrix_head.winfo_children():
            w.destroy()
        tk.Label(self._matrix_head, text="", bg=CARD).pack(side="left")
        box = tk.Frame(self._matrix_head, bg=CARD)
        box.pack(side="right")
        for i in range(n):
            nm = (active[i]["name"].get().strip() if i < len(active) else "") or f"{i + 1}번"
            tk.Label(box, text=nm[:5], width=8, anchor="center", bg=CARD, fg=MUTE,
                     font=(FONT, 8, "bold")).pack(side="left")
        # 셀
        old = self._cell_vars
        self._cells.clear()
        self._cell_vars = {}
        for mod in ALL_PHASES:
            holder = self._phase_rows[mod.KEY]
            for w in holder.winfo_children():
                w.destroy()
            for i in range(n):
                key = (mod.KEY, i)
                v = old.get(key) or tk.BooleanVar(value=True)
                self._cell_vars[key] = v
                cell = CellPill(holder, v, CARD)
                cell.pack(side="left", padx=1)
                cell.set_enabled(self._phase_vars[mod.KEY].get())
                self._cells[key] = cell

    def _sync_row_enabled(self, phase_key: str):
        """단계 토글 on/off를 그 행의 셀들에 반영."""
        on = self._phase_vars[phase_key].get()
        for (k, _i), cell in getattr(self, "_cells", {}).items():
            if k == phase_key:
                cell.set_enabled(on)

    # 입력 항목 정의 — (라벨, 키, 선택방식, 힌트). 순서 = 자동입력 4개 → 사용자 선택 2개
    PERSON_FIELDS = [
        ("신고인 성명", "name", None, ""),
        ("주민등록번호", "rrn", None, ""),
        ("홈택스 변환파일", "hometax", "file", ".01"),
        ("위택스 변환파일", "wetax", "file", ".Y13"),
        ("부속서류 폴더", "attach", "dir", "폴더 내 파일 전부 첨부"),
        ("PDF 저장 폴더", "outdir", "dir", "없으면 자동 생성"),
    ]
    COL_W = 320      # 사람 열 최소 폭(px) — 3명까지는 스크롤 없이, 4명↑ 가로 스크롤
    ROW_H = 38       # 행 높이 — 라벨 열과 사람 열 정렬을 맞추기 위해 고정
    HEAD_H = 22      # 사람 열 헤더(번호·삭제) 높이

    def _build_input_card(self, parent):
        c, head = self._card(parent, "입력 정보", ret_head=True)
        # 카드 제목 옆에 버튼·설명을 배치(별도 행을 만들지 않아 세로 공간 절약)
        RButton(head, "신고인 선택", self._open_picker, kind="primary", bg=CARD,
                width=100, height=28, font=(FONT, 9, "bold")).pack(side="left", padx=(12, 0))
        RButton(head, "+ 직접 입력", self._add_blank_person, kind="ghost", bg=CARD,
                width=86, height=28, font=(FONT, 9, "bold")).pack(side="left", padx=6)
        tk.Label(head, text="변환파일에서 자동으로 채우거나, 빈 칸에 직접 입력할 수 있습니다.",
                 bg=CARD, fg=MUTE, font=(FONT, 8)).pack(side="left", padx=8)

        body = tk.Frame(c, bg=CARD)
        body.pack(fill="x", padx=16, pady=(4, 12))
        h = self.ROW_H * len(self.PERSON_FIELDS) + self.HEAD_H   # 헤더(번호) + 행들
        self._col_h = h

        # 왼쪽 라벨 열 — 가로 스크롤해도 고정
        lab = tk.Frame(body, bg=CARD, width=140, height=h)
        lab.pack(side="left", anchor="n")
        lab.pack_propagate(False)
        tk.Frame(lab, bg=CARD, height=self.HEAD_H).pack(fill="x")   # 헤더 자리 맞춤
        for text, _k, _p, hint in self.PERSON_FIELDS:
            cell = tk.Frame(lab, bg=CARD, height=self.ROW_H)
            cell.pack(fill="x")
            cell.pack_propagate(False)
            pad = (10, 0) if not hint else (3, 0)   # 힌트 없는 항목은 세로 가운데에 가깝게
            tk.Label(cell, text=text, bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w", pady=pad)
            if hint:
                tk.Label(cell, text=hint, bg=CARD, fg=MUTE, font=(FONT, 8)).pack(anchor="w")

        # 오른쪽 사람 열 — 4명 이상이면 가로 스크롤
        holder = tk.Frame(body, bg=CARD)
        holder.pack(side="left", fill="x", expand=True)
        self.pcanvas = tk.Canvas(holder, bg=CARD, highlightthickness=0, height=h)
        hsb = ttk.Scrollbar(holder, orient="horizontal", command=self.pcanvas.xview)
        self.pcols = tk.Frame(self.pcanvas, bg=CARD)
        self._pwin = self.pcanvas.create_window((0, 0), window=self.pcols, anchor="nw")
        self.pcanvas.configure(xscrollcommand=hsb.set)
        self.pcanvas.pack(side="top", fill="x", expand=True)
        hsb.pack(side="bottom", fill="x")
        self.pcols.bind("<Configure>",
                        lambda e: self.pcanvas.configure(scrollregion=self.pcanvas.bbox("all")))
        self.pcanvas.bind("<Configure>", self._fit_person_cols)

        # 기본으로 빈 칸 하나 — 바로 직접 입력할 수 있게(신고인 선택 시 이 칸부터 채워짐)
        self.people = [self._new_person()]
        self._render_people()

    def _fit_person_cols(self, event=None):
        """열이 3개 이하면 캔버스 폭에 맞춰 늘리고, 넘치면 최소 폭 유지(가로 스크롤)."""
        try:
            need = max(1, len(self.people)) * self.COL_W
            w = self.pcanvas.winfo_width()
            self.pcanvas.itemconfig(self._pwin, width=max(need, w))
        except Exception:
            pass

    def _render_people(self):
        """현재 self.people 기준으로 사람 열을 다시 그린다."""
        for w in self.pcols.winfo_children():
            w.destroy()
        if not self.people:
            tk.Label(self.pcols,
                     text="[신고인 선택]으로 변환파일에서 자동으로 채우거나, [+ 직접 입력]으로 빈 칸을 추가하세요.\n"
                          "(출력 단계만 실행할 때는 변환파일 없이 성명·주민번호만 있으면 됩니다)",
                     bg=CARD, fg=MUTE, font=(FONT, 9), justify="left").pack(anchor="w", padx=12, pady=16)
            self._fit_person_cols()
            return
        for idx, pv in enumerate(self.people):
            # ⚠ height를 반드시 줄 것 — pack_propagate(False)라 자식이 높이를 못 늘려
            #   height 미지정 시 0이 되어 열이 통째로 안 보인다.
            col = tk.Frame(self.pcols, bg=CARD, width=self.COL_W, height=self._col_h)
            col.pack(side="left", fill="y", padx=(0, 10))
            col.pack_propagate(False)
            # 헤더: 번호 + 삭제
            hd = tk.Frame(col, bg=CARD, height=self.HEAD_H)
            hd.pack(fill="x")
            hd.pack_propagate(False)
            tk.Label(hd, text=f"{idx + 1}", bg=ACCENT_SOFT, fg=ACCENT,
                     font=(FONT, 8, "bold"), padx=7).pack(side="left")
            RButton(hd, "×", lambda i=idx: self._remove_person(i), kind="mini", bg=CARD,
                    width=24, height=20, font=(FONT, 9, "bold")).pack(side="right")
            for _text, key, pick, _hint in self.PERSON_FIELDS:
                cell = tk.Frame(col, bg=CARD, height=self.ROW_H)
                cell.pack(fill="x")
                cell.pack_propagate(False)
                inner = tk.Frame(cell, bg=CARD)
                inner.pack(fill="x", pady=(6, 0))
                e = tk.Entry(inner, textvariable=pv[key], font=(FONT, 9), bg="#FFFFFF",
                             fg=INK, relief="flat", highlightthickness=1,
                             highlightbackground=BORDER, highlightcolor=ACCENT,
                             insertbackground=INK)
                e.pack(side="left", fill="x", expand=True, ipady=4)
                # 긴 경로는 끝부분이 보이도록
                e.bind("<FocusOut>", lambda ev, ent=e: ent.xview_moveto(1.0))
                pv.setdefault("_entries", {})[key] = e
                if pick:
                    def cmd(v=pv[key], ent=e, pk=pick):
                        (self._pick_dir if pk == "dir" else self._pick_file)(v)
                        ent.xview_moveto(1.0)
                    RButton(inner, "찾기", cmd, kind="mini", bg=CARD, width=48, height=28,
                            font=(FONT, 9, "bold")).pack(side="left", padx=(4, 0))
        self._fit_person_cols()
        self._render_phase_matrix()
        self._refresh_validation()

    def _new_person(self, row: dict | None = None) -> dict:
        """사람 열 하나의 StringVar 묶음 생성(선택 결과로 자동 채움)."""
        row = row or {}
        pv = {k: tk.StringVar(value=str(row.get(k, "") or ""))
              for _t, k, _p, _h in self.PERSON_FIELDS}
        for v in pv.values():
            v.trace_add("write", lambda *a: self._refresh_validation())
        return pv

    def _open_picker(self):
        folder = self._settings.get("convert_folder", "")
        PersonPicker(self.root, folder, self._on_people_picked)

    @staticmethod
    def _is_blank(pv: dict) -> bool:
        """아무것도 입력 안 된 빈 칸인지."""
        return not any((pv[k].get() or "").strip()
                       for k in ("name", "rrn", "hometax", "wetax", "attach", "outdir"))

    def _on_people_picked(self, rows: list, folder: str):
        """[신고인 선택] 결과 반영 — 빈 칸이 있으면 그 칸부터 채우고, 모자라면 추가."""
        if folder:
            self._settings["convert_folder"] = folder
            save_settings(self._settings)
        exists = {(pv["rrn"].get(), pv["hometax"].get())
                  for pv in self.people if not self._is_blank(pv)}
        added = 0
        for r in rows:
            if (r.get("rrn", ""), r.get("hometax", "")) in exists:
                continue          # 이미 있는 사람은 건너뜀
            blank = next((pv for pv in self.people if self._is_blank(pv)), None)
            if blank is not None:
                for k in ("name", "rrn", "hometax", "wetax"):
                    blank[k].set(str(r.get(k, "") or ""))
            else:
                self.people.append(self._new_person(r))
            added += 1
        self._render_people()
        if added:
            self._append_log(f"[i] 신고인 {added}명 추가 — 부속서류·PDF 저장 폴더를 지정하세요.")

    def _add_blank_person(self):
        """빈 칸 추가 — 변환파일 없이 성명·주민번호만으로 출력 단계만 돌릴 때."""
        self.people.append(self._new_person())
        self._render_people()

    def _remove_person(self, idx: int):
        if 0 <= idx < len(self.people):
            self.people.pop(idx)
            if not self.people:              # 최소 한 칸은 남겨 바로 입력 가능하게
                self.people.append(self._new_person())
            self._render_people()

    def _clear_people(self):
        self.people = [self._new_person()]
        self._render_people()

    def _build_option_card(self, parent, expand=False):
        c = self._card(parent, "옵션", expand=expand)
        opt = tk.Frame(c, bg=CARD)
        opt.pack(fill="x", padx=16, pady=(2, 12))

        self.var_mode = tk.StringVar(value="pdf")
        self.var_incname = tk.BooleanVar(value=False)
        self.var_disclose = tk.BooleanVar(value=True)
        self.var_merge = tk.BooleanVar(value=False)
        self.var_del_src = tk.BooleanVar(value=False)
        self.var_napbu_wait = tk.StringVar(value="3")

        seg = tk.Frame(opt, bg=CARD)
        seg.pack(fill="x", pady=(0, 4))
        tk.Label(seg, text="서류 처리", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        Segmented(seg, self.var_mode, [("pdf", "PDF 저장"), ("print", "출력(인쇄)")], CARD).pack(side="right")

        self._switch(opt, "파일명에 성명 포함", "공동명의 등 구분이 필요할 때", self.var_incname)
        self._switch(opt, "서류 개인정보 공개", "출력 서류에 주민번호 등 공개 표시", self.var_disclose)
        self._switch(opt, "접수증·신고서 병합", "접수증+양도세+지방세 신고서를 [접수증&신고서]로 (PDF 저장 시)", self.var_merge)
        self._switch(opt, "   └ 병합 후 개별 원본 삭제", "병합 성공 시에만 삭제 — 병합본만 남김(납부서는 유지)",
                     self.var_del_src)

        wrow = tk.Frame(opt, bg=CARD)
        wrow.pack(fill="x", pady=3)
        wtxt = tk.Frame(wrow, bg=CARD)
        wtxt.pack(side="left")
        tk.Label(wtxt, text="위택스 납부서 대기", bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        tk.Label(wtxt, text="지방세 가상계좌 생성 대기 시간 (납부서 출력 전)", bg=CARD, fg=MUTE,
                 font=(FONT, 8)).pack(anchor="w")
        wbox = tk.Frame(wrow, bg=CARD)
        wbox.pack(side="right")
        tk.Label(wbox, text="분", bg=CARD, fg=MUTE, font=(FONT, 9)).pack(side="right", padx=(4, 0))
        tk.Entry(wbox, textvariable=self.var_napbu_wait, font=(FONT, 10), width=4, justify="center",
                 bg="#FFFFFF", fg=INK, relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT).pack(side="right", ipady=3)

    def _switch(self, parent, label, hint, var):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        Toggle(row, var, CARD).pack(side="right")
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=label, bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        tk.Label(txt, text=hint, bg=CARD, fg=MUTE, font=(FONT, 8),
                 wraplength=380, justify="left").pack(anchor="w")

    def _napbu_wait_seconds(self) -> int:
        """'위택스 납부서 대기' 분 입력 → 초. 파싱 실패 시 기본 3분."""
        raw = (self.var_napbu_wait.get() or "").strip().replace(",", ".")
        try:
            return max(0, int(round(float(raw) * 60)))
        except ValueError:
            return 180

    # ── 필수 입력 검증 ──
    def _setup_validation(self):
        # 병합을 끄면 '개별 원본 삭제'도 같이 꺼짐(단독으로는 의미 없는 옵션)
        def _sync_del(*_a):
            if not self.var_merge.get() and self.var_del_src.get():
                self.var_del_src.set(False)
        self.var_merge.trace_add("write", _sync_del)

        # 사람별 입력값은 _new_person에서 개별로 trace를 건다(열이 동적이라).
        watch = [self.var_mode, self.var_incname]
        for v in watch:
            v.trace_add("write", lambda *a: self._refresh_validation())
        for v in self._phase_vars.values():
            v.trace_add("write", lambda *a: self._refresh_validation())
        self._refresh_validation()

    def _missing(self) -> list[str]:
        """현재 선택/입력 기준 부족한 필수 항목 라벨 목록(없으면 빈 리스트)."""
        if not self._browsers_ready:
            return ["브라우저 구성요소 다운로드 완료 대기"]
        sel = {k for k, v in self._phase_vars.items() if v.get()}
        if not sel:
            return ["실행 단계 선택"]
        # 빈 칸(아무것도 입력 안 된 열)은 검증·실행에서 제외 — 기본 빈 칸이 실행을 막지 않게
        active = [pv for pv in self.people if not self._is_blank(pv)]
        if not active:
            return ["신고인 정보 입력"]
        miss: list[str] = []

        # 신고인마다 필요한 값이 채워졌는지 — 부족하면 "홍길동: 부속서류 폴더" 형태로 안내
        wetax_out = sel & {"wetax_docs", "wetax_napbu"}
        hometax_out = sel & {"hometax_docs", "hometax_napbu"}
        for idx, pv in enumerate(active, 1):
            who = pv["name"].get().strip() or f"{idx}번"

            def need(key, label, _pv=pv, _who=who):
                if not _pv[key].get().strip():
                    miss.append(f"{_who}: {label}")

            # 성명: 위택스 출력은 신고내역을 이름으로 찾으므로 항상 필요,
            # 홈택스 출력은 '파일명에 성명 포함'을 켰을 때만 필요.
            if wetax_out or (self.var_incname.get() and hometax_out):
                need("name", "신고인 성명")
            if "wetax_filing" in sel:
                need("wetax", "위택스 변환파일")
            if "hometax_filing" in sel:
                need("hometax", "홈택스 변환파일")
            if sel & {"hometax_attach", "hometax_docs", "hometax_napbu"}:
                digits = "".join(c for c in pv["rrn"].get() if c.isdigit())
                if len(digits) != 13:
                    miss.append(f"{who}: 주민등록번호(13자리)")
            if "hometax_attach" in sel:
                need("attach", "부속서류 폴더")
            if (sel & {"hometax_docs", "wetax_docs", "hometax_napbu", "wetax_napbu"}) \
                    and self.var_mode.get() == "pdf":
                need("outdir", "PDF 저장 폴더")

        seen, out = set(), []
        for m in miss:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def _refresh_validation(self):
        miss = self._missing()
        self.start_btn.set_enabled(not miss)
        self.hint_var.set(("필요: " + ", ".join(miss)) if miss else "")

    # ── 파일 선택 ──
    def _pick_file(self, var):
        p = filedialog.askopenfilename(title="파일 선택")
        if p:
            var.set(p)

    def _pick_dir(self, var):
        p = filedialog.askdirectory(title="폴더 선택")
        if p:
            var.set(p)

    # ── 실행 ──
    def _start(self):
        if self._busy:
            messagebox.showinfo("실행 중", "이미 진행 중입니다. 끝난 뒤 다시 시작하세요.")
            return

        selected = [k for k, v in self._phase_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("단계 없음", "실행할 단계를 하나 이상 켜세요.")
            return

        active = [pv for pv in self.people if not self._is_blank(pv)]
        if not active:
            messagebox.showwarning("신고인 없음",
                                   "[신고인 선택]으로 고르거나 빈 칸에 직접 입력하세요.")
            return

        people = [Inputs(
            name_label=pv["name"].get().strip() or f"{i}번",
            wetax_convert_file=pv["wetax"].get().strip(),
            hometax_convert_file=pv["hometax"].get().strip(),
            seller_rrn="".join(c for c in pv["rrn"].get() if c.isdigit()),
            attach_folder=pv["attach"].get().strip(),
            output_dir=pv["outdir"].get().strip(),
            output_mode=self.var_mode.get(),
            auto_submit=True,  # 제출까지 자동(토글 제거). 검증까지만 원하면 코드/요청으로 조정.
            disclose_personal_info=self.var_disclose.get(),
            include_name=self.var_incname.get(),
            merge_docs=self.var_merge.get(),
            delete_merged_sources=self.var_del_src.get(),
            napbu_wait_sec=self._napbu_wait_seconds(),
        ) for i, pv in enumerate(active, 1)]

        # 사람마다 실행할 단계 = 단계 토글 ON × 그 사람 셀 체크 ON
        jobs = []
        for i, inp in enumerate(people):
            keys = [k for k in selected
                    if self._cell_vars.get((k, i), tk.BooleanVar(value=True)).get()]
            jobs.append((inp, keys))
        if not any(keys for _inp, keys in jobs):
            messagebox.showwarning("실행할 단계 없음",
                                   "각 신고인의 단계 칸이 모두 제외 상태입니다.\n"
                                   "칸을 클릭해 실행할 단계를 켜세요.")
            return

        self._stop = False
        for (k, i), cell in self._cells.items():
            if self._cell_vars[(k, i)].get() and self._phase_vars[k].get():
                cell.set_status("idle")     # 이번에 돌릴 칸만 초기화(완료 이력은 유지)
        self.log_text.delete("1.0", "end")
        self.status_var.set("실행 중…")

        def emit(kind, **kw):
            self.events.put({"kind": kind, **kw})

        async def main():
            try:
                await run_batch(self.session, jobs, emit, stop_check=lambda: self._stop)
            except asyncio.CancelledError:
                # 중단 버튼 = 즉시 취소. 화면이 어중간해도 phase는 시작 시 하드 리셋(goto)
                # 하므로 다음 실행은 깨끗하게 시작된다. 브라우저는 유지.
                emit("log", text="[i] 중단됨 — 즉시 종료 (브라우저 유지, 다음 실행 시 화면 자동 리셋)")
                emit("done")
            except Exception as e:  # noqa: BLE001
                emit("log", text=f"[!] 예외: {e}")
                emit("done")

        self._ensure_session()
        self._busy = True
        self._run_fut = asyncio.run_coroutine_threadsafe(main(), self.session_loop)

    def _stop_clicked(self):
        self._stop = True
        if self._run_fut is not None and not self._run_fut.done():
            self._run_fut.cancel()   # 실행 중인 태스크 즉시 취소 (await 지점에서 끊김)
        self.status_var.set("중단됨")

    # ── 큐 폴링 ──
    def _poll(self):
        try:
            while True:
                evt = self.events.get_nowait()
                kind = evt["kind"]
                if kind == "log":
                    self._append_log(evt["text"])
                elif kind == "phase":
                    self._set_phase(evt["key"], evt["status"], evt.get("person"))
                elif kind == "status":
                    self.status_var.set(evt.get("text", ""))
                elif kind == "done":
                    self._busy = False
                    self.status_var.set("완료 — 다음 건 입력 후 바로 시작 가능 (브라우저 유지)")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _append_log(self, text: str):
        tag = ""
        t = text.lstrip()
        if t.startswith("[v]") or "✓" in t or t.startswith("[결과]"):
            tag = "ok"
        elif t.startswith("[!]"):
            tag = "fail"
        elif t.startswith("[i]"):
            tag = "info"
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")

    def _set_phase(self, key: str, status: str, person: int | None = None):
        """단계×신고인 셀 상태 갱신. 완료(ok)되면 체크를 자동으로 풀어
        '시작'을 다시 눌렀을 때 실패·미완료분만 재시도되게 한다(재제출 방지)."""
        targets = [person] if person is not None else \
                  [i for (k, i) in self._cells if k == key]
        for i in targets:
            cell = self._cells.get((key, i))
            if cell is None:
                continue
            cell.set_status(status)
            if status == "ok":
                v = self._cell_vars.get((key, i))
                if v is not None and v.get():
                    v.set(False)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
