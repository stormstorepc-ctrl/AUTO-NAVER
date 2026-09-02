from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .db import Base, engine, get_db
from .models import Product, SyncLog
from .services import apply_source_update, calculate_sale_price, log
from .settings import settings

Base.metadata.create_all(engine)
app = FastAPI(title='STORMPC AUTO COMMERCE v3')

ADMIN_COOKIE = 'stormpc_admin'

def admin_ok(request: Request) -> bool:
    return request.cookies.get(ADMIN_COOKIE) == 'ok'

def require_admin(request: Request):
    if not admin_ok(request):
        return RedirectResponse('/admin/login', status_code=303)

auth_css = '''<style>body{font-family:Arial,sans-serif;background:#f4f6f8;margin:0;color:#172033}.box{max-width:420px;margin:100px auto;background:#fff;padding:32px;border-radius:16px;box-shadow:0 8px 30px #0001}input,button{width:100%;padding:12px;margin-top:10px;box-sizing:border-box}button{background:#111827;color:#fff;border:0;border-radius:8px;cursor:pointer}.err{color:#b91c1c}</style>'''

@app.get('/health')
def health():
    return {'status':'ok','version':'v3'}

@app.get('/admin/login', response_class=HTMLResponse)
def admin_login(error: str = ''):
    return HTMLResponse(auth_css + f'''<div class="box"><h1>STORMPC 관리자</h1><form method="post"><input name="username" placeholder="관리자 ID" autofocus><input name="password" type="password" placeholder="비밀번호"><button>로그인</button></form><div class="err">{error}</div></div>''')

@app.post('/admin/login')
def admin_login_post(username: str = Form(...), password: str = Form(...)):
    if username == settings.admin_username and password == settings.admin_password:
        r = RedirectResponse('/admin', status_code=303)
        r.set_cookie(ADMIN_COOKIE, 'ok', httponly=True, samesite='lax')
        return r
    return RedirectResponse('/admin/login?error=관리자 정보가 올바르지 않습니다.', status_code=303)

@app.get('/admin/logout')
def admin_logout():
    r = RedirectResponse('/admin/login', status_code=303)
    r.delete_cookie(ADMIN_COOKIE)
    return r

@app.get('/admin', response_class=HTMLResponse)
def admin(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard: return guard
    total = db.scalar(select(func.count(Product.id))) or 0
    pending = db.scalar(select(func.count(Product.id)).where(Product.status.in_(['PENDING','PRICE_REVIEW']))) or 0
    approved = db.scalar(select(func.count(Product.id)).where(Product.approved == True)) or 0
    listed = db.scalar(select(func.count(Product.id)).where(Product.smartstore_product_id.is_not(None))) or 0
    soldout = db.scalar(select(func.count(Product.id)).where(Product.status == 'SOLD_OUT')) or 0
    logs = db.scalars(select(SyncLog).order_by(SyncLog.created_at.desc()).limit(20)).all()
    products = db.scalars(select(Product).order_by(Product.updated_at.desc()).limit(100)).all()
    rows = ''.join(f'''<tr><td>{p.id}</td><td>{p.name}</td><td>{p.category or ''}</td><td>{p.supply_price:,}</td><td>{p.sale_price:,}</td><td>{p.stock}</td><td>{p.status}</td><td>{'승인' if p.approved else '대기'}</td><td><form method="post" action="/products/{p.id}/approve" style="display:inline"><button>승인</button></form> <form method="post" action="/products/{p.id}/smartstore" style="display:inline"><button>스토어</button></form></td></tr>''' for p in products)
    logrows = ''.join(f'<tr><td>{x.created_at}</td><td>{x.action}</td><td>{x.level}</td><td>{x.message}</td></tr>' for x in logs)
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><title>STORMPC 관리자</title><style>body{{font-family:Arial;margin:0;background:#f5f7fb}}header{{background:#111827;color:#fff;padding:18px 28px;display:flex;justify-content:space-between}}main{{padding:24px}}.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}.card{{background:#fff;padding:18px;border-radius:14px}}table{{width:100%;border-collapse:collapse;background:#fff;margin-top:18px}}th,td{{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}}button{{padding:7px 10px;border:0;border-radius:6px;background:#111827;color:white}}</style></head><body><header><b>STORMPC AUTO COMMERCE v3</b><a href="/admin/logout" style="color:white">로그아웃</a></header><main><div class="cards"><div class="card"><b>전체</b><h2>{total}</h2></div><div class="card"><b>승인 대기</b><h2>{pending}</h2></div><div class="card"><b>승인 완료</b><h2>{approved}</h2></div><div class="card"><b>스토어 등록</b><h2>{listed}</h2></div><div class="card"><b>품절</b><h2>{soldout}</h2></div></div><h2>상품관리</h2><table><tr><th>ID</th><th>상품명</th><th>카테고리</th><th>공급가</th><th>판매가</th><th>재고</th><th>상태</th><th>승인</th><th>작업</th></tr>{rows}</table><h2>최근 작업로그</h2><table><tr><th>시간</th><th>작업</th><th>레벨</th><th>내용</th></tr>{logrows}</table></main></body></html>''')

@app.get('/products')
def products(db: Session = Depends(get_db)):
    return db.scalars(select(Product).order_by(Product.id)).all()

@app.post('/products/{product_id}/approve')
def approve(product_id: int, request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard: return guard
    p = db.get(Product, product_id)
    if not p: return {'ok':False,'error':'product not found'}
    p.approved = True
    if p.status not in ('SOLD_OUT',): p.status = 'APPROVED'
    log(db, 'APPROVE', '관리자 승인', p.id)
    db.commit()
    return RedirectResponse('/admin', status_code=303)

@app.post('/pricing/recalculate/{product_id}')
def recalculate(product_id: int, request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard: return guard
    p = db.get(Product, product_id)
    if not p: return {'ok':False,'error':'product not found'}
    if p.supply_price == 1:
        p.status='SOLD_OUT'; p.stock=0; p.sale_price=0
    else:
        p.sale_price = max(calculate_sale_price(p.supply_price), settings.default_min_sale_price)
        p.status='PRICE_REVIEW' if not p.approved else 'APPROVED'
    log(db,'PRICE_RECALCULATE','판매가 재계산',p.id)
    db.commit()
    return RedirectResponse('/admin', status_code=303)

@app.post('/products/{product_id}/smartstore')
def smartstore(product_id: int, request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard: return guard
    p = db.get(Product, product_id)
    if not p: return {'ok':False,'error':'product not found'}
    if not p.approved: return RedirectResponse('/admin', status_code=303)
    # 실제 Commerce API 호출은 인증정보와 스토어별 필수 payload가 설정된 뒤 연결한다.
    p.status = 'SMARTSTORE_PENDING'
    log(db,'SMARTSTORE_REGISTER','스마트스토어 등록 대기 payload 생성',p.id)
    db.commit()
    return RedirectResponse('/admin', status_code=303)

@app.post('/products/{product_id}/cafe')
def cafe(product_id: int, request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard: return guard
    p = db.get(Product, product_id)
    if not p: return {'ok':False,'error':'product not found'}
    log(db,'CAFE_POST','카페 게시 대기',p.id)
    db.commit()
    return RedirectResponse('/admin', status_code=303)

@app.post('/crawl/macromart')
def crawl_macromart(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard: return guard
    log(db,'CRAWL','매크로마트 수집 요청 접수')
    db.commit()
    return {'ok':True,'message':'crawler job accepted'}
