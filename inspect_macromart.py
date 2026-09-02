import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.crawlers.macromart import MacroMartCrawler, ARTIFACTS
from app.settings import settings

def main():
    if not settings.macromart_id or not settings.macromart_password:
        raise SystemExit("먼저 .env에 MACROMART_ID / MACROMART_PASSWORD를 넣으세요.")

    ARTIFACTS.mkdir(exist_ok=True)
    crawler = MacroMartCrawler()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.macromart_headless)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        crawler.login(page)

        page.screenshot(path=str(ARTIFACTS / "macromart_login.png"), full_page=True)
        (ARTIFACTS / "macromart_products.html").write_text(page.content(), encoding="utf-8")

        inputs = []
        for i in range(page.locator("input").count()):
            el = page.locator("input").nth(i)
            inputs.append({
                "index": i,
                "type": el.get_attribute("type"),
                "name": el.get_attribute("name"),
                "id": el.get_attribute("id"),
                "placeholder": el.get_attribute("placeholder"),
            })

        buttons = []
        for i in range(page.locator("button").count()):
            el = page.locator("button").nth(i)
            try:
                buttons.append({
                    "index": i,
                    "text": el.inner_text(),
                    "id": el.get_attribute("id"),
                    "class": el.get_attribute("class"),
                })
            except Exception:
                pass

        links = []
        for i in range(min(page.locator("a").count(), 1000)):
            el = page.locator("a").nth(i)
            try:
                links.append({
                    "index": i,
                    "text": el.inner_text().strip(),
                    "href": el.get_attribute("href"),
                })
            except Exception:
                pass

        (ARTIFACTS / "macromart_forms.json").write_text(
            json.dumps({"inputs": inputs, "buttons": buttons}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (ARTIFACTS / "macromart_links.json").write_text(
            json.dumps(links, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("로그인 후 URL:", page.url)
        print("링크 수:", len(links))
        print("결과:", ARTIFACTS.resolve())
        browser.close()

if __name__ == "__main__":
    main()
