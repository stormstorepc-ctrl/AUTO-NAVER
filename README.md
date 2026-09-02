# STORMPC AUTO COMMERCE v3.2

매크로마트 → STORMPC 상품 DB → 가격/재고 → 관리자 승인 → 네이버 스마트스토어 연동을 위한 프로젝트입니다.

## 현재 구현

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
- Render 배포 설정

## 설치

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
uvicorn app.main_v31:app --reload
```

브라우저에서 `http://127.0.0.1:8000/admin/login` 접속 후 관리자 계정으로 로그인합니다.

## 반드시 설정할 값

`.env` 또는 Render의 Environment에 입력합니다. 비밀번호/API Secret은 GitHub에 올리지 않습니다.

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

## 매크로마트 수집

관리자에서 `매크로마트 즉시 수집`을 누르면 Playwright가 매크로마트에 로그인한 뒤 현재 페이지에서 상품 상세 URL 후보를 찾고 상세페이지를 순회합니다.

현재는 사이트 변경에 대응하기 위해 여러 일반 selector를 사용합니다. 실제 운영 전에 `python inspect_macromart.py`로 로그인 후 화면의 input/button/link를 확인하고, 필요하면 selector를 한 번 더 맞춰야 합니다.

수집 결과는 DB에 저장되고 중복 URL은 갱신합니다. 판매가가 1원이거나 페이지에 품절 문구가 있으면 품절로 처리합니다.

## 관리자 상품 편집

상품관리의 상품명을 클릭하면 다음을 수정할 수 있습니다.

- 상품명
- 브랜드
- 모델명
- 네이버 카테고리 ID
- 대표 이미지 URL
- 상세 HTML
- 공급가
- 판매가
- 재고
- 승인 여부
- 상태

`공급가 기준 가격 재계산`을 누르면 현재 가격정책으로 판매가를 다시 계산합니다.

## 스마트스토어

Commerce API 인증 및 `/v2/products` 호출 코드가 포함되어 있습니다. 다만 실제 상품 등록에는 스토어의 카테고리와 상품정보제공고시, 배송 정책 등 필수 payload가 필요하므로 **처음에는 반드시 상품 1개로 테스트**해야 합니다.

관리자에서 `스토어 등록`을 실행했을 때 성공하면 네이버 상품번호를 DB에 저장하고 `SMARTSTORE_LISTED` 상태로 변경합니다. 실패하면 `SMARTSTORE_ERROR`와 오류 내용을 작업로그에 저장합니다.

## Render

`render.yaml`을 사용하면 다음 명령으로 배포하도록 구성되어 있습니다.

```text
pip install -r requirements.txt && playwright install chromium
uvicorn app.main_v31:app --host 0.0.0.0 --port 8000
```

Render Dashboard에서 위 환경변수를 입력하고 배포합니다.

## 주의

현재 매크로마트 재고 수량은 사이트의 정확한 수량 필드 selector가 확인되지 않은 경우 `판매 가능=1`, 품절=0으로 저장될 수 있습니다. 실제 수량을 제공하는 화면이면 `inspect_macromart.py` 결과를 기준으로 수량 selector를 지정하는 추가 작업이 필요합니다.
