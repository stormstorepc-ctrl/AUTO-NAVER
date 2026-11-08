@echo off
cd /d "%~dp0"
echo [cart probe %date% %time%] > cart_probe_log.txt
python -X utf8 cart_collect.py --probe >> cart_probe_log.txt 2>&1
echo EXIT=%errorlevel% >> cart_probe_log.txt
