from datetime import datetime, timezone
from decimal import Decimal as Dd

import pytest

from app.purchasing.importer import validate_product
from app.purchasing.pricing import ChannelTerms, FxRate, SaleTerms, ShippingRateCard
from app.purchasing.store import Store
from app.purchasing.workflow import RateBook, approve, price_product

NOW = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)
CH = ("smartstore", "danggeun", "bunjang")


def sample(i, **over):
    p = {"source": "taobao", "source_product_id": f"P{i:04d}", "title_src": f"收纳盒 {i}", "category": "수납",
         "description_src": "<script>alert(1)</script> 尺寸 20x10cm", "supply_url": f"https://item.taobao.com/item.htm?id={i}",
         "images": [f"https://img.example.com/{i}.jpg"], "est_delivery_days": {"min": 7, "max": 14},
         "compliance": {"sale_allowed_confirmed": True, "restricted_flags": []},
         "options": [{"source_option_id": "A", "name": "白色", "unit_price": "100", "weight_g": "300"},
                     {"source_option_id": "B", "name": "黑色", "unit_price": "120", "weight_g": "350"}]}
    # Synthetic fixtures explicitly confirm these costs as zero, rather than leaving them unknown.
    for option in p["options"]:
        for key in ("china_shipping_krw", "handling_krw", "seller_customs_krw", "domestic_shipping_krw",
                    "payment_fee_rate", "reserve_rate"):
            option[key] = "0"
    p.update(over)
    return validate_product(p)


def rates(now=NOW):
    return RateBook(FxRate("CNY", Dd("190"), now), ShippingRateCard(Dd("9000"), now, Dd(100), Dd(100)),
                    {c: ChannelTerms(c, Dd("0.06"), Dd("0.03"), Dd(0), now, verified=True) for c in CH})


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "p.db"))


def prepare(store, n=3, channels=("smartstore",), now=NOW, account="mock:a1", approve_them=True):
    """합성 상품 n개를 가져오고 번역 검수·견적·승인까지 진행한다."""
    store.upsert_products([sample(i) for i in range(n)])
    ids = store.list_product_ids()
    for pid in ids:
        v = store.add_translation(pid, f"수납함 {pid}", "크기 20x10cm", {"A": "화이트", "B": "블랙"})
        store.review_translation(pid, v, "tester")
        for ch in channels:
            price_product(store, pid, ch, rates(now), now)
    if approve_them:
        for ch in channels:
            assert approve(store, ids, ch, account, "tester", now) == {}
    return ids
