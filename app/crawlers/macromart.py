from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs
import json
import re
from collections import deque
from playwright.sync_api import sync_playwright, Page
from ..settings import settings

ARTIFACTS = Path('artifacts')
PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?:\s*원)?')
PRODUCT_NO_RE = re.compile(r'(?:product_no|goods_no|item_no|prd_no)\s*["\'=:\s]+(\d+)', re.I)
PRODUCT_DETAIL_RE = re.compile(r'/product/(?:[^\s"\'<>]+/)?detail\.html\?[^\s"\'<>]*?(?:product_no|goods_no|item_no|prd_no)=(\d+)', re.I)

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
        page.wait_for_timeout(1200); return page

    @staticmethod
    def _is_product_url(url:str)->bool:
        p=urlparse(url); path=p.path.lower(); q=parse_qs(p.query)
        return (path.endswith('/product/detail.html') and any(q.get(k) for k in ('product_no','goods_no','item_no','prd_no'))) or ('/product/' in path and 'detail' in path and any(q.get(k) for k in ('product_no','goods_no','item_no','prd_no')))

    def _extract_product_urls_from_source(self,page:Page,seen:set[str])->list[str]:
        found=[]
        try:
            html=page.content()
            for m in PRODUCT_DETAIL_RE.finditer(html):
                u=urljoin(page.url,m.group(0)).split('#',1)[0]
                if u.startswith(settings.macromart_base_url) and u not in seen: seen.add(u); found.append(u)
            for m in PRODUCT_NO_RE.finditer(html):
                no=m.group(1); u=urljoin(settings.macromart_base_url,f'/product/detail.html?product_no={no}')
                if u not in seen: seen.add(u); found.append(u)
            for attr in page.locator('[data-product-no], [data-product-no-id], [data-i-product-no]').all():
                for a in ('data-product-no','data-product-no-id','data-i-product-no'):
                    no=(attr.get_attribute(a) or '').strip()
                    if no.isdigit():
                        u=urljoin(settings.macromart_base_url,f'/product/detail.html?product_no={no}')
                        if u not in seen: seen.add(u); found.append(u)
        except Exception: pass
        return found

    def _collect_from_current_page(self,page:Page,seen:set[str])->list[str]:
        found=[]
        try:
            for el in page.locator('a[href]').all():
                try:
                    href=(el.get_attribute('href') or '').strip()
                    if not href or href.lower().startswith(('javascript:','#','mailto:')): continue
                    u=urljoin(page.url,href).split('#',1)[0]
                    if u.startswith(settings.macromart_base_url) and self._is_product_url(u) and u not in seen:
                        seen.add(u); found.append(u)
                except Exception: pass
        except Exception: pass
        found.extend(self._extract_product_urls_from_source(page,seen))
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
        seen=set(); out=self._collect_from_current_page(page,seen); queue=deque(self._category_urls(page)); queued=set(queue)
        while queue and len(out)<limit:
            cat=queue.popleft()
            try:
                page.goto(cat,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(900)
                out.extend(self._collect_from_current_page(page,seen))
                if len(out)>=limit: break
                for u in self._category_urls(page):
                    if u not in queued: queued.add(u); queue.append(u)
                for el in page.locator('a[href]').all():
                    try:
                        txt=(el.inner_text() or '').strip(); href=(el.get_attribute('href') or '').strip()
                        if href and txt in {'2','3','4','5','6','7','8','9','10','다음','Next','›','>'}:
                            u=urljoin(page.url,href).split('#',1)[0]
                            if u.startswith(settings.macromart_base_url) and u not in queued: queued.add(u); queue.append(u)
                    except Exception: pass
            except Exception: continue
        try:
            ARTIFACTS.mkdir(exist_ok=True)
            (ARTIFACTS/'macromart_product_urls.txt').write_text('\n'.join(out[:limit]),encoding='utf-8')
            (ARTIFACTS/'macromart_discovery_debug.json').write_text(json.dumps({'count':len(out),'urls':out[:limit],'last_page':page.url},ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception: pass
        return out[:limit]

    @staticmethod
    def _structured_price(page:Page)->int:
        for sel in ['meta[itemprop="price"]','meta[property="product:price:amount"]','meta[property="og:price:amount"]','[itemprop="price"]']:
            try:
                loc=page.locator(sel)
                for i in range(min(loc.count(),10)):
                    el=loc.nth(i); val=el.get_attribute('content') or el.inner_text() or ''
                    n=money(val)
                    if n: return n
            except Exception: pass
        for script in page.locator('script[type="application/ld+json"]').all():
            try:
                data=json.loads(script.inner_text()); stack=data if isinstance(data,list) else [data]
                while stack:
                    x=stack.pop()
                    if isinstance(x,dict):
                        for k in ('price','lowPrice'):
                            n=money(str(x.get(k,'')))
                            if n: return n
                        offers=x.get('offers')
                        if offers: stack.extend(offers if isinstance(offers,list) else [offers])
                        stack.extend(v for v in x.values() if isinstance(v,dict))
                    elif isinstance(x,list): stack.extend(x)
            except Exception: pass
        for sel in ['#span_product_price_text','#span_product_price','.xans-product-detail .price','.xans-product-detail .prdPrice','.sale_price','.goods_price','.product-price']:
            try:
                if page.locator(sel).count():
                    n=money(page.locator(sel).first.inner_text())
                    if n: return n
            except Exception: pass
        return 0

    def detail(self,page:Page,url:str)->dict[str,Any]:
        page.goto(url,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(500)
        name=''
        for s in ['[itemprop="name"]','h1','.prdName','.product-name','.goods_name','.item-name','#span_product_name']:
            if page.locator(s).count():
                try:
                    el=page.locator(s).first; name=el.get_attribute('content') or el.inner_text().strip()
                    if name: break
                except Exception: pass
        if not name:
            try: name=page.title().strip()
            except Exception: name=''
        price=self._structured_price(page); body=page.locator('body').inner_text()
        if not name or name.strip().lower() in {'카페24','cafe24','상품','상품명','미상 상품'} or price<=0:
            return {'url':url,'error':f'실제 상품이 아닌 페이지: name={name!r}, price={price}'}
        soldout=price==1 or any(t in body for t in ('품절','일시품절','판매중지')); stock=0 if soldout else 1
        rep=''
        try:
            if page.locator('meta[property="og:image"]').count(): rep=page.locator('meta[property="og:image"]').get_attribute('content') or ''
            if not rep and page.locator('.product-image img,.prdImg img,.goods_img img').count(): rep=urljoin(url,page.locator('.product-image img,.prdImg img,.goods_img img').first.get_attribute('src') or '')
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
        results=[]
        for url in self.product_links(page,limit):
            try: results.append(self.detail(page,url))
            except Exception as exc: results.append({'url':url,'error':str(exc)})
        return results

    def crawl(self,limit:int=100)->list[dict[str,Any]]:
        ARTIFACTS.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=settings.macromart_headless)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            self.login(page); page.screenshot(path=str(ARTIFACTS/'macromart_after_login.png'),full_page=True)
            results=self.collect(page,limit); browser.close(); return results
