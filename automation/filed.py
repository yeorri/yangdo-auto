"""신고 기록 — 변환파일 → 홈택스 접수번호. 실행이 끝나도 남는다.

왜 필요한가: 같은 사람의 신고건이 조회 화면에 여러 줄 뜨면(같은 달에 두 채를 판 경우 등)
'첫 행'·'마지막 버튼' 같은 위치로는 어느 건인지 알 수 없다(2026-11-18 정미희 건: 2번 신고의
납부서로 1번 신고 것이 저장되고, 부속서류는 1번 건을 보고 '이미 제출됨'으로 오판).
신고할 때 접수번호를 적어두면, 나중에 그 변환파일로 출력·부속서류만 다시 돌려도 같은 행을 찾는다.

저장 위치: app_data_dir()/filed.json  (이름·주민번호는 넣지 않는다 — 경로와 접수번호만)
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from .browser import app_data_dir

_PATH = app_data_dir() / "filed.json"


def _key(convert_file: str) -> str:
    return os.path.normcase(os.path.abspath(convert_file)) if convert_file else ""


def _load() -> dict:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def remember(convert_file: str, receipt_no: str) -> None:
    """신고 직후 호출. 같은 변환파일로 다시 신고하면 새 접수번호로 덮어쓴다."""
    k = _key(convert_file)
    if not k or not receipt_no:
        return
    d = _load()
    d[k] = {"receipt": receipt_no, "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    try:
        _PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass        # 기록 실패가 신고 흐름을 깨면 안 된다


def recall(convert_file: str) -> str:
    """이 변환파일로 신고했던 접수번호(없으면 '')."""
    return (_load().get(_key(convert_file)) or {}).get("receipt", "")
