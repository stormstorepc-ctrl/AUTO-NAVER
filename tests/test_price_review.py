import os
os.environ['DATABASE_URL'] = 'sqlite://'
from app.models import Product
from app.services import apply_source_update


class FakeDB:
    def add(self, obj):
        pass


def make(price):
    return Product(id=1, name='x', last_source_price=price, supply_price=price, sale_price=price * 2)


def test_price_review_not_bypassed_by_second_sync():
    p = make(100000)
    apply_source_update(FakeDB(), p, 200000, 5)
    assert p.status == 'PRICE_REVIEW'
    old_sale = p.sale_price
    apply_source_update(FakeDB(), p, 200000, 5)
    assert p.status == 'PRICE_REVIEW'
    assert p.sale_price == old_sale


def test_small_change_updates_baseline():
    p = make(100000)
    apply_source_update(FakeDB(), p, 105000, 5)
    assert p.status == 'PENDING'
    assert p.last_source_price == 105000
