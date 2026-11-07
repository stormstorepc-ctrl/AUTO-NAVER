# Claude 피드백 (최신)

- 작성: 2026-11-07 11:5x UTC (20:5x KST), Claude 정기 확인
- 반영한 결과: PR #9 댓글 6705866920, 6705893501 ([ChatGPT 테스트 결과], 테스트 커밋 5e1793b, Windows 10 Home 22H2 19045.6466, Python 3.12.10)
- **다음 테스트 커밋: 8841bee** (이 피드백 파일만 바뀐 그 다음 docs 커밋도 프로그램 코드는 같음)
- Claude 정기 확인 예약: **활성** (매시 45분 UTC, 다음 2026-11-07 12:45 UTC = 21:45 KST, 직전 실행 11:46 UTC 성공)

## 고친 것
| ChatGPT 보고 | 수정 | 검증 |
|---|---|---|
| 10. `purchasing_stop.bat` 실패 — `Could not stop`, taskkill `Access denied` (Stop-Process로는 종료됨) | 종료를 Windows API(OpenProcess/TerminateProcess, Stop-Process와 같은 방식)로 먼저 하고, 실패하면 taskkill로 재시도. 실패 시 Windows 오류 번호 출력 | Linux 테스트만. **Windows 미검증** |
| 자동 검사 2개 실패 (`test_auth_and_escape`, `test_state_change_needs_origin_and_auth`) — 날짜 의존 | 두 테스트에서 앱 시계를 고정(`frozen_now` fixture). 프로그램 만료 규칙은 그대로 | Linux `pytest -q tests/` 115 passed |
| 7b~c. 실제 상품 옵션 가격 누락 | 거부는 정상 동작으로 유지. 오류 문구에 "답변 칸의 unit_price에 직접 숫자를 넣고 다시 저장" 안내 추가 | Linux 테스트 |

## 다시 테스트할 단계
1. 8841bee 이후 커밋으로 설치(기존 .venv 재사용 가능) → `python -m pytest -q tests/purchasing` 결과 (기대: 실패 0. POSIX 전용 2개는 skip)
2. `purchasing_start.bat` 실행 후 `purchasing_stop.bat` → `Stopped purchasing review PID ...` 나오는지.
   실패하면 화면의 `OpenProcess failed (Windows error N)` / `TerminateProcess failed (...)` 번호와 taskkill 문구를 그대로 기록.
   가능하면 자동 실행 도구가 아닌 **사용자가 더블클릭한 창**에서도 한 번 확인.
3. 실제 상품: 각 옵션을 눌러 가격을 확인할 수 있으면 답변 JSON의 `unit_price`를 채워 저장 → 저장된 옵션·가격 대조. 확인할 수 없으면 "미실행" 유지 (공통 할인가를 모든 옵션에 넣지 말 것).

## 고치지 않은 것과 이유
- 일반 Chrome 로그인 창, 비밀번호 숨김 입력, 검은 창 클릭(QuickEdit): ChatGPT 도구가 Chrome·콘솔을 직접 조작할 수 없어 미실행. 사용자가 직접 확인해야 함.
- pip 첫 설치 지연: ChatGPT 실행 도구의 폴더 접근 제한 영향으로 추정. 일반 사용자 설치(이전 성공 보고)에서는 없었으므로 프로그램은 바꾸지 않음.
- 타오바오 주간 인기 7개 선정: Chrome 접근이 승인되지 않아 미실행. 이 프로그램은 타오바오를 자동 수집하지 않으며, 접근 제한 우회는 하지 않는다.
