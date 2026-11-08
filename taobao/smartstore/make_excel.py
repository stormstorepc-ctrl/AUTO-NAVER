"""
스마트스토어 엑셀 일괄등록 파일 생성기

입력: 상품 정의 JSON (예: ../sample/listing_test.json)
      + 네이버 스마트스토어센터에서 받은 일괄등록 양식 (ExcelSaveTemplate.xlsx)
출력: 업로드용 xlsx (작성가이드 3~6행 삭제, 데이터는 3행부터)

사용법:
    python make_excel.py ../sample/listing_test.json 출력파일.xlsx

판매가 공식 (사용자 지정):
    (위안 가격 × 환율 200원 + 배송비 6,000원) × 1.3  → 100원 단위 올림
    배송비는 판매가에 포함하고 배송비 유형은 '무료'
"""

import json
import math
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

HERE = Path(__file__).parent
TEMPLATE = HERE / "ExcelSaveTemplate.xlsx"

RATE_KRW_PER_CNY = 200
SHIPPING_KRW = 6000
MARGIN = 0.30


def calc_price(cny: float) -> int:
    """판매가 계산: (위안×200 + 6000) × 1.3, 100원 단위 올림."""
    raw = (cny * RATE_KRW_PER_CNY + SHIPPING_KRW) * (1 + MARGIN)
    return int(math.ceil(round(raw, 2) / 100.0) * 100)


DETAIL_NOTICE = (
    "<p>[해외구매대행 안내]<br>본 상품은 해외구매대행 상품으로 주문 후 현지에서 구매가 진행되며, "
    "배송까지 약 7~14일 소요됩니다.<br>통관을 위해 개인통관고유부호가 필요합니다.<br>"
    "현지 사정에 따라 색상·디테일이 사진과 다소 다를 수 있습니다.</p>"
)

# 모든 상품에 공통으로 들어가는 값 (양식의 헤더명 그대로)
COMMON = {
    "상품상태": "신상품",
    "부가세": "과세상품",
    "관부가세": "부과 대상 아님",
    "수입사": "해외구매대행",
    "복수원산지여부": "N",
    "미성년자 구매": "Y",
    "배송방법": "택배‚ 소포‚ 등기",  # 양식 목록값이 특수 쉼표(U+201A)를 씀
    "택배사코드": "CJGLS",
    "배송비유형": "무료",
    "반품배송비": 20000,
    "교환배송비": 40000,
    "별도설치비": "N",
    "상품정보제공고시\n모델명": "상세설명 참조",
    "상품정보제공고시\n인증허가사항": "상세설명 참조",
    "상품정보제공고시\n제조자": "중국 제조사 (상세설명 참조)",
    "A/S 안내": "해외구매대행 상품으로 국내 A/S가 어렵습니다. 초기 불량은 수령 후 7일 이내 고객센터로 문의해 주세요.",
    "판매자특이사항": "해외구매대행 상품으로 주문 후 현지 구매가 진행되며 배송까지 약 7~14일 소요됩니다. 통관을 위해 개인통관고유부호가 필요합니다.",
    "구매평 노출여부": "Y",
}

# 사용자가 스마트스토어센터 팝업에서 확인해 채워야 하는 칸 (노란색 표시)
MUST_FILL = ["카테고리코드", "원산지코드", "A/S 전화번호"]


def build_row(p: dict, settings: dict) -> dict:
    row = dict(COMMON)
    row.update({
        "판매자 상품코드": f"TB{p['item_id']}",
        "상품명": p["title_ko"],
        "판매가": calc_price(p["price_cny"]),
        "재고수량": p.get("stock", 99),
        "대표이미지": p["images"][0],
        "추가이미지": "\n".join(p["images"][1:10]),
        "상세설명": (
            '<div style="text-align:center;font-size:15px;line-height:1.8">'
            f"<p><b>{p['title_ko']}</b></p><p>{p.get('description', '')}</p>{DETAIL_NOTICE}</div>"
        ),
        "상품정보제공고시\n품명": p.get("notice_name", p["title_ko"][:50]),
    })
    # 옵션 (조합형, 옵션명 1개)
    opts = p.get("options")
    if opts:
        base = calc_price(p["price_cny"])
        row["옵션형태"] = "조합형"
        row["옵션명"] = p.get("option_name", "옵션")
        row["옵션값"] = ",".join(o["name"] for o in opts)
        row["옵션가"] = ",".join(str(calc_price(o["price_cny"]) - base) for o in opts)
        row["옵션 재고수량"] = ",".join(str(o.get("stock", 20)) for o in opts)
    for k in MUST_FILL:
        if settings.get(k):
            row[k] = settings[k]
    return row


def check_option_prices(row: dict) -> list[str]:
    """스마트스토어 옵션가 규칙(판매가 1만원 이상: -50%~+50%) 위반 검사."""
    problems = []
    if "옵션가" not in row:
        return problems
    price = row["판매가"]
    diffs = [int(x) for x in row["옵션가"].split(",")]
    if 0 not in diffs:
        problems.append("옵션가 중 0원인 옵션이 최소 1개 있어야 함")
    lo, hi = (-0.5 * price, 0.5 * price) if price >= 10000 else (-0.5 * price, 1.0 * price)
    for d in diffs:
        if not (lo <= d <= hi):
            problems.append(f"옵션가 {d}원이 허용 범위({lo:.0f}~{hi:.0f})를 벗어남")
    return problems


def make_excel(listing_path: Path, out_path: Path, template: Path = TEMPLATE) -> list[str]:
    data = json.loads(Path(listing_path).read_text(encoding="utf-8"))
    settings = data.get("settings", {})
    wb = load_workbook(template)
    ws = wb.active
    hdr = {ws.cell(2, c).value: c for c in range(1, ws.max_column + 1)}
    yellow = PatternFill("solid", start_color="FFFF00")
    warnings = []

    for i, p in enumerate(data["products"]):
        r = 7 + i  # 양식의 데이터 유효성 검사가 7행부터 → 나중에 3~6행 삭제
        row = build_row(p, settings)
        warnings += [f"{p['item_id']}: {w}" for w in check_option_prices(row)]
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(r, c)
            cell.font = Font(name="맑은 고딕", size=9)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for k, v in row.items():
            if k not in hdr:
                raise KeyError(f"양식에 '{k}' 열이 없습니다 (양식이 바뀌었는지 확인)")
            ws.cell(r, hdr[k], v)
        ws.cell(r, hdr["원산지코드"]).number_format = "@"
        for k in MUST_FILL:
            if not row.get(k):
                ws.cell(r, hdr[k]).fill = yellow
                warnings.append(f"{p['item_id']}: '{k}' 비어 있음 (스마트스토어센터에서 확인 후 입력)")

    ws.delete_rows(3, 4)  # 작성가이드 행 삭제 (양식 안내문 지시사항)
    wb.save(out_path)
    return warnings


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python make_excel.py <listing.json> <output.xlsx>")
        sys.exit(1)
    warns = make_excel(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"저장: {sys.argv[2]}")
    for w in warns:
        print("  ⚠", w)
