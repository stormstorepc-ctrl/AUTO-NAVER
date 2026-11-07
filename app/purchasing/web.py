"""로컬 검토 화면 (루프백 전용). 모든 변경 요청은 Basic 인증 + Origin/Host 검증을 거친다."""
from __future__ import annotations

import base64
import html
import ipaddress
import os
import secrets
import io
import json
import tempfile
import zipfile
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .store import Store
from .workflow import (approve, blockers_before_approval, exclude, EXPECTED_MARGIN, price_product,
                       RateBook, MockChannelAdapter, run_week, export_draft, publish_blockers)
from .store import now_utc
from .pricing import D, ValidationError, FxRate, ShippingRateCard, ChannelTerms, SaleTerms
from .importer import import_json, import_csv, validate_product
from .review_ui import (import_form, product_forms, sample_document, channel_nav, COST_LABELS,
                        url_import_form, url_import_reply_form)
from .assist import product_request, parse_product_reply, parse_translation_reply
from .capture import MAX_CAPTURE_BYTES, first_price, product_from_capture, validate_capture
from .cli import week_key

CHANNELS = ("smartstore", "danggeun", "bunjang")
E = html.escape
MAX_IMPORT = 2 * 1024 * 1024
CHANNEL_LABELS = {"smartstore": "스마트스토어", "danggeun": "당근", "bunjang": "번개장터"}
STATE_LABELS = {"discovered": "가져옴", "approved": "승인됨", "publishing": "처리 중",
                "published": "등록 이력 있음", "claimed": "처리 중", "unknown": "결과 확인 중",
                "failed": "실패", "rejected": "제외됨"}


def percent(value):
    return "-" if value is None else f"{Decimal(str(value)) * 100:.2f}%"


def rejected_list(rejected: list[dict]) -> str:
    """Readable rejection reasons for the import result page."""
    if not rejected:
        return "<p>오류 없음 · 모든 상품을 가져왔습니다.</p>"
    items = "".join(
        f"<li>{E(str(r.get('index', '?') + 1 if isinstance(r.get('index'), int) else '?'))}번째 상품"
        f"{' (' + E(r['source_product_id']) + ')' if r.get('source_product_id') else ''}: "
        f"{E(' / '.join(map(str, r.get('errors') or ['알 수 없는 오류'])))}</li>"
        for r in rejected)
    return f"<p>가져오지 못한 상품</p><ul>{items}</ul>"


def create_app(store: Store, username: str, password: str, allow_hosts: tuple[str, ...] = ()) -> FastAPI:
    if not password or len(password) < 8:
        raise RuntimeError("검토 화면 비밀번호(PURCHASING_REVIEW_PASSWORD, 8자 이상)가 필요합니다. 기본값은 없습니다.")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def guard(request: Request, mutating: bool) -> str:
        host = request.client.host if request.client else ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback and host not in allow_hosts:
            raise HTTPException(403, "loopback only")
        auth = request.headers.get("authorization", "")
        ok = False
        if auth.startswith("Basic "):
            try:
                u, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
                ok = secrets.compare_digest(u, username) & secrets.compare_digest(pw, password)
            except Exception:
                ok = False
        if not ok:
            raise HTTPException(401, "auth required", headers={"WWW-Authenticate": 'Basic realm="review"'})
        if mutating:
            origin = request.headers.get("origin") or request.headers.get("referer")
            if not origin or urlparse(origin).netloc != request.headers.get("host"):
                raise HTTPException(403, "origin check failed")
        return username

    def page(body: str) -> HTMLResponse:
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>구매대행 검토</title>"
                            f"<meta name=viewport content='width=device-width,initial-scale=1'><meta name=referrer content=no-referrer>"
                            f"<style>body{{font:15px sans-serif;margin:24px auto;max-width:1100px;padding:0 16px;background:#f7f8fc;color:#17223b}}"
                            f"td,th{{border:1px solid #ccd;padding:8px}}table{{border-collapse:collapse;width:100%;overflow-wrap:anywhere}}"
                            f"section,fieldset{{background:white;padding:16px;margin:16px 0;border:1px solid #ccd;border-radius:10px}}"
                            f"label{{display:block;margin:12px 0}}input,textarea,select,button{{font:inherit;padding:8px;max-width:100%;box-sizing:border-box}}"
                            f"textarea{{display:block;width:100%}}button{{cursor:pointer;background:#234dbe;color:white;border:0;border-radius:6px;margin:6px 0}}"
                            f"nav{{margin:16px 0}}a{{color:#234dbe}}.notice{{padding:12px;background:#e8edff}}"
                            f"</style><header><a href='/'>상품 목록</a> · <a href='/import'>상품 가져오기</a> · <a href='/import/url'>주소로 상품 추가</a> · <a href='/capture'>Chrome 확장으로 가져오기</a>"
                            f"<p class=notice>구매대행 시연 · 실제 판매 채널 등록 없이 모의 흐름을 확인합니다.</p></header>{body}",
                            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src https: http:; form-action 'self'",
                                     "X-Frame-Options": "DENY", "Cache-Control": "no-store"})

    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        response = page(f"<h1>입력 확인이 필요합니다</h1><p>{E(str(exc))}</p><p>값을 수정한 뒤 다시 진행하세요.</p>")
        response.status_code = 400
        return response

    def product(pid):
        with store.tx() as c:
            p = store.get_product(c, pid)
        if p is None:
            raise HTTPException(404, "상품 없음")
        return p

    async def fields(request, multiple=False):
        # All state-changing routes authenticate and check Origin before reading input.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_IMPORT:
                raise HTTPException(413, "입력은 최대 2MB입니다")
        try:
            parsed = parse_qs(body.decode(), keep_blank_values=True, max_num_fields=3000)
            return parsed if multiple else {key: vals[0] for key, vals in parsed.items()}
        except (ValueError, UnicodeError):
            raise ValidationError("입력 형식을 확인하세요.")

    def version(form):
        try:
            return int(form["product_version"])
        except (KeyError, ValueError):
            raise ValidationError("화면을 새로 열고 다시 진행하세요.")

    def channel_value(form):
        channel = form.get("channel", "")
        if channel not in CHANNELS:
            raise ValidationError("판매 채널을 선택하세요.")
        return channel

    def done(message, pid=None, channel="smartstore"):
        link = f"/product/{pid}?channel={channel}" if pid else f"/?channel={channel}"
        return page(f"<h1>{E(message)}</h1><a href='{link}'>검토 화면으로 돌아가기</a>")

    @app.get("/import", response_class=HTMLResponse)
    def import_screen(request: Request):
        guard(request, False)
        return page(import_form())

    @app.get("/sample.json")
    def sample_file(request: Request):
        guard(request, False)
        return Response(json.dumps(sample_document(), ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="purchasing-demo.json"', "Cache-Control": "no-store"})

    @app.post("/import")
    async def import_products(request: Request):
        actor = guard(request, True)
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise ValidationError("파일 크기 정보를 확인하세요.")
        if size > MAX_IMPORT:
            raise HTTPException(413, "파일과 입력은 최대 2MB입니다")
        async with request.form(max_files=1, max_fields=5, max_part_size=MAX_IMPORT) as form:
            file = form.get("file")
            raw = form.get("raw", "")
            if file is not None and hasattr(file, "read") and file.filename:
                if raw:
                    raise ValidationError("파일과 붙여넣기 중 하나만 입력하세요.")
                data = await file.read(MAX_IMPORT + 1)
            else:
                if not isinstance(raw, str):
                    raise ValidationError("상품 내용을 입력하세요.")
                data = raw.encode()
            if len(data) > MAX_IMPORT:
                raise HTTPException(413, "파일은 최대 2MB입니다")
            try:
                text = data.decode("utf-8-sig")
            except UnicodeError:
                raise ValidationError("UTF-8 JSON/CSV 파일을 선택하세요.")
            fmt = form.get("format")
            if fmt not in ("json", "csv"):
                raise ValidationError("JSON 또는 CSV 형식을 선택하세요.")
            report = import_json(text) if fmt == "json" else import_csv(text)
        counts = store.upsert_products(report.accepted, actor)
        return page(f"<h1>가져오기 결과</h1><p>유효 {len(report.accepted)}개 · 거부 {len(report.rejected)}개</p>"
                    f"<p>새 상품 {counts['added']}개 · 변경 {counts['updated']}개 · 동일 {counts['unchanged']}개</p>"
                    f"{rejected_list(report.rejected)}<a href='/'>상품 목록에서 계속</a>")

    @app.post("/product/{pid}/translation")
    async def save_translation(pid: int, request: Request):
        guard(request, True)
        form = await fields(request)
        channel = channel_value(form)
        p = product(pid)
        title, description = form.get("title_ko", "").strip(), form.get("description_ko", "").strip()
        names = {o["source_option_id"]: form.get(f"option_{i}", "").strip() for i, o in enumerate(p["options"])}
        if not title or len(title) > 500 or not description or len(description) > 20000 or any(not x or len(x) > 300 for x in names.values()):
            raise ValidationError("상품명(500자), 설명(20,000자), 모든 옵션명(300자)을 입력하세요.")
        store.add_translation(pid, title, description, names, expected_version=version(form))
        return done("번역 초안을 저장했습니다. 원문과 대조한 뒤 검수 완료를 눌러주세요.", pid, channel)

    @app.get("/import/url", response_class=HTMLResponse)
    def url_import_screen(request: Request):
        guard(request, False)
        return page(url_import_form())

    @app.post("/import/url")
    async def url_import_request(request: Request):
        guard(request, True)
        form = await fields(request)
        url = form.get("url", "")
        return page(url_import_reply_form(url, product_request(url, form.get("page_text", ""))))

    @app.post("/import/url/save")
    async def url_import_save(request: Request):
        actor = guard(request, True)
        form = await fields(request)
        item = parse_product_reply(form.get("url", ""), form.get("reply", ""), form.get("sale_allowed") == "yes",
                                   form.get("image_urls", ""), form.get("delivery_min", "").strip(),
                                   form.get("delivery_max", "").strip())
        counts = store.upsert_products([item], actor)
        with store.tx() as c:
            pid = c.execute("SELECT id FROM products WHERE source=? AND source_product_id=?",
                            (item["source"], item["source_product_id"])).fetchone()[0]
        state = "새로 추가" if counts["added"] else "정보 변경" if counts["updated"] else "변경 없음"
        options = "".join(f"<li>{E(o['name'])} · {E(o['unit_price'])}위안"
                          f"{' · ' + E(o['weight_g']) + 'g' if o.get('weight_g') else ' · 무게 미확인'}</li>" for o in item["options"])
        from .workflow import screen_blockers
        blockers = screen_blockers(item)
        days = item.get("est_delivery_days")
        facts = (f"<p>이미지 {len(item['images'])}개 · 배송 "
                 f"{E(str(days['min']) + '~' + str(days['max']) + '일') if days else '미입력'}</p>")
        warn = facts + ("" if not blockers else
                        "<p>승인 전에 해결할 것: " + E(" / ".join(blockers)) + "</p>")
        return page(f"<h1>상품 저장: {state}</h1><p>{E(item['title_src'])}</p><ul>{options}</ul>{warn}"
                    f"<p>가격과 옵션이 페이지와 맞는지 꼭 확인하세요.</p>"
                    f"<a href='/product/{pid}'>상품 화면에서 가격 계산·번역 계속</a>")

    # ---- Chrome 확장 수집 ----
    @app.post("/capture")
    async def capture_receive(request: Request):
        """Called by the extension popup after the user clicks. Pairing code instead of Basic auth."""
        host = request.client.host if request.client else ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback and host not in allow_hosts:
            return JSONResponse({"ok": False, "error": "loopback only"}, status_code=403)
        if not (request.headers.get("origin") or "").startswith("chrome-extension://"):
            return JSONResponse({"ok": False, "error": "확장 프로그램에서만 보낼 수 있습니다."}, status_code=403)
        sent = request.headers.get("x-capture-token", "")
        if not sent or not secrets.compare_digest(sent.encode(), store.capture_token().encode()):
            return JSONResponse({"ok": False, "error": "연결 코드가 맞지 않습니다. 검토 화면의 'Chrome 확장으로 가져오기'에서 코드를 다시 복사하세요."},
                                status_code=401)
        if "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"ok": False, "error": "JSON만 받습니다."}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_CAPTURE_BYTES:
                return JSONResponse({"ok": False, "error": "데이터가 너무 큽니다."}, status_code=413)
        try:
            payload = json.loads(body.decode("utf-8"))
            data = validate_capture(payload)
        except ValidationError as ex:  # subclass of ValueError: must come first
            return JSONResponse({"ok": False, "error": str(ex)}, status_code=422)
        except (ValueError, UnicodeError):
            return JSONResponse({"ok": False, "error": "JSON 형식이 올바르지 않습니다."}, status_code=400)
        cid = store.add_capture(data["item_id"], data["url"], data)
        port = request.url.port or 8765
        return JSONResponse({"ok": True, "capture_id": cid, "review_url": f"http://127.0.0.1:{port}/capture/{cid}",
                             "images": len(data["images"]) + len(data["detail_images"]),
                             "price_found": bool(first_price(data["price_texts"]))})

    @app.get("/capture", response_class=HTMLResponse)
    def capture_home(request: Request):
        guard(request, False)
        token = store.capture_token()
        rows = "".join(
            f"<tr><td><a href='/capture/{r['id']}'>{r['id']}</a></td><td>{E(r['data'].get('title', ''))}</td>"
            f"<td>{E(', '.join(r['data'].get('selected_options', [])) or '-')}</td>"
            f"<td>{'저장됨' if r['status'] == 'saved' else '검토 대기'}</td><td>{E(r['created_at'][:16])}</td></tr>"
            for r in store.list_captures())
        return page(
            "<h1>Chrome 확장으로 가져오기</h1>"
            "<section><h2>처음 한 번: 확장 프로그램 설치</h2><ol>"
            "<li>Chrome 주소창에 <b>chrome://extensions</b> 를 입력합니다.</li>"
            "<li>오른쪽 위 <b>개발자 모드</b>를 켭니다.</li>"
            "<li><b>압축해제된 확장 프로그램을 로드합니다</b>를 누르고, AUTO-NAVER 폴더 안의 <b>chrome_extension</b> 폴더를 고릅니다.</li>"
            "<li>퍼즐 모양 아이콘에서 <b>AUTO-NAVER 상품 가져오기</b>를 고정(핀)합니다.</li>"
            "<li>확장 아이콘을 누르고, 아래 <b>연결 코드</b>를 붙여넣은 뒤 <b>저장</b>을 누릅니다.</li></ol>"
            f"<label>연결 코드 <input readonly value='{E(token, quote=True)}' style='width:100%'></label>"
            "<p>연결 코드는 이 PC의 검토 프로그램과 확장 프로그램만 아는 값입니다. 다른 사람에게 보내지 마세요.</p>"
            "<form method=post action='/capture/token/rotate'><button>연결 코드 새로 만들기</button></form></section>"
            "<section><h2>상품 가져오기</h2><ol>"
            "<li>Chrome에서 타오바오/티몰 상품 페이지를 엽니다. 로그인이 필요하면 직접 로그인합니다.</li>"
            "<li>원하는 옵션(색상·사이즈)을 누르고, 상세 이미지를 보려면 페이지 끝까지 한 번 내립니다.</li>"
            "<li>확장 아이콘 → <b>이 상품 가져오기</b>를 누릅니다.</li>"
            "<li>나오는 <b>검토 화면 열기</b>에서 가격·이미지를 확인하고 저장합니다. 다른 옵션은 그 옵션을 누른 뒤 다시 가져오면 같은 상품에 추가됩니다.</li></ol>"
            "<p>확장 프로그램은 버튼을 누른 그 탭의 화면만 읽습니다. 로그인·보안 확인 화면이면 멈추고 알려줍니다.</p></section>"
            "<h2>가져온 목록</h2><table><tr><th>번호</th><th>원문 제목</th><th>선택 옵션</th><th>상태</th><th>시각(UTC)</th></tr>"
            f"{rows}</table>")

    @app.post("/capture/token/rotate")
    async def capture_rotate(request: Request):
        guard(request, True)
        store.capture_token(rotate=True)
        return page("<h1>연결 코드를 새로 만들었습니다</h1><p>확장 프로그램에 새 코드를 다시 저장하세요.</p>"
                    "<a href='/capture'>돌아가기</a>")

    def capture_or_404(cid):
        cap = store.get_capture(cid)
        if cap is None:
            raise HTTPException(404, "가져온 기록 없음")
        return cap

    @app.get("/capture/{cid}", response_class=HTMLResponse)
    def capture_review(cid: int, request: Request):
        guard(request, False)
        cap = capture_or_404(cid)
        d = cap["data"]
        existing = store.find_product("taobao", cap["item_id"])
        def figure(u, checked):
            return (f"<label style='display:inline-block;width:160px;vertical-align:top'>"
                    f"<input type=checkbox name=images value='{E(u, quote=True)}' {'checked' if checked else ''}> "
                    f"<img src='{E(u, quote=True)}' alt='' style='width:150px;height:150px;object-fit:contain;background:#eee'></label>")
        main = "".join(figure(u, True) for u in d["images"]) or "<p>대표 이미지를 찾지 못했습니다.</p>"
        detail = "".join(figure(u, True) for u in d["detail_images"]) or "<p>상세 이미지를 찾지 못했습니다.</p>"
        notes = "".join(f"<li>{E(n)}</li>" for n in d["notes"])
        prices = " / ".join(E(t) for t in d["price_texts"]) or "가격 표시를 찾지 못했습니다"
        have = ("" if not existing else
                f"<p class=notice>이미 저장된 상품입니다(옵션 {len(existing['options'])}개). 저장하면 이 옵션이 추가되거나 갱신됩니다. "
                f"<a href='/product/{existing['id']}'>저장된 상품 보기</a></p>")
        days = (existing or {}).get("est_delivery_days") or {}
        return page(
            f"<h1>가져온 상품 확인</h1>{have}<p><b>{E(d['title'])}</b></p>"
            f"<p><a href='{E(cap['url'], quote=True)}' rel=noreferrer target=_blank>{E(cap['url'])}</a> · 가져온 시각 {E(d['captured_at'])}</p>"
            + (f"<ul>{notes}</ul>" if notes else "") +
            f"<form method=post action='/capture/{cid}/save'>"
            "<section><h2>1. 옵션과 가격</h2>"
            f"<p>화면에 보인 가격: {prices}</p>"
            "<p>선택하지 않은 옵션의 가격은 추측하지 않습니다. 다른 옵션은 그 옵션을 누른 뒤 다시 가져오세요.</p>"
            f"<label>옵션 이름(원문) <input name=option_name value='{E(' / '.join(d['selected_options']) or '기본', quote=True)}' required></label>"
            f"<label>이 옵션의 구매 가격(위안) <input name=unit_price value='{E(first_price(d['price_texts']), quote=True)}' required inputmode=decimal></label>"
            "<label>무게(g, 모르면 비움) <input name=weight_g inputmode=decimal></label></section>"
            "<section><h2>2. 이미지</h2><p>쓸 이미지만 체크된 상태로 두세요.</p>"
            f"<h3>대표 이미지</h3>{main}<h3>상세 이미지</h3>{detail}"
            "<label>이미지 주소 직접 추가(한 줄에 하나) <textarea name=image_urls rows=2></textarea></label></section>"
            "<section><h2>3. 배송과 판매 확인</h2>"
            f"<label>예상 배송 기간 최소(일) <input name=delivery_min value='{days.get('min', '')}' inputmode=numeric></label>"
            f"<label>최대(일) <input name=delivery_max value='{days.get('max', '')}' inputmode=numeric></label>"
            "<label><input type=checkbox name=sale_allowed value=yes> 한국에서 판매해도 되는 상품인지 확인했습니다</label>"
            "<button>확인하고 저장</button></section></form>")

    @app.post("/capture/{cid}/save")
    async def capture_save(cid: int, request: Request):
        actor = guard(request, True)
        raw = await fields(request, multiple=True)
        form = {k: (v if k == "images" else v[0]) for k, v in raw.items()}
        form.setdefault("images", [])
        cap = capture_or_404(cid)
        existing = store.find_product("taobao", cap["item_id"])
        item = product_from_capture(cap, existing, form)
        counts = store.upsert_products([item], actor)
        saved = store.find_product("taobao", cap["item_id"])
        store.mark_capture_saved(cid, saved["id"])
        from .workflow import screen_blockers
        blockers = screen_blockers(item)
        state = "새로 추가" if counts["added"] else "옵션 추가·갱신" if counts["updated"] else "변경 없음"
        return page(f"<h1>상품 저장: {state}</h1><p>{E(item['title_src'])}</p>"
                    f"<p>옵션 {len(item['options'])}개 · 이미지 {len(item['images'])}개</p>"
                    + ("" if not blockers else "<p>승인 전에 해결할 것: " + E(" / ".join(blockers)) + "</p>") +
                    f"<a href='/product/{saved['id']}'>상품 화면에서 가격 계산·번역 계속</a> · <a href='/capture'>가져온 목록</a>")

    @app.post("/product/{pid}/translation/assist")
    async def translation_assist_save(pid: int, request: Request):
        guard(request, True)
        form = await fields(request)
        channel = channel_value(form)
        title, description, names = parse_translation_reply(product(pid), form.get("reply", ""))
        store.add_translation(pid, title, description, names, expected_version=version(form))
        return done("Claude 번역을 초안으로 저장했습니다. 원문과 대조한 뒤 검수 완료를 눌러주세요.", pid, channel)

    @app.post("/product/{pid}/translation/review")
    async def review_translation(pid: int, request: Request):
        actor = guard(request, True)
        form = await fields(request)
        channel = channel_value(form)
        product(pid)
        if form.get("confirmed") != "yes":
            raise ValidationError("원문·수치·옵션 대조 확인이 필요합니다.")
        try:
            v = int(form.get("translation_version", ""))
        except ValueError:
            raise ValidationError("검수할 번역 버전을 확인하세요.")
        store.review_translation(pid, v, actor)
        return done("번역 검수를 완료했습니다.", pid, channel)

    @app.post("/product/{pid}/price")
    async def calculate(pid: int, request: Request):
        actor = guard(request, True)
        form = await fields(request)
        channel = channel_value(form)
        p = product(pid)
        if form.get("rates_confirmed") != "yes":
            raise ValidationError("적용할 환율·배송·수수료를 확인하세요.")
        def number(key):
            return D(form.get(key), key)
        for i, option in enumerate(p["options"]):
            option["weight_g"] = str(number(f"cost_{i}_weight_g"))
            option["dims_cm"] = [str(number(f"cost_{i}_dim_{j}")) for j in range(3)]
            for key in COST_LABELS:
                value = number(f"cost_{i}_{key}")
                option[key] = str(value / 100 if key.endswith("rate") else value)
        now = now_utc()
        ship = ShippingRateCard(number("shipping_rate"), now, number("min_billable_g"),
                                number("billing_step_g"), number("volumetric_divisor"), "사용자 확인 입력")
        if ship.min_billable_g <= 0 or ship.billing_step_g <= 0 or ship.volumetric_divisor <= 0:
            raise ValidationError("배송 청구 단위·최소 중량·부피중량 나눗수는 양수여야 합니다.")
        terms = ChannelTerms(channel, number("commission_pct") / 100, number("shipping_fee_pct") / 100,
                             number("fixed_fee"), now, "사용자 확인 입력", verified=False)
        customer_shipping = number("customer_shipping")
        sale = SaleTerms(free_shipping=customer_shipping == 0, customer_shipping_krw=customer_shipping,
                         seller_discount_rate=number("discount_pct") / 100)
        rates = RateBook(FxRate("CNY", number("fx"), now, "사용자 확인 입력"), ship, {channel: terms}, {channel: sale})
        # Validate prices before persisting changes; a bad form must not alter the product.
        from .workflow import option_input
        from .pricing import quote_price
        clean = validate_product(p)
        for o in clean["options"]:
            quote_price(option_input(o), rates.fx, ship, terms, sale, now)
        store.upsert_products([clean], actor, expected_version=version(form))
        price_product(store, pid, channel, rates, now)
        return done("모든 옵션의 가격을 계산했습니다.", pid, channel)

    @app.post("/product/{pid}/export")
    async def download_draft(pid: int, request: Request):
        guard(request, True)
        form = await fields(request)
        channel = channel_value(form)
        product(pid)
        with tempfile.TemporaryDirectory(prefix="purchasing-draft-") as tmp:
            folder = export_draft(store, pid, channel, tmp)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in folder.iterdir():
                    archive.writestr(path.name, path.read_bytes())
        return Response(buffer.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="draft-{pid}-{channel}.zip"', "Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, channel: str = "smartstore"):
        guard(request, False)
        if channel not in CHANNELS:
            raise HTTPException(400, "unknown channel")
        rows = []
        with store.tx() as c:
            for r in c.execute("SELECT id FROM products ORDER BY id").fetchall():
                p = store.get_product(c, r["id"])
                b = blockers_before_approval(store, c, p["id"], channel, now_utc())
                qs = store.latest_quotes(c, p["id"], channel)
                margins = [q["result"].get("margin") for q in qs if q["result"].get("margin")]
                pubs = c.execute("SELECT state, adapter_kind, account FROM publications WHERE product_id=? AND channel=?", (p["id"], channel)).fetchall()
                publication_text = "; ".join(f"{pub['account']}: " +
                    ("모의 등록 완료" if pub['state'] == 'published' and pub['adapter_kind'] == 'mock'
                     else STATE_LABELS.get(pub['state'], pub['state'])) for pub in pubs)
                tr = store.latest_translation(c, p["id"])
                rows.append(
                    f"<tr><td><input type=checkbox name=ids value={p['id']} form=bulk></td>"
                    f"<td><a href='/product/{p['id']}?channel={E(channel)}'>{p['id']}</a></td><td>{E(tr['title_ko']) + '<br>' if tr else ''}{E(p['title_src'])}</td>"
                    f"<td>{E(STATE_LABELS.get(p['status'], p['status']))}</td><td>{E(', '.join(percent(m) for m in margins) or '-')}</td>"
                    f"<td>{E('; '.join(b) or '검토 가능')}</td><td>{E(publication_text or '-')}</td></tr>")
        empty = "<p>아직 상품이 없습니다. 위의 ‘상품 가져오기’에서 가상 상품 샘플로 시작하세요.</p>" if not rows else ""
        return page(channel_nav(channel) + f"<h1>후보 · {CHANNEL_LABELS[channel]}</h1><p>목표 마진 {percent(EXPECTED_MARGIN)}. 모의 게시는 실제 게시가 아닙니다.</p>{empty}"
                    f"<form id=bulk method=post action='/bulk'><input type=hidden name=channel value='{E(channel)}'>"
                    f"계정 <input name=account value='mock:acct1'> <button name=action value=approve>일괄 승인</button> "
                    f"<button name=action value=publish>승인본 모의 등록</button> <button name=action value=exclude>제외</button></form>"
                    f"<table><tr><th></th><th>ID</th><th>원문 제목</th><th>상태</th><th>마진</th><th>근거 부족/차단</th><th>채널 상태</th></tr>{''.join(rows)}</table>")

    @app.get("/product/{pid}", response_class=HTMLResponse)
    def detail(pid: int, request: Request, channel: str = "smartstore"):
        guard(request, False)
        if channel not in CHANNELS:
            raise HTTPException(400, "unknown channel")
        with store.tx() as c:
            p = store.get_product(c, pid)
            if not p:
                raise HTTPException(404)
            tr = store.latest_translation(c, pid)
            qs = store.latest_quotes(c, pid, channel)
        q_rows = "".join(
            f"<tr><td>{E(q['source_option_id'])}</td><td>{E(str(q['result'].get('list_price')))}</td>"
            f"<td>{E(str(q['result'].get('total_cost_krw')))} {E(str(q['result'].get('cost_breakdown')))}</td>"
            f"<td>{E(str(q['result'].get('commission_krw')))}/{E(str(q['result'].get('shipping_fee_krw')))}/{E(str(q['result'].get('fixed_fee_krw')))}</td>"
            f"<td>{E(percent(q['result'].get('margin')))}</td><td>{E(str(q['result'].get('scenarios')))}</td>"
            f"<td>{E(', '.join(q['result'].get('blockers') or []))}</td></tr>" for q in qs)
        return page(
            f"<a href='/'>목록</a><h1>{E(p['title_src'])}</h1>"
            f"<h2>원문 / 번역 비교</h2><table><tr><th>원문</th><th>번역({'검수 완료' if tr and tr['status'] == 'reviewed' else '초안' if tr else '없음'})</th></tr>"
            f"<tr><td>{E(p['title_src'])}<hr>{E(p['description_src'])}</td><td>{E(tr['title_ko']) if tr else '-'}<hr>{E(tr['description_ko']) if tr else '-'}</td></tr></table>"
            f"<h2>가격 구성 · {CHANNEL_LABELS[channel]} — 고정비·소득세 차감 전, 이익 보장 아님</h2>"
            f"<table><tr><th>옵션</th><th>판매가</th><th>원가</th><th>수수료/배송수수료/고정</th><th>마진</th><th>원가 상승 시나리오</th><th>차단</th></tr>{q_rows}</table>"
            f"<p>이미지 {len(p['images'])}개, 배송 {E(str(p.get('est_delivery_days')))}</p>" + product_forms(p, tr, qs, channel))

    @app.post("/bulk")
    async def bulk(request: Request):
        actor = guard(request, True)
        form = await fields(request, multiple=True)
        channel = (form.get("channel") or [""])[0]
        account = (form.get("account") or [""])[0]
        if channel not in CHANNELS or not account:
            raise HTTPException(400, "channel/account required")
        try:
            ids = list(dict.fromkeys(int(x) for x in form.get("ids", [])))
        except ValueError:
            raise HTTPException(400, "bad ids")
        action = (form.get("action") or [""])[0]
        if not ids or len(ids) > 100:
            raise ValidationError("상품을 1~100개 선택하세요.")
        if action in ("approve", "publish") and not account.startswith("mock:"):
            raise ValidationError("시연 화면에서는 mock: 계정만 사용할 수 있습니다.")
        if action == "publish":
            adapter = MockChannelAdapter(store)
            reasons = []
            with store.tx() as c:
                for pid in ids:
                    pub = c.execute("SELECT state FROM publications WHERE product_id=? AND channel=? AND account=?",
                                    (pid, channel, account)).fetchone()
                    if pub and pub["state"] in ("published", "claimed", "unknown"):
                        continue
                    b = publish_blockers(store, c, pid, channel, account, adapter, now_utc())
                    if b:
                        reasons.append(f"상품 {pid}: {'; '.join(b)}")
            summary = run_week(store, week_key(), [(pid, channel, account) for pid in ids], adapter)
            outcomes = summary["outcomes"]
            return page(f"<h1>모의 등록 결과</h1><p>실제 등록 0건</p>"
                        f"<p>이번 요청 모의 성공 {outcomes.get('published', 0)}건 · 이미 처리한 상품 {outcomes.get('skipped', 0)}건 · "
                        f"보류 {outcomes.get('blocked', 0)}건 · 실패 {outcomes.get('failed', 0)}건 · 결과 확인 중 {outcomes.get('unknown', 0)}건</p>"
                        f"<ul>{''.join('<li>' + E(reason) + '</li>' for reason in reasons)}</ul>"
                        f"<a href='/?channel={channel}'>상품 목록으로 돌아가기</a>")
        if action == "approve":
            failed = approve(store, ids, channel, account, actor)
            return page(f"승인 {len(ids) - len(failed)}건, 보류 {len(failed)}건: {E(str(failed))} <a href='/'>돌아가기</a>")
        if action == "exclude":
            exclude(store, ids, actor, "검토 화면에서 제외")
            return page(f"{len(ids)}건 제외 <a href='/'>돌아가기</a>")
        raise HTTPException(400, "bad action")

    return app


def app_from_env():  # uvicorn --factory app.purchasing.web:app_from_env --host 127.0.0.1
    return create_app(Store(os.environ.get("PURCHASING_DB", "purchasing.db")),
                      os.environ.get("PURCHASING_REVIEW_USER", "reviewer"), os.environ.get("PURCHASING_REVIEW_PASSWORD", ""))
