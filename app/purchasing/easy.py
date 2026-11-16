"""간편 설정, 간편 판매가, 네이버 스마트스토어 일괄등록 엑셀.

판매가 규칙 (사용자 결정 2026-11-16): 판매 수수료를 뺀 뒤에도 원가의 N%(기본 7%)가 남도록 한다.
    원가   = 위안 가격 × 환율 + 상품 1개당 추가 비용(국제·국내 배송비 등)
    판매가 = 원가 × (1 + 마진) ÷ (1 − 판매 수수료율), 10원 단위 올림
엑셀 열 구성은 사용자가 스마트스토어센터에서 받은 ExcelSaveTemplate_20260324.xlsx 와 같다.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from .pricing import ValidationError

DEFAULTS = {
    "margin_pct": "7", "commission_pct": "", "fx_krw_per_cny": "", "extra_cost_krw": "",
    "stock": "999", "category_code": "", "origin_code": "", "importer": "", "customs": "부과 대상 아님",
    "shipping_template_code": "", "as_template_code": "", "as_phone": "", "as_note": "",
}
LABELS = {
    "margin_pct": "마진(%) — 수수료를 뺀 뒤 원가 대비 남길 비율",
    "commission_pct": "판매 수수료(%) — 판매처가 떼는 비율 (네이버 정산 내역에서 확인)",
    "fx_krw_per_cny": "환율 — 1위안에 몇 원",
    "extra_cost_krw": "상품 1개당 추가 비용(원) — 국제 배송비, 국내 배송비 등 합계",
    "stock": "재고 수량 (옵션마다 같은 값)",
    "category_code": "네이버 카테고리 코드 (기본값, 상품마다 다르면 엑셀에서 수정)",
    "origin_code": "원산지 코드 (스마트스토어 '원산지 찾기'에서 중국 코드 확인)",
    "importer": "수입사 (원산지가 수입산이면 필수)",
    "customs": "관부가세",
    "shipping_template_code": "배송비 템플릿 코드 (스마트스토어 > 템플릿관리)",
    "as_template_code": "A/S 템플릿 코드 (있으면 아래 두 칸은 비워도 됨)",
    "as_phone": "A/S 전화번호", "as_note": "A/S 안내",
}
CUSTOMS_CHOICES = ("부과 대상 아님", "관부가세 포함", "관부가세 미포함")
SETTINGS_KEY = "easy_settings"


def _dec(value, name: str, required: bool = True) -> Decimal | None:
    text = str(value if value is not None else "").replace(",", "").strip()
    if not text:
        if required:
            raise ValidationError(f"설정에서 '{LABELS.get(name, name).split(' — ')[0]}' 값을 먼저 넣어주세요.")
        return None
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ValidationError(f"{LABELS.get(name, name).split(' — ')[0]}: 숫자로 넣어주세요.")
    if not d.is_finite() or d < 0:
        raise ValidationError(f"{LABELS.get(name, name).split(' — ')[0]}: 0 이상의 숫자로 넣어주세요.")
    return d


def clean_settings(form: dict) -> dict:
    out = {}
    for key, default in DEFAULTS.items():
        value = str(form.get(key, default) or "").strip()[:200]
        if key in ("margin_pct", "commission_pct", "fx_krw_per_cny", "extra_cost_krw", "stock") and value:
            _dec(value, key)
        if key == "commission_pct" and value and _dec(value, key) >= 100:
            raise ValidationError("판매 수수료는 100%보다 작아야 합니다.")
        if key == "customs" and value not in CUSTOMS_CHOICES:
            raise ValidationError("관부가세 값을 목록에서 고르세요.")
        if key == "as_phone" and value and not re.fullmatch(r"[0-9+\-]{1,20}", value):
            raise ValidationError("A/S 전화번호는 숫자, -, + 만 20자까지 넣을 수 있습니다.")
        out[key] = value
    return out


def sale_price(unit_price_cny, settings: dict) -> dict:
    """판매가와 계산 내역. 10원 단위로 올림한다(네이버 판매가는 10원 단위)."""
    price = _dec(unit_price_cny, "unit_price")
    fx = _dec(settings.get("fx_krw_per_cny"), "fx_krw_per_cny")
    margin = _dec(settings.get("margin_pct"), "margin_pct") / 100
    commission = _dec(settings.get("commission_pct"), "commission_pct") / 100
    extra = _dec(settings.get("extra_cost_krw"), "extra_cost_krw")
    if fx <= 0:
        raise ValidationError("환율은 0보다 커야 합니다.")
    if commission >= 1:
        raise ValidationError("판매 수수료는 100%보다 작아야 합니다.")
    cost = price * fx + extra
    exact = cost * (1 + margin) / (1 - commission)
    sale = int((exact / 10).to_integral_value(rounding=ROUND_CEILING) * 10)
    fee = Decimal(sale) * commission
    profit = Decimal(sale) - fee - cost
    return {"sale_krw": sale, "cost_krw": int(cost.to_integral_value(rounding=ROUND_CEILING)),
            "fee_krw": int(fee.to_integral_value(rounding=ROUND_CEILING)), "profit_krw": int(profit),
            "profit_over_cost": (profit / cost) if cost > 0 else Decimal(0)}


# ---- 네이버 일괄등록 엑셀 -------------------------------------------------------------------------------

NAVER_GROUPS = (("A", "상품 기본정보"), ("Z", "상품 주요정보"), ("AI", "배송정보"), ("AY", "상품정보제공고시"),
                ("BD", "A/S, 특이사항"), ("BH", "할인/혜택정보"), ("BY", "기타 정보"))
NAVER_MERGES = ("A1:Y1", "Z1:AH1", "AI1:AX1", "AY1:BC1", "BD1:BG1", "BH1:BX1", "BY1:CO1")
NAVER_HEADERS = (
    "판매자 상품코드", "카테고리코드", "상품명", "상품상태", "판매가", "단위가격 사용여부", "표시용량", "표시단위", "총용량",
    "부가세", "관부가세", "재고수량", "옵션형태", "옵션명", "옵션값", "옵션가", "옵션 재고수량", "직접입력 옵션",
    "추가상품명", "추가상품값", "추가상품가", "추가상품 재고수량", "대표이미지", "추가이미지", "상세설명", "브랜드", "제조사",
    "제조일자", "유효일자", "원산지코드", "수입사", "복수원산지여부", "원산지 직접입력", "미성년자 구매", "배송비 템플릿코드",
    "배송방법", "택배사코드", "배송비유형", "기본배송비", "배송비 결제방식", "조건부무료-\n상품판매가 합계", "수량별부과-수량",
    "구간별-\n2구간수량", "구간별-\n3구간수량", "구간별-\n3구간배송비", "구간별-\n추가배송비", "반품배송비", "교환배송비",
    "지역별 차등 배송비", "별도설치비", "상품정보제공고시 템플릿코드", "상품정보제공고시\n품명", "상품정보제공고시\n모델명",
    "상품정보제공고시\n인증허가사항", "상품정보제공고시\n제조자", "A/S 템플릿코드", "A/S 전화번호", "A/S 안내", "판매자특이사항",
    "즉시할인 값\n(기본할인)", "즉시할인 단위\n(기본할인)", "모바일\n즉시할인 값", "모바일\n즉시할인 단위",
    "복수구매할인\n조건 값", "복수구매할인\n조건 단위", "복수구매할인\n값", "복수구매할인\n단위", "상품구매시 포인트\n지급 값",
    "상품구매시 포인트\n지급 단위", "텍스트리뷰 작성시\n지급 포인트", "포토/동영상 리뷰 작성시\n지급 포인트",
    "한달사용 텍스트리뷰\n작성시 지급 포인트", "한달사용\n포토/동영상리뷰 작성시 지급 포인트",
    "알림받기동의 고객 리뷰 작성 시 지급 포인트", "무이자\n할부 개월", "사은품", "판매자바코드", "구매평 노출여부",
    "구매평\n비노출사유", "알림받기 동의 고객 전용 여부", "ISBN", "ISSN", "독립출판", "출간일", "출판사", "글작가", "그림작가",
    "번역자명", "문화비 소득공제", "사이즈\n상품군", "사이즈\n사이즈명", "사이즈\n상세 사이즈", "사이즈 \n모델명",
)
_NAME_FORBIDDEN = re.compile(r'[\\*?"<>]')


def _option_value(name: str) -> str:
    return re.sub(r"[,\n\r]+", " ", name).strip()[:25] or "옵션"


def naver_row(p: dict, translation: dict | None, settings: dict) -> tuple[dict, list[str]]:
    """상품 1개의 엑셀 한 줄(열 이름 → 값)과, 올리기 전에 확인할 점 목록."""
    warnings: list[str] = []
    if not translation:
        raise ValidationError("한국어 번역이 없습니다. 상품 화면에서 번역을 먼저 저장하세요.")
    title = _NAME_FORBIDDEN.sub(" ", translation["title_ko"]).strip()
    if len(title) > 100:
        warnings.append("상품명이 100자를 넘어 잘랐습니다.")
        title = title[:100]
    if translation.get("status") != "reviewed":
        warnings.append("번역이 아직 검수 완료가 아닙니다.")
    if not p.get("images"):
        raise ValidationError("이미지가 없습니다. 대표이미지는 필수입니다.")
    if not settings.get("category_code"):
        warnings.append("카테고리 코드가 비어 있습니다. 엑셀의 '카테고리코드' 칸을 채워야 올라갑니다.")
    if not settings.get("origin_code"):
        warnings.append("원산지 코드가 비어 있습니다. 엑셀의 '원산지코드' 칸을 채워야 올라갑니다.")
    if not settings.get("as_template_code") and not (settings.get("as_phone") and settings.get("as_note")):
        warnings.append("A/S 템플릿 코드 또는 A/S 전화번호·안내가 필요합니다.")
    if not settings.get("shipping_template_code"):
        warnings.append("배송비 템플릿 코드가 없으면 '배송없음' 상품으로 등록됩니다.")

    names = translation.get("option_names") or {}
    priced = [(_option_value(names.get(o["source_option_id"]) or o["name"]),
               sale_price(o["unit_price"], settings)["sale_krw"]) for o in p["options"]]
    base = min(price for _, price in priced)
    row = {"판매자 상품코드": f"TB{p['source_product_id']}"[:30], "카테고리코드": settings.get("category_code", ""),
           "상품명": title, "상품상태": "신상품", "판매가": base, "부가세": "과세상품", "관부가세": settings.get("customs", ""),
           "재고수량": int(_dec(settings.get("stock"), "stock")),
           "대표이미지": p["images"][0], "추가이미지": "\n".join(p["images"][1:10]),
           "원산지코드": settings.get("origin_code", ""), "수입사": settings.get("importer", ""),
           "배송비 템플릿코드": settings.get("shipping_template_code", ""),
           "A/S 템플릿코드": settings.get("as_template_code", ""), "A/S 전화번호": settings.get("as_phone", ""),
           "A/S 안내": settings.get("as_note", "")}
    if len(priced) > 1 or priced[0][0] not in ("기본", "옵션"):
        values, seen = [], set()
        for value, price in priced:
            while value in seen:
                value = (value[:23] + "_2") if not value.endswith("_2") else value[:22] + "_3"
            seen.add(value)
            values.append((value, price))
        limit = base if base < 10000 else base // 2      # 옵션가 상한: 1만원 미만 +100%, 1만원 이상 +50%
        if any(price - base > limit for _, price in values):
            warnings.append("옵션 가격 차이가 네이버 허용 범위(판매가의 +50%, 1만원 미만은 +100%)를 넘습니다. 옵션을 나눠 등록하세요.")
        row.update({"옵션형태": "조합형", "옵션명": "옵션", "옵션값": ",".join(v for v, _ in values),
                    "옵션가": ",".join(str(price - base) for _, price in values),
                    "옵션 재고수량": ",".join([str(row["재고수량"])] * len(values))})
    text = "".join(f"<p>{_html(line)}</p>" for line in translation["description_ko"].splitlines() if line.strip())
    row["상세설명"] = text + "".join(f'<img src="{_html(u)}">' for u in p["images"])
    return row, warnings


def _html(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def naver_workbook(rows: list[dict]) -> bytes:
    """1~2행은 양식의 제목 줄, 3행부터 상품. (양식의 3~6행 작성 가이드는 업로드 전에 지우라고 안내되어 있다.)"""
    from openpyxl import Workbook
    from openpyxl.utils import column_index_from_string

    wb = Workbook()
    ws = wb.active
    ws.title = "일괄등록"
    for col, title in NAVER_GROUPS:
        ws.cell(1, column_index_from_string(col), title)
    for merged in NAVER_MERGES:
        ws.merge_cells(merged)
    for i, header in enumerate(NAVER_HEADERS, start=1):
        ws.cell(2, i, header)
    index = {h: i for i, h in enumerate(NAVER_HEADERS, start=1)}
    text_columns = {"카테고리코드", "원산지코드", "배송비 템플릿코드", "A/S 템플릿코드", "판매자 상품코드", "옵션가", "옵션 재고수량"}
    for r, row in enumerate(rows, start=3):
        for header, value in row.items():
            if value in ("", None):
                continue
            cell = ws.cell(r, index[header], str(value) if header in text_columns else value)
            if header in text_columns:
                cell.number_format = "@"      # 앞자리 0이 지워지지 않게 텍스트로
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
