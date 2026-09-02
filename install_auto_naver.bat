@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ========================================
echo STORMPC AUTO-NAVER - Windows Installer
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 goto NO_PY
py -3 --version
if errorlevel 1 goto NO_PY

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating Python virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 goto ERROR
) else (
  echo [1/4] Existing virtual environment found.
)

echo [2/4] Installing Python packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto ERROR
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto ERROR

echo [3/4] Installing Playwright Chromium...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto ERROR

echo [4/4] Checking environment file...
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  if errorlevel 1 goto ERROR
  echo Created .env from .env.example.
) else (
  echo Existing .env found. Keeping it unchanged.
)

echo.
echo INSTALLATION COMPLETE.
echo Next step: edit .env, then run start_auto_naver.bat
echo.
pause
exit /b 0

:NO_PY
echo.
echo ERROR: Python 3 is not available.
echo Install Python 3.12 or newer from python.org and enable "Add Python to PATH".
echo.
pause
exit /b 1

:ERROR
echo.
echo ERROR: Installation failed. Check the message above.
echo.
pause
exit /b 1
