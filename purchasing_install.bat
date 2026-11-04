@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>&1
if errorlevel 1 goto usepython
py -3.12 -m venv .venv
if errorlevel 1 goto fail
goto install
:usepython
python -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Ready. Run purchasing_start.bat to open the review server.
pause
exit /b 0
:fail
echo Setup failed. Install Python 3.12 and check the error above.
pause
exit /b 1
