@echo off
setlocal
cd /d "%~dp0"
set "ERRORLEVEL="
if not exist ".venv\Scripts\python.exe" (
    echo The review server was never installed here.
    pause
    exit /b 0
)
".venv\Scripts\python.exe" -m app.purchasing.local_server stop
set "purchasing_exit=%errorlevel%"
rem Keep the window open so the result can be read after a double-click.
pause
exit /b %purchasing_exit%
