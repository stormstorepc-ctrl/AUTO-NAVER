@echo off
setlocal
cd /d "%~dp0"
rem A failed venv can leave python.exe pointing at a runtime that does not exist.
rem Check that it actually runs; file existence alone is not a readiness check.
set "purchasing_backup_needed="
if not exist ".venv" goto findruntime
if not exist ".venv\Scripts\python.exe" goto brokenvenv
".venv\Scripts\python.exe" -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto brokenvenv
goto install
:brokenvenv
echo The previous virtual environment is incomplete or cannot run.
echo It will be preserved in a backup folder before rebuilding.
set "purchasing_backup_needed=1"
:findruntime
where py >nul 2>&1
if errorlevel 1 goto usepython
py -3.12 -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto installruntime
goto usepy
:installruntime
echo Python 3.12 is missing. Installing it with Python Install Manager...
py install 3.12
if errorlevel 1 goto runtimehelp
py -3.12 -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto runtimehelp
:usepy
set "purchasing_runtime=py -3.12"
goto preparevenv
:usepython
python -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto runtimehelp
set "purchasing_runtime=python"
:preparevenv
if not defined purchasing_backup_needed goto createvenv
:choosebackup
set "purchasing_backup=.venv.backup-%RANDOM%-%RANDOM%"
if exist "%purchasing_backup%" goto choosebackup
move ".venv" "%purchasing_backup%" >nul
if errorlevel 1 goto fail
echo Previous environment saved as %purchasing_backup%.
:createvenv
%purchasing_runtime% -m venv .venv
if errorlevel 1 goto fail
if not exist ".venv\Scripts\python.exe" goto fail
".venv\Scripts\python.exe" -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -c "from app.purchasing.web import app_from_env"
if errorlevel 1 goto fail
echo Ready. Run purchasing_start.bat to open the review server.
pause
exit /b 0
:runtimehelp
echo Python 3.12 could not be installed automatically.
echo Check the installation error above and your Internet connection.
echo Older Python launchers do not support "py install".
echo Install Python 3.12 from https://www.python.org/downloads/windows/ and run this file again.
echo Your existing environment and application data were not removed.
pause
exit /b 1
:fail
echo Setup failed. Check the error above. Later steps were not run.
echo Application data was not removed. Any previous environment backup was kept.
pause
exit /b 1
