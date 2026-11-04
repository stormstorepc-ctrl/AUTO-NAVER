# 구매대행 1단계 구현 (T-COMMERCE-001)

범위: 로컬 기반(가져오기·가격·저장·검토 화면·승인·모의 게시·초안 내보내기). **실계정 게시/장바구니/구매/결제 없음. 실제 타오바오 수집 없음.**

## 구성 (`app/purchasing/`)
| 파일 | 역할 |
| --- | --- |
| `importer.py` | JSON(schema_version=1)/CSV 가져오기와 검증. 외부 텍스트·HTML은 저장만 하고 화면에서 이스케이프 |
| `pricing.py` | Decimal 가격 엔진 (배송 포함/별도, 채널 요율, 고정 수수료, 충당금, 환율, 부피중량, 할인, 시나리오) |
| `store.py` | SQLite(표준 라이브러리). 상품/옵션/번역/견적/승인/게시/시도/실행/감사 기록, 비밀키 마스킹 |
| `workflow.py` | 견적 → 승인(내용 해시, 24h 만료) → 원자적 점유 게시 → 주간 실행 → 초안 내보내기, 모의 어댑터 |
| `web.py` | 루프백 검토 화면 (Basic 인증 + Origin 검사 + CSP). 비밀번호 기본값 없음 |
| `cli.py` | `weekly-mock` 주간 모의 실행 |

기존 코드 재사용 판단: 기존 `Product`(공급가/판매가 1개, 승인 불리언)는 옵션·채널별 견적과 승인 버전을 표현할 수 없어 기존 테이블과 분리된 신규 모듈로 구현했다. 기존 `app/*` 파일은 수정하지 않았다. 기존 진입점 불일치(`start_auto_naver.bat`=`app.main_v31:app`, README/Dockerfile=`app.main:app`)는 건드리지 않았고, 신규 화면은 별도 진입점 `app.purchasing.web:app_from_env`를 쓴다.

## 정책 요약
- 예상 공헌이익률 = (고객 실결제액 − 총원가 − 판매수수료 − 고정수수료) / 실결제액. 고정비·소득세 차감 전, 이익 보장 아님.
- 원단위: 원가 항목은 원 단위 올림, 수수료는 건별 원 단위 반올림(HALF_UP), 판매가는 100원 단위 올림 후 마진 재검산(미달 시 한 단위씩 상승).
- 환율 24시간, 배송 요율/채널 수수료 30일 초과 시 만료 → 가격 확정(publishable) 불가. 누락값을 0으로 대체하지 않는다.
- 승인은 상품·옵션·이미지·번역·견적 입력/결과의 해시를 저장. 게시 직전 해시·만료·견적 유효기간 재검사.
- 게시 점유는 `BEGIN IMMEDIATE` 트랜잭션 + (상품, 채널, 계정) 유일 키. 응답 유실/예외는 `unknown`이며 재POST하지 않고 조회로만 정리. 강제 종료로 남은 `claimed`도 조회로 정리.
- 실채널(스마트스토어/당근/번개장터)은 `REAL_CHANNELS_VERIFIED=False` → `blocked`. 모의 어댑터는 `mock:` 계정에만 사용.
- 집계: `mock_published`(모의)와 `real_published`(실제)를 분리. 초안 내보내기는 게시 성공으로 집계하지 않음.

## 테스트
```
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements-dev.txt
python -m pytest -q tests/purchasing
```

## Windows 실행 (미검증)
- 시작: `set PURCHASING_REVIEW_PASSWORD=<8자 이상>` 후 `purchasing_start.bat` → http://127.0.0.1:8765 (Basic 인증, 사용자 `reviewer`)
- 중지: `purchasing_stop.bat` / 재시작: stop 후 start
- 예약(월 09:00 제안값): `schtasks /Create /SC WEEKLY /D MON /ST 09:00 /TN "PurchasingWeeklyMock" /TR "\"%CD%\purchasing_weekly.bat\""` — 실행 전 사용자 확인 필요. 이 저장소 작업에서는 예약을 만들지 않았다.
- 위 .bat 파일과 예약은 Linux 환경에서 작성만 했고 **Windows 실환경(잠금/절전/재부팅/미로그인) 검증은 하지 않았다.**

## 남은 제약
번역 수치/단위 자동 대조(2단계), 근거 기반 트렌드 점수(2단계), 타오바오·실채널 연동(3~4단계), Windows 실환경 검증(5단계)은 미구현/미검증. 검토 화면에는 번역 입력/검수 폼이 없고 현재는 API(`Store.add_translation`/`review_translation`)와 가져오기 스크립트로만 처리한다.
