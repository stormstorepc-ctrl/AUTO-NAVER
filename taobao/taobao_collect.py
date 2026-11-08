"""
AUTO-NAVER 1단계 - 타오바오 생활용품 인기상품 수집기

- 내 PC에서 실행합니다.
- start_chrome.bat 으로 띄운 Chrome(타오바오 로그인 상태)에 연결해서 수집합니다.
- 결과: output/날짜/ 폴더에 products.json, products.csv, 상품별 이미지, 디버깅용 HTML

필요 패키지: pip install -r requirements.txt
번역: 구글 번역 무료 주소 사용 (API 키 불필요). 실패 시 중국어 원문 유지.
"""

import asyncio
import csv
import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from itertools import zip_longest
from urllib.parse import quote, urlparse, parse_qs

import requests
from playwright.async_api import async_playwright

# ===================== 설정 =====================
CDP_URL = "http://127.0.0.1:9222"           # start_chrome.bat 의 디버깅 포트
# 디자인 예쁜 조명·인테리어 소품 위주 검색어 (판매량순으로 각각 검색해서 섞음)
KEYWORDS = [
    "ins风 氛围灯",        # 무드등
    "设计感 台灯",         # 디자인 스탠드
    "北欧 家居摆件",       # 북유럽 인테리어 소품
    "设计感 花瓶",         # 디자인 화병
    "ins风 创意 家居好物", # 감성 인테리어 아이템
]
PER_KEYWORD = 6                              # 검색어마다 후보로 가져올 상품 수
TOP_N = 7                                    # 최종 수집할 상품 수
MIN_PRICE = 39.0                             # 이 가격(위안) 미만은 제외 (약 7,500원)
MAX_VISITS = 20                              # 조건 맞는 상품 찾으려고 최대 몇 개까지 열어볼지
TITLE_BLACKLIST = [                          # 상품명에 들어가면 제외할 단어
    "纸巾", "卫生纸", "抽纸", "湿巾", "剃须", "刮胡", "牙刷", "牙膏", "洗衣", "垃圾袋",
    "粘毛", "双面胶", "胶带", "抹布", "清洁剂", "洗洁精", "一次性", "保鲜膜",
]
MAX_IMAGES = 10                              # 상품당 대표 이미지 최대 개수
MIN_IMAGE_BYTES = 15000                      # 이보다 작은 이미지(아이콘·로고)는 버림
HISTORY_FILE = Path(__file__).parent / "history.json"  # 이미 수집한 상품은 다음 주에 다시 안 가져옴
DELAY_RANGE = (8, 20)                        # 상품 사이 랜덤 대기(초)
CAPTCHA_WAIT_SEC = 600                       # 캡차가 뜨면 사람이 풀 때까지 기다리는 최대 시간(10분)
OUT_ROOT = Path(__file__).parent / "output"
# =================================================

ITEM_LINK_RE = re.compile(r"(item\.taobao\.com/item\.htm|detail\.tmall\.com/item\.htm)")
CAPTCHA_MARKERS = ["nc_1_n1z", "baxia-dialog", "请按住滑块", "滑动验证", "punish", "x5secdata"]


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def alert(msg: str) -> None:
    """캡차/오류 시 알림 (Windows면 비프음)."""
    log(f"⚠️  {msg}")
    if sys.platform.startswith("win"):
        try:
            import winsound
            for _ in range(3):
                winsound.Beep(1000, 300)
        except Exception:
            pass


async def human_pause(a: float = 1.5, b: float = 4.0) -> None:
    await asyncio.sleep(random.uniform(a, b))


async def human_scroll(page, steps: int = 6) -> None:
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(400, 900))
        await human_pause(0.6, 1.6)


async def is_captcha(page) -> bool:
    url = page.url.lower()
    if "punish" in url or "login.taobao.com" in url:
        return True
    try:
        html = await page.content()
    except Exception:
        return False
    return any(m in html for m in CAPTCHA_MARKERS)


async def is_logged_out(page) -> bool:
    try:
        return await page.locator("text=亲，请登录").count() > 0
    except Exception:
        return False


async def ensure_login(page) -> bool:
    """로그인이 안 되어 있으면 알리고, 사용자가 이 Chrome 창에서 로그인할 때까지 대기."""
    if not await is_logged_out(page):
        return True
    try:
        await page.bring_to_front()
    except Exception:
        pass
    alert(f"이 수집용 Chrome 창에 타오바오 로그인이 안 되어 있습니다. 지금 이 창에서 로그인해 주세요. (최대 {CAPTCHA_WAIT_SEC}초 대기)")
    waited = 0
    while waited < CAPTCHA_WAIT_SEC:
        await asyncio.sleep(5)
        waited += 5
        try:
            if "login" in page.url:
                continue
            await page.goto(search_url(KEYWORDS[0]), wait_until="domcontentloaded", timeout=60000)
            await human_pause(3, 5)
        except Exception:
            continue
        if not await is_logged_out(page):
            log("로그인 확인. 계속 진행합니다.")
            return True
    alert("시간 안에 로그인되지 않아 중단합니다.")
    return False


async def wait_if_captcha(page) -> bool:
    """캡차/로그인 화면이면 알리고 사람이 해결할 때까지 대기. 해결되면 True."""
    if not await is_captcha(page):
        return True
    try:
        await page.bring_to_front()
    except Exception:
        pass
    alert(f"캡차 또는 로그인 화면 감지. Chrome에서 직접 풀어주세요. (최대 {CAPTCHA_WAIT_SEC}초 대기)")
    waited = 0
    last_beep = 0
    while waited < CAPTCHA_WAIT_SEC:
        await asyncio.sleep(5)
        waited += 5
        if waited - last_beep >= 60:  # 1분마다 다시 알림
            alert(f"아직 캡차 대기 중 ({waited}초 경과)")
            last_beep = waited
        if not await is_captcha(page):
            log("해결 확인. 계속 진행합니다.")
            await human_pause(2, 4)
            return True
    alert("시간 안에 해결되지 않아 중단합니다.")
    return False


def search_url(keyword: str) -> str:
    return f"https://s.taobao.com/search?q={quote(keyword)}&sort=sale-desc"  # 판매량순


def load_history() -> set[str]:
    try:
        return set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_history(ids: set[str]) -> None:
    HISTORY_FILE.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def item_id_from_url(url: str) -> str | None:
    if not ITEM_LINK_RE.search(url):
        return None
    ids = parse_qs(urlparse(url).query).get("id")
    return ids[0] if ids else None


async def collect_item_ids(page, keyword: str, skip: set[str]) -> list[str]:
    log(f"검색 페이지 열기: {keyword} (판매량순)")
    await page.goto(search_url(keyword), wait_until="domcontentloaded", timeout=60000)
    await human_pause(3, 6)
    if not await wait_if_captcha(page):
        return []
    if not await ensure_login(page):
        return []
    # "呀，不知道哪里出了问题 / 重试" 오류면 한 번 새로고침
    if await page.locator("text=不知道哪里出了问题").count() > 0:
        log("검색 결과 로딩 오류 → 새로고침")
        await page.reload(wait_until="domcontentloaded")
        await human_pause(4, 7)
    # 상품 카드가 그려질 때까지 최대 20초 대기
    try:
        await page.wait_for_selector('a[href*="item.htm"]', timeout=20000)
    except Exception:
        log("상품 링크가 20초 안에 나타나지 않음")
    await human_scroll(page, steps=5)

    cards = await page.eval_on_selector_all(
        "a[href]", "els => els.map(e => ({href: e.href, text: (e.innerText || '').slice(0, 400)}))")
    ids: list[str] = []
    found = cheap = banned = 0
    for c in cards:
        iid = item_id_from_url(c["href"])
        if not iid or iid in ids or iid in skip:
            continue
        found += 1
        text = c["text"]
        m = re.search(r"[¥￥]\s*(\d+)(?:\s*\.\s*(\d+))?", text)
        if m:  # 검색 결과에 가격이 보이면 여기서 미리 거름 (상세페이지 안 열어도 됨)
            card_price = float(m.group(1) + "." + (m.group(2) or "0"))
            if card_price < MIN_PRICE:
                cheap += 1
                continue
        if any(w in text for w in TITLE_BLACKLIST):
            banned += 1
            continue
        ids.append(iid)
    log(f"  상품 {found}개 중 저가 {cheap}개·금지어 {banned}개 제외 → 상위 {min(len(ids), PER_KEYWORD)}개 후보")
    return ids[:PER_KEYWORD]


EXTRACT_JS = r"""
() => {
  const pick = (sel) => { const el = document.querySelector(sel); return el ? (el.content || el.innerText || '').trim() : ''; };

  // 상품명
  let title = pick('meta[property="og:title"]') || pick('h1') ||
              document.title.replace(/[-–]\s*(淘宝网|tmall\.com天猫|天猫).*$/, '').trim();

  // 가격: class 에 price 가 들어간 요소 중 숫자 있는 첫 번째
  let price = '';
  for (const el of document.querySelectorAll('[class*="rice"]')) {
    const m = (el.innerText || '').match(/\d+(?:\.\d+)?/);
    if (m && el.offsetParent !== null) { price = m[0]; break; }
  }
  if (!price) {
    const m = document.body.innerText.match(/[¥￥]\s*(\d+(?:\.\d+)?)/);
    if (m) price = m[1];
  }

  // 판매량(참고용)
  const salesMatch = document.body.innerText.match(/(?:已售|月销|销量)\s*[:：]?\s*([\d.]+\s*[万+]*)/);

  // 이미지: alicdn 상품 이미지
  const imgs = [];
  for (const img of document.querySelectorAll('img')) {
    let src = img.getAttribute('src') || img.getAttribute('data-src') || '';
    if (!/alicdn\.com/.test(src)) continue;
    if (!/(imgextra|bao\/uploaded|\/i\d\/)/.test(src)) continue;
    if (src.startsWith('//')) src = 'https:' + src;
    src = src.replace(/_\d+x\d+.*$/, '').replace(/\.(jpg|png|webp)_.*$/, '.$1');
    if (!imgs.includes(src)) imgs.push(src);
  }
  return { title, price, sales: salesMatch ? salesMatch[1] : '', images: imgs };
}
"""


async def collect_item(page, item_id: str, out_dir: Path) -> dict | None:
    url = f"https://item.taobao.com/item.htm?id={item_id}"
    log(f"상품 열기: {item_id}")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await human_pause(3, 6)
    if not await wait_if_captcha(page):
        return None
    await human_scroll(page, steps=3)

    data = await page.evaluate(EXTRACT_JS)
    try:
        price = float(data["price"])
    except Exception:
        price = 0.0
    bad = next((w for w in TITLE_BLACKLIST if w in data["title"]), None)
    if bad or price < MIN_PRICE:
        why = f"금지어 '{bad}'" if bad else f"가격 ¥{data['price'] or '?'} < ¥{MIN_PRICE:g}"
        log(f"  제외: {data['title'][:30]} ({why})")
        return {"skipped": True, "item_id": item_id}
    item_dir = out_dir / item_id
    item_dir.mkdir(parents=True, exist_ok=True)

    # 디버깅용 HTML 저장 (수집 실패 시 원인 분석용)
    (item_dir / "page.html").write_text(await page.content(), encoding="utf-8")

    # 이미지 다운로드 (로그인된 브라우저 쿠키 사용)
    saved = []
    for src in data["images"]:
        if len(saved) >= MAX_IMAGES:
            break
        try:
            resp = await page.context.request.get(src, headers={"Referer": "https://item.taobao.com/"})
            if resp.ok:
                body = await resp.body()
                if len(body) < MIN_IMAGE_BYTES:
                    continue  # 아이콘·로고 등 작은 이미지 제외
                ext = ".png" if src.lower().endswith(".png") else ".jpg"
                path = item_dir / f"{len(saved) + 1:02d}{ext}"
                path.write_bytes(body)
                saved.append(str(path.relative_to(out_dir)))
        except Exception as e:
            log(f"  이미지 실패: {src} ({e})")
        await human_pause(0.3, 0.9)

    result = {
        "item_id": item_id,
        "url": page.url,
        "title_cn": data["title"],
        "price_cny": data["price"],
        "sales": data["sales"],
        "images": saved,
        "collected_at": datetime.now().isoformat(timespec="seconds"),
    }
    problems = [k for k in ("title_cn", "price_cny") if not result[k]]
    if not saved:
        problems.append("images")
    result["problems"] = problems
    log(f"  상품명: {result['title_cn'][:40]} | 가격: {result['price_cny']} | 이미지 {len(saved)}장"
        + (f" | ❌ 누락: {', '.join(problems)}" if problems else ""))
    return result


def translate_ko(text: str) -> str:
    """구글 번역 무료 주소로 중국어→한국어 번역 (API 키 불필요). 실패하면 빈 문자열."""
    if not text:
        return ""
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "zh-CN", "tl": "ko", "dt": "t", "q": text},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        r.raise_for_status()
        return "".join(part[0] for part in r.json()[0] if part and part[0]).strip()
    except Exception as e:
        log(f"  번역 실패(원문 유지): {e}")
        return ""


def save_results(items: list[dict], out_dir: Path) -> None:
    (out_dir / "products.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["item_id", "title_cn", "title_ko", "price_cny", "sales", "url", "images", "problems", "collected_at"]
    with open(out_dir / "products.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for it in items:
            row = {k: it.get(k, "") for k in fields}
            row["images"] = " | ".join(it.get("images", []))
            row["problems"] = ", ".join(it.get("problems", []))
            w.writerow(row)


async def main() -> int:
    out_dir = OUT_ROOT / datetime.now().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            alert(f"Chrome 연결 실패. start_chrome.bat 으로 Chrome을 먼저 켜주세요. ({e})")
            return 1

        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        items: list[dict] = []
        history = load_history()
        try:
            # 1) 검색어별 후보 모으기 (검색어끼리 번갈아 섞음)
            per_kw: list[list[str]] = []
            seen: set[str] = set(history)
            for k, kw in enumerate(KEYWORDS):
                ids = await collect_item_ids(page, kw, seen)
                if not ids and await is_captcha(page):
                    break
                seen.update(ids)
                per_kw.append(ids)
                if k < len(KEYWORDS) - 1:
                    await human_pause(4, 9)
            candidates = [x for group in zip_longest(*per_kw) for x in group if x]
            if not candidates:
                (out_dir / "search_page.html").write_text(await page.content(), encoding="utf-8")
                alert("검색 결과에서 상품을 찾지 못했습니다. output 폴더의 search_page.html 을 확인하세요.")
                return 1
            log(f"후보 {len(candidates)}개 → 조건(¥{MIN_PRICE:g} 이상, 금지어 제외) 맞는 {TOP_N}개 수집")

            # 2) 후보를 하나씩 열어서 조건 맞는 것만 수집
            for n, iid in enumerate(candidates[:MAX_VISITS], 1):
                if len(items) >= TOP_N:
                    break
                log(f"--- 후보 {n} / 수집 {len(items)}/{TOP_N} ---")
                try:
                    item = await collect_item(page, iid, out_dir)
                except Exception as e:
                    log(f"  수집 오류: {e}")
                    item = None
                if item is None:
                    if await is_captcha(page):
                        break
                    continue
                if not item.get("skipped"):
                    item["title_ko"] = translate_ko(item["title_cn"])
                    log(f"  번역: {item['title_ko'][:40]}")
                    items.append(item)
                    history.add(iid)
                    save_results(items, out_dir)  # 중간 저장
                    save_history(history)
                wait = random.uniform(*DELAY_RANGE)
                log(f"  다음 상품까지 {wait:.0f}초 대기")
                await asyncio.sleep(wait)
        finally:
            await page.close()

    ok = sum(1 for it in items if not it["problems"])
    log(f"완료: {len(items)}개 수집 (문제 없음 {ok}개) → {out_dir}")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
