# ChatGPT로 이어서 테스트하기

ChatGPT(코드 실행이 되는 **Codex** 또는 GitHub 연결된 ChatGPT)에서 이 저장소를 연결한 뒤, 아래 프롬프트를 그대로 붙여넣으세요.

> ChatGPT는 타오바오·스마트스토어센터에 직접 접속하지 못합니다. 그래서 테스트는 **오프라인(엑셀 생성·가격·파싱)** 부분을 ChatGPT가 하고, **실제 수집/업로드는 내 PC**에서 합니다.

---

## 1) 기본 테스트 프롬프트 (복사해서 사용)

```
저장소 stormstorepc-ctrl/AUTO-NAVER 의 브랜치 taobao-collector 에서 taobao/ 폴더를 작업해줘.

[프로젝트]
타오바오 상품을 내 PC Chrome(로그인 상태, 디버깅 포트 9222)으로 수집 → 한국어 상품명/판매가 생성
→ 스마트스토어 엑셀 일괄등록 파일 생성. 자세한 건 taobao/README.md 참고.

[해줄 일]
1. cd taobao && pip install -r requirements.txt && python -m pytest tests -q 실행해서 결과 보여줘.
2. python smartstore/make_excel.py sample/listing_test.json out.xlsx 실행하고,
   출력된 경고와 out.xlsx 3~4행의 주요 값(상품명, 판매가, 옵션값, 옵션가, 배송비유형)을 표로 보여줘.
3. 실패하거나 이상한 점이 있으면 원인과 수정안을 제시해줘.

[규칙]
- 판매가 공식: (위안×200 + 6000)×1.3, 100원 단위 올림, 무료배송. 바꾸지 말 것.
- 코드 수정 시 생략 없이 전체 파일로 보여주고, 수정 후 테스트를 다시 돌려 통과 확인.
- 타오바오/네이버 사이트에 접속하는 코드를 실행하지 말 것 (내 PC에서만 실행).
- 카테고리코드·원산지코드 값은 추측해서 넣지 말 것 (스마트스토어센터 팝업에서 내가 확인).
```

## 2) 내 PC 수집 결과로 엑셀 만들기 프롬프트

수집 후 `output/날짜_cart/products.json` 내용을 붙여넣고:

```
아래 products.json(타오바오 수집 결과)을 taobao/sample/listing_test.json 형식으로 바꿔줘.
- title_ko: 스마트스토어용 한국어 상품명 (검색 키워드 포함, 과장표현·브랜드 제외, 50자 이내)
- description: 2~3줄 한국어 소개
- price_cny: 가장 기본 옵션 가격, 옵션별 가격이 다르면 options 배열로
- images: P{번호}_main.jpg, P{번호}_add1.jpg ... (상품과 무관한 사진·로고·다른 상품 사진 제외)
결과 JSON 전체를 보여주고, make_excel.py로 엑셀까지 만들어줘.

(products.json 붙여넣기)
```

## 3) 다음 개발 과제 (ChatGPT에 맡길 만한 것)

- `cart_collect.py` 결과(`products.json`) → `listing_test.json` 형식 자동 변환 스크립트
- 상품 이미지 자동 선별 (작은 이미지·로고·사람 사진 제외, 대표 이미지 1:1 리사이즈)
- 네이버 **커머스 API**로 비공개 상품 등록 (`app/integrations/naver.py` 활용, 키는 `.env`에만)
- 수집 결과 `price_cny` 비어 있을 때 `page.html` 의 `"price":"…"` 값에서 보충
