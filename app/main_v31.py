from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .db import Base, engine, get_db
from .models import Product, SyncLog
from .services import apply_source_update, calculate_sale_price, log
from .settings import settings
from .naver import naver_commerce
from .naver_cafe import naver_cafe
from .crawlers.macromart import MacroMartCrawler
from .admin_routes import router as admin_product_router

Base.metadata.create_all(engine)
app = FastAPI(title='STORMPC AUTO COMMERCE v3.2')
app.include_router(admin_product_router)
ADMIN_COOKIE='stormpc_admin'

def guard(request: Request):
    if request.cookies.get(ADMIN_COOKIE) != 'ok': return RedirectResponse('/admin/login',303)

auth_css='''<style>body{font-family:Arial;background:#f4f6f8}.box{max-width:420px;margin:100px auto;background:#fff;padding:32px;border-radius:16px}input,button{padding:11px;margin:5px;box-sizing:border-box}input{width:100%}button{border:0;border-radius:7px;background:#111827;color:white;cursor:pointer}.err{color:#b91c1c}</style>'''

@app.get('/health')
def health(): return {'status':'ok','version':'v3.2'}

@app.get('/admin/login',response_class=HTMLResponse)
def login(error:str=''):
    return HTMLResponse(auth_css+f'''<div class="box"><h1>STORMPC 관리자</h1><form method="post"><input name="username" placeholder="관리자 ID" autofocus><input name="password" type="password" placeholder="비밀번호"><button>로그인</button></form><div class="err">{error}</div></div>''')

@app.post('/admin/login')
def login_post(username:str=Form(...),password:str=Form(...)):
    if username==settings.admin_username and password==settings.admin_password:
        r=RedirectResponse('/admin',303); r.set_cookie(ADMIN_COOKIE,'ok',httponly=True,samesite='lax',max_age=28800); return r
    return RedirectResponse('/admin/login?error=관리자 정보가 올바르지 않습니다.',303)

@app.get('/admin/logout')
def logout():
    r=RedirectResponse('/admin/login',303); r.delete_cookie(ADMIN_COOKIE); return r

@app.get('/admin',response_class=HTMLResponse)
def admin(request:Request,db:Session=Depends(get_db)):
    g=guard(request)
    if g:return g
    total=db.scalar(select(func.count(Product.id))) or 0
    pending=db.scalar(select(func.count(Product.id)).where(Product.status.in_(['PENDING','PRICE_REVIEW']))) or 0
    approved=db.scalar(select(func.count(Product.id)).where(Product.approved==True)) or 0
    listed=db.scalar(select(func.count(Product.id)).where(Product.smartstore_product_id.is_not(None))) or 0
    soldout=db.scalar(select(func.count(Product.id)).where(Product.status=='SOLD_OUT')) or 0
    logs=db.scalars(select(SyncLog).order_by(SyncLog.created_at.desc()).limit(25)).all()
    products=db.scalars(select(Product).order_by(Product.updated_at.desc()).limit(200)).all()
    cafe_ready=naver_cafe.configured; cafe_token=bool(getattr(naver_cafe,'_token',{}).get('access_token'))
    rows=''.join(f'''<tr><td>{p.id}</td><td><a href="/admin/products/{p.id}/edit">{p.name}</a></td><td>{p.category or ''}</td><td>{p.supply_price:,}</td><td>{p.sale_price:,}</td><td>{p.stock}</td><td>{p.status}</td><td>{'승인' if p.approved else '대기'}</td><td><form method="post" action="/products/{p.id}/approve"><button>승인</button></form><form method="post" action="/products/{p.id}/recalculate"><button>가격 재계산</button></form><form method="post" action="/products/{p.id}/smartstore"><button>스토어 등록</button></form><form method="post" action="/products/{p.id}/cafe"><button>카페 등록</button></form></td></tr>''' for p in products)
    logrows=''.join(f'<tr><td>{x.created_at}</td><td>{x.action}</td><td>{x.level}</td><td>{x.message}</td></tr>' for x in logs)
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{{font-family:Arial;margin:0;background:#f5f7fb;color:#172033}}header{{background:#111827;color:#fff;padding:18px 24px;display:flex;justify-content:space-between}}main{{padding:20px;overflow:auto}}.cards{{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:12px}}.card{{background:white;padding:16px;border-radius:14px}}table{{width:100%;border-collapse:collapse;background:#fff;margin-top:16px}}th,td{{padding:9px;border-bottom:1px solid #e5e7eb;white-space:nowrap;text-align:left}}form{{display:inline}}button{{padding:7px 9px;margin:2px}}a{{color:#111827;font-weight:700}}.notice{{background:#fff;padding:14px;border-radius:12px;margin:16px 0}}</style></head><body><header><b>STORMPC AUTO COMMERCE v3.2</b><a style="color:#fff" href="/admin/logout">로그아웃</a></header><main><div class="cards"><div class="card">전체<h2>{total}</h2></div><div class="card">승인대기<h2>{pending}</h2></div><div class="card">승인완료<h2>{approved}</h2></div><div class="card">스토어등록<h2>{listed}</h2></div><div class="card">품절<h2>{soldout}</h2></div></div><div class="notice"><b>네이버 카페:</b> {'연결됨' if cafe_token else '미연결'} / API 설정 {'완료' if cafe_ready else '필요'} &nbsp; <a href="/naver/login?reprompt=1">네이버 카페 재인증</a></div><p><form method="post" action="/crawl/macromart"><button>매크로마트 전체 수집</button></form></p><h2>상품관리</h2><table><tr><th>ID</th><th>상품명</th><th>카테고리</th><th>공급가</th><th>판매가</th><th>재고</th><th>상태</th><th>승인</th><th>작업</th></tr>{rows}</table><h2>작업로그</h2><table><tr><th>시간</th><th>작업</th><th>레벨</th><th>내용</th></tr>{logrows}</table></main></body></html>''')

@app.get('/naver/login')
def naver_login(request: Request, reprompt:int=0):
    g=guard(request)
    if g:return g
    try: return RedirectResponse(naver_cafe.authorization_url(reprompt=bool(reprompt)),303)
    except Exception as exc: return HTMLResponse(f'<h2>네이버 카페 설정 오류</h2><p>{exc}</p><p><a href="/admin">관리자</a></p>',500)

@app.get('/naver/callback')
def naver_callback(request: Request, code: str = '', state: str = '', error: str = '', error_description: str = ''):
    if error:return HTMLResponse(f'<h2>네이버 인증 실패</h2><p>{error_description or error}</p><p><a href="/admin">관리자</a></p>',400)
    if not code or not state:return HTMLResponse('<h2>네이버 인증 정보가 없습니다.</h2><p><a href="/admin">관리자</a></p>',400)
    try: naver_cafe.exchange_code(code,state); return RedirectResponse('/admin',303)
    except Exception as exc:return HTMLResponse(f'<h2>네이버 인증 처리 실패</h2><p>{exc}</p><p><a href="/admin">관리자</a></p>',500)

@app.post('/products/{product_id}/approve')
def approve(product_id:int,request:Request,db:Session=Depends(get_db)):
    g=guard(request)
    if g:return g
    p=db.get(Product,product_id)
    if p and p.status!='SOLD_OUT': p.approved=True; p.status='APPROVED'; log(db,'APPROVE','관리자 승인',p.id); db.commit()
    return RedirectResponse('/admin',303)

@app.post('/products/{product_id}/recalculate')
def recalc(product_id:int,request:Request,db:Session=Depends(get_db)):
    g=guard(request)
    if g:return g
    p=db.get(Product,product_id)
    if p:
        if p.supply_price==1 or p.stock<=0: p.status='SOLD_OUT'; p.stock=0; p.sale_price=0
        else: p.sale_price=max(calculate_sale_price(p.supply_price),settings.default_min_sale_price); p.status='APPROVED' if p.approved else 'PENDING'
        log(db,'PRICE_RECALCULATE','판매가 재계산',p.id); db.commit()
    return RedirectResponse('/admin',303)

@app.post('/products/{product_id}/smartstore')
def smartstore(product_id:int,request:Request,db:Session=Depends(get_db)):
    g=guard(request)
    if g:return g
    p=db.get(Product,product_id)
    if p:
        try:
            if not p.approved: raise RuntimeError('승인되지 않은 상품입니다.')
            if p.status=='SOLD_OUT': raise RuntimeError('품절 상품입니다.')
            no=naver_commerce.register_product(p); p.smartstore_product_id=no; p.status='SMARTSTORE_LISTED'; log(db,'SMARTSTORE_REGISTER',f'등록 성공 상품번호={no}',p.id)
        except Exception as exc: p.status='SMARTSTORE_ERROR'; log(db,'SMARTSTORE_REGISTER',str(exc),p.id,'ERROR')
        db.commit()
    return RedirectResponse('/admin',303)

@app.post('/products/{product_id}/cafe')
def cafe(product_id:int,request:Request,db:Session=Depends(get_db)):
    g=guard(request)
    if g:return g
    p=db.get(Product,product_id)
    if p:
        try:
            if not naver_cafe.configured: raise RuntimeError('네이버 카페 API 설정이 완료되지 않았습니다.')
            title=p.name; content=f'{p.name}\n\n공급가: {p.supply_price:,}원\n판매가: {p.sale_price:,}원\n재고: {p.stock}개\n\n{p.detail_html or ""}'
            result=naver_cafe.post(title,content); p.cafe_post_id=str(result.get('articleId') or result.get('articleid') or result.get('id') or '') or None; log(db,'CAFE_POST',f'카페 게시 성공 {result}',p.id)
        except Exception as exc: log(db,'CAFE_POST',str(exc),p.id,'ERROR')
        db.commit()
    return RedirectResponse('/admin',303)

@app.post('/crawl/macromart')
def crawl(request:Request,db:Session=Depends(get_db)):
    g=guard(request)
    if g:return g
    try:
        data=MacroMartCrawler().crawl(limit=100); new=changed=0
        for item in data:
            if item.get('error') or not item.get('url'): continue
            ext=item['url'][:100]; p=db.scalar(select(Product).where(Product.external_id==ext))
            if not p: p=Product(external_id=ext,name=item.get('name') or '미상 상품',category=item.get('category_path') or '',status='PENDING'); db.add(p); db.flush(); new+=1
            else: changed+=1
            p.name=item.get('name') or p.name
            if item.get('category_path') and not p.category:p.category=item['category_path']
            p.representative_image=item.get('representative_image') or p.representative_image; p.detail_html=item.get('detail_html') or p.detail_html
            apply_source_update(db,p,int(item.get('source_price') or 0),int(item.get('source_stock') or 0))
        log(db,'CRAWL',f'매크로마트 전체 수집 완료 신규={new}, 갱신={changed}'); db.commit()
    except Exception as exc: log(db,'CRAWL',str(exc),None,'ERROR'); db.commit()
    return RedirectResponse('/admin',303)
