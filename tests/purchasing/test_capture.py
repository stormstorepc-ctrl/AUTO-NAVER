"""Chrome extension capture: payload validation, pairing-code endpoint, review and merge. Synthetic data only."""
import re

import pytest

from app.purchasing.capture import first_price, option_id, product_from_capture, validate_capture
from app.purchasing.pricing import ValidationError
from app.purchasing.workflow import screen_blockers
from tests.purchasing.test_review_ui import ORIGIN, form_values
from tests.purchasing.test_web import client, AUTH

EXT = {"Origin": "chrome-extension://abcdefghijklmnop", "Content-Type": "application/json"}


def payload(**over):
    p = {"schema": 1, "status": "ok", "url": "https://detail.tmall.com/item.htm?id=1055677150014&skuId=5",
         "title": "合成测试 沥水架", "price_texts": ["¥39.90", "¥59.00"], "selected_options": ["白色 50cm"],
         "images": ["https://img.example.invalid/main1.jpg", "//img.example.invalid/main2.jpg", "data:image/png;base64,xx"],
         "detail_images": ["https://img.example.invalid/d1.jpg", "https://img.example.invalid/main1.jpg"],
         "notes": ["note"], "captured_at": "2026-11-08T00:00:00Z"}
    p.update(over)
    return p


def test_validate_capture_normalizes_and_filters():
    d = validate_capture(payload())
    assert d["item_id"] == "1055677150014" and d["url"] == "https://detail.tmall.com/item.htm?id=1055677150014"
    assert d["images"] == ["https://img.example.invalid/main1.jpg", "https://img.example.invalid/main2.jpg"]
    assert d["detail_images"] == ["https://img.example.invalid/d1.jpg"]  # duplicate of main removed
    assert first_price(d["price_texts"]) == "39.90"


@pytest.mark.parametrize("over, msg", [
    ({"status": "login_required"}, "로그인"), ({"status": "captcha"}, "보안 확인"), ({"status": "no_product"}, "상품 정보"),
    ({"schema": 2}, "형식"), ({"url": "https://evil.example/item.htm?id=1055677150014"}, "타오바오"),
    ({"title": ""}, "제목"), ({"images": "x"}, "images"),
])
def test_validate_capture_rejects(over, msg):
    with pytest.raises(ValidationError) as e:
        validate_capture(payload(**over))
    assert msg in str(e.value)


# Cases from ChatGPT report (PR #9 comment 6711128206).
@pytest.mark.parametrize("text, expected", [
    ("¥1,299.00", "1299.00"), ("满200减30，到手价¥39.90", "39.90"), ("月销 1000+", ""), ("已选50cm，¥39.90", "39.90"),
    ("¥1299.00", "1299.00"), ("¥39.90", "39.90"), ("39.90", "39.90"), ("39.90元", "39.90"),
    ("券后 ¥12.5-30", ""), ("¥12.5~¥30", ""), ("39", "39"), ("已售 2万+", ""),
])
def test_first_price_only_suggests_clear_amounts(text, expected):
    assert first_price([text]) == expected


def test_first_price_skips_unclear_and_uses_next():
    assert first_price(["月销 1000+", "¥39.90"]) == "39.90"
    assert first_price([]) == ""


def test_recapture_keeps_weight_and_costs():
    cap = {"item_id": "1055677150014", "url": "https://detail.tmall.com/item.htm?id=1055677150014",
           "data": validate_capture(payload(price_texts=["¥39.90"], selected_options=["白色"]))}
    first = product_from_capture(cap, None, {"option_name": "白色", "unit_price": "39.90", "weight_g": "500",
                                             "delivery_min": "7", "delivery_max": "14"})
    costs = ("china_shipping_krw", "handling_krw", "seller_customs_krw", "domestic_shipping_krw", "payment_fee_rate", "reserve_rate")
    for key in costs:
        first["options"][0][key] = "0"
    again = product_from_capture(cap, first, {"option_name": "白色", "unit_price": "41", "weight_g": ""})
    o = again["options"][0]
    assert o["weight_g"] == "500" and o["unit_price"] == "41" and all(k in o for k in costs) and len(again["options"]) == 1
    heavier = product_from_capture(cap, again, {"option_name": "白色", "unit_price": "41", "weight_g": "650"})
    assert heavier["options"][0]["weight_g"] == "650"


def test_other_images_are_kept_apart_and_selectable():
    d = validate_capture(payload(other_images=["https://img.example.invalid/rec.jpg", "https://img.example.invalid/main1.jpg"]))
    assert d["other_images"] == ["https://img.example.invalid/rec.jpg"]
    cap = {"item_id": d["item_id"], "url": d["url"], "data": d}
    p = product_from_capture(cap, None, {"option_name": "a", "unit_price": "1", "images": ["https://img.example.invalid/rec.jpg"]})
    assert p["images"] == ["https://img.example.invalid/rec.jpg"]


def test_merge_keeps_other_options_and_images():
    cap = {"item_id": "1055677150014", "url": "https://detail.tmall.com/item.htm?id=1055677150014", "data": validate_capture(payload())}
    first = product_from_capture(cap, None, {"option_name": "白色 50cm", "unit_price": "39.90",
                                             "images": ["https://img.example.invalid/main1.jpg"],
                                             "delivery_min": "7", "delivery_max": "14", "sale_allowed": "yes"})
    assert [o["name"] for o in first["options"]] == ["白色 50cm"] and first["images"] == ["https://img.example.invalid/main1.jpg"]
    assert screen_blockers(first) == []
    second = product_from_capture(cap, first, {"option_name": "黑色 60cm", "unit_price": "45",
                                               "images": ["https://img.example.invalid/d1.jpg", "https://not-captured.example/x.jpg"]})
    assert [o["name"] for o in second["options"]] == ["白色 50cm", "黑色 60cm"]
    assert second["images"] == ["https://img.example.invalid/main1.jpg", "https://img.example.invalid/d1.jpg"]
    assert second["est_delivery_days"] == {"min": 7, "max": 14} and second["compliance"]["sale_allowed_confirmed"]
    again = product_from_capture(cap, second, {"option_name": "黑色 60cm", "unit_price": "44"})
    assert len(again["options"]) == 2 and again["options"][-1]["unit_price"] == "44"
    with pytest.raises(ValidationError):
        product_from_capture(cap, None, {"option_name": "x", "unit_price": ""})


def token_of(c):
    return re.search(r"readonly value='([^']+)'", c.get("/capture", headers=AUTH).text).group(1)


def test_capture_endpoint_auth_and_flow(store):
    c = client(store)
    token = token_of(c)
    url = "/capture"
    assert c.post(url, json=payload(), headers={**EXT}).status_code == 401
    assert c.post(url, json=payload(), headers={**EXT, "X-Capture-Token": "wrong"}).status_code == 401
    assert c.post(url, json=payload(), headers={"Origin": "https://evil.example", "X-Capture-Token": token}).status_code == 403
    from fastapi.testclient import TestClient
    from app.purchasing.web import create_app
    remote = TestClient(create_app(store, "rev", "s3cretpass"), base_url="http://127.0.0.1:8000")  # "testclient" not allowed
    assert remote.post(url, json=payload(), headers={**EXT, "X-Capture-Token": token}).status_code == 403
    bad = c.post(url, json=payload(status="login_required"), headers={**EXT, "X-Capture-Token": token})
    assert bad.status_code == 422 and "로그인" in bad.json()["error"]
    r = c.post(url, json=payload(), headers={**EXT, "X-Capture-Token": token})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["images"] == 3 and r.json()["price_found"]
    cid = r.json()["capture_id"]
    review = c.get(f"/capture/{cid}", headers=AUTH)
    assert review.status_code == 200 and "合成测试 沥水架" in review.text and "39.90" in review.text
    assert "img-src https:" in review.headers["content-security-policy"]
    values = form_values(review, f"/capture/{cid}/save")
    assert values["option_name"] == "白色 50cm" and values["unit_price"] == "39.90"
    saved = c.post(f"/capture/{cid}/save", headers=ORIGIN,
                   data={**values, "images": ["https://img.example.invalid/main1.jpg", "https://img.example.invalid/d1.jpg"],
                         "delivery_min": "7", "delivery_max": "14", "sale_allowed": "yes"})
    assert saved.status_code == 200 and "새로 추가" in saved.text and "이미지 2개" in saved.text and "승인 전에" not in saved.text
    p = store.find_product("taobao", "1055677150014")
    assert p["options"][0]["source_option_id"] == option_id("白色 50cm")
    assert "저장됨" in c.get("/capture", headers=AUTH).text


def test_rotating_token_invalidates_old_one(store):
    c = client(store)
    old = token_of(c)
    assert c.post("/capture/token/rotate", headers=ORIGIN).status_code == 200
    assert c.post("/capture", json=payload(), headers={**EXT, "X-Capture-Token": old}).status_code == 401
    assert c.post("/capture/token/rotate", headers=AUTH).status_code == 403  # same-origin check still applies


def test_token_not_written_to_audit(store):
    token = store.capture_token(rotate=True)
    with store.tx() as cx:
        assert all(token not in (r[0] or "") for r in cx.execute("SELECT detail FROM audit"))
