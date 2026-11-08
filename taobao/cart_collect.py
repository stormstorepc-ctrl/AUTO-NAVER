"""
AUTO-NAVER - 타오바오 장바구니 상품 수집기 (천천히 모드)

- 내가 장바구니에 담아둔 상품들을 하나씩 천천히 열어서 상품명·가격·이미지 수집 + 한국어 번역
- 장바구니는 읽기만 함 (클릭/삭제/수량 변경 없음)
- 결과: output/날짜_cart/ 폴더
"""

import asyncio
import random
import sys
from datetime import datetime

from playwright.async_api import async_playwright

import taobao_collect as t

CART_URL = "https://cart.taobao.com/cart.htm"
SLOW_DELAY = (35, 75)      # 상품 사이 대기(초) - 천천히
MAX_ITEMS = 30             # 한 번에 최대 몇 개까지

# 장바구니는 내가 고른 상품이므로 가격/금지어 필터 끔
t.MIN_PRICE = 0
t.TITLE_BLACKLIST = []


CART_IDS_JS = r"""
() => {
  const idOf = (href) => {
    const m = href.match(/(item\.taobao\.com\/item\.htm|detail\.tmall\.com\/item\.htm)[^#]*[?&]id=(\d+)/);
    return m ? m[2] : null;
  };
  const anchors = [...document.querySelectorAll('a[href]')];
  // 1) 장바구니 행: 가까운 조상에 체크박스가 있고, 그 조상 안 상품이 1~2개뿐인 링크
  const cart = [];
  for (const a of anchors) {
    const id = idOf(a.href); if (!id) continue;
    let el = a, ok = false;
    for (let i = 0; i < 12; i++) {
      el = el.parentElement; if (!el) break;
      if (el.querySelector('input[type=checkbox],[role=checkbox],[class*="heckbox"]')) {
        const inner = new Set([...el.querySelectorAll('a[href]')].map(x => idOf(x.href)).filter(Boolean));
        ok = inner.size <= 2; break;
      }
    }
    if (ok && !cart.includes(id)) cart.push(id);
  }
  // 2) 보조: "猜你喜欢"(추천) 제목보다 위에 있는 링크만
  let rec = null;
  for (const el of document.querySelectorAll('h1,h2,h3,h4,div,span,p')) {
    if (el.children.length === 0 && /猜你喜欢|为你推荐|你可能还喜欢/.test(el.textContent || '')) { rec = el; break; }
  }
  const before = [];
  for (const a of anchors) {
    const id = idOf(a.href); if (!id) continue;
    if (rec && (rec.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
    if (!before.includes(id)) before.push(id);
  }
  return { cart, beforeRecommend: before };
}
"""


async def collect_cart_ids(page) -> list[str]:
    t.log("장바구니 열기")
    await page.goto(CART_URL, wait_until="domcontentloaded", timeout=60000)
    await t.human_pause(5, 8)
    if not await t.wait_if_captcha(page):
        return []
    if "login" in page.url:
        t.alert("로그인 화면으로 넘어갔습니다. 수집용 Chrome 창에서 로그인해 주세요.")
        if not await t.wait_if_captcha(page):
            return []
        await page.goto(CART_URL, wait_until="domcontentloaded", timeout=60000)
        await t.human_pause(5, 8)
    try:
        await page.wait_for_selector('a[href*="item.htm"]', timeout=30000)
    except Exception:
        t.log("장바구니에서 상품 링크가 30초 안에 나타나지 않음")
    # 장바구니가 길면 아래까지 천천히 스크롤해서 전부 불러오기
    for _ in range(12):
        await page.mouse.wheel(0, random.randint(500, 900))
        await t.human_pause(1.0, 2.0)

    ids = await page.evaluate(CART_IDS_JS)
    t.log(f"장바구니 상품 {len(ids['cart'])}개 발견 (체크박스 기준) / 추천상품 제외 기준 {len(ids['beforeRecommend'])}개")
    chosen = ids["cart"] or ids["beforeRecommend"]
    return chosen[:MAX_ITEMS]


async def main() -> int:
    out_dir = t.OUT_ROOT / (datetime.now().strftime("%Y-%m-%d") + "_cart")
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(t.CDP_URL)
        except Exception as e:
            t.alert(f"Chrome 연결 실패. start_chrome.bat 으로 Chrome을 먼저 켜주세요. ({e})")
            return 1

        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        items: list[dict] = []
        history = t.load_history()
        try:
            ids = await collect_cart_ids(page)
            (out_dir / "cart_page.html").write_text(await page.content(), encoding="utf-8")
            (out_dir / "cart_ids.txt").write_text("\n".join(ids), encoding="utf-8")
            if "--probe" in sys.argv:
                t.log(f"[확인 모드] 수집할 상품 {len(ids)}개: {', '.join(ids)}")
                return 0
            if not ids:
                (out_dir / "cart_page.html").write_text(await page.content(), encoding="utf-8")
                t.alert("장바구니에서 상품을 찾지 못했습니다. cart_page.html 을 확인하세요.")
                return 1

            for n, iid in enumerate(ids, 1):
                wait = random.uniform(*SLOW_DELAY)
                t.log(f"  {wait:.0f}초 쉬었다가 다음 상품 열기")
                await asyncio.sleep(wait)
                t.log(f"--- {n}/{len(ids)} ---")
                try:
                    item = await t.collect_item(page, iid, out_dir)
                except Exception as e:
                    t.log(f"  수집 오류: {e}")
                    item = None
                if item is None:
                    if await t.is_captcha(page):
                        break
                    continue
                item["title_ko"] = t.translate_ko(item["title_cn"])
                t.log(f"  번역: {item['title_ko'][:50]}")
                items.append(item)
                history.add(iid)
                t.save_results(items, out_dir)  # 중간 저장
                t.save_history(history)
        finally:
            await page.close()

    ok = sum(1 for it in items if not it["problems"])
    t.log(f"완료: {len(items)}개 수집 (문제 없음 {ok}개) → {out_dir}")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
