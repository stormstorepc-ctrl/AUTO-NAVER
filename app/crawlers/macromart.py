from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs
import json
import re
from playwright.sync_api import sync_playwright, Page
from ..settings import settings

ARTIFACTS = Path('artifacts')
PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?:\s*원)?')
GENERIC_NAMES = {'카페24', 'cafe24', '상품', '상품명', '미상 상품', ''}

def money(text: str) -> int:
    m = PRICE_RE.search((text or '').replace('\xa0',' '))
    return int(m.group(1).replace(',','')) if m else 0

class MacroMartCrawler:
    def login(self,page:Page)->Page:
        page.goto(settings.macromart_start_url,wait_until='domcontentloaded',timeout=60000)
        id_candidates=['input[name="id"]','input[name="userid"]','input[name="user_id"]','input[name="member_id"]','input[type="text"]']
        pw_candidates=['input[name="password"]','input[name="passwd"]','input[name="userpw"]','input[type="password"]']
        id_el=next((page.locator(s).first for s in id_candidates if page.locator(s).count()),None)
        pw_el=next((page.locator(s).first for s in pw_candidates if page.locator(s).count()),None)
        if not id_el or not pw_el: raise RuntimeError('매크로마트 로그인 입력창을 찾지 못했습니다.')
        if not settings.macromart_id or not settings.macromart_password: raise RuntimeError('MACROMART_ID / MACROMART_PASSWORD가 설정되지 않았습니다.')
        id_el.fill(settings.macromart_id); pw_el.fill(settings.macromart_password)
        for s in ['button[type="submit"]','input[type="submit"]','button:has-text("로그인")','a:has-text("로그인")']:
            if page.locator(s).count():
                page.locator(s).first.click()
                try: page.wait_for_load_state('domcontentloaded')
                except Exception: pass
                break
        page.wait_for_timeout(1000); return page

    @staticmethod
    def _is_product_url(url:str)->bool:
        p=urlparse(url); path=p.path.lower(); q=parse_qs(p.query)
        return (path.endswith('/product/detail.html') and bool(q.get('product_no'))) or ('/product/' in path and ('detail' in path or 'product_no' in q)) or any(k in q for k in ('product_no','goods_no','item_no','prd_no'))

    def _collect_from_current_page(self,page:Page,seen:set[str])->list[str]:
        found=[]
        for el in page.locator('a[href]').all():
            try:
                href=(el.get_attribute('href') or '').strip()
                if not href or href.lower().startswith(('javascript:','#','mailto:')): continue
                u=urljoin(page.url,href).split('#',1)[0]
                if u.startswith(settings.macromart_base_url) and self._is_product_url(u):
                    if u not in seen: seen.add(u); found.append(u)
            except Exception: pass
        return found

    def _category_urls(self,page:Page)->list[str]:
        out=[]; seen=set()
        for el in page.locator('a[href]').all():
            try:
                href=(el.get_attribute('href') or '').strip()
                if not href or href.lower().startswith(('javascript:','#','mailto:')): continue
                u=urljoin(page.url,href).split('#',1)[0]
                if u.startswith(settings.macromart_base_url) and '/category/' in urlparse(u).path.lower() and u not in seen:
                    seen.add(u); out.append(u)
            except Exception: pass
        return out

    def product_links(self,page:Page,limit:int=100)->list[str]:
        seen=set(); out=self._collect_from_current_page(page,seen)
        for cat in self._category_urls(page)[:100]:
            try:
                page.goto(cat,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(400)
                out.extend(self._collect_from_current_page(page,seen))
                if len(out)>=limit: return out[:limit]
            except Exception: pass
        return out[:limit]

    def _structured_price(self,page:Page)->int:
        for sel in ['meta[itemprop="price"]','meta[property="product:price:amount"]','meta[property="og:price:amount"]']:
            if page.locator(sel).count():
                for i in range(min(page.locator(sel).count(),5)):
                    try:
                        n=money(page.locator(sel).nth(i).get_attribute('content') or '')
                        if n: return n
                    except Exception: pass
        for script in page.locator('script[type="application/ld+json"]').all():
            try:
                data=json.loads(script.inner_text()); stack=data if isinstance(data,list) else [data]
                while stack:
                    item=stack.pop()
                    if isinstance(item,dict):
                        for key in ('price','lowPrice'):
                            n=money(str(item.get(key,'')))
                            if n: return n
                        offers=item.get('offers')
                        if offers: stack.extend(offers if isinstance(offers,list) else [offers])
                        stack.extend(v for v in item.values() if isinstance(v,dict))
                    elif isinstance(item,list): stack.extend(item)
            except Exception: pass
        for sel in ['[itemprop="price"]','#span_product_price_text','#span_product_price','.xans-product-detail .price','.xans-product-detail .prdPrice','.sale_price','.goods_price','.product-price']:
            if page.locator(sel).count():
                try:
                    loc=page.locator(sel).first; n=money(loc.get_attribute('content') or loc.inner_text())
                    if n: return n
                except Exception: pass
        return 0

    def detail(self,page:Page,url:str)->dict[str,Any]:
        page.goto(url,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(300)
        name=''
        for s in ['[itemprop="name"]','h1','.prdName','.product-name','.goods_name','.item-name']:
            if page.locator(s).count():
                try:
                    name=page.locator(s).first.get_attribute('content') or page.locator(s).first.inner_text().strip()
                    if name: break
                except Exception: pass
        if not name:
            try: name=page.title().strip()
            except Exception: name=''
        price=self._structured_price(page); body=page.locator('body').inner_text()
        if not name or name.strip().lower() in GENERIC_NAMES or price<=0:
            return {'url':url,'error':f'실제 상품이 아닌 페이지: name={name!r}, price={price}'}
        soldout=price==1 or any(t in body for t in ('품절','일시품절','판매중지'))
        stock=0 if soldout else 1
        for sel in ['meta[itemprop="inventoryLevel"]','[itemprop="inventoryLevel"]','.stock','[class*="stock"]','[id*="stock"]']:
            if page.locator(sel).count():
                try:
                    raw=page.locator(sel).first.get_attribute('content') or page.locator(sel).first.inner_text(); stock=money(raw); break
                except Exception: pass
        rep=''
        if page.locator('meta[property="og:image"]').count(): rep=page.locator('meta[property="og:image"]').get_attribute('content') or ''
        if not rep:
            for s in ['.product-image img','.prdImg img','.goods_img img']:
                if page.locator(s).count():
                    try:
                        rep=urljoin(url,page.locator(s).first.get_attribute('src') or '')
                        if rep: break
                    except Exception: pass
        detail_html=''
        for s in ['#prdDetail','.detail','.product-detail','.prdDetail','[class*="detail"]']:
            if page.locator(s).count():
                try:
                    detail_html=page.locator(s).first.inner_html()
                    if detail_html: break
                except Exception: pass
        if not detail_html: detail_html=f'<p>{name}</p>'
        category=[]
        for s in ['.breadcrumb a','.location a','.category a','[class*="breadcrumb"] a']:
            if page.locator(s).count():
                try:
                    category=[x.strip() for x in page.locator(s).all_inner_texts() if x.strip()]
                    if category: break
                except Exception: pass
        return {'url':url,'name':name,'source_price':price,'source_stock':stock,'representative_image':rep,'detail_html':detail_html,'category_path':' > '.join(category)}

    def collect(self,page:Page,limit:int=100)->list[dict[str,Any]]:
        urls=self.product_links(page,limit); ARTIFACTS.mkdir(exist_ok=True)
        try: (ARTIFACTS/'macromart_product_urls.txt').write_text('\n'.join(urls),encoding='utf-8')
        except Exception: pass
        return [self.detail(page,u) for u in urls]

    def crawl(self,limit:int=100)->list[dict[str,Any]]:
        ARTIFACTS.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=settings.macromart_headless); page=browser.new_page(viewport={'width':1440,'height':1000})
            self.login(page); page.screenshot(path=str(ARTIFACTS/'macromart_after_login.png'),full_page=True)
            results=self.collect(page,limit); browser.close(); return results
