# 설계 의사결정 기록 (ADR)

## 1. 무엇을 만드는가
세무대리인이 **양도소득세(홈택스)**와 **지방소득세 양도분(위택스)**을 신고·서류처리하는
과정을 자동화하는 Windows 데스크톱 프로그램. 변환파일(.01 등)은 사용자가 양도박사 등으로
미리 생성(1파일=1건).

## 2. 스택 — Python + Playwright + Tkinter
같은 사무소의 성공·배포된 홈택스 자동화 `incometax_printing`(종소세 인쇄)과 동일 스택.
패턴 모음 `reference/AUTOMATION_PATTERNS.md`를 복사해 재사용. 이전 실패작(yangdose-auto:
Selenium+디버깅모드+pyautogui)은 참고만.

## 3. 브라우저 — `launch_persistent_context` (+ `--kiosk-printing`)
자체 Chromium을 영구 프로필(`.profile`)로 실행 → 한 번 로그인하면 세션 유지.
로그인은 사용자가 직접. PDF 저장 모드일 때 기본 프린터를 'Microsoft Print to PDF'로 sticky.

## 4. ★ Phase 단위 독립 개발 + 선택/연속 실행 (핵심 구조)
큰 흐름을 **독립적인 phase**로 쪼개고, GUI에서 일부만(선택 실행) 또는 전부(연속 실행) 돌린다.
phase 내부 세부 단계는 미리 단정하지 않고 라이브 화면 보며 채운다.

**기본 순서** (GUI 토글 가능):
1. **위택스 지방세 파일변환신고** — 납부서 가상계좌가 늦게 떠서 먼저 하는 게 유리
2. **홈택스 양도세 파일변환신고** — 변환파일 미리 입력
3. **홈택스 부속서류 제출** — 양도인 주민번호 미리 받고, 폴더 안 파일 전부 첨부
4. **홈택스 서류 PDF저장/출력** — 미리 설정한 이름·경로로 저장 or 출력(옵션)
5. **위택스 지방세 서류 PDF저장/출력** — 동일 옵션

1·2는 구조가 동일해 `filing.file_convert_filing()` 공유. 3·4·5는 각자 모듈.
각 phase 모듈은 `KEY / LABEL / async run(ctx, inp, emit, stop_check)` 인터페이스를 따른다.

## 4-1. Phase 격리 — 진입 시 하드 리셋
각 phase는 **"로그인된 홈에서 시작"**이라는 단 하나의 가정만 갖는다(배치/독립 실행 동일).
이를 위해 phase 진입 내비게이션이 **시작에서 `page.goto`로 하드 리셋**한다:
- 홈택스: `reset_to_home()` = `goto(홈택스 홈)` → 메뉴로 self-navigate (WebSquare SPA라 대상 URL 직접 이동 불가)
- 위택스: `navigate_to_filing()` = `goto(B070301M10.do)` (직접 대상 URL = 리셋+이동 한 번에)

goto는 모달·오버레이·DOM 잔재를 통째로 날려, 앞 phase가 모달 띄운 채 죽어도 다음 phase가 깨끗하게
시작한다 → 진입화면 분기/예외처리 불필요. 비용은 phase당 홈 1회 로드(수 초)로 무시할 수준.

## 5. 서류 처리 — PDF저장 vs 출력 옵션
`Inputs.output_mode`("pdf"|"print")로 선택. pdf면 sticky+pywinauto로 지정 경로·이름 저장,
print면 기본 프린터로 출력. 자동 제출(`auto_submit`)은 기본 ON(서류 PDF로 사후검증 가능).

## 6. 파일 구조
```
gui.py                     Tkinter 진입점 (phase 체크박스 선택/연속, 입력, queue 패턴)
automation/
  browser.py               launch_persistent_context + kiosk + PDF sticky + find_page/open_homepages
  hometax.py               홈택스: reset_to_home/navigate_to_file_convert/inject_convert_file
                           /verify_and_wait/submit_filing (텍스트 기반, 라이브 검증)
  wetax.py                 위택스: navigate_to_filing(직접 URL)/inject_file/next_and_verify/submit_filing
  pdf_save.py              접수증/서류 PDF 저장 — OS 다이얼로그 pywinauto + mtime 검증
  pipeline.py              선택 phase를 기본 순서대로 한 브라우저에서 실행
  util.py                  websquare_click 다층전략 등
  phases/
    base.py                Inputs / PhaseResult
    __init__.py            ALL_PHASES 레지스트리(기본 순서) / PHASE_BY_KEY
    wetax_filing.py        ① 위택스 파일변환신고
    hometax_filing.py      ② 홈택스 파일변환신고
    hometax_attach.py      ③ 홈택스 부속서류 제출 (folder, 주민번호)  ← 골격
    hometax_print.py       ④ 홈택스 서류 PDF/출력                      ← 골격
    wetax_print.py         ⑤ 위택스 서류 PDF/출력                      ← 골격
reference/AUTOMATION_PATTERNS.md
```

## 7. 현재 상태 / 다음 할 일
- 브라우저 실행+로그인 대기+PDF 저장 기계는 동작(검증된 코드). phase 골격·레지스트리·GUI 완성.
- **실제 셀렉터(SiteConfig.sel_*, 각 phase의 SEL_*)와 phase 3·4·5 내부 로직은 미구현(TODO).**
- 다음: phase 하나씩, 라이브 화면 보며 사용자가 단계별로 알려주는 대로 채운다.
  (먼저 ① 위택스 또는 ② 홈택스 파일변환신고부터 셀렉터 채우는 게 자연스러움)
