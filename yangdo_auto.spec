# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 양도소득세 자동화 GUI 배포 빌드.

onedir 빌드 + Playwright Chromium 동봉(인터넷/설치 불필요).
빌드:  pyinstaller yangdo_auto.spec --noconfirm
산출:  dist/YangdoAuto/  (이 폴더를 통째로 압축해 배포)
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# Playwright 드라이버(node.exe + cli 등) 수집
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

# 동봉할 브라우저: ms-playwright의 Chromium + winldd(의존성 검사기). headless_shell/ffmpeg는 제외.
MS = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
browser_datas = []
for name in ("chromium-1217", "winldd-1007"):
    src = MS / name
    if src.exists():
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src).parent
                dest = f"playwright-browsers/{name}" if str(rel) == "." else f"playwright-browsers/{name}/{rel}"
                browser_datas.append((str(f), dest))

hiddenimports = pw_hidden + [
    "pywinauto", "pywinauto.findwindows", "comtypes",
    "win32api", "win32con", "win32gui", "win32process", "pywintypes",
    "pypdf",
]

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=pw_binaries,
    datas=pw_datas + browser_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytesseract", "PIL", "numpy", "cv2", "openpyxl", "matplotlib", "pandas", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YangdoAuto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # GUI 앱 — 콘솔창 숨김
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="YangdoAuto",
)
