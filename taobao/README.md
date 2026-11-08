# AUTO-NAVER · 타오바오 → 스마트스토어 (구매대행)

타오바오 상품을 **내 PC에서** 수집하고, 한국어 상품명과 판매가를 만들어 **스마트스토어 엑셀 일괄등록 파일**로 만드는 도구입니다.

```
[타오바오] --(내 PC Chrome, 로그인 상태)--> 수집(상품명·가격·이미지)
      --> 번역(구글 무료 주소) --> 판매가 계산 --> 스마트스토어 일괄등록 엑셀
```

## 폴더 구성

| 파일 | 역할 |
|---|---|
| `start_chrome.bat` | 수집용 Chrome 실행 (디버깅 포트 9222, 전용 프로필, **자동번역 끔**) |
| `taobao_collect.py` | 검색어(디자인 조명·인테리어 소품) 판매량순 수집. ¥39 미만·금지어 제외, 중복 방지 |
| `cart_collect.py` | **내 장바구니** 상품만 천천히 수집 (`--probe`: 개수만 확인) |
| `test_run.bat` / `run_weekly.bat` | 검색 수집 실행 (주간 작업 스케줄러용) |
| `cart_run.bat` / `cart_probe.bat` | 장바구니 수집 / 개수 확인 |
| `setup.bat` | 패키지 설치 |
| `smartstore/make_excel.py` | 상품 JSON → 스마트스토어 일괄등록 xlsx |
| `smartstore/ExcelSaveTemplate.xlsx` | 스마트스토어센터에서 받은 일괄등록 양식 (2026-03-24판) |
| `sample/listing_test.json` | 테스트용 상품 2개 (회전목마 오르골, 캔들 무드등) |
| `tests/test_offline.py` | 인터넷 없이 돌아가는 테스트 |

## 사용법 (Windows)

1. `setup.bat` 더블클릭 (Python 3.10+ 필요)
2. `start_chrome.bat` → 뜬 창에서 **타오바오 로그인** (처음 한 번)
3. `cart_probe.bat` 으로 장바구니 개수 확인 → `cart_run.bat` 으로 수집
4. 결과: `output/날짜_cart/products.json`, 상품별 이미지 폴더
5. 엑셀 만들기:
   ```
   cd smartstore
   python make_excel.py ..\sample\listing_test.json 업로드.xlsx
   ```
6. 스마트스토어센터 → 상품 일괄등록 → **이미지 먼저 업로드** → 엑셀 업로드

## 판매가 공식

`(위안 × 200원 + 배송비 6,000원) × 1.3` → 100원 단위 올림, **무료배송**(배송비는 판매가에 포함)

## 테스트

```
cd taobao
pip install -r requirements.txt
python -m pytest tests -q
```

## 지금까지 확인된 것 (2026-11-09)

- ✅ 로그인된 수집용 Chrome으로 검색·상세 수집 성공 (7/7)
- ✅ 장바구니 상품만 골라내기 (체크박스 기준, 추천상품 제외) 10/10
- ✅ 엑셀 일괄등록 파일 생성 → 업로드 시 **필수 3칸(카테고리코드·원산지코드·A/S 전화번호) 미입력 + 이미지 미업로드**로 실패 → 채우면 됨
- ⚠ 짧은 시간에 많이 열면 타오바오가 **캡차 / "접속 이상 감지"** 로 막음 → 하루 1회, 상품 간 35~75초 대기 권장
- ⚠ 수집용 Chrome이 페이지를 **자동번역**하면 가격("엔")·상품명 파싱이 깨짐 → `start_chrome.bat`에서 번역 끔
- ⚠ 엑셀 양식에 **전시 안 함(비공개)·해외구매대행 표시** 칸이 없음 → 업로드 후 스마트스토어센터에서 판매중지/구매대행 설정
- ⚠ LED 조명은 전기용품이라 **KC 인증** 확인 필요 (`인증허가사항`은 임시값)

## 주의

- `chrome-profile/`(로그인 쿠키), `output/`(수집 사진), `history.json`은 **GitHub에 올리지 않습니다** (`.gitignore` 처리됨). 이 저장소는 공개 저장소입니다.
- 타오바오 판매자 사진은 저작권 문제가 생길 수 있습니다.
- 매주 완전 자동 등록은 엑셀 대신 **네이버 커머스 API**로 가는 것을 권장합니다 (상위 폴더 `app/integrations/naver.py` 참고).
