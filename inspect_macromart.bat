@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo STORMPC AUTO-NAVER - MacroMart Inspector
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv\Scripts\python.exe 를 찾을 수 없습니다.
  echo 프로젝트 폴더에서 실행했는지 확인하세요.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [ERROR] .env 파일을 찾을 수 없습니다.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" inspect_macromart.py
set "RC=%ERRORLEVEL%"

echo.
echo ========================================
if "%RC%"=="0" (
  echo 검사 완료
) else (
  echo 검사 중 오류가 발생했습니다. 코드: %RC%
)
echo artifacts 폴더를 확인하세요.
echo ========================================
pause
exit /b %RC%
