@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 먼저 install_auto_naver.bat 를 실행하세요.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run_macromart_sync.py --limit 100
pause
