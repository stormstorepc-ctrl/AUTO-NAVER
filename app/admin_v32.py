from html import escape
from urllib.parse import quote
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import Product
from .services import calculate_sale_price, log
from .settings import settings

COOKIE='stormpc_admin'

def guard(request: Request):
    if request.cookies.get(COOKIE) != 'ok':
        return RedirectResponse('/admin/login', 303)

def product_page(p: Product, error: str='') -> str:
    img = escape(p.representative_image or '')
    detail = escape(p.detail_html or '')
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>상품 편집</title><style>
body{{font-family:Arial,sans-serif;background:#f5f7fb;margin:0;color:#172033}}header{{background:#111827;color:white;padding:16px 22px}}main{{max-width:1100px;margin:24px auto;padding:0 18px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:white;border-radius:16px;padding:20px;box-shadow:0 3px 16px #0000000a}}label{{display:block;font-weight:700;margin:13px 0 5px}}input,textarea,select{{width:100%;box-sizing:border-box;padding:11px;border:1px solid #d1d5db;border-radius:9px}}textarea{{min-height:180px;font-family:inherit}}button,a.btn{{display:inline-block;border:0;border-radius:9px;padding:10px 14px;background:#111827;color:white;text-decoration:none;cursor:pointer;margin-right:6px}}.secondary{{background:#6b7280!important}}.err{{color:#b91c1c;background:#fee2e2;padding:10px;border-radius:8px}}img.preview{{max-width:100%;max-height:340px;object-fit:contain;border:1px solid #eee;border-radius:10px}}small{{color:#6b7280}}</style></head><body><header><b>STORMPC AUTO COMMERCE — 상품 편집 #{p.id}</b></header><main><p><a class="btn secondary" href="/admin">← 상품관리</a></p>{f'<div class="err">{escape(error)}</div>' if error else ''}<div class="grid"><section class="card"><h2>상품 기본정보</h2><form method="post" action="/admin/products/{p.id}/save"><label>상품명</label><input name="name" value="{escape(p.name)}" required><label>브랜드</label><input name="brand" value="{escape(p.brand or '')}"><label>모델</label><input name="model" value="{escape(p.model or '')}"><label>네이버 카테고리 ID</label><input name="category" value="{escape(p.category or '')}"><small>스마트스토어 등록용 leafCategoryId</small><label>대표 이미지 URL</label><input name="representative_image" value="{img}"><label>상세 설명 HTML</label><textarea name="detail_html">{detail}</textarea><button type="submit">저장</button></form></section><section class="card"><h2>판매 설정</h2><form method="post" action="/admin/products/{p.id}/save"><input type="hidden" name="name" value="{escape(p.name)}"><input type="hidden" name="brand" value="{escape(p.brand or '')}"><input type="hidden" name="model" value="{escape(p.model or '')}"><input type="hidden" name="category" value="{escape(p.category or '')}"><input type="hidden" name="representative_image" value="{img}"><input type="hidden" name="detail_html" value="{detail}"><label>공급가</label><input name="supply_price" type="number" min="0" value="{p.supply_price}"><label>판매가</label><input name="sale_price" type="number" min="0" value="{p.sale_price}"><label>재고</label><input name="stock" type="number" min="0" value="{p.stock}"><label>상태</label><select name="status"><option {'selected' if p.status=='PENDING' else ''}>PENDING</option><option {'selected' if p.status=='PRICE_REVIEW' else ''}>PRICE_REVIEW</option><option {'selected' if p.status=='APPROVED' else ''}>APPROVED</option><option {'selected' if p.status=='SOLD_OUT' else ''}>SOLD_OUT</option><option {'selected' if p.status=='SMARTSTORE_LISTED' else ''}>SMARTSTORE_LISTED</option><option {'selected' if p.status=='SMARTSTORE_ERROR' else ''}>SMARTSTORE_ERROR</option></select><label><input style="width:auto" type="checkbox" name="approved" {'checked' if p.approved else ''}> 관리자 승인</label><button type="submit">저장</button></form><form method="post" action="/admin/products/{p.id}/reprice"><button type="submit" class="secondary">현재 공급가로 판매가 재계산</button></form><hr><h3>대표 이미지 미리보기</h3>{f'<img class="preview" src="{img}" onerror="this.style.display=\'none\'">' if img else '<p>이미지 없음</p>'}</section></div></main></body></html>'''


def router_app():
    from fastapi import FastAPI
    app=FastAPI()

    @app.get('/admin/products/{product_id}/edit', response_class=HTMLResponse)
    def edit(product_id:int,request:Request,db:Session=Depends(get_db)):
        g=guard(request)
        if g:return g
        p=db.get(Product,product_id)
        if not p:return HTMLResponse('상품을 찾을 수 없습니다.',404)
        return HTMLResponse(product_page(p))

    @app.post('/admin/products/{product_id}/save')
    def save(product_id:int,request:Request,db:Session=Depends(get_db),name:str=Form(...),brand:str=Form(''),model:str=Form(''),category:str=Form(''),representative_image:str=Form(''),detail_html:str=Form(''),supply_price:int=Form(0),sale_price:int=Form(0),stock:int=Form(0),status:str=Form('PENDING'),approved:str|None=Form(None)):
        g=guard(request)
        if g:return g
        p=db.get(Product,product_id)
        if not p:return HTMLResponse('상품을 찾을 수 없습니다.',404)
        p.name=name.strip();p.brand=brand.strip() or None;p.model=model.strip() or None;p.category=category.strip() or None;p.representative_image=representative_image.strip() or None;p.detail_html=detail_html;p.supply_price=max(0,supply_price);p.sale_price=max(0,sale_price);p.stock=max(0,stock);p.status=status;p.approved=approved is not None
        if p.supply_price==1 or p.stock==0:p.status='SOLD_OUT';p.stock=0;p.sale_price=0
        log(db,'ADMIN_EDIT','상품 정보 저장',p.id);db.commit()
        return RedirectResponse(f'/admin/products/{p.id}/edit',303)

    @app.post('/admin/products/{product_id}/reprice')
    def reprice(product_id:int,request:Request,db:Session=Depends(get_db)):
        g=guard(request)
        if g:return g
        p=db.get(Product,product_id)
        if not p:return RedirectResponse('/admin',303)
        if p.supply_price==1 or p.stock<=0:p.status='SOLD_OUT';p.stock=0;p.sale_price=0
        else:p.sale_price=max(calculate_sale_price(p.supply_price),settings.default_min_sale_price);p.status='APPROVED' if p.approved else 'PENDING'
        log(db,'PRICE_RECALCULATE','관리자 화면에서 판매가 재계산',p.id);db.commit()
        return RedirectResponse(f'/admin/products/{p.id}/edit',303)
    return app
