"""간편 설정, 판매가(수수료 뺀 뒤 원가의 7%), 네이버 일괄등록 엑셀. 합성 자료만 사용."""
import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.purchasing import easy
from app.purchasing.pricing import ValidationError
from tests.purchasing.test_review_ui import ORIGIN, form_values, ready
from tests.purchasing.test_web import client, AUTH

SETTINGS = {**easy.DEFAULTS, "margin_pct": "7", "commission_pct": "5", "fx_krw_per_cny": "200", "extra_cost_krw": "3000",
            "category_code": "50003307", "origin_code": "0200037", "importer": "구매대행", "shipping_template_code": "2035152",
            "as_phone": "02-0000-0000", "as_note": "평일 10~17시"}


def test_sale_price_leaves_margin_of_cost_after_fee():
    q = easy.sale_price("100", SETTINGS)              # 원가 = 100×200 + 3000 = 23,000
    assert q["cost_krw"] == 23000
    assert q["sale_krw"] == 25910                     # 23,000×1.07÷0.95 = 25,905.26… → 10원 올림
    assert q["sale_krw"] % 10 == 0
    assert q["profit_krw"] >= 23000 * 0.07            # 수수료(5%)를 뺀 뒤에도 원가의 7% 이상
    assert q["profit_over_cost"] >= Decimal("0.07")


def test_margin_change_reprices():
    assert easy.sale_price("100", {**SETTINGS, "margin_pct": "10"})["sale_krw"] == 26640   # 23,000×1.10÷0.95 올림
    assert easy.sale_price("100", {**SETTINGS, "margin_pct": "0", "commission_pct": "0"})["sale_krw"] == 23000


@pytest.mark.parametrize("patch", [{"fx_krw_per_cny": ""}, {"commission_pct": ""}, {"extra_cost_krw": ""},
                                   {"fx_krw_per_cny": "0"}, {"margin_pct": "abc"}])
def test_missing_or_bad_settings_block_price(patch):
    with pytest.raises(ValidationError):
        easy.sale_price("100", {**SETTINGS, **patch})


def test_clean_settings_validates():
    assert easy.clean_settings({"margin_pct": " 7 "})["margin_pct"] == "7"
    for bad in ({"commission_pct": "100"}, {"customs": "모름"}, {"as_phone": "전화"}, {"stock": "-1"}):
        with pytest.raises(ValidationError):
            easy.clean_settings(bad)


PRODUCT = {"source_product_id": "712345678901", "title_src": "收纳盒",
           "images": [f"https://img.example.invalid/{i}.jpg" for i in range(12)],
           "options": [{"source_option_id": "a", "name": "白色", "unit_price": "100"},
                       {"source_option_id": "b", "name": "黑色", "unit_price": "120"}]}
TR = {"title_ko": '책상 수납함 "특가" <신상>', "description_ko": "크기 20x10x5cm\n소재 <PP>", "status": "reviewed",
      "option_names": {"a": "화이트, 소형", "b": "블랙"}}


def test_naver_row_options_images_and_escaping():
    row, warnings = easy.naver_row(PRODUCT, TR, SETTINGS)
    assert warnings == []
    assert row["상품명"] == "책상 수납함  특가   신상" and row["판매가"] == 25910 and row["판매자 상품코드"] == "TB712345678901"
    assert row["옵션형태"] == "조합형" and row["옵션명"] == "옵션" and row["옵션값"] == "화이트  소형,블랙"
    assert row["옵션가"] == "0,4510" and row["옵션 재고수량"] == "999,999"       # 120위안 → 30,420원
    assert row["대표이미지"].endswith("/0.jpg") and row["추가이미지"].count("\n") == 8   # 추가이미지 최대 9개
    assert "&lt;PP&gt;" in row["상세설명"] and row["상세설명"].count("<img ") == 12


def test_naver_row_warnings_and_blocks():
    _, warnings = easy.naver_row(PRODUCT, {**TR, "status": "draft"}, {**SETTINGS, "category_code": "", "origin_code": "",
                                                                   "shipping_template_code": "", "as_phone": ""})
    assert len(warnings) == 5
    far = {**PRODUCT, "options": [PRODUCT["options"][0], {"source_option_id": "b", "name": "大", "unit_price": "400"}]}
    assert any("옵션 가격 차이" in w for w in easy.naver_row(far, TR, SETTINGS)[1])
    with pytest.raises(ValidationError):
        easy.naver_row(PRODUCT, None, SETTINGS)
    with pytest.raises(ValidationError):
        easy.naver_row({**PRODUCT, "images": []}, TR, SETTINGS)


def test_workbook_matches_naver_template_layout():
    row, _ = easy.naver_row(PRODUCT, TR, SETTINGS)
    ws = load_workbook(io.BytesIO(easy.naver_workbook([row]))).active
    assert ws.title == "일괄등록" and ws.max_column == 93 and len(easy.NAVER_HEADERS) == 93
    assert ws["A1"].value == "상품 기본정보" and ws["BY1"].value == "기타 정보"
    assert sorted(str(r) for r in ws.merged_cells.ranges) == sorted(easy.NAVER_MERGES)
    assert [ws["A2"].value, ws["E2"].value, ws["W2"].value, ws["Y2"].value, ws["AD2"].value, ws["AI2"].value,
            ws["BE2"].value, ws["CO2"].value] == ["판매자 상품코드", "판매가", "대표이미지", "상세설명", "원산지코드",
                                                 "배송비 템플릿코드", "A/S 전화번호", "사이즈 \n모델명"]
    assert ws["C3"].value == row["상품명"] and ws["E3"].value == 25910
    assert ws["AD3"].value == "0200037" and ws["AD3"].number_format == "@"      # 앞자리 0 유지
    assert ws["B3"].value == "50003307" and ws["P3"].value == "0,4510"


def test_settings_and_export_through_web(store):
    c = client(store)
    ready(c)                                            # 샘플 상품 + 검수된 번역
    assert "간편 설정" in c.get("/easy", headers=AUTH).text
    assert c.post("/easy/settings", headers=AUTH, data=SETTINGS).status_code == 403          # Origin 검사 유지
    assert c.post("/easy/settings", headers=ORIGIN, data=SETTINGS).status_code == 200
    page = c.get("/easy", headers=AUTH)
    assert "25,910원" in page.text and form_values(page, "/easy/settings")["margin_pct"] == "7"
    check = c.post("/easy/naver/check", headers=ORIGIN, data={"ids": "1"})
    assert "엑셀에 들어가는 상품 1개" in check.text and "확인할 점이 없습니다" in check.text
    r = c.post("/easy/naver.xlsx", headers=ORIGIN, data={"ids": "1"})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws["C3"].value == "시연용 수납함" and ws["E3"].value == 25910 and ws["O3"].value == "화이트,블랙"
    assert c.post("/easy/naver.xlsx", headers=ORIGIN, data={}).status_code == 400
