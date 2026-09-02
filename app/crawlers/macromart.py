from pathlib import Path
from typing import Any
from playwright.sync_api import Page
from ..settings import settings

ARTIFACTS = Path('artifacts')

class MacroMartCrawler:
    def login(self, page: Page):
        page.goto(settings.macromart_start_url, wait_until='domcontentloaded')
        # 로그인 UI가 변경될 수 있으므로 여러 일반적인 selector를 순차 시도한다.
        id_candidates = ['input[name="id"]','input[name="userid"]','input[name="user_id"]','input[type="text"]']
        pw_candidates = ['input[name="password"]','input[name="passwd"]','input[type="password"]']
        id_el = next((page.locator(s).first for s in id_candidates if page.locator(s).count()), None)
        pw_el = next((page.locator(s).first for s in pw_candidates if page.locator(s).count()), None)
        if id_el and pw_el and settings.macromart_id:
            id_el.fill(settings.macromart_id)
            pw_el.fill(settings.macromart_password)
            for s in ['button[type="submit"]','input[type="submit"]','button:has-text("로그인")']:
                if page.locator(s).count():
                    page.locator(s).first.click()
                    page.wait_for_load_state('domcontentloaded')
                    break
        return page

    def collect(self, page: Page) -> list[dict[str, Any]]:
        # 실사이트 selector는 inspect_macromart.py 결과에 맞춰 추가 보정해야 한다.
        items = []
        for el in page.locator('a').all():
            try:
                text = el.inner_text().strip()
                href = el.get_attribute('href')
                if text and href and ('product' in href.lower() or 'goods' in href.lower()):
                    items.append({'name': text, 'url': href})
            except Exception:
                continue
        return items
