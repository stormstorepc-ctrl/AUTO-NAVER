"""이미 스마트스토어에 등록된 상품을 다시 등록(중복 상품 생성)하지 않아야 한다. 임시 SQLite, 외부 호출은 가짜."""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{_tmp}/t.db'

from fastapi.testclient import TestClient  # noqa: E402
from app import main_v31  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Product  # noqa: E402


def test_listed_product_is_not_registered_again(monkeypatch):
    calls = []
    monkeypatch.setattr(main_v31.naver_commerce, 'register_product',
                        lambda p: calls.append(p.id) or 'NEW-NO')
    with SessionLocal() as db:
        p = Product(name='테스트', supply_price=10000, sale_price=11000, stock=3, approved=True,
                    status='SMARTSTORE_LISTED', smartstore_product_id='OLD-NO')
        db.add(p); db.commit(); pid = p.id
    c = TestClient(main_v31.app, follow_redirects=False)
    c.cookies.set('stormpc_admin', 'ok')
    assert c.post(f'/products/{pid}/smartstore').status_code == 303
    assert calls == []
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert p.smartstore_product_id == 'OLD-NO'
        assert p.status == 'SMARTSTORE_LISTED'
