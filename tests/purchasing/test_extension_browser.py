"""Runs chrome_extension/extract.js in a real Chromium against synthetic pages, and checks that the extension
can reach the local server. No request leaves the machine: every page and image is served by route().

Skipped when no Chromium is available. What this cannot cover: the real Taobao page structure, and the
user's own click on the extension button (activeTab is only granted by a real click).
"""
import hashlib
import os
import socket
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXT_DIR = ROOT / "chrome_extension"
FIXTURES = Path(__file__).parent / "fixtures"
EXTRACT = (EXT_DIR / "extract.js").read_text(encoding="utf-8")
PRODUCT_URL = "https://detail.tmall.com/item.htm?id=1055677150014"

sync_api = pytest.importorskip("playwright.sync_api")


def png(w, h):
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


BIG, ICON = png(400, 400), png(20, 20)


def launch_options():
    yield {}
    for path in filter(None, [os.environ.get("PURCHASING_TEST_CHROMIUM"), "/opt/pw-browsers/chromium"]):
        if Path(path).exists():
            yield {"executable_path": path}
    yield {"channel": "chrome"}


@pytest.fixture(scope="module")
def pw():
    with sync_api.sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    errors = []
    for opts in launch_options():
        try:
            b = pw.chromium.launch(**opts)
        except Exception as ex:  # noqa: BLE001 - try the next way to find a browser
            errors.append(str(ex).splitlines()[0])
            continue
        yield b
        b.close()
        return
    pytest.skip("Chromium not available: " + " | ".join(errors))


def serve(route):
    url = route.request.url
    if url.startswith("https://img.example.invalid/"):
        return route.fulfill(status=200, content_type="image/png", body=ICON if "icon" in url else BIG)
    page = {"login": "login_like.html", "captcha": "captcha_like.html"}.get(route.request.headers.get("x-fixture", ""), "taobao_like.html")
    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=(FIXTURES / page).read_text(encoding="utf-8"))


def extract(browser, fixture="product", url=PRODUCT_URL):
    ctx = browser.new_context(extra_http_headers={"x-fixture": fixture})
    ctx.route("**/*", serve)
    page = ctx.new_page()
    page.goto(url)
    page.wait_for_load_state("load")
    result = page.evaluate(EXTRACT)
    ctx.close()
    return result


def test_extract_reads_title_price_selected_options_and_images(browser):
    r = extract(browser)
    assert r["status"] == "ok" and r["schema"] == 1 and r["url"] == PRODUCT_URL
    assert r["title"] == "合成测试 沥水架 可伸缩"
    assert r["price_texts"] == ["¥39.90", "¥59.00"]
    assert r["selected_options"] == ["白色 50cm", "加厚款"]  # the "unselected" item is not taken
    assert r["images"] == ["https://img.example.invalid/main1.jpg", "https://img.example.invalid/main2_800.jpg"]
    assert r["detail_images"] == ["https://img.example.invalid/d1.jpg", "https://img.example.invalid/d2_lazy.jpg"]
    assert any("아직 화면에 안 나온 이미지 1개" in n for n in r["notes"])


def test_extract_stops_on_login_and_captcha(browser):
    assert extract(browser, "login")["status"] == "login_required"
    assert extract(browser, "captcha")["status"] == "captcha"
    assert extract(browser, "product", "https://login.taobao.com/member/login.jhtml")["status"] == "login_required"


def test_extract_output_is_accepted_by_server_validation(browser):
    from app.purchasing.capture import validate_capture
    d = validate_capture(extract(browser))
    assert d["item_id"] == "1055677150014" and len(d["images"]) == 2 and len(d["detail_images"]) == 2


def unpacked_extension_id(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


@pytest.mark.skipif(os.name == "nt", reason="uses the POSIX server start path and a Linux Chromium")
def test_extension_page_can_post_to_local_server(pw, tmp_path):
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", 8765)) == 0:
            pytest.skip("port 8765 is in use")
    exe = os.environ.get("PURCHASING_TEST_CHROMIUM") or "/opt/pw-browsers/chromium"
    if not Path(exe).exists():
        pytest.skip("full Chromium binary needed to load an unpacked extension")
    from app.purchasing.store import Store
    db = tmp_path / "p.db"
    token = Store(str(db)).capture_token()
    env = {**os.environ, "PURCHASING_REVIEW_PASSWORD": "browser-test-pass", "PURCHASING_DB": str(db)}
    server = subprocess.Popen([sys.executable, "-m", "app.purchasing.local_server", "start"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", 8765)) == 0:
                    break
            time.sleep(0.1)
        ctx = pw.chromium.launch_persistent_context(
            str(tmp_path / "profile"), executable_path=exe, headless=True,
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}"])
        try:
            page = ctx.new_page()
            page.goto(f"chrome-extension://{unpacked_extension_id(EXT_DIR)}/popup.html")
            assert page.locator("#capture").inner_text() == "이 상품 가져오기"
            payload = {"schema": 1, "status": "ok", "url": PRODUCT_URL, "title": "合成测试", "price_texts": ["¥39.90"],
                       "selected_options": ["白色"], "images": ["https://img.example.invalid/main1.jpg"],
                       "detail_images": [], "notes": [], "captured_at": "2026-11-08T00:00:00Z"}
            result = page.evaluate("""async ([token, payload]) => {
                const r = await fetch("http://127.0.0.1:8765/capture", {method: "POST",
                    headers: {"Content-Type": "application/json", "X-Capture-Token": token}, body: JSON.stringify(payload)});
                return {status: r.status, body: await r.json()};
            }""", [token, payload])
            assert result["status"] == 200 and result["body"]["ok"], result
            assert result["body"]["review_url"].startswith("http://127.0.0.1:8765/capture/")
            wrong = page.evaluate("""async (payload) => (await fetch("http://127.0.0.1:8765/capture", {method: "POST",
                headers: {"Content-Type": "application/json", "X-Capture-Token": "wrong"}, body: JSON.stringify(payload)})).status""",
                payload)
            assert wrong == 401
        finally:
            ctx.close()
        assert Store(str(db)).list_captures()[0]["item_id"] == "1055677150014"
    finally:
        subprocess.run([sys.executable, "-m", "app.purchasing.local_server", "stop"], cwd=ROOT, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if server.poll() is None:
            server.kill()
