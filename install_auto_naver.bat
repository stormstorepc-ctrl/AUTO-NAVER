@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo STORMPC AUTO-NAVER - Windows Installer
echo ========================================

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python이 설치되어 있지 않거나 PATH에 없습니다.
  echo Python 3.12 이상을 설치한 후 다시 실행하세요.
  pause
  exit /b 1
)

python --version

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] 가상환경 생성 중...
  python -m venv .venv
  if errorlevel 1 goto :error
) else (
  echo [1/4] 기존 가상환경 사용
)

echo [2/4] Python 패키지 설치 중...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/4] Playwright Chromium 설치 중...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error

echo [4/4] 환경설정 파일 확인 중...
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo .env 파일을 생성했습니다.
  echo 다음 단계에서 .env를 메모장으로 열어 실제 계정/API 정보를 입력하세요.
) else (
  echo 기존 .env 파일을 유지합니다.
)

echo.
echo 설치가 완료되었습니다.
echo 1) .env 파일 설정
orecho 2) start_auto_naver.bat 실행
pause
exit /b 0

:error
echo.
echo [ERROR] 설치 중 오류가 발생했습니다.
pause
exit /b 1
