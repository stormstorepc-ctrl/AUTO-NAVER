@echo off
setlocal
cd /d "%~dp0"

echo ===============================================
echo STORMPC AUTO COMMERCE - Windows Installer
echo ===============================================

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher 'py' was not found.
  echo Install Python 3.12+ from https://www.python.org/downloads/windows/
  echo During installation, enable "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
)

echo Installing Python packages...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed.
  pause
  exit /b 1
)

echo Installing Playwright Chromium browser...
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
  echo Playwright installation failed.
  pause
  exit /b 1
)

if not exist ".env" (
  copy /Y .env.example .env >nul
  echo .env created from .env.example.
  echo Edit .env before starting the service.
)

echo.
echo Installation completed.
echo Next step: edit .env, then run start_auto_naver.bat
pause
