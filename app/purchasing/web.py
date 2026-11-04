"""로컬 검토 화면 (루프백 전용). 모든 변경 요청은 Basic 인증 + Origin/Host 검증을 거친다."""
from __future__ import annotations

import base64
import html
import ipaddress
import os
import secrets
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .store import Store
from .workflow import approve, blockers_before_approval, exclude, EXPECTED_MARGIN
from .store import now_utc

CHANNELS = ("smartstore", "danggeun", "bunjang")
E = html.escape


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
                            f"<style>body{{font:14px sans-serif;margin:16px}}td,th{{border:1px solid #ccc;padding:4px}}</style>{body}",
                            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
                                     "X-Frame-Options": "DENY", "Cache-Control": "no-store"})

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
                pub = c.execute("SELECT state, adapter_kind FROM publications WHERE product_id=? AND channel=?", (p["id"], channel)).fetchone()
                rows.append(
                    f"<tr><td><input type=checkbox name=ids value={p['id']} form=bulk></td>"
                    f"<td><a href='/product/{p['id']}?channel={E(channel)}'>{p['id']}</a></td><td>{E(p['title_src'])}</td>"
                    f"<td>{E(p['status'])}</td><td>{E(', '.join(f'{float(m):.4f}' for m in margins) or '-')}</td>"
                    f"<td>{E('; '.join(b) or '검토 가능')}</td><td>{E((pub['adapter_kind'] + ':' + pub['state']) if pub else '-')}</td></tr>")
        return page(f"<h1>후보 ({E(channel)})</h1><p>목표 마진 {EXPECTED_MARGIN}. 모의(mock) 게시는 실제 게시가 아닙니다.</p>"
                    f"<form id=bulk method=post action='/bulk'><input type=hidden name=channel value='{E(channel)}'>"
                    f"계정 <input name=account value='mock:acct1'> <button name=action value=approve>일괄 승인</button> "
                    f"<button name=action value=exclude>제외</button></form>"
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
            f"<td>{E(str(q['result'].get('margin')))}</td><td>{E(str(q['result'].get('scenarios')))}</td>"
            f"<td>{E(', '.join(q['result'].get('blockers') or []))}</td></tr>" for q in qs)
        return page(
            f"<a href='/'>목록</a><h1>{E(p['title_src'])}</h1>"
            f"<h2>원문 / 번역 비교</h2><table><tr><th>원문</th><th>번역({E(tr['status']) if tr else '없음'})</th></tr>"
            f"<tr><td>{E(p['title_src'])}<hr>{E(p['description_src'])}</td><td>{E(tr['title_ko']) if tr else '-'}<hr>{E(tr['description_ko']) if tr else '-'}</td></tr></table>"
            f"<h2>가격 구성 ({E(channel)}) — 고정비·소득세 차감 전, 이익 보장 아님</h2>"
            f"<table><tr><th>옵션</th><th>판매가</th><th>원가</th><th>수수료/배송수수료/고정</th><th>마진</th><th>원가 상승 시나리오</th><th>차단</th></tr>{q_rows}</table>"
            f"<p>이미지 {len(p['images'])}개, 배송 {E(str(p.get('est_delivery_days')))}</p>")

    @app.post("/bulk")
    async def bulk(request: Request):
        actor = guard(request, True)
        form = parse_qs((await request.body()).decode(), keep_blank_values=True)
        channel = (form.get("channel") or [""])[0]
        account = (form.get("account") or [""])[0]
        if channel not in CHANNELS or not account:
            raise HTTPException(400, "channel/account required")
        try:
            ids = [int(x) for x in form.get("ids", [])]
        except ValueError:
            raise HTTPException(400, "bad ids")
        action = (form.get("action") or [""])[0]
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
