@echo off
rem 작업 스케줄러용 주간 모의 실행. 놓친 실행은 다음 기동에 같은 주차 키로 1회 복구되며 완료 항목은 건너뜁니다.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.purchasing.cli weekly-mock
