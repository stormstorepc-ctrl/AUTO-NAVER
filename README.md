# STORMPC AUTO COMMERCE v2

매크로마트 → STORMPC 상품 DB → 가격/재고 → 관리자 승인 → 네이버 스마트스토어/카페 연동용 프로젝트입니다.

## 반영된 매크로마트 규칙

- 판매가 `1원` = 품절
- CPU/인텔/AMD 등 원본 카테고리 경로 보존
- 목록에서 상품을 찾고 상세페이지에서 상세정보/이미지를 추가 수집
- 대표 이미지/상세 이미지 URL 저장
- 공급가/재고/품절 상태 동기화
- 마진율/최저판매가/안전재고 지원
- 가격변동이 설정값보다 크면 `PRICE_REVIEW`로 보류
- 품절이면 재고 0 및 `SOLD_OUT`
- 재입고 시 다시 가격계산 후보
- 수집/승인/API 오류를 `sync_logs`에 기록

## 설치

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

`.env`에 매크로마트 ID/비밀번호를 넣습니다. 비밀번호를 코드나 GitHub에 넣지 마세요.

## 1차 점검

```powershell
python inspect_macromart.py
```

결과는 `artifacts/`에 저장됩니다.

- macromart_login.png
- macromart_products.html
- macromart_forms.json
- macromart_links.json

로그인 과정을 눈으로 확인하려면 `MACROMART_HEADLESS=false`.

## 서버

```powershell
uvicorn app.main:app --reload
```

`http://127.0.0.1:8000/docs`

## API

- GET /health
- GET /products
- POST /crawl/macromart
- POST /pricing/recalculate/{product_id}
- POST /products/{product_id}/approve
- POST /products/{product_id}/smartstore
- POST /products/{product_id}/cafe
- GET /naver/login
- GET /naver/callback

## 네이버

Commerce API는 Client Credentials 방식입니다. Client ID/Secret과 판매자 account ID를 서버에 저장하고 서버에서 토큰을 발급합니다.

Cafe API는 OAuth 2.0 access token으로 일반 게시판 글쓰기를 지원합니다. 상품게시판은 공식 Cafe API 글쓰기 대상이 아니므로 일반 게시판 ID를 사용해야 합니다.

실제 스마트스토어 상품 등록 payload는 네이버 카테고리 ID, 상품정보제공고시, 배송정보 등 스토어별 필수값이 필요합니다. 따라서 프로젝트에서는 원본 데이터를 먼저 안전하게 저장하고, 등록 직전에 명시적인 payload를 생성하도록 분리했습니다.

처음에는 반드시 1개 상품으로 테스트하세요.


## 관리자 화면 v3

서버 실행 후:

`http://127.0.0.1:8000/admin`

메뉴:
- 대시보드
- 상품관리
- 매크로마트 수집
- 작업로그
- 연동 설정

상품관리에서:
1. 상품 수정
2. 승인
3. 스마트스토어 등록
4. 카페 게시

순으로 사용할 수 있습니다.

**주의:** 현재 관리자 화면에는 로그인/권한인증을 넣지 않은 내부 테스트 버전입니다. 인터넷에 공개하기 전에는 관리자 인증을 반드시 추가해야 합니다.
