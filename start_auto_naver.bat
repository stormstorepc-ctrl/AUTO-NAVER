@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv가 없습니다.
  echo 먼저 install_auto_naver.bat를 실행하세요.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [ERROR] .env가 없습니다.
  echo 먼저 install_auto_naver.bat를 실행하세요.
  pause
  exit /b 1
)

echo ========================================
echo STORMPC AUTO-NAVER
echo ========================================
echo 관리자: http://127.0.0.1:8000/admin/login
echo 종료하려면 이 창에서 Ctrl+C를 누르세요.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main_v31:app --host 127.0.0.1 --port 8000

pause
