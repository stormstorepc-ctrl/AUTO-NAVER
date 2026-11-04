from app.models import Product
from app.services import apply_source_update


class FakeDB:
    def add(self, obj):
        pass


def test_restock_after_soldout_marker_is_not_price_review():
    p = Product(id=1, name="x", last_source_price=100000, stock=5, supply_price=100000)
    apply_source_update(FakeDB(), p, 1, 0)  # 공급가 1원 = 품절 표시
    assert p.status == "SOLD_OUT"
    apply_source_update(FakeDB(), p, 100000, 5)  # 재입고
    assert p.status == "PENDING"
    assert p.sale_price == 108000


def test_legacy_baseline_of_one_is_ignored():
    p = Product(id=1, name="x", last_source_price=1, stock=0, supply_price=1)
    apply_source_update(FakeDB(), p, 100000, 5)
    assert p.status == "PENDING"
