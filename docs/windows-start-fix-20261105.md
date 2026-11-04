# Windows 설치·시작 오류 수정 기록 (T-COMMERCE-001)

상태: **코드 수정 + Linux 검증만 완료. Windows 실기 검증은 미실행.**
이 작업 환경(Linux 클라우드 컨테이너)에는 Windows, cmd.exe, PowerShell, wine이 없다.
따라서 아래 "Windows 설치 완료" 또는 "Windows 검증 완료"로 표시하지 않는다.

## 1. 설치 실패 — `No runtime installed that matches 3.12`

### 원인 (소스 근거, Windows 실행으로는 미확인)
python/pymanager 소스(커밋 e634365) 확인 결과:
- `py -3.12 ...` 에서 3.12 런타임이 없으면 py.exe는 `0xA0000004`(ERROR_NO_MATCHING_INSTALL),
  `0xA0000005`, 자동설치 비활성 시 `0xA0000006`을 반환한다 (`src/pymanager/main.cpp`).
- 이 값은 32비트 부호 있는 정수로 음수다. cmd의 `if errorlevel 1`은 "1 이상"일 때만 참이므로
  **음수 실패 코드를 성공으로 처리**한다.

1b754b4 설치 스크립트에 대입하면 사용자 화면과 정확히 일치하는 흐름:
1. `py -3.12 -c ... >nul 2>&1` 실패(음수) → `if errorlevel 1` 거짓 → `py install 3.12` 단계를 **건너뜀**
   (사용자 출력에 "Python 3.12 is missing. Installing..." 줄이 없음).
2. `py -3.12 -m venv .venv` → `[ERROR] No runtime installed that matches 3.12...` 출력, 음수 반환 → 다시 통과.
3. `if not exist ".venv\Scripts\python.exe" goto fail` 에서 비로소 `Setup failed...` 출력.

즉 실패 단계는 "Python 실행기(py.exe) 종료코드 판정"이며, 가상환경·의존성 단계에는 도달하지 않았다.
(Windows에서 `py -3.12 -c "1"` 직후 `echo %errorlevel%`가 `-1610612732` 등 음수로 나오는지 확인하면 확정된다.)

### 수정
- `purchasing_install.bat`: 모든 `if errorlevel 1` → `if %errorlevel% neq 0`.
- 확인용 probe가 화면 없이 자동설치를 시작하지 않도록 `PYTHON_MANAGER_AUTOMATIC_INSTALL=false`(스크립트 내부 한정).
  명시적 `py install 3.12`는 영향받지 않는다.
- 단계 표시 `[1/5]`~`[5/5]`와 실패 시 종료코드 출력 → 다음 실패 시 단계 식별 가능.
- 기존 .venv 백업 후 재생성 동작, 사용자 데이터 비삭제는 그대로 유지.
- 모든 purchasing_*.bat을 CRLF로 저장하고 `.gitattributes`에 `*.bat -text` 지정
  (LF 전용 배치 파일은 cmd가 goto 레이블을 잘못 찾는 알려진 문제가 있음).

## 2. 시작 실패 — `purchasing_start.ps1 ... 디지털 서명되지 않았습니다`

### 원인
`purchasing_start.bat`이 서명 없는 `.ps1`을 `powershell -File`로 실행했다. 실행 정책이
AllSigned이거나, RemoteSigned + 인터넷에서 받은 ZIP 표시(Mark of the Web)가 붙은 파일이면 차단된다.

### 수정 (실행 정책 변경·우회 플래그 없음)
- `purchasing_start.ps1`, `purchasing_stop.ps1` 삭제. 배치 파일이 `.venv\Scripts\python.exe -m app.purchasing.local_server start|stop`을 직접 실행.
  실행 정책은 .ps1 스크립트에만 적용되므로 정책·그룹 정책을 바꾸지 않고 시작된다.
- 암호: `getpass`로 화면 비표시 입력, 메모리에서 앱에 전달. 환경변수·파일·콘솔에 기록하지 않음.
- 바인딩: 127.0.0.1:8765 고정(앱 자체도 loopback 외 요청 403).
- 중지: 시작 시 `.purchasing_server.json`에 PID·프로세스 생성 시각·실행 파일을 기록(암호 없음).
  stop은 이 정보가 일치하는 프로세스만 종료하고, 8765 포트를 다른 PID가 쓰면 거부한다
  (netstat 상태 문자열 현지화에 의존하지 않음). Windows 프로세스 조회는 ctypes(OpenProcess/GetProcessTimes).

## 3. 검증 결과

| 항목 | 결과 | 환경 |
|---|---|---|
| 기존 + 신규 자동 테스트 (`pytest -q tests/`) | 94 통과 | Linux, Python 3.13.18 |
| 실제 서버 start → 401(무인증)/200(인증) → stop, 상태파일·출력에 암호 없음 | 통과 | Linux |
| 중복 start 거부, 다른 PID 포트 점유 시 stop 거부, PID 재사용 시 stop 무시 | 통과 | Linux (포트 점유는 단위 테스트) |
| .bat CRLF·PowerShell 미사용·`if errorlevel` 미사용 정적 검사 | 통과 | Linux |
| Windows 정상 설치 / 중단 후 재설치 / 깨진 .venv 복구 | **미실행** | Windows 없음 |
| 서명 제한 Windows에서 시작 | **미실행** | Windows 없음 |
| Windows ctypes·netstat·taskkill 경로 | **미실행** (Linux에선 /proc 경로로 대체 실행) | |
| Python 3.12에서 실행 | **미실행** (컨테이너는 3.13) | |
| 가져오기→가격→번역검수→승인→모의등록→ZIP Windows 시연 | **미실행** | |

## 4. Windows에서 확인할 절차
1. ZIP을 새 폴더에 풀고 `purchasing_install.bat` 실행 → `[1/5]`~`[5/5]`와 `Ready.` 확인. 실패 시 마지막 `[n/5]` 단계와 exit code 기록.
2. `purchasing_start.bat` → 암호 입력(화면에 표시되지 않아야 함) → Chrome에서 http://127.0.0.1:8765.
3. 다른 cmd 창에서 `purchasing_stop.bat` → `Stopped purchasing review PID ...`.
4. 깨진 .venv 재현: `.venv\pyvenv.cfg`의 home을 없는 경로로 바꾼 뒤 1번 재실행 → `.venv.backup-*` 생성 후 재설치되는지 확인.
