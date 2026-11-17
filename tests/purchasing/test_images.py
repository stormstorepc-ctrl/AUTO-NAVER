"""사진 PC 저장과 네이버용 사진 ZIP. 네트워크 대신 httpx MockTransport를 쓴다."""
import io
import zipfile

import httpx
import pytest

from app.purchasing import easy, images
from app.purchasing.pricing import ValidationError
from tests.purchasing.test_easy import PRODUCT, SETTINGS, TR

JPG = b"\xff\xd8\xff\xe0fakejpeg"


def handler(request):
    url = str(request.url)
    if "webp" in url:
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=b"RIFF")
    if "html" in url:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")
    if "missing" in url:
        return httpx.Response(404)
    if "huge" in url:
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"x" * (images.MAX_IMAGE_BYTES + 1))
    if "redirect" in url:
        return httpx.Response(302, headers={"location": "https://evil.example/x.jpg"})
    if "evil.example" in url:
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=JPG)
    return httpx.Response(200, headers={"content-type": "image/png" if url.endswith(".png") else "image/jpeg; charset=x"},
                          content=JPG)


@pytest.fixture
def mock_client():
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as c:
        yield c


def product(*urls):
    return {"source_product_id": "712345678901", "images": list(urls)}


def test_allowed_hosts():
    assert images.allowed_url("https://img.alicdn.com/imgextra/a.jpg")
    assert images.allowed_url("https://gw.alicdn.com/x.png") and images.allowed_url("http://img01.taobaocdn.com/a.jpg")
    for bad in ("https://evil.example/a.jpg", "https://alicdn.com.evil.example/a.jpg", "file:///etc/passwd", "ftp://img.alicdn.com/a"):
        assert not images.allowed_url(bad)


def test_save_names_and_skips_and_failures(store, tmp_path, mock_client):
    p = product("https://img.alicdn.com/a.jpg", "https://img.alicdn.com/b.png", "https://img.alicdn.com/c.webp",
                "https://img.alicdn.com/page.html", "https://img.alicdn.com/missing.jpg", "https://img.alicdn.com/huge.jpg",
                "https://img.alicdn.com/redirect.jpg", "https://evil.example/d.jpg")
    r = images.save_product_images(store, p, mock_client, tmp_path)
    assert r["saved"] == ["TB712345678901_01.jpg", "TB712345678901_02.png"]
    reasons = [why for _, why in r["failed"]]
    assert len(reasons) == 6 and any("webp" in w for w in reasons) and any("이미지가 아닙니다" in w for w in reasons)
    assert any("404" in w for w in reasons) and any("10MB" in w for w in reasons)
    assert any("다른 사이트" in w for w in reasons) and any("타오바오 이미지 서버" in w for w in reasons)
    assert (tmp_path / "TB712345678901_01.jpg").read_bytes() == JPG
    again = images.save_product_images(store, p, mock_client, tmp_path)
    assert again["saved"] == [] and again["kept"] == r["saved"]                   # nothing downloaded twice
    assert images.local_names(store, p["images"], tmp_path) == {
        "https://img.alicdn.com/a.jpg": "TB712345678901_01.jpg", "https://img.alicdn.com/b.png": "TB712345678901_02.png"}


def test_safe_path_and_zip(store, tmp_path, mock_client):
    images.save_product_images(store, product("https://img.alicdn.com/a.jpg"), mock_client, tmp_path)
    for bad in ("../.env", "TB1_01.jpg", "TB712345678901_01.jpg/../x", "x.jpg"):
        with pytest.raises(ValidationError):
            images.safe_path(bad, tmp_path)
    data = images.zip_files(["TB712345678901_01.jpg", "TB712345678901_01.jpg"], tmp_path)
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["TB712345678901_01.jpg"]


def test_excel_uses_file_names_in_file_mode():
    files = {PRODUCT["images"][0]: "TB712345678901_01.jpg", PRODUCT["images"][1]: "TB712345678901_02.jpg"}
    row, warnings = easy.naver_row(PRODUCT, TR, {**SETTINGS, "image_mode": "file"}, files)
    assert row["대표이미지"] == "TB712345678901_01.jpg"
    assert row["추가이미지"].split("\n")[0] == "TB712345678901_02.jpg" and row["추가이미지"].count("\n") == 8
    assert any("저장되지 않은 사진 8개" in w for w in warnings)
    assert "https://img.example.invalid/0.jpg" in row["상세설명"]                  # detail page keeps web addresses


def test_web_save_serve_and_zip(store, tmp_path, monkeypatch, mock_client):
    import json
    from tests.purchasing.test_review_ui import ORIGIN, ready
    from tests.purchasing.test_web import client, AUTH
    monkeypatch.setattr(images, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(images, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    c = client(store)
    ready(c)
    with store.tx() as cx:   # point the sample product at an allowed image host
        d = json.loads(cx.execute("SELECT data FROM products WHERE id=1").fetchone()[0])
        d.update(images=["https://img.alicdn.com/a.jpg"], source_product_id="712345678901")
        cx.execute("UPDATE products SET data=? WHERE id=1", (json.dumps(d),))
    assert c.post("/product/1/images/save", headers=AUTH).status_code == 403
    r = c.post("/product/1/images/save", headers=ORIGIN)
    assert r.status_code == 200 and "새로 저장 1개" in r.text and "/local-images/TB712345678901_01.jpg" in r.text
    assert c.get("/local-images/TB712345678901_01.jpg", headers=AUTH).content == JPG
    assert c.get("/local-images/x.jpg", headers=AUTH).status_code == 400
    assert c.get("/local-images/TB712345678901_09.jpg", headers=AUTH).status_code == 404
    z = c.post("/easy/naver-images.zip", headers=ORIGIN, data={"ids": "1"})
    assert z.status_code == 200 and zipfile.ZipFile(io.BytesIO(z.content)).namelist() == ["TB712345678901_01.jpg"]
    assert "PC 저장 1" in c.get("/easy", headers=AUTH).text
    assert "PC에 저장 1개" in c.get("/product/1", headers=AUTH).text
