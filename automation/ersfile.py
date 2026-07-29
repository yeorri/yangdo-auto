"""전자신고 변환파일(.01 / .Y13 / .Y11) 읽기 — 성명·주민번호 등 자동 추출.

양도박사가 만든 변환파일은 CP949 텍스트 + 고정길이 레코드다.
`.01`(홈택스 양도세)의 `01` 레코드에 신고인 정보가 들어 있어, 파일만 고르면
성명·주민번호를 자동으로 채울 수 있다(오타 방지 + 입력 단계 축소).

레코드 구조 (검증: ERSDATA .01 7건 + .Y13):
    공통 [0:2] 레코드 타입, [2:9] 서식/대리인 코드(C116300), [9:22] 주민등록번호 13자리
    - `.01`(홈택스)  : **01** 레코드가 신고인 — 주민번호 뒤 'YYYYMM성명'
    - `.Y13/.Y11`(위택스): 01 레코드는 세무대리인이고 **02** 레코드가 신고인 — 주민번호 뒤 '성명'
    → 두 형식 모두 "[9:22]가 13자리 숫자인 첫 레코드"를 찾고, 그 뒤 첫 한글 덩어리를 성명으로.
      주민번호로 사람을 묶으면 동명이인도 안전하다.
"""
from __future__ import annotations

import re
from pathlib import Path

_YM_NAME = re.compile(r"(20\d{4})([가-힣]{2,10})")
_NAME = re.compile(r"([가-힣]{2,10})")


def read_text(path) -> str:
    """변환파일을 텍스트로 읽기(CP949 우선, 실패 시 UTF-8)."""
    b = Path(path).read_bytes()
    for enc in ("cp949", "utf-8"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("cp949", errors="replace")


def parse_convert_file(path) -> dict:
    """변환파일에서 신고인 정보 추출. 실패해도 예외 없이 빈 값 반환.

    반환: {name, rrn, report_ym, ok}
      name      신고인 성명
      rrn       주민등록번호 13자리(하이픈 없음)
      report_ym 신고연월 'YYYYMM'
    """
    out = {"name": "", "rrn": "", "report_ym": "", "ok": False}
    try:
        text = read_text(path)
    except Exception:
        return out
    # 신고인 레코드 = [9:22]가 13자리 숫자인 첫 레코드
    # (.01은 01 레코드, .Y13은 02 레코드 — 01은 세무대리인이라 여기서 걸러짐)
    rec = ""
    for ln in text.splitlines():
        if len(ln) >= 22 and ln[9:22].isdigit():
            rec = ln
            break
    if not rec:
        return out
    out["rrn"] = rec[9:22]
    rest = rec[22:]
    m = _YM_NAME.search(rest)          # .01: 'YYYYMM성명'
    if m:
        out["report_ym"] = m.group(1)
        out["name"] = m.group(2).strip()
    else:
        n = _NAME.search(rest)         # .Y13: 주민번호 뒤 바로 성명
        if n:
            out["name"] = n.group(1).strip()
    out["ok"] = bool(out["name"] and out["rrn"])
    return out


HOMETAX_EXTS = (".01",)
WETAX_EXTS = (".Y13", ".Y11")


def parse_filename(path) -> dict:
    """파일명에서 양도연월·자산종류 추출.

    양도박사 규칙: {양도|지방소득세}_{성명}_{자산}_{양도연월}_{코드}.{확장자}
      예) 양도_홍길동_부동산_202608_C116300.01
    자산은 부동산/주식 등으로 바뀔 수 있으나 **위치가 같아** 인덱스로 뽑는다.
    ⚠ 파일 내부의 YYYYMM은 '신고 작성 시점'이라 양도연월과 다르다 — 목록 표시는 파일명 기준.
    반환: {trade_ym, asset, name_in_file} (규칙이 다르면 빈 값)
    """
    parts = Path(path).stem.split("_")
    out = {"trade_ym": "", "asset": "", "name_in_file": ""}
    if len(parts) >= 4:
        out["name_in_file"] = parts[1]
        out["asset"] = parts[2]
        if re.fullmatch(r"20\d{4}", parts[3]):
            out["trade_ym"] = parts[3]
    return out


def group_by_person(paths) -> list[dict]:
    """고른 변환파일들을 신고건별로 묶는다. 확장자로 홈택스/위택스를 가르고,
    **주민번호+양도연월**로 같은 건을 묶는다.

    주민번호만으로 묶으면 같은 사람의 다른 양도건(202606/202608)이 한 줄로 합쳐지므로
    양도연월(파일명)까지 키에 넣는다. 동명이인은 주민번호로 구분된다.
    반환: [{name, rrn, trade_ym, hometax, wetax, mtime}, ...] (처음 등장 순)
    """
    rows: list[dict] = []
    index: dict[str, dict] = {}
    for p in paths:
        path = Path(p)
        info = parse_convert_file(path)
        fn = parse_filename(path)
        rrn, name = info["rrn"], info["name"] or fn["name_in_file"]
        key = f"{rrn}|{fn['trade_ym']}" if rrn else f"?{path.stem}"
        row = index.get(key)
        if row is None:
            row = {"name": name, "rrn": rrn, "trade_ym": fn["trade_ym"],
                   "asset": fn["asset"], "hometax": "", "wetax": "", "mtime": 0.0}
            index[key] = row
            rows.append(row)
        elif name and not row["name"]:
            row["name"] = name
        ext = path.suffix.upper()
        if ext in [e.upper() for e in HOMETAX_EXTS]:
            row["hometax"] = str(path)
        elif ext in [e.upper() for e in WETAX_EXTS]:
            row["wetax"] = str(path)
        try:
            row["mtime"] = max(row["mtime"], path.stat().st_mtime)
        except Exception:
            pass
    return rows


def scan_folder(folder) -> list[dict]:
    """변환파일 폴더를 스캔해 신고건 목록을 최근 수정순으로 반환.

    사용자가 폴더를 한 번 지정해두면 '신고인 선택' 목록을 여기서 만든다.
    (양도박사가 재변환 시 덮어쓰므로 같은 건은 한 줄로 유지된다.)
    """
    root = Path(folder)
    if not root.is_dir():
        return []
    exts = [e.upper() for e in HOMETAX_EXTS + WETAX_EXTS]
    paths = [p for p in root.iterdir()
             if p.is_file() and p.suffix.upper() in exts]
    rows = group_by_person(paths)
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def find_sibling(convert_path, exts=(".Y13", ".Y11")) -> str:
    """같은 폴더에서 이름이 대응하는 위택스 변환파일 찾기.

    양도박사 파일명 규칙: 양도_{성명}_부동산_{YYYYMM}_{코드}.01
                          지방소득세_{성명}_부동산_{YYYYMM}_{코드}.Y13
    성명+연월이 같은 파일을 우선 매칭. 없으면 빈 문자열.
    """
    p = Path(convert_path)
    if not p.exists():
        return ""
    parts = p.stem.split("_")
    if len(parts) < 4:
        return ""
    name, ym = parts[1], parts[3]
    best = ""
    for cand in p.parent.iterdir():
        if not cand.is_file() or cand.suffix.upper() not in [e.upper() for e in exts]:
            continue
        cp = cand.stem.split("_")
        if len(cp) >= 4 and cp[1] == name and cp[3] == ym:
            return str(cand)          # 성명+연월 일치 = 확실
        if len(cp) >= 2 and cp[1] == name and not best:
            best = str(cand)          # 성명만 일치 = 차선
    return best


def guess_folders(name: str, work_root: str) -> dict:
    """업무 폴더에서 해당 납세자의 부속서류/저장 폴더 후보 추정.

    폴더명 규칙이 제각각(김수정/, 김수진&김석/, 김지연(이기옥)/, ...)이라
    '이름이 포함된 폴더'를 찾고 그 안에서 '부속'/'신고납부' 들어간 하위 폴더를 고른다.
    확정이 아니라 후보 — 사용자가 GUI에서 언제든 수정할 수 있어야 한다.
    반환: {attach, output} (없으면 빈 문자열)
    """
    res = {"attach": "", "output": ""}
    if not name or not work_root:
        return res
    root = Path(work_root)
    if not root.is_dir():
        return res
    person = next((d for d in root.iterdir() if d.is_dir() and name in d.name), None)
    if person is None:
        return res
    subs = [d for d in person.iterdir() if d.is_dir()]
    # 부속서류: 이름이 붙은 것(부속서류_홍길동) 우선 — 공동명의 폴더 대응
    for d in subs:
        if "부속" in d.name and name in d.name:
            res["attach"] = str(d)
            break
    if not res["attach"]:
        res["attach"] = next((str(d) for d in subs if "부속" in d.name), "")
    for d in subs:
        if ("신고납부" in d.name or "서류" in d.name) and name in d.name:
            res["output"] = str(d)
            break
    if not res["output"]:
        res["output"] = next((str(d) for d in subs
                              if "신고납부" in d.name or "서류" in d.name), "")
    return res
