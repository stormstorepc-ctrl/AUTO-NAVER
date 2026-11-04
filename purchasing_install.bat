@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>&1
if errorlevel 1 goto usepython
py -3.12 -c "import venv" >nul 2>&1
if errorlevel 1 goto installruntime
goto createvenv
:installruntime
echo Python 3.12 is missing. Installing it with Python Install Manager...
py install 3.12
if errorlevel 1 goto runtimehelp
py -3.12 -c "import venv" >nul 2>&1
if errorlevel 1 goto runtimehelp
:createvenv
py -3.12 -m venv .venv
if errorlevel 1 goto fail
goto install
:usepython
python -c "import sys, venv; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto runtimehelp
python -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Ready. Run purchasing_start.bat to open the review server.
pause
exit /b 0
:runtimehelp
echo Python 3.12 could not be installed automatically.
echo Check the installation error above and your Internet connection.
echo Older Python launchers do not support "py install".
echo Install Python 3.12 from https://www.python.org/downloads/windows/ and run this file again.
pause
exit /b 1
:fail
echo Setup failed. Check the error above. No later steps were run.
pause
exit /b 1
