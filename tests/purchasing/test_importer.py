import json

import pytest

from app.purchasing.importer import import_csv, import_json, CSV_COLUMNS
from app.purchasing.pricing import ValidationError
from tests.purchasing.conftest import sample


def doc(products, v=1):
    return json.dumps({"schema_version": v, "products": products})


def raw(i, **o):
    p = {"source_product_id": f"P{i}", "title_src": "t", "images": ["https://x/y.jpg"],
         "options": [{"source_option_id": "A", "name": "n", "unit_price": "10"}]}
    p.update(o)
    return p


def test_valid_and_html_kept_inert():
    r = import_json(doc([raw(1, description_src="<img src=x onerror=alert(1)>")]))
    assert r.summary == {"accepted": 1, "rejected": 0}
    assert r.accepted[0]["description_src"].startswith("<img")   # 저장만, 실행/렌더링 없음


@pytest.mark.parametrize("bad", [
    raw(1, source_product_id=""), raw(1, title_src=None), raw(1, options=[]),
    raw(1, options=[{"source_option_id": "A", "name": "n", "unit_price": "-1"}]),
    raw(1, options=[{"source_option_id": "A", "name": "n", "unit_price": "x"}]),
    raw(1, options=[{"source_option_id": "A", "name": "n", "unit_price": "1", "currency": "USD"}]),
    raw(1, options=[{"source_option_id": "A", "name": "n", "unit_price": "1", "quantity": 0}]),
    raw(1, options=[{"source_option_id": "A", "name": "n", "unit_price": "1"}] * 2),
    raw(1, images=["javascript:alert(1)"]), raw(1, compliance={"restricted_flags": ["bogus"]}),
    raw(1, est_delivery_days={"min": 9, "max": 3}),
])
def test_invalid_rows_rejected_not_crash(bad):
    r = import_json(doc([bad, raw(2)]))
    assert r.summary == {"accepted": 1, "rejected": 1}


def test_schema_version_and_duplicate_ids():
    with pytest.raises(ValidationError):
        import_json(doc([raw(1)], v=2))
    with pytest.raises(ValidationError):
        import_json("not json")
    r = import_json(doc([raw(1), raw(1)]))
    assert r.summary == {"accepted": 1, "rejected": 1}


def test_csv_import_groups_options():
    head = ",".join(CSV_COLUMNS)
    def row(opt, price):
        d = dict.fromkeys(CSV_COLUMNS, "")
        d.update(schema_version="1", source_product_id="C1", title_src="제목", images="https://a/1.jpg|https://a/2.jpg",
                 source_option_id=opt, option_name=opt, unit_price=price, quantity="1")
        return ",".join(d[k] for k in CSV_COLUMNS)
    r = import_csv("\n".join([head, row("A", "10"), row("B", "20"), row("A", "10")]))
    assert r.summary == {"accepted": 0, "rejected": 1}      # 옵션 ID 중복 -> 상품 거부
    r = import_csv("\n".join([head, row("A", "10"), row("B", "20")]))
    assert r.summary["accepted"] == 1 and len(r.accepted[0]["options"]) == 2 and len(r.accepted[0]["images"]) == 2


def test_upsert_idempotent_and_change_bumps_version(store):
    p = sample(1)
    assert store.upsert_products([p])["added"] == 1
    assert store.upsert_products([p])["unchanged"] == 1
    p2 = sample(1, title_src="변경")
    assert store.upsert_products([p2])["updated"] == 1
