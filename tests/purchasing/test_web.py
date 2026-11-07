import base64

from fastapi.testclient import TestClient

from app.purchasing.web import create_app
from tests.purchasing.conftest import prepare

AUTH = {"Authorization": "Basic " + base64.b64encode(b"rev:s3cretpass").decode()}


def client(store, host="testclient"):
    return TestClient(create_app(store, "rev", "s3cretpass", allow_hosts=("testclient",)), base_url="http://127.0.0.1:8000")


def test_requires_password_configured(store):
    import pytest
    with pytest.raises(RuntimeError):
        create_app(store, "rev", "")


def test_auth_and_escape(store, frozen_now):
    ids = prepare(store, 2, approve_them=False)
    from app.purchasing.workflow import MockChannelAdapter  # noqa
    c = client(store)
    assert c.get("/").status_code == 401
    assert c.get("/", headers={"Authorization": "Basic " + base64.b64encode(b"rev:wrong").decode()}).status_code == 401
    r = c.get("/", headers=AUTH)
    assert r.status_code == 200 and "검토 가능" in r.text
    d = c.get(f"/product/{ids[0]}", headers=AUTH)
    assert "<script>alert(1)</script>" not in d.text and "&lt;script&gt;" in d.text   # 원문 HTML 이스케이프
    assert "default-src 'none'" in d.headers["content-security-policy"]


def test_state_change_needs_origin_and_auth(store, frozen_now):
    ids = prepare(store, 2, approve_them=False)
    c = client(store)
    body = {"channel": "smartstore", "account": "mock:a1", "action": "approve", "ids": [str(i) for i in ids]}
    assert c.post("/bulk", data=body).status_code == 401
    assert c.post("/bulk", data=body, headers=AUTH).status_code == 403                                  # Origin 없음
    assert c.post("/bulk", data=body, headers={**AUTH, "Origin": "http://evil.example"}).status_code == 403
    with store.tx() as cx:
        assert cx.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    ok = c.post("/bulk", data=body, headers={**AUTH, "Origin": "http://127.0.0.1:8000"})
    assert ok.status_code == 200 and "승인 2건" in ok.text
    ex = c.post("/bulk", data={**body, "action": "exclude", "ids": [str(ids[0])]}, headers={**AUTH, "Origin": "http://127.0.0.1:8000"})
    assert ex.status_code == 200
    with store.tx() as cx:
        assert cx.execute("SELECT status FROM products WHERE id=?", (ids[0],)).fetchone()[0] == "rejected"


def test_non_loopback_rejected(store):
    c = TestClient(create_app(store, "rev", "s3cretpass"), base_url="http://127.0.0.1:8000")   # testclient 호스트는 허용 목록 없음
    assert c.get("/", headers=AUTH).status_code == 403
