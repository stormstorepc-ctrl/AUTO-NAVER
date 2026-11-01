import os, tempfile
_d = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_d}/t.db"

from fastapi.testclient import TestClient
from app.main_v31 import app
from app.db import SessionLocal
from app.models import Product, SyncLog

PAYLOAD = "<script>alert(1)</script>"


def test_dashboard_escapes_untrusted_text():
    with SessionLocal() as db:
        db.add(Product(name=PAYLOAD, category=PAYLOAD, supply_price=1000, sale_price=1100, stock=1, status="PENDING"))
        db.add(SyncLog(action="X", message=PAYLOAD, level="INFO"))
        db.commit()
    c = TestClient(app)
    c.cookies.set("stormpc_admin", "ok")
    html = c.get("/admin").text
    assert PAYLOAD not in html
    assert "&lt;script&gt;" in html


def test_login_error_is_escaped():
    html = TestClient(app).get("/admin/login", params={"error": PAYLOAD}).text
    assert PAYLOAD not in html
