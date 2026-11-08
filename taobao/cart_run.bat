@echo off
cd /d "%~dp0"
echo [cart run %date% %time%] > cart_log.txt
powershell -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Chrome debug port not open - starting collection Chrome >> cart_log.txt
  call start_chrome.bat
  timeout /t 15 /nobreak >nul
)
python -X utf8 cart_collect.py >> cart_log.txt 2>&1
echo EXIT=%errorlevel% >> cart_log.txt
