"""Phase 공통 타입 — 입력 묶음과 결과.

각 phase는 독립 모듈(KEY/LABEL/run)로 개발하고, 동일한 Inputs/PhaseResult를 공유한다.
phase 내부 세부 단계는 단정짓지 않는다(라이브 화면 보며 단계별로 채움).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Inputs:
    """실행 전에 GUI에서 한 번에 받아두는 입력. phase가 필요한 것만 골라 쓴다."""
    name_label: str = "납세자"          # 파일명/로그용 라벨
    wetax_convert_file: str = ""        # 위택스 지방세 변환파일
    hometax_convert_file: str = ""      # 홈택스 양도세 변환파일
    seller_rrn: str = ""                # 양도인 주민등록번호 (부속서류용)
    attach_folder: str = ""             # 부속서류 폴더 (안의 파일 전부 첨부)
    output_dir: str = ""                # PDF 저장 경로
    output_mode: str = "pdf"            # "pdf"(저장) | "print"(출력)
    auto_submit: bool = True            # 파일변환신고 제출까지 자동 여부
    disclose_personal_info: bool = True # 서류 출력 시 개인정보 공개 여부(디폴트 공개)
    include_name: bool = False          # 서류 파일명에 성명 포함(공동명의 등)
    merge_docs: bool = False            # 접수증+신고서들 PDF 병합([접수증&신고서]) 여부
    delete_merged_sources: bool = False  # 병합 성공 시 개별 접수증·신고서 원본 삭제
    napbu_wait_sec: int = 60            # 위택스 납부서 출력 전 가상계좌 생성 대기(초)
    # 대기 중 사용자 개입용 콜백(GUI가 주입). 가상계좌는 PDF 문서 안 값이라 프로그램이
    # 생성 여부를 알 수 없어, 눈으로 확인한 사용자가 즉시 진행/연장을 지시한다.
    napbu_skip_check: object = None      # () -> bool  : True면 남은 대기를 건너뜀
    napbu_extend_check: object = None    # () -> int   : 반환한 초만큼 대기 연장


@dataclass
class PhaseResult:
    key: str
    label: str
    ok: bool = False
    receipt_no: str = ""
    outputs: list[str] = field(default_factory=list)   # 저장된 PDF 경로 등
    reason: str = ""
