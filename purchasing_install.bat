@echo off
setlocal
cd /d "%~dp0"
rem Exit codes are checked with "neq 0", not "if errorlevel 1".
rem The Python Install Manager (py.exe) reports a missing runtime with codes
rem such as 0xA0000004. cmd stores them as negative numbers, and
rem "if errorlevel 1" treats every negative number as success.
set "ERRORLEVEL="
rem Probes must not start a hidden automatic install behind >nul.
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "purchasing_check=import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
set "purchasing_backup_needed="

echo [1/5] Checking the existing virtual environment...
if not exist ".venv" goto findruntime
if not exist ".venv\Scripts\python.exe" goto brokenvenv
".venv\Scripts\python.exe" -c "%purchasing_check%" >nul 2>&1
if %errorlevel% neq 0 goto brokenvenv
echo       Existing .venv runs Python 3.12. Reusing it.
goto install
:brokenvenv
echo       The previous virtual environment is incomplete or cannot run.
echo       It will be preserved in a backup folder before rebuilding.
set "purchasing_backup_needed=1"

:findruntime
echo [2/5] Looking for Python 3.12...
where py >nul 2>&1
if %errorlevel% neq 0 goto usepython
py -3.12 -c "%purchasing_check%" >nul 2>&1
if %errorlevel% neq 0 goto installruntime
goto usepy
:installruntime
echo       Python 3.12 is missing. Installing it with Python Install Manager...
py install 3.12
if %errorlevel% neq 0 goto runtimehelp
py -3.12 -c "%purchasing_check%" >nul 2>&1
if %errorlevel% neq 0 goto runtimehelp
:usepy
set "purchasing_runtime=py -3.12"
goto preparevenv
:usepython
python -c "%purchasing_check%" >nul 2>&1
if %errorlevel% neq 0 goto runtimehelp
set "purchasing_runtime=python"

:preparevenv
echo [3/5] Creating the virtual environment with %purchasing_runtime%...
if not defined purchasing_backup_needed goto createvenv
:choosebackup
set "purchasing_backup=.venv.backup-%RANDOM%-%RANDOM%"
if exist "%purchasing_backup%" goto choosebackup
move ".venv" "%purchasing_backup%" >nul
if %errorlevel% neq 0 goto fail
echo       Previous environment saved as %purchasing_backup%.
:createvenv
%purchasing_runtime% -m venv .venv
if %errorlevel% neq 0 goto fail
if not exist ".venv\Scripts\python.exe" goto fail
".venv\Scripts\python.exe" -c "%purchasing_check%"
if %errorlevel% neq 0 goto fail

:install
echo [4/5] Installing packages from requirements.txt...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if %errorlevel% neq 0 goto fail
echo [5/5] Checking that the review app loads...
".venv\Scripts\python.exe" -c "import app.purchasing.local_server, app.purchasing.web"
if %errorlevel% neq 0 goto fail
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
echo Setup failed at the step shown above (exit code %errorlevel%). Later steps were not run.
echo Application data was not removed. Any previous environment backup was kept.
pause
exit /b 1
