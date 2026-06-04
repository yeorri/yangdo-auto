"""양도소득세 홈택스+위택스 신고 자동화 — Tkinter GUI (모던 테마).

phase를 각각 켜고(선택 실행) 전부 켜서(연속 실행) 돌릴 수 있다. 기본 순서는 레지스트리 순.
순수 Tkinter Canvas로 그린 커스텀 테마(외부 의존성 없음): 다크 헤더 + 화이트 카드 +
인디고 액센트, iOS식 토글 스위치, 둥근 버튼, 상태 pill, 콘솔형 로그.

실행:  python gui.py
"""
from __future__ import annotations

import os
import sys

# 배포(frozen exe)면 동봉된 Chromium을 Playwright가 쓰도록 — 어떤 playwright import보다 먼저.
if getattr(sys, "frozen", False):
    _base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          os.path.join(_base, "playwright-browsers"))

import asyncio
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from automation import ALL_PHASES, Inputs, run_pipeline

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


# ─────────────────────────── 앱 ───────────────────────────
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("양도소득세 신고 자동화")
        root.geometry("1120x940")
        root.minsize(1000, 760)
        root.configure(bg=BG)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Vertical.TScrollbar", background=TRACK, troughcolor=BG,
                        bordercolor=BG, arrowcolor=MUTE, relief="flat")

        self.events: queue.Queue = queue.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.worker: threading.Thread | None = None
        self._stop = False
        self._phase_vars: dict[str, tk.BooleanVar] = {}
        self._phase_pills: dict[str, Pill] = {}

        self._build_ui()
        self.root.after(100, self._poll)

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

    def _card(self, parent, title, subtitle=None, expand=False):
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
        return c

    def _build_phase_card(self, parent, expand=False):
        c = self._card(parent, "실행 단계", "전부 체크 = 연속 실행 · 일부만 체크 = 선택 실행", expand=expand)
        for i, mod in enumerate(ALL_PHASES, 1):
            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", padx=16, pady=2)
            var = tk.BooleanVar(value=True)
            self._phase_vars[mod.KEY] = var
            Toggle(row, var, CARD).pack(side="left")
            site = getattr(mod, "SITE", "")
            if site in SITE_BADGE:
                bgc, fgc = SITE_BADGE[site]
                tk.Label(row, text=site, bg=bgc, fg=fgc, font=(FONT, 8, "bold"),
                         padx=7, pady=1).pack(side="left", padx=(12, 8))
            tk.Label(row, text=f"{i}.  {mod.LABEL}", bg=CARD, fg=INK,
                     font=(FONT, 10)).pack(side="left")
            pill = Pill(row, CARD)
            pill.pack(side="right")
            self._phase_pills[mod.KEY] = pill
        tk.Frame(c, bg=CARD, height=6).pack()

    def _build_input_card(self, parent):
        c = self._card(parent, "입력 정보")
        form = tk.Frame(c, bg=CARD)
        form.pack(fill="x", padx=16, pady=(2, 12))
        form.columnconfigure(1, weight=1)

        self.var_name = tk.StringVar()
        self.var_wt_file = tk.StringVar()
        self.var_ht_file = tk.StringVar()
        self.var_rrn = tk.StringVar()
        self.var_folder = tk.StringVar()
        self.var_outdir = tk.StringVar()  # 기본값 비움 — PDF 모드에서 필수 검증 대상

        self._field(form, "신고인 성명", self.var_name, hint="파일명/로그용 라벨")
        self._field(form, "위택스 변환파일", self.var_wt_file, pick="file", hint=".Y13 / .Y11")
        self._field(form, "홈택스 변환파일", self.var_ht_file, pick="file", hint=".01")
        self._field(form, "양도인 주민번호", self.var_rrn, hint="부속서류·신고내역 조회용")
        self._field(form, "부속서류 폴더", self.var_folder, pick="dir", hint="폴더 내 파일 전부 첨부")
        self._field(form, "PDF 저장 폴더", self.var_outdir, pick="dir")

    def _field(self, parent, label, var, pick=None, hint=None):
        r = parent.grid_size()[1]
        lab = tk.Frame(parent, bg=CARD)
        lab.grid(row=r, column=0, sticky="w", padx=(2, 12), pady=3)
        tk.Label(lab, text=label, bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        if hint:
            tk.Label(lab, text=hint, bg=CARD, fg=MUTE, font=(FONT, 8)).pack(anchor="w")
        e = tk.Entry(parent, textvariable=var, font=(FONT, 10), bg="#FFFFFF", fg=INK,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, insertbackground=INK)
        e.grid(row=r, column=1, sticky="ew", ipady=5, pady=3)
        # 긴 경로는 끝부분(파일명/마지막 폴더)이 보이도록 — 입력칸 떠날 때 끝으로 스크롤.
        e.bind("<FocusOut>", lambda ev, ent=e: ent.xview_moveto(1.0))
        if pick:
            def cmd(v=var, ent=e):
                (self._pick_dir if pick == "dir" else self._pick_file)(v)
                ent.xview_moveto(1.0)
            RButton(parent, "찾기", cmd, kind="mini", bg=CARD, width=54, height=32,
                    font=(FONT, 9, "bold")).grid(row=r, column=2, padx=(8, 2))

    def _build_option_card(self, parent, expand=False):
        c = self._card(parent, "옵션", expand=expand)
        opt = tk.Frame(c, bg=CARD)
        opt.pack(fill="x", padx=16, pady=(2, 12))

        self.var_mode = tk.StringVar(value="pdf")
        self.var_incname = tk.BooleanVar(value=False)
        self.var_disclose = tk.BooleanVar(value=True)
        self.var_merge = tk.BooleanVar(value=False)
        self.var_napbu_wait = tk.StringVar(value="3")

        seg = tk.Frame(opt, bg=CARD)
        seg.pack(fill="x", pady=(0, 4))
        tk.Label(seg, text="서류 처리", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        Segmented(seg, self.var_mode, [("pdf", "PDF 저장"), ("print", "출력(인쇄)")], CARD).pack(side="right")

        self._switch(opt, "파일명에 성명 포함", "공동명의 등 구분이 필요할 때", self.var_incname)
        self._switch(opt, "서류 개인정보 공개", "출력 서류에 주민번호 등 공개 표시", self.var_disclose)
        self._switch(opt, "접수증·신고서 병합", "접수증+양도세+지방세 신고서를 [접수증&신고서]로 (PDF 저장 시)", self.var_merge)

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
        watch = [self.var_name, self.var_wt_file, self.var_ht_file, self.var_rrn,
                 self.var_folder, self.var_outdir, self.var_mode, self.var_incname]
        for v in watch:
            v.trace_add("write", lambda *a: self._refresh_validation())
        for v in self._phase_vars.values():
            v.trace_add("write", lambda *a: self._refresh_validation())
        self._refresh_validation()

    def _missing(self) -> list[str]:
        """현재 선택/입력 기준 부족한 필수 항목 라벨 목록(없으면 빈 리스트)."""
        sel = {k for k, v in self._phase_vars.items() if v.get()}
        if not sel:
            return ["실행 단계 선택"]
        miss: list[str] = []

        def need(var, label):
            if not var.get().strip():
                miss.append(label)

        # 신고인 성명: 위택스 출력(신고서/납부서)은 신고내역 행을 이름으로 찾으므로 항상 필요,
        # 홈택스 출력은 '파일명에 성명 포함' 옵션을 켰을 때만 필요. 신고/부속서류는 불필요(로그 라벨용).
        wetax_out = sel & {"wetax_docs", "wetax_napbu"}
        hometax_out = sel & {"hometax_docs", "hometax_napbu"}
        if wetax_out or (self.var_incname.get() and hometax_out):
            need(self.var_name, "신고인 성명")
        if "wetax_filing" in sel:
            need(self.var_wt_file, "위택스 변환파일")
        if "hometax_filing" in sel:
            need(self.var_ht_file, "홈택스 변환파일")
        if sel & {"hometax_attach", "hometax_docs", "hometax_napbu"}:
            digits = "".join(c for c in self.var_rrn.get() if c.isdigit())
            if len(digits) != 13:
                miss.append("양도인 주민번호(13자리)")
        if "hometax_attach" in sel:
            need(self.var_folder, "부속서류 폴더")
        if (sel & {"hometax_docs", "wetax_docs", "hometax_napbu", "wetax_napbu"}) \
                and self.var_mode.get() == "pdf":
            need(self.var_outdir, "PDF 저장 폴더")

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
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("실행 중", "이미 진행 중입니다.")
            return

        selected = [k for k, v in self._phase_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("단계 없음", "실행할 단계를 하나 이상 켜세요.")
            return

        inp = Inputs(
            name_label=self.var_name.get().strip() or "납세자",
            wetax_convert_file=self.var_wt_file.get().strip(),
            hometax_convert_file=self.var_ht_file.get().strip(),
            seller_rrn="".join(c for c in self.var_rrn.get() if c.isdigit()),
            attach_folder=self.var_folder.get().strip(),
            output_dir=self.var_outdir.get().strip(),
            output_mode=self.var_mode.get(),
            auto_submit=True,  # 제출까지 자동(토글 제거). 검증까지만 원하면 코드/요청으로 조정.
            disclose_personal_info=self.var_disclose.get(),
            include_name=self.var_incname.get(),
            merge_docs=self.var_merge.get(),
            napbu_wait_sec=self._napbu_wait_seconds(),
        )

        self._stop = False
        for k in self._phase_vars:
            self._set_phase(k, "idle")
        self.log_text.delete("1.0", "end")
        self.status_var.set("실행 중…")

        def emit(kind, **kw):
            self.events.put({"kind": kind, **kw})

        async def main():
            try:
                await run_pipeline(selected, inp, emit, stop_check=lambda: self._stop)
            except Exception as e:  # noqa: BLE001
                emit("log", text=f"[!] 예외: {e}")
            finally:
                emit("done")

        def thread_target():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(main())
            finally:
                self.loop.close()

        self.worker = threading.Thread(target=thread_target, daemon=True)
        self.worker.start()

    def _stop_clicked(self):
        self._stop = True
        self.status_var.set("중단 요청됨")
        self.events.put({"kind": "log", "text": "[i] 중단 요청 — 현재 단계 후 멈춥니다."})

    # ── 큐 폴링 ──
    def _poll(self):
        try:
            while True:
                evt = self.events.get_nowait()
                kind = evt["kind"]
                if kind == "log":
                    self._append_log(evt["text"])
                elif kind == "phase":
                    self._set_phase(evt["key"], evt["status"])
                elif kind == "status":
                    self.status_var.set(evt.get("text", ""))
                elif kind == "done":
                    self.status_var.set("완료")
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

    def _set_phase(self, key: str, status: str):
        pill = self._phase_pills.get(key)
        if pill:
            pill.set(status)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
