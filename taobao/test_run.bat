@echo off
cd /d "%~dp0"
echo [test run %date% %time%] > collect_log.txt
python -X utf8 taobao_collect.py >> collect_log.txt 2>&1
echo EXIT=%errorlevel% >> collect_log.txt
