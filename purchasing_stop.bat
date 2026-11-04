@echo off
setlocal
cd /d "%~dp0"
set "ERRORLEVEL="
if not exist ".venv\Scripts\python.exe" (
    echo The review server was never installed here.
    exit /b 0
)
".venv\Scripts\python.exe" -m app.purchasing.local_server stop
exit /b %errorlevel%
