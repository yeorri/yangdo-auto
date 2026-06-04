# 양도소득세 홈택스 신고 자동화

세무대리인이 **양도소득세**를 홈택스(파일변환 신고) + 위택스(지방소득세)에 신고하는
과정을 자동화하는 Windows 데스크톱 프로그램.

- 스택: **Python + Playwright(Chromium) + Tkinter**
- 브라우저: 영구 프로필 Chromium — 로그인 한 번이면 세션 유지 (`.profile`)
- 설계 배경: [docs/decisions.md](docs/decisions.md) · 패턴 모음: [reference/AUTOMATION_PATTERNS.md](reference/AUTOMATION_PATTERNS.md)

> 같은 사무소의 성공한 종소세 자동화 프로젝트(`incometax_printing`)와 동일 스택·패턴.

## 흐름 — Phase 단위 독립 (선택/연속 실행)

각 단계를 독립 phase로 분리. GUI에서 일부만(선택) 또는 전부(연속) 실행. 기본 순서:

| 순서 | Phase | 메모 |
|---|---|---|
| 1 | 위택스 지방세 파일변환신고 | 납부서 가상계좌 지연 대비 먼저 |
| 2 | 홈택스 양도세 파일변환신고 | 변환파일 미리 입력 |
| 3 | 홈택스 부속서류 제출 | 양도인 주민번호 + 폴더 전체 첨부 |
| 4 | 홈택스 서류 PDF저장/출력 | 옵션 선택 |
| 5 | 위택스 지방세 서류 PDF저장/출력 | 옵션 선택 |

각 사이트 로그인 + 해당 화면까지는 사용자가 직접, 코드는 폼을 감지해 이어받는다.

## 개발 시작

```powershell
pip install -r requirements.txt
python -m playwright install chromium
python gui.py
```

위택스 CAPTCHA OCR을 쓰려면 Tesseract 엔진 별도 설치:
https://github.com/UB-Mannheim/tesseract/wiki

## 사용 흐름

1. `python gui.py` 실행 → "브라우저 실행 + 자동 신고 시작"
2. 뜬 Chromium에서 **홈택스 로그인(첫 실행만)** + 양도세 신고 메뉴까지 진입
3. 폼이 감지되면 Phase 1~5 자동 진행
4. `제출까지 자동` 체크 해제 시 검증/첨부까지만 하고 사람이 최종 확인

## 현재 상태

브라우저 실행 + 로그인 대기 토대는 동작. **양도세/위택스 실제 셀렉터는 미구현(`SEL_*` TODO)** —
실제 화면을 보며 `automation/hometax.py`, `automation/wetax.py`에 채워야 함.

> ⚠ 실제 신고를 제출하는 자동화입니다. 잘못 제출 시 가산세 위험이 있으니
> 충분히 테스트하고, 초기엔 `제출까지 자동`을 끄고 사용하세요.
