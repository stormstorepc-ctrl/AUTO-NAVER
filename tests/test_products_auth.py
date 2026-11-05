import os, tempfile
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(tempfile.mkdtemp(), 't.db')
from fastapi.testclient import TestClient
from app.main import app, ADMIN_COOKIE
from app.db import SessionLocal
from app.models import Product


def test_products_requires_admin():
    with SessionLocal() as db:
        db.add(Product(name='fixture', supply_price=12345)); db.commit()
    c = TestClient(app, follow_redirects=False)
    r = c.get('/products')
    assert r.status_code == 303 and '12345' not in r.text
    c.cookies.set(ADMIN_COOKIE, 'ok')
    assert c.get('/products').status_code == 200
