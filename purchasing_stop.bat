@echo off
powershell.exe -NoProfile -File "%~dp0purchasing_stop.ps1"
exit /b %errorlevel%
