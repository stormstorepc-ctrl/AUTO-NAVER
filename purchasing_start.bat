@echo off
rem 구매대행 검토 화면(루프백 전용). Windows 실환경 검증 전 - 미검증.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo [ERROR] install_auto_naver.bat 먼저 실행하세요. & exit /b 1 )
if "%PURCHASING_REVIEW_PASSWORD%"=="" ( echo [ERROR] PURCHASING_REVIEW_PASSWORD 환경변수(8자 이상)를 설정하세요. & exit /b 1 )
rem 8765 포트, 127.0.0.1 에만 바인딩. 외부 게시 기능 없음(모의 어댑터만).
".venv\Scripts\python.exe" -m uvicorn app.purchasing.web:app_from_env --factory --host 127.0.0.1 --port 8765
