# Claude 우선 작업 — Windows 설치/시작 오류 해결

작업 T-COMMERCE-001. 2026-11-05 사용자 명시 지시: ChatGPT는 직접 코드 수정을 중단하고 Claude에게 구현을 인계한다.
상태: GitHub 인계 자료. 이 문서의 커밋은 Claude 작업 시작·접수·완료의 증거가 아니다.

## 작업 위치
- 저장소: stormstorepc-ctrl/AUTO-NAVER
- 이어갈 브랜치: claude/purchasing-agent-stage1-20261104 (PR #9)
- 재현 기준 최신 앱 커밋: 1b754b4c95405eb8472913166eddb82c2c07af73
- ChatGPT가 작성하던 미반영 PowerShell 대체 코드는 중단·별도 보존했고 이 브랜치에 포함하지 않았다. 구현은 Claude가 담당한다.

## 최우선: 현재 사용자가 시작하지 못하는 오류
사용자는 Python 설치 단계 후 purchasing_start.bat 실행 시 다음 오류를 받는다:

```
purchasing_start.ps1 파일을 로드할 수 없습니다.
파일이 디지털 서명되지 않았습니다. 현재 시스템에서 이 스크립트를 실행할 수 없습니다.
CategoryInfo: 보안 오류 / PSSecurityException
FullyQualifiedErrorId: UnauthorizedAccess
```

현재 purchasing_start.bat은 서명되지 않은 purchasing_start.ps1을 직접 호출한다.
Windows 실행 정책을 바꾸거나 시스템 전체 스크립트 검증을 해제하는 방법을 기본 해결책으로 쓰지 말 것.
설치·실행에 필요한 최소 변경으로 사용자가 시작할 수 있는 경로를 구현할 것.

## 이전 설치 실패도 함께 재현할 것
```
[ERROR] No runtime installed that matches 3.12. Try running "py install 3.12".
Setup failed. Check the error above. Later steps were not run.
Application data was not removed. Any previous environment backup was kept.
```

확인된 기존 결함: 파일이 있다는 이유만으로 .venv의 python.exe를 정상으로 간주했다.
현재 커밋은 실행 가능 여부 확인과 백업 후 재생성을 시도하지만 Windows에서 성공했다는 증거가 없다.
오류가 보인 정확한 실행 단계는 아직 분리되지 않았다. 추정 원인을 확인된 사실로 보고하지 말 것.
사용자에게 프로그램 ZIP을 반복해서 내려받도록 안내하기 전에 실패 단계를 명확하게 식별할 것.

## Claude가 납품할 결과
1. 재현과 원인: Python 실행기/실제 런타임/가상환경/의존성/PowerShell 시작 중 어디가 실패했는지 분리.
2. 실제 Windows에서 정상 설치·중단 후 재설치·기존 깨진 .venv 복구 검증.
3. 서명 제한이 있는 Windows에서 실행 정책의 시스템 전체 완화 없이 앱 시작 검증.
4. 암호가 화면·로그·파일에 노출되지 않고 로컬 127.0.0.1에서만 검토 화면 실행됨을 확인.
5. 상품 가져오기 → 가격 계산 → 번역 검수 → 승인 → 모의 등록 → ZIP 다운로드 시연.
6. 기존 상품 DB·설정·고객 자료를 삭제하지 않을 것. 불필요한 프로세스를 종료하지 않을 것.
7. 결과물은 기존 작업 브랜치/검토용 PR에 올리고 커밋 SHA, 실제 명령, Windows 버전·Python 버전, 성공/실패/미실행을 보고.
8. Windows 접근이 없으면 그 한계를 명시하고 설치 완료·Windows 검증 완료로 표시하지 말 것.

## 역할과 제한
Claude: 코드 수정과 실행 검증. ChatGPT: 기획·요구사항·결과 독립 검토만 담당.
실제 상품 게시/장바구니 변경/주문/결제/운영 배포/자동 머지는 이번 작업에 포함되지 않는다.
Claude Pro 구독을 사용하고 유료 API·추가 과금으로 전환하지 않는다.
기존 Linux 자동 테스트 88개 및 브라우저 시연 통과는 Windows 설치 성공을 의미하지 않는다.
