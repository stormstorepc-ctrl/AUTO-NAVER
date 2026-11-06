"""Copy-paste flow for real Taobao products and chat translations. No network access is used."""
import pytest

from app.purchasing.assist import (parse_product_reply, parse_translation_reply, product_request, taobao_item,
                                   translation_request)
from app.purchasing.pricing import ValidationError
from tests.purchasing.test_review_ui import ORIGIN, form_values
from tests.purchasing.test_web import client, AUTH

URL = "https://item.taobao.com/item.htm?spm=a21n57.1.0.0&id=712345678901&ns=1"
PAGE = "收纳盒 桌面整理 白色 黑色 ¥19.90 ¥24.50 重量 300g 尺寸 20x10x5cm"
REPLY = """여기 JSON입니다:
```json
{"source_product_id": "FORGED", "supply_url": "https://evil.example/",
 "title_src": "桌面收纳盒", "category": "수납용품", "description_src": "尺寸 20x10x5cm",
 "restricted_flags": ["battery", "unknown_flag"],
 "options": [{"name": "白色", "unit_price": "¥19.90", "weight_g": "300"},
             {"name": "黑色", "unit_price": "24.50", "weight_g": ""}]}
```"""


@pytest.mark.parametrize("url, item_id, clean", [
    (URL, "712345678901", "https://item.taobao.com/item.htm?id=712345678901"),
    ("detail.tmall.com/item.htm?id=600000000001&skuId=1", "600000000001", "https://detail.tmall.com/item.htm?id=600000000001"),
    ("https://world.taobao.com/item/623456789012.htm", "623456789012", "https://item.taobao.com/item.htm?id=623456789012"),
])
def test_taobao_item_from_address(url, item_id, clean):
    assert taobao_item(url) == (item_id, clean)


@pytest.mark.parametrize("url", ["https://m.tb.cn/h.abc", "https://evil-taobao.com/item.htm?id=712345678901",
                                 "https://item.taobao.com/item.htm?id=abc", "javascript:alert(1)"])
def test_taobao_item_rejects_other_addresses(url):
    with pytest.raises(ValidationError):
        taobao_item(url)


def test_product_request_contains_page_and_rules():
    text = product_request(URL, PAGE)
    assert PAGE in text and "712345678901" in text and "지어내지" in text
    with pytest.raises(ValidationError):
        product_request(URL, "  ")


def test_product_reply_identity_comes_from_address_not_reply():
    p = parse_product_reply(URL, REPLY, sale_allowed_confirmed=False)
    assert p["source"] == "taobao" and p["source_product_id"] == "712345678901"
    assert p["supply_url"] == "https://item.taobao.com/item.htm?id=712345678901"
    assert [o["unit_price"] for o in p["options"]] == ["19.90", "24.50"]
    assert p["options"][0]["weight_g"] == "300" and "weight_g" not in p["options"][1]
    assert p["compliance"] == {"sale_allowed_confirmed": False, "restricted_flags": ["battery"]}


@pytest.mark.parametrize("reply", ["", "no json here", "{broken", '{"title_src": "x", "options": []}',
                                   '{"title_src": "x", "options": [{"name": "a", "unit_price": ""}]}'])
def test_bad_product_replies_are_rejected(reply):
    with pytest.raises(ValidationError):
        parse_product_reply(URL, reply, True)


def test_translation_reply_needs_every_option():
    p = parse_product_reply(URL, REPLY, True)
    assert "opt1" in translation_request(p) and "桌面收纳盒" in translation_request(p)
    good = '{"title_ko": "책상 수납함", "description_ko": "크기 20x10x5cm", "options": {"opt1": "화이트", "opt2": "블랙"}}'
    assert parse_translation_reply(p, good) == ("책상 수납함", "크기 20x10x5cm", {"opt1": "화이트", "opt2": "블랙"})
    with pytest.raises(ValidationError):
        parse_translation_reply(p, '{"title_ko": "a", "description_ko": "b", "options": {"opt1": "화이트"}}')


def test_url_import_and_translation_through_web(store):
    c = client(store)
    assert "주소로 상품 추가" in c.get("/import/url", headers=AUTH).text
    r = c.post("/import/url", headers=ORIGIN, data={"url": URL, "page_text": PAGE})
    assert r.status_code == 200 and "712345678901" in r.text and "Claude 답변" in r.text
    r = c.post("/import/url/save", headers=ORIGIN, data={"url": URL, "reply": REPLY})
    assert r.status_code == 200 and "새로 추가" in r.text and "승인 단계에서 막힙니다" in r.text
    r = c.post("/import/url/save", headers=ORIGIN, data={"url": URL, "reply": REPLY, "sale_allowed": "yes"})
    assert "정보 변경" in r.text
    page = c.get("/product/1", headers=AUTH)
    assert "Claude로 번역하기" in page.text
    values = form_values(page, "/product/1/translation/assist")
    reply = '{"title_ko": "책상 수납함", "description_ko": "크기 20x10x5cm", "options": {"opt1": "화이트", "opt2": "블랙"}}'
    r = c.post("/product/1/translation/assist", headers=ORIGIN, data={**values, "reply": reply})
    assert r.status_code == 200, r.text
    page = c.get("/product/1", headers=AUTH)
    assert "책상 수납함" in page.text and "/product/1/translation/review" in page.text


@pytest.mark.parametrize("path", ["/import/url", "/import/url/save", "/product/1/translation/assist"])
def test_new_posts_require_same_origin(store, path):
    assert client(store).post(path, headers=AUTH, data={}).status_code == 403
