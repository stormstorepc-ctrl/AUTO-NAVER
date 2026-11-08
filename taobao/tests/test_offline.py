"""
오프라인 테스트 (타오바오/네이버 접속 없이 실행 가능)

    cd taobao
    python -m pytest tests -q      # 또는: python tests/test_offline.py

- 가격 공식, 상품번호 추출, 검색결과 가격 파싱, 엑셀 생성 규칙을 검사합니다.
- playwright 가 설치되어 있지 않아도 동작하도록 가짜 모듈로 대체합니다.
"""

import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "smartstore"))

if "playwright.async_api" not in sys.modules:  # 브라우저 없이 import 가능하게
    pw = types.ModuleType("playwright")
    api = types.ModuleType("playwright.async_api")
    api.async_playwright = None
    sys.modules["playwright"] = pw
    sys.modules["playwright.async_api"] = api

import taobao_collect as t  # noqa: E402
import make_excel as mx  # noqa: E402

CARD_PRICE_RE = re.compile(r"[¥￥]\s*(\d+)(?:\s*\.\s*(\d+))?")


def test_item_id_from_url():
    assert t.item_id_from_url("https://item.taobao.com/item.htm?id=123456789&spm=x") == "123456789"
    assert t.item_id_from_url("https://detail.tmall.com/item.htm?abc=1&id=987") == "987"
    assert t.item_id_from_url("https://www.taobao.com/") is None


def test_card_price_parse():
    m = CARD_PRICE_RE.search("北欧台灯\n¥\n128\n.5\n2000+人付款")
    assert float(m.group(1) + "." + (m.group(2) or "0")) == 128.5
    assert CARD_PRICE_RE.search("가격 21.8 엔") is None  # 자동번역되면 파싱 불가 → 번역 꺼야 함


def test_price_formula():
    assert mx.calc_price(205) == 61100     # (41000+6000)*1.3 = 61100
    assert mx.calc_price(21.8) == 13500    # 13468 → 13500
    assert mx.calc_price(46.8) == 20000    # 19968 → 20000


def test_make_excel(tmp_path=None):
    from openpyxl import load_workbook
    out = Path(tmp_path or ROOT) / "_test_output.xlsx"
    warns = mx.make_excel(ROOT / "sample" / "listing_test.json", out)
    ws = load_workbook(out).active
    hdr = {ws.cell(2, c).value: c for c in range(1, ws.max_column + 1)}
    assert ws.max_row == 4                          # 헤더 2행 + 상품 2개
    assert ws.cell(3, hdr["판매가"]).value == 61100
    assert ws.cell(4, hdr["옵션가"]).value == "0,0,0,6500,6500,6500,6500,6500"
    assert ws.cell(3, hdr["배송비유형"]).value == "무료"
    assert any("카테고리코드" in w for w in warns)  # 빈 필수칸 경고
    assert not any("옵션가" in w and "범위" in w for w in warns)
    if tmp_path is None:
        out.unlink()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
