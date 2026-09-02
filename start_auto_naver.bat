@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found.
  echo Run install_auto_naver.bat first.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [ERROR] .env file not found.
  echo Run install_auto_naver.bat first.
  pause
  exit /b 1
)

echo ========================================
echo STORMPC AUTO-NAVER
echo ========================================
echo Admin: http://127.0.0.1:8000/admin/login
echo Press CTRL+C in this window to stop.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main_v31:app --host 127.0.0.1 --port 8000

pause
