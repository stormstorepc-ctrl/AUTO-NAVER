from html import escape
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from .db import get_db
from .models import Product
from .services import calculate_sale_price, log
from .settings import settings

router = APIRouter()
COOKIE = 'stormpc_admin'


def guard(request: Request):
    if request.cookies.get(COOKIE) != 'ok':
        return RedirectResponse('/admin/login', status_code=303)


def page(p: Product, error: str = '') -> str:
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>상품 편집</title>
<style>body{{font-family:Arial,sans-serif;background:#f5f7fb;margin:0;color:#172033}}header{{background:#111827;color:#fff;padding:16px 22px}}main{{max-width:1180px;margin:24px auto;padding:0 18px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:#fff;border-radius:16px;padding:22px;box-shadow:0 3px 18px #0000000a}}label{{display:block;font-weight:700;margin:12px 0 5px}}input,textarea,select{{width:100%;box-sizing:border-box;padding:11px;border:1px solid #d1d5db;border-radius:9px}}textarea{{min-height:220px;font-family:inherit}}button,a.btn{{display:inline-block;border:0;border-radius:9px;padding:10px 14px;background:#111827;color:#fff;text-decoration:none;cursor:pointer;margin:5px 5px 5px 0}}.secondary{{background:#6b7280!important}}.danger{{background:#b91c1c!important}}.err{{color:#991b1b;background:#fee2e2;padding:10px;border-radius:8px}}img.preview{{max-width:100%;max-height:360px;object-fit:contain;border:1px solid #eee;border-radius:10px}}small{{color:#6b7280}}</style></head>
<body><header><b>STORMPC AUTO COMMERCE · 상품 편집 #{p.id}</b></header><main><a class="btn secondary" href="/admin">← 관리자</a>{f'<div class="err">{escape(error)}</div>' if error else ''}<div class="grid">
<section class="card"><h2>상품 정보</h2><form method="post" action="/admin/products/{p.id}/save"><label>상품명</label><input name="name" value="{escape(p.name)}" required><label>브랜드</label><input name="brand" value="{escape(p.brand or '')}"><label>모델</label><input name="model" value="{escape(p.model or '')}"><label>네이버 카테고리 ID</label><input name="category" value="{escape(p.category or '')}"><small>예: 네이버 Commerce API의 leafCategoryId</small><label>대표 이미지 URL</label><input name="representative_image" value="{escape(p.representative_image or '')}"><label>상세설명 HTML</label><textarea name="detail_html">{escape(p.detail_html or '')}</textarea><button>상품정보 저장</button></form></section>
<section class="card"><h2>판매/재고</h2><form method="post" action="/admin/products/{p.id}/save"><input type="hidden" name="name" value="{escape(p.name)}"><input type="hidden" name="brand" value="{escape(p.brand or '')}"><input type="hidden" name="model" value="{escape(p.model or '')}"><input type="hidden" name="category" value="{escape(p.category or '')}"><input type="hidden" name="representative_image" value="{escape(p.representative_image or '')}"><input type="hidden" name="detail_html" value="{escape(p.detail_html or '')}"><label>공급가</label><input name="supply_price" type="number" min="0" value="{p.supply_price}"><label>판매가</label><input name="sale_price" type="number" min="0" value="{p.sale_price}"><label>재고</label><input name="stock" type="number" min="0" value="{p.stock}"><label>상태</label><select name="status">{''.join(f'<option value="{s}" {"selected" if p.status==s else ""}>{s}</option>' for s in ["PENDING","PRICE_REVIEW","APPROVED","SOLD_OUT","SMARTSTORE_LISTED","SMARTSTORE_ERROR"])}</select><label><input style="width:auto" type="checkbox" name="approved" {'checked' if p.approved else ''}> 관리자 승인</label><button>판매정보 저장</button></form><form method="post" action="/admin/products/{p.id}/reprice"><button class="secondary">공급가 기준 가격 재계산</button></form><h3>이미지 미리보기</h3>{f'<img class="preview" src="{escape(p.representative_image)}" onerror="this.style.display=\'none\'">' if p.representative_image else '<p>대표 이미지가 없습니다.</p>'}</section></div></main></body></html>'''


@router.get('/admin/products/{product_id}/edit', response_class=HTMLResponse)
def edit(product_id: int, request: Request, db: Session = Depends(get_db)):
    g = guard(request)
    if g: return g
    p = db.get(Product, product_id)
    if not p: return HTMLResponse('상품을 찾을 수 없습니다.', status_code=404)
    return HTMLResponse(page(p))


@router.post('/admin/products/{product_id}/save')
def save(product_id: int, request: Request, db: Session = Depends(get_db), name: str = Form(...), brand: str = Form(''), model: str = Form(''), category: str = Form(''), representative_image: str = Form(''), detail_html: str = Form(''), supply_price: int = Form(0), sale_price: int = Form(0), stock: int = Form(0), status: str = Form('PENDING'), approved: str | None = Form(None)):
    g = guard(request)
    if g: return g
    p = db.get(Product, product_id)
    if not p: return HTMLResponse('상품을 찾을 수 없습니다.', status_code=404)
    p.name = name.strip(); p.brand = brand.strip() or None; p.model = model.strip() or None; p.category = category.strip() or None
    p.representative_image = representative_image.strip() or None; p.detail_html = detail_html
    p.supply_price = max(0, supply_price); p.sale_price = max(0, sale_price); p.stock = max(0, stock)
    p.status = status; p.approved = approved is not None
    if p.supply_price == 1 or p.stock <= 0:
        p.stock = 0; p.sale_price = 0; p.status = 'SOLD_OUT'
    log(db, 'ADMIN_EDIT', '관리자가 상품정보를 저장했습니다.', p.id)
    db.commit()
    return RedirectResponse(f'/admin/products/{p.id}/edit', status_code=303)


@router.post('/admin/products/{product_id}/reprice')
def reprice(product_id: int, request: Request, db: Session = Depends(get_db)):
    g = guard(request)
    if g: return g
    p = db.get(Product, product_id)
    if not p: return RedirectResponse('/admin', status_code=303)
    if p.supply_price == 1 or p.stock <= 0:
        p.stock = 0; p.sale_price = 0; p.status = 'SOLD_OUT'
    else:
        p.sale_price = max(calculate_sale_price(p.supply_price), settings.default_min_sale_price)
        p.status = 'APPROVED' if p.approved else 'PENDING'
    log(db, 'PRICE_RECALCULATE', '관리자 상품편집에서 판매가 재계산', p.id)
    db.commit()
    return RedirectResponse(f'/admin/products/{p.id}/edit', status_code=303)
