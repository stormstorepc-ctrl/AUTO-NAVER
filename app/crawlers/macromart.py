from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs
import json
import re
from playwright.sync_api import sync_playwright, Page
from ..settings import settings

ARTIFACTS = Path('artifacts')
PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?:\s*원)?')

def money(text: str) -> int:
    m = PRICE_RE.search(text or '')
    return int(m.group(1).replace(',', '')) if m else 0

class MacroMartCrawler:
    def login(self, page: Page) -> Page:
        page.goto(settings.macromart_start_url, wait_until='domcontentloaded', timeout=60000)
        id_candidates=['input[name="id"]','input[name="userid"]','input[name="user_id"]','input[name="member_id"]','input[type="text"]']
        pw_candidates=['input[name="password"]','input[name="passwd"]','input[name="userpw"]','input[type="password"]']
        id_el=next((page.locator(s).first for s in id_candidates if page.locator(s).count()),None)
        pw_el=next((page.locator(s).first for s in pw_candidates if page.locator(s).count()),None)
        if not id_el or not pw_el: raise RuntimeError('매크로마트 로그인 입력창을 찾지 못했습니다.')
        if not settings.macromart_id or not settings.macromart_password: raise RuntimeError('MACROMART_ID / MACROMART_PASSWORD가 설정되지 않았습니다.')
        id_el.fill(settings.macromart_id); pw_el.fill(settings.macromart_password)
        for s in ['button[type="submit"]','input[type="submit"]','button:has-text("로그인")','a:has-text("로그인")']:
            if page.locator(s).count():
                page.locator(s).first.click(); page.wait_for_load_state('domcontentloaded'); break
        page.wait_for_timeout(1000); return page

    @staticmethod
    def _is_product_url(url: str) -> bool:
        p=urlparse(url); path=p.path.lower(); q=parse_qs(p.query)
        return (path.endswith('/product/detail.html') and bool(q.get('product_no'))) or ('/product/' in path and ('detail' in path or 'product_no' in q)) or any(k in q for k in ('product_no','goods_no','item_no','prd_no'))

    def _collect_from_current_page(self,page:Page,seen:set[str])->list[str]:
        found=[]
        for el in page.locator('a[href]').all():
            try:
                href=(el.get_attribute('href') or '').strip()
                if not href or href.lower().startswith(('javascript:','#','mailto:')): continue
                u=urljoin(page.url,href).split('#',1)[0]
                if u.startswith(settings.macromart_base_url) and self._is_product_url(u) and u not in seen:
                    seen.add(u); found.append(u)
            except Exception: pass
        return found

    def product_links(self,page:Page,limit:int=100)->list[str]:
        seen=set(); out=[]
        out.extend(self._collect_from_current_page(page,seen))
        category_urls=[]
        for el in page.locator('a[href]').all():
            try:
                href=(el.get_attribute('href') or '').strip()
                if href and not href.lower().startswith(('javascript:','#','mailto:')):
                    u=urljoin(page.url,href).split('#',1)[0]
                    if u.startswith(settings.macromart_base_url) and '/category/' in urlparse(u).path.lower() and u not in category_urls: category_urls.append(u)
            except Exception: pass
        for cat in category_urls[:80]:
            try:
                page.goto(cat,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(300)
                out.extend(self._collect_from_current_page(page,seen))
                if len(out)>=limit: return out[:limit]
                for _ in range(8):
                    nxt=None
                    for el in page.locator('a[href]').all():
                        try:
                            txt=(el.inner_text() or '').strip(); href=(el.get_attribute('href') or '').strip()
                            if href and txt in {'2','3','4','5','다음','Next','›','>'}:
                                u=urljoin(page.url,href)
                                if u.startswith(settings.macromart_base_url) and u != page.url: nxt=u; break
                        except Exception: pass
                    if not nxt: break
                    page.goto(nxt,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(250)
                    before=len(out); out.extend(self._collect_from_current_page(page,seen))
                    if len(out)==before or len(out)>=limit: break
            except Exception: pass
        try:
            html=page.content()
            for m in re.finditer(r'(?:product_no|goods_no|item_no|prd_no)[^\d]{0,20}(\d+)',html,re.I):
                u=urljoin(settings.macromart_base_url,f'/product/detail.html?product_no={m.group(1)}')
                if u not in seen: seen.add(u); out.append(u)
                if len(out)>=limit: break
        except Exception: pass
        return out[:limit]

    @staticmethod
    def _structured_price(page: Page) -> int:
        for selector in ['meta[itemprop="price"]','meta[property="product:price:amount"]','meta[property="og:price:amount"]']:
            if page.locator(selector).count():
                for i in range(min(page.locator(selector).count(),5)):
                    try:
                        v=page.locator(selector).nth(i).get_attribute('content') or ''
                        n=money(v)
                        if n: return n
                    except Exception: pass
        for script in page.locator('script[type="application/ld+json"]').all():
            try:
                raw=script.inner_text()
                data=json.loads(raw)
                stack=data if isinstance(data,list) else [data]
                while stack:
                    item=stack.pop()
                    if isinstance(item,dict):
                        offers=item.get('offers')
                        if offers: stack.extend(offers if isinstance(offers,list) else [offers])
                        for key in ('price','lowPrice'):
                            n=money(str(item.get(key,'')))
                            if n: return n
                        stack.extend(v for v in item.values() if isinstance(v,dict))
            except Exception: pass
        return 0

    def detail(self,page:Page,url:str)->dict[str,Any]:
        page.goto(url,wait_until='domcontentloaded',timeout=60000); page.wait_for_timeout(300)
        name=''
        for s in ['h1','.prdName','.product-name','.goods_name','.item-name']:
            if page.locator(s).count():
                try:
                    name=page.locator(s).first.inner_text().strip()
                    if name: break
                except Exception: pass
        if not name: name=page.title().strip()
        price=self._structured_price(page)
        if not price:
            for s in ['#span_product_price_text','#span_product_price','.xans-product-detail .price','.xans-product-detail .prdPrice','.sale_price','.goods_price','.product-price']:
                if page.locator(s).count():
                    try:
                        n=money(page.locator(s).first.inner_text())
                        if n: price=n; break
                    except Exception: pass
        body=page.locator('body').inner_text()
        soldout=price==1 or any(t in body for t in ('품절','일시품절','판매중지'))
        stock=0 if soldout else 1
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
        for s in ['.detail','.product-detail','.prdDetail','#detail','[class*="detail"]']:
            if page.locator(s).count():
                try:
                    detail_html=page.locator(s).first.inner_html()
                    if detail_html: break
                except Exception: pass
        if not detail_html: detail_html='<p>'+name+'</p>'
        category=[]
        for s in ['.breadcrumb a','.location a','.category a','[class*="breadcrumb"] a']:
            if page.locator(s).count():
                try:
                    category=[x.strip() for x in page.locator(s).all_inner_texts() if x.strip()]
                    if category: break
                except Exception: pass
        return {'url':url,'name':name or '미상 상품','source_price':price,'source_stock':stock,'representative_image':rep,'detail_html':detail_html,'category_path':' > '.join(category)}

    def collect(self,page:Page,limit:int=100)->list[dict[str,Any]]:
        urls=self.product_links(page,limit); ARTIFACTS.mkdir(exist_ok=True)
        try: (ARTIFACTS/'macromart_product_urls.txt').write_text('\n'.join(urls),encoding='utf-8')
        except Exception: pass
        results=[]
        for url in urls:
            try: results.append(self.detail(page,url))
            except Exception as exc: results.append({'url':url,'error':str(exc)})
        return results

    def crawl(self,limit:int=100)->list[dict[str,Any]]:
        ARTIFACTS.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=settings.macromart_headless); page=browser.new_page(viewport={'width':1440,'height':1000})
            self.login(page); page.screenshot(path=str(ARTIFACTS/'macromart_after_login.png'),full_page=True)
            results=self.collect(page,limit); browser.close(); return results
