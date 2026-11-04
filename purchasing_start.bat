@echo off
setlocal
cd /d "%~dp0"
rem Runs Python directly. No .ps1 file is loaded, so script signing and
rem execution policy settings do not block the start and are not changed.
set "ERRORLEVEL="
if not exist ".venv\Scripts\python.exe" (
    echo Run purchasing_install.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m app.purchasing.local_server start
set "purchasing_exit=%errorlevel%"
if not "%purchasing_exit%"=="0" pause
exit /b %purchasing_exit%
