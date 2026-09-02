@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Python virtual environment not found.
  echo Run install_auto_naver.bat first.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [2/3] .env file not found.
  copy /Y .env.example .env >nul
  echo .env.example was copied to .env.
  echo Please edit .env and enter your MacroMart/Naver settings, then run this file again.
  pause
  exit /b 1
)

echo [3/3] Starting STORMPC AUTO COMMERCE locally...
echo Admin: http://127.0.0.1:8000/admin/login
".venv\Scripts\python.exe" -m uvicorn app.main_v31:app --host 127.0.0.1 --port 8000

pause
