@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0purchasing_start.ps1"
set "purchasing_exit=%errorlevel%"
if not "%purchasing_exit%"=="0" pause
exit /b %purchasing_exit%
