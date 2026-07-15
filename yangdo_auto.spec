# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 양도소득세(홈택스+위택스) 신고 자동화 GUI 배포 빌드.

onedir 빌드. Chromium은 동봉하지 않고 첫 실행 때 자동 다운로드(browser_setup.py)
→ 배포 zip이 ~240MB에서 수십 MB로 줄어 업데이트가 가볍다. (v1.0.0부터)
Chromium은 공용 위치(%LOCALAPPDATA%\\ms-playwright)에 설치돼 ingunbi/vat 등 같은 방식의
다른 프로그램과 공유된다.
빌드:  pyinstaller yangdo_auto.spec --noconfirm
산출:  dist/YangdoAuto/  (이 폴더를 통째로 압축해 배포)
"""
from PyInstaller.utils.hooks import collect_all

# Playwright 드라이버(node.exe + cli 등) 수집 — 'install chromium' 실행에도 필요
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

hiddenimports = pw_hidden + [
    "pywinauto", "pywinauto.findwindows", "comtypes",
    "win32api", "win32con", "win32gui", "win32process", "pywintypes",
    "pypdf",
]

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=pw_binaries,
    datas=pw_datas,
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
