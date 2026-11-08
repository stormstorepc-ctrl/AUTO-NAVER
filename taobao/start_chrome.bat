@echo off
REM 수집용 Chrome을 디버깅 포트(9222)로 실행합니다.
REM 처음 한 번은 이 창에서 타오바오에 로그인해 주세요. 이후 로그인 상태가 유지됩니다.
REM 자동번역(Translate)을 꺼야 가격/상품명이 중국어 원문으로 수집됩니다.

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

start "" %CHROME% --remote-debugging-port=9222 --user-data-dir="%~dp0chrome-profile" --disable-features=Translate https://www.taobao.com
