from pathlib import Path
from typing import Any
from urllib.parse import urljoin
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
        id_candidates = ['input[name="id"]','input[name="userid"]','input[name="user_id"]','input[name="member_id"]','input[type="text"]']
        pw_candidates = ['input[name="password"]','input[name="passwd"]','input[name="userpw"]','input[type="password"]']
        id_el = next((page.locator(s).first for s in id_candidates if page.locator(s).count()), None)
        pw_el = next((page.locator(s).first for s in pw_candidates if page.locator(s).count()), None)
        if not id_el or not pw_el:
            raise RuntimeError('매크로마트 로그인 입력창을 찾지 못했습니다. inspect_macromart.py 결과를 확인하세요.')
        if not settings.macromart_id or not settings.macromart_password:
            raise RuntimeError('MACROMART_ID / MACROMART_PASSWORD가 설정되지 않았습니다.')
        id_el.fill(settings.macromart_id); pw_el.fill(settings.macromart_password)
        for s in ['button[type="submit"]','input[type="submit"]','button:has-text("로그인")','a:has-text("로그인")']:
            if page.locator(s).count():
                page.locator(s).first.click(); page.wait_for_load_state('domcontentloaded'); break
        page.wait_for_timeout(700)
        return page

    def product_links(self, page: Page, limit: int = 100) -> list[str]:
        out=[]; seen=set()
        for el in page.locator('a[href]').all():
            try:
                href=el.get_attribute('href') or ''; text=el.inner_text().strip()
                if not text or href.lower().startswith(('javascript:','#','mailto:')): continue
                url=urljoin(settings.macromart_base_url,href); key=url.lower()
                if any(k in key for k in ('product','goods','item','detail','view')) and key not in seen:
                    seen.add(key); out.append(url)
                    if len(out)>=limit: break
            except Exception: continue
        return out

    def detail(self, page: Page, url: str) -> dict[str, Any]:
        page.goto(url, wait_until='domcontentloaded', timeout=60000); page.wait_for_timeout(250)
        name=''
        for s in ['h1','.prdName','.product-name','.goods_name','.item-name','title']:
            if page.locator(s).count():
                try:
                    name=page.locator(s).first.inner_text().strip()
                    if name: break
                except Exception: pass
        body=page.locator('body').inner_text(); price=0
        for s in ['.sale_price','.price','.goods_price','.product-price','[class*="price"]','[id*="price"]']:
            if page.locator(s).count():
                try:
                    price=money(page.locator(s).first.inner_text())
                    if price: break
                except Exception: pass
        if not price:
            candidates=[money(x) for x in re.findall(r'[^\n]{0,30}\d{1,3}(?:,\d{3})+[^\n]{0,30}',body)]
            price=next((p for p in candidates if p>0),0)
        soldout = price == 1 or any(t in body for t in ('품절','일시품절','판매중지'))
        stock = 0 if soldout else 1
        rep=''
        if page.locator('meta[property="og:image"]').count(): rep=page.locator('meta[property="og:image"]').get_attribute('content') or ''
        if not rep:
            for s in ['.product-image img','.prdImg img','.goods_img img','img']:
                if page.locator(s).count():
                    rep=page.locator(s).first.get_attribute('src') or ''
                    if rep: rep=urljoin(url,rep); break
        detail_html=''
        for s in ['.detail','.product-detail','.prdDetail','#detail','[class*="detail"]']:
            if page.locator(s).count():
                try:
                    detail_html=page.locator(s).first.inner_html()
                    if detail_html: break
                except Exception: pass
        if not detail_html: detail_html='<p>'+ (name or '상품') +'</p>'
        category=[]
        for s in ['.breadcrumb a','.location a','.category a','[class*="breadcrumb"] a']:
            if page.locator(s).count():
                try:
                    category=[x.strip() for x in page.locator(s).all_inner_texts() if x.strip()]
                    if category: break
                except Exception: pass
        return {'url':url,'name':name or '미상 상품','source_price':price,'source_stock':stock,'representative_image':rep,'detail_html':detail_html,'category_path':' > '.join(category)}

    def collect(self,page:Page,limit:int=100)->list[dict[str,Any]]:
        results=[]
        for url in self.product_links(page,limit):
            try: results.append(self.detail(page,url))
            except Exception as exc: results.append({'url':url,'error':str(exc)})
        return results

    def crawl(self, limit:int=100)->list[dict[str,Any]]:
        ARTIFACTS.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=settings.macromart_headless)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            self.login(page)
            page.screenshot(path=str(ARTIFACTS/'macromart_after_login.png'),full_page=True)
            results=self.collect(page,limit=limit)
            browser.close(); return results
