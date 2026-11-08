@echo off
cd /d "%~dp0"
echo [AUTO-NAVER setup] > setup_log.txt
where python >> setup_log.txt 2>&1
python --version >> setup_log.txt 2>&1
python -m pip install --upgrade pip >> setup_log.txt 2>&1
python -m pip install -r requirements.txt >> setup_log.txt 2>&1
python -c "import playwright, requests; print(\"IMPORT_OK\")" >> setup_log.txt 2>&1
echo DONE >> setup_log.txt
