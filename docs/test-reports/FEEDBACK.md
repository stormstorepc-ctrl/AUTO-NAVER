# Claude 피드백 (최신)

- 작성: 2026-11-16 (KST), Claude
- 사용자 결정(Claude 채팅): 장바구니 기반으로 단순화, 마진은 "수수료를 뺀 뒤 원가의 7%"(변경 가능), 네이버 일괄등록 엑셀. 사용자가 네이버 양식 `ExcelSaveTemplate_20260324.xlsx` 제공
- **다음 테스트 커밋: 이 파일이 포함된 최신 head** (기능 커밋: "간편 설정·네이버 엑셀")
- 설명: `docs/purchasing-easy-naver-excel.md`
- Claude 정기 확인 예약: 활성, 2시간마다

## 새로 만든 것
- `/easy`: 가격 설정(마진·수수료·환율·추가 비용), 네이버 등록 기본값, 상품 선택 → 네이버 일괄등록 엑셀 내려받기 / 올리기 전 확인할 점
- `app/purchasing/easy.py`, `tests/purchasing/test_easy.py`, `requirements.txt`에 `openpyxl` 추가 (설치 다시 필요)

## 다시 테스트할 단계
1. `purchasing_install.bat` (openpyxl 설치 확인) → `python -m pytest -q -rs tests/purchasing`
2. `/easy`에서 수수료 5, 환율 200, 추가 비용 3000 저장 → 샘플 상품(100위안) 판매가 25,910원, 마진을 10으로 바꾸면 26,640원
3. 번역 검수된 샘플 상품으로 엑셀 내려받기 → Excel에서 열어 1~2행 제목이 네이버 양식과 같은지, 3행에 상품명·판매가·옵션값·옵션가가 들어갔는지
4. 번역 없는 상품은 "올리기 전 확인할 점"에 제외 사유가 나오는지
5. (사용자만 가능) 스마트스토어센터 일괄등록에 실제로 올려 오류 메시지 확인 — 오류 문구를 그대로 기록

## 추가 (장바구니 가져오기, 확장 0.2.0)
- 장바구니 탭에서 확장 버튼 → `POST /capture/cart` → `/capture` 화면의 "장바구니에서 가져온 상품" 목록
- 테스트: `tests/purchasing/test_capture.py`(장바구니 검증·수신·검토 화면 채움), `test_extension_browser.py::test_cart_extract_reads_rows_and_skips_recommendations`
- 다시 테스트할 단계: 합성 장바구니 payload로 401/403/200, 같은 장바구니를 두 번 보내도 줄 수가 늘지 않는지, 목록 상태가 "안 열었음 → 사진 가져옴 → 상품 저장됨"으로 바뀌는지
- 실제 타오바오 장바구니 화면에서는 미검증

## 아직 안 된 것
- 상세 이미지 파일 저장, 이미지 한글화, 다른 판매처 엑셀: 다음 단계
- 실제 타오바오 페이지에서 확장 동작: 미검증
