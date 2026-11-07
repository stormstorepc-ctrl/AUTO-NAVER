# Claude 피드백 (최신)

- 작성: 2026-11-07 19:xx UTC (2026-11-08 04:xx KST), Claude 정기 확인
- 반영한 결과: PR #9 댓글 6711089604 (**Windows 10 Home 22H2 / Python 3.12.10**), 6711128206 (Linux / Python 3.12.14)
- **다음 테스트 커밋: da5fca8**
- Claude 정기 확인 예약: 활성 (매시 45분 UTC)

## 고친 것
| 보고 | 원인 | 수정 | Claude 검증 (Linux) |
|---|---|---|---|
| 일반 Chrome 폼 제출 403 `origin check failed` (샘플 가져오기, capture 저장) | ChatGPT 추정이 맞음: f3c9d27에서 모든 화면에 넣은 `<meta name=referrer content=no-referrer>` 때문에 Chrome이 `Origin: null`을 보냄 | 전체 화면 메타 제거. 외부 이미지에만 `referrerpolicy=no-referrer`. Origin 검사는 그대로(‘null’ 허용 안 함) | 새 Chromium 테스트가 **헤더를 덧붙이지 않은 실제 폼 제출**로 가져오기 → capture 저장 2회(옵션 2개 병합) → 연결 코드 재발급 확인. 옛 메타를 다시 넣으면 이 테스트가 403으로 실패함을 확인 |
| 가격 제안 오인식 4건 + 분리 span | `first_price`가 첫 숫자만 사용 | ¥/￥ 앞 또는 元 뒤 금액, 또는 숫자만 있는 문구만 제안. 범위(12.5-30)·판매량·조건 숫자는 **비워서 직접 입력**. extract.js는 `¥`/`39`/`.90` 분리 span을 부모에서 통째로 읽음 | 보고서 6개 + 범위·판매량 등 12개 케이스, 실제 Chromium fixture에서 `¥39.90` |
| 같은 옵션 재수집 시 무게·비용 6필드 소실 | 옵션을 새 dict로 교체 | 기존 옵션 위에 이름·가격만 갱신, 무게는 새로 입력했을 때만 교체 | 보고서 재현 케이스 통과 |
| lazy placeholder → 이미지 0개 / 추천 이미지 혼입 | 작은 src를 먼저 사용, document.images 전체 사용 | 작은 placeholder + data-src면 data-src 사용(대기 이미지로 안내). 갤러리/상세 영역 밖·추천 영역 이미지는 `other_images`로 분리, 검토 화면에서 **기본 해제** | fixture에 placeholder·추천 블록 추가, Chromium에서 확인 |

`pytest -q tests/` **161 passed** (Chromium 브라우저 테스트 5개 포함, 2회 연속 실행).

## 다시 테스트할 단계
1. `python -m pytest -q -rs tests/purchasing` (Windows는 POSIX 전용 2개 + 서버 띄우는 브라우저 테스트 2개 skip 예상 → 사유 기록)
2. **헤더를 덧붙이지 않은 실제 브라우저 기본 제출**로: 샘플 파일 가져오기 → 가격 → 번역 → 승인 → 모의 등록 → ZIP
3. capture: 합성 POST(테스트 연결 코드) → `/capture/{n}` → 배송·판매 확인 → "확인하고 저장" → 다른 옵션으로 한 번 더 → 옵션 2개
4. 같은 옵션 재수집(무게 비움) → 무게·비용 유지
5. 독립 검사 `test_requirements.py`(가격 4 + 재수집 1)와 `extract_diagnostics.cjs` 재실행. 참고: extract_diagnostics의 test double은 `document.querySelectorAll`만 흉내 내므로, 새 extract.js의 `el.contains`/`closest(GALLERY)` 호출에 맞춰 double을 보완해야 할 수 있음 (실제 Chromium 테스트는 위 1번에 포함)

## 아직 안 된 것
- 실제 타오바오/티몰 페이지, 실제 확장 버튼 클릭(activeTab), Windows에서 확장 로드: 미검증
- OCR 한글 이미지, 7개 일괄, 3단계 화면, 실제 스마트스토어 등록: 사용자 결정 대기
