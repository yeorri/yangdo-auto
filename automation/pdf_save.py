"""Windows '다른 이름으로 저장' 다이얼로그 자동 채우기 (incometax_printing 검증판 이식).

Microsoft Print to PDF / Chrome PDF 저장에서 인쇄 trigger 후 뜨는 다이얼로그를
pywinauto(win32)로 잡아 파일명(전체경로) 입력 + 저장. 포커스 안 가져감(WM_SETTEXT),
덮어쓰기 처리, mtime 검증으로 false-positive 차단.
"""
import time
from pathlib import Path

# Windows 버전/언어별 저장 다이얼로그 제목 변형 모두 매칭
SAVE_DIALOG_TITLE_RE = (
    r"(다(른|음) 이름으로.*저장"
    r"|Save Print Output As|Save As)"
)


def wait_for_save_dialog(timeout_sec: float = 30.0, poll_interval: float = 0.3):
    """저장 다이얼로그 핸들을 polling으로 찾아 반환(win32 backend). 못 찾으면 None."""
    from pywinauto import findwindows

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            handles = findwindows.find_windows(title_re=SAVE_DIALOG_TITLE_RE)
            if handles:
                return handles[0]
        except Exception:
            pass
        time.sleep(poll_interval)
    return None


def _send_with_timeout(hwnd: int, msg: int, wParam: int, lParam, timeout_ms: int = 1000):
    """SendMessageTimeoutW — block 시간을 timeout_ms로 제한(hang 방지)."""
    import ctypes
    user32 = ctypes.windll.user32
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_size_t(0)
    user32.SendMessageTimeoutW(
        hwnd, msg, wParam, lParam, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result),
    )
    return result.value


def fill_and_save(target_path, timeout_sec: float = 30.0, log=None) -> tuple:
    """뜨는 저장 다이얼로그를 잡아 target_path로 저장(백그라운드). (성공, 에러메시지) 반환.

    ComboBoxEx32→ComboBox→Edit 모든 레이어에 WM_SETTEXT → WM_COMMAND IDOK
    → 덮어쓰기 처리 → 안 닫히면 저장 Button BM_CLICK → 파일 mtime 검증.
    """
    import ctypes

    target_path = Path(target_path)
    _log = log if log is not None else (lambda s: None)

    user32 = ctypes.windll.user32
    WM_SETTEXT = 0x000C
    WM_COMMAND = 0x0111
    BM_CLICK = 0x00F5
    IDOK = 1

    start_ts = time.time()

    _log(f"    PDF: 다이얼로그 대기 중... (최대 {int(timeout_sec)}초)")
    handle = wait_for_save_dialog(timeout_sec=timeout_sec)
    if handle is None:
        return False, f"다이얼로그가 {timeout_sec}초 안에 뜨지 않음"
    _log(f"    PDF: 다이얼로그 잡음 (handle={handle})")

    try:
        from pywinauto import Application
        app = Application(backend="win32").connect(handle=handle)
        dlg = app.window(handle=handle)

        path_wchar = ctypes.c_wchar_p(str(target_path))
        targets_set = []
        try:
            for combo_ex in dlg.descendants(class_name="ComboBoxEx32"):
                try:
                    _send_with_timeout(int(combo_ex.handle), WM_SETTEXT, 0, path_wchar, 1200)
                    targets_set.append("ComboBoxEx32")
                except Exception:
                    pass
                for ic in combo_ex.descendants(class_name="ComboBox"):
                    try:
                        _send_with_timeout(int(ic.handle), WM_SETTEXT, 0, path_wchar, 1200)
                        targets_set.append("ComboBox")
                    except Exception:
                        pass
                for ie in combo_ex.descendants(class_name="Edit"):
                    try:
                        _send_with_timeout(int(ie.handle), WM_SETTEXT, 0, path_wchar, 1200)
                        targets_set.append("InnerEdit")
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            for edit in dlg.descendants(class_name="Edit"):
                try:
                    _send_with_timeout(int(edit.handle), WM_SETTEXT, 0, path_wchar, 800)
                except Exception:
                    continue
        except Exception:
            pass

        if not targets_set:
            _log("    PDF: [!] ComboBoxEx32 set 대상 못 찾음 — Edit fallback만 시도됨")
        time.sleep(0.3)

        _send_with_timeout(int(handle), WM_COMMAND, IDOK, 0, 1500)
        _log("    PDF: WM_COMMAND IDOK 전송")

        time.sleep(0.3)
        _handle_overwrite_dialog(timeout_sec=5.0, log=_log)

        # 다이얼로그 닫힘 확인
        deadline = time.time() + 5
        closed = False
        while time.time() < deadline:
            if not user32.IsWindow(int(handle)):
                closed = True
                break
            time.sleep(0.2)

        if not closed:
            try:
                for btn in dlg.descendants(class_name="Button"):
                    try:
                        if (btn.window_text() or "").strip() in ("저장(&S)", "저장", "Save", "OK"):
                            user32.SendMessageW(int(btn.handle), BM_CLICK, 0, 0)
                            _log("    PDF: BM_CLICK fallback(저장)")
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(0.5)
            _handle_overwrite_dialog(timeout_sec=3.0, log=_log)

        # mtime 검증 (start_ts 이후 = 이번에 새로 저장됨)
        deadline = time.time() + 15
        while time.time() < deadline:
            if target_path.exists():
                try:
                    if target_path.stat().st_mtime >= start_ts - 1:
                        _log(f"    PDF: ✓ 저장 완료 ({target_path.name})")
                        return True, None
                except Exception:
                    pass
            time.sleep(0.2)

        if target_path.exists():
            try:
                diff = time.time() - target_path.stat().st_mtime
                return False, f"파일이 존재하지만 새로 저장되지 않음 (mtime {diff:.0f}초 전)"
            except Exception:
                pass
        return False, "OK 보냈으나 파일이 생성되지 않음 (다이얼로그 형식 다를 가능성)"

    except Exception as e:
        return False, f"다이얼로그 자동화 예외: {e}"


def _handle_overwrite_dialog(timeout_sec: float = 5.0, log=None) -> bool:
    """파일 존재 시 뜨는 덮어쓰기 확인 다이얼로그를 잡아 '예' 클릭."""
    import ctypes
    from pywinauto import Application, findwindows

    user32 = ctypes.windll.user32
    BM_CLICK = 0x00F5
    _log = log if log is not None else (lambda s: None)
    overwrite_title_re = r"(다(른|음) 이름으로 저장 확인|Confirm Save As)"

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            handles = findwindows.find_windows(title_re=overwrite_title_re)
        except Exception:
            handles = []
        for h in handles:
            try:
                dlg = Application(backend="win32").connect(handle=h).window(handle=h)
                for btn in dlg.descendants(class_name="Button"):
                    try:
                        if (btn.window_text() or "").strip() in ("예(&Y)", "예", "Yes"):
                            user32.SendMessageW(int(btn.handle), BM_CLICK, 0, 0)
                            _log("    PDF: 덮어쓰기 '예' 자동 클릭")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        time.sleep(0.2)
    return False


def fmt_due(date_str: str) -> str:
    """'2026-08-31' → '26.08.31'. 날짜 없으면 ''."""
    import re
    m = re.search(r"(?:20)?(\d\d)-(\d\d)-(\d\d)", date_str or "")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else ""


def doc_name(tag: str, parts=(), include_name: bool = False, name: str = "") -> str:
    """서류 PDF 파일명 생성. 예) tag='납부서', parts=['양도소득세','26.06.30'], name='홍길동'
       → include_name이면 '[납부서]홍길동_양도소득세_26.06.30.pdf', 아니면 '[납부서]양도소득세_26.06.30.pdf'.
    뒤에 오는 항목들은 '_'로 연결, 이름은 태그 바로 뒤."""
    segs = []
    if include_name and name:
        segs.append(name)
    segs += [str(p) for p in parts if p]
    body = "_".join(segs)
    return sanitize_filename(f"[{tag}]{body}") + ".pdf"


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Windows 파일명 금지문자 제거 + 길이 제한."""
    import re
    if not name:
        return "_"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = name.strip(" .")
    name = re.sub(r"\s+", " ", name)
    if not name:
        return "_"
    return name[:max_len].rstrip() if len(name) > max_len else name


def merge_pdfs(src_paths, out_path, log=print) -> bool:
    """여러 PDF를 순서대로 병합해 out_path로 저장. pypdf 사용.

    src_paths 중 실제 존재하는 파일만 순서 유지하며 병합. 2개 미만이면 건너뜀(False).
    """
    paths = [Path(p) for p in src_paths if p and Path(p).is_file()]
    if len(paths) < 2:
        log(f"[i] 병합 대상 부족({len(paths)}개) — 병합 건너뜀")
        return False
    try:
        from pypdf import PdfWriter
    except ImportError:
        log("[!] pypdf 미설치 — 'pip install pypdf' 후 병합 가능")
        return False
    try:
        writer = PdfWriter()
        for p in paths:
            writer.append(str(p))
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            writer.write(f)
        writer.close()
        log(f"[v] 병합 완료: {out_path.name} ({len(paths)}개)")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"[!] 병합 실패: {str(e)[:80]}")
        return False


# 하위호환: 기존 호출부가 safe_name을 쓰면 sanitize_filename으로 위임
safe_name = sanitize_filename
