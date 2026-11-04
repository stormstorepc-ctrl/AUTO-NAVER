@echo off
rem 8765 포트를 사용하는 검토 화면 프로세스를 종료합니다. 이미 전송된 요청의 결과는 별도로 조회/복구(recover_stale_claims)해야 합니다.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "127.0.0.1:8765" ^| findstr LISTENING') do taskkill /PID %%p /F
