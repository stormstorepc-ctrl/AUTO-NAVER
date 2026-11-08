@echo off
REM 작업 스케줄러에서 매주 실행할 파일입니다.
cd /d "%~dp0"

REM Chrome이 꺼져 있으면 켜기
powershell -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  call start_chrome.bat
  timeout /t 10 /nobreak >nul
)

python -X utf8 taobao_collect.py >> collect_log.txt 2>&1
