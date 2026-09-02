# STORMPC AUTO COMMERCE v3.2

매크로마트 → STORMPC 상품 DB → 가격/재고 → 관리자 승인 → 네이버 스마트스토어 연동을 위한 프로젝트입니다.

## 운영 방식: 별도 Render 서비스 없이 사용자 PC에서 실행

현재는 **Render에 별도 서비스를 추가하지 않고 Windows PC에서 직접 실행하는 방식**을 권장합니다.

```text
Windows PC
  └─ STORMPC AUTO COMMERCE
       ├─ FastAPI 관리자 화면
       ├─ SQLite 상품 DB
       ├─ Playwright / Chromium
       ├─ MacroMart 수집
       └─ Naver Commerce API
```

이 방식에서는 AUTO-NAVER용 Render 서비스를 만들 필요가 없습니다. 상품 DB(`stormpc.db`)도 PC의 로컬 디스크에 저장됩니다.

## 1. Windows 설치

GitHub에서 저장소를 내려받은 뒤 프로젝트 폴더에서 `install_auto_naver.bat`를 **한 번 실행**합니다.

설치 프로그램은 다음을 자동으로 처리합니다.

- Python 가상환경 생성
- Python 패키지 설치
- Playwright Chromium 설치
- `.env` 파일 생성

Python 3.12 이상이 필요합니다.

## 2. 환경변수 설정

생성된 `.env` 파일을 메모장으로 열어 실제 값을 입력합니다.

```text
ADMIN_USERNAME=ADMIN
ADMIN_PASSWORD=원하는관리자비밀번호
SECRET_KEY=충분히긴랜덤문자열

MACROMART_ID=매크로마트아이디
MACROMART_PASSWORD=매크로마트비밀번호
MACROMART_HEADLESS=true

NAVER_COMMERCE_CLIENT_ID=네이버커머스ClientID
NAVER_COMMERCE_CLIENT_SECRET=네이버커머스ClientSecret
NAVER_COMMERCE_ACCOUNT_ID=판매자AccountID
```

비밀번호/API Secret은 GitHub에 올리지 않습니다. `.env`는 `.gitignore`에 포함되어 있습니다.

## 3. 프로그램 시작

`start_auto_naver.bat`를 실행합니다.

브라우저에서 아래 주소로 접속합니다.

```text
http://127.0.0.1:8000/admin/login
```

관리자 로그인 후 `/admin`에서 상품 수집, 가격 재계산, 승인, 스마트스토어 등록을 실행할 수 있습니다.

## 4. MacroMart 즉시 수집

관리자 화면의 `매크로마트 즉시 수집` 버튼을 누르거나 다음 파일을 실행합니다.

```text
sync_once.bat
```

명령줄에서는:

```powershell
.venv\Scripts\python.exe run_macromart_sync.py --limit 100
```

수집 결과는 로컬 `stormpc.db`에 저장됩니다.

## 5. 현재 구현

- 관리자 로그인 `/admin/login`
- 관리자 대시보드 `/admin`
- 상품 목록에서 상품명을 클릭해 상세 편집
- 상품명/브랜드/모델/네이버 카테고리 ID/이미지/상세 HTML 수정
- 공급가/판매가/재고/승인상태 수정
- 공급가 기준 판매가 자동 계산
- 매크로마트 판매가 `1원` = 품절
- 가격 급변 시 `PRICE_REVIEW`
- 매크로마트 로그인 후 상품 링크 탐색 및 상세페이지 수집
- 대표 이미지/상세 HTML 저장
- 네이버 Commerce API 토큰 발급 및 상품 등록 코드
- 작업로그 기록
- Windows 로컬 실행 스크립트 제공
- Render 배포 설정도 별도로 유지

## 6. 스마트스토어

Commerce API 인증 및 `/v2/products` 호출 코드가 포함되어 있습니다. 다만 실제 상품 등록에는 스토어의 카테고리와 상품정보제공고시, 배송 정책 등 필수 payload가 필요하므로 **처음에는 반드시 상품 1개로 테스트**해야 합니다.

관리자에서 `스토어 등록`을 실행했을 때 성공하면 네이버 상품번호를 DB에 저장하고 `SMARTSTORE_LISTED` 상태로 변경합니다. 실패하면 `SMARTSTORE_ERROR`와 오류 내용을 작업로그에 저장합니다.

## 7. 자동화 예약

현재 `run_macromart_sync.py`는 **1회 수집 작업**입니다. Windows 작업 스케줄러에서 이 파일을 1일 여러 번 실행하면 PC 기반 자동 수집으로 사용할 수 있습니다.

권장 시작 주기 예:

```text
09:00 / 13:00 / 18:00 / 23:00
```

관리자 승인 후 스마트스토어 등록 정책을 적용하기 전까지는 수집 → 가격/재고 갱신까지만 자동화하는 것을 권장합니다.

## 8. MacroMart selector 보정

관리자에서 수집을 실행하기 전에 다음 명령으로 실제 MacroMart 화면의 input/button/link 정보를 확인할 수 있습니다.

```powershell
.venv\Scripts\python.exe inspect_macromart.py
```

현재 crawler는 여러 일반 selector를 사용합니다. 실제 사이트의 로그인/상품 목록/가격/재고 selector가 다른 경우 `inspect_macromart.py` 결과를 기준으로 추가 보정해야 합니다.

특히 **재고 수량은 정확한 수량 필드를 아직 확정하지 못한 상태**이므로 현재 crawler가 판매 가능 상품을 `1`로 기록할 수 있습니다. 사이트에서 실제 수량을 표시한다면 해당 selector를 확정한 뒤 정확한 재고 수량 동기화로 변경해야 합니다.

## 9. Render는 선택 사항

`render.yaml`은 향후 서버형 운영이 필요할 때를 위해 유지합니다. 현재 목적은 **추가 Render 서비스 비용 없이 PC에서 AUTO-NAVER를 실행하는 것**입니다.
