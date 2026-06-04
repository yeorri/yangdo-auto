"""양도소득세 홈택스+위택스 신고 자동화 패키지.

phase 단위 독립 개발. 기본 순서·레지스트리는 automation.phases.
"""
from .phases import ALL_PHASES, PHASE_BY_KEY
from .phases.base import Inputs, PhaseResult
from .pipeline import run_pipeline

__all__ = ["ALL_PHASES", "PHASE_BY_KEY", "Inputs", "PhaseResult", "run_pipeline"]
