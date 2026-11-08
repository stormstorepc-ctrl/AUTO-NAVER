// Injected into the tab the user clicked on (activeTab). Reads what is already on screen; sends nothing itself.
// The value of the last expression is returned to the popup.
(() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const textOf = (el) => clean(el && (el.innerText || el.textContent));
  const abs = (u) => {
    if (!u || /^(data|blob|javascript):/i.test(u)) return "";
    try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : ""; } catch (e) { return ""; }
  };
  const out = {
    schema: 1, status: "ok", url: location.href, title: "", price_texts: [], selected_options: [],
    images: [], detail_images: [], other_images: [], notes: [], captured_at: new Date().toISOString(),
  };
  const host = location.hostname;

  if (/(^|\.)login\.(taobao|tmall)\.com$/.test(host) || document.querySelector("input[type=password]")) {
    out.status = "login_required"; return out;
  }
  if (document.querySelector('[id*="nocaptcha" i],[class*="nocaptcha" i],[class*="baxia-dialog" i],[id*="baxia-dialog" i]')) {
    out.status = "captcha"; return out;
  }

  // Title: the page's own product heading first, then og:title, then the tab title without the site suffix.
  const heading = document.querySelector('[class*="mainTitle" i], [class*="ItemTitle" i] h1, h1');
  const og = document.querySelector('meta[property="og:title"]');
  out.title = textOf(heading) || clean(og && og.content) ||
    clean(document.title.replace(/[-–—_|].*(淘宝|天猫|taobao|tmall).*$/i, ""));

  // Prices: the smallest element with a class mentioning "price" whose text is a complete amount
  // (currency mark, decimals or 元). A price split into "¥" / "39" / ".90" spans is read from their parent.
  const complete = (t) => /[¥￥]\s*\d|\d\.\d|\d\s*元/.test(t);
  const priceEls = [...document.querySelectorAll('[class*="price" i]')]
    .filter((el) => { const t = textOf(el); return t && t.length <= 40 && complete(t); });
  const seenPrice = new Set();
  for (const el of priceEls) {
    if (priceEls.some((o) => o !== el && el.contains(o))) continue; // a smaller complete price is inside
    let t = textOf(el);
    // A struck-through or "origin" price is marked so the local app does not suggest it as the purchase price.
    if (el.closest('del,s,[class*="origin" i],[class*="original" i],[class*="lineThrough" i]') && !/原价|划线价/.test(t)) t = "原价 " + t;
    if (!seenPrice.has(t)) { seenPrice.add(t); out.price_texts.push(t); }
    if (out.price_texts.length >= 20) break;
  }

  // Selected options: checked/selected items inside a SKU area.
  const seenOpt = new Set();
  const selectedSel = '[aria-checked="true"],[aria-selected="true"],[class*="isSelected" i],[class*="selected" i]';
  for (const el of document.querySelectorAll(selectedSel)) {
    if (!el.closest('[class*="sku" i],[id*="sku" i]')) continue;
    if (/unselect|disabled|notselected/i.test(el.getAttribute("class") || "")) continue;
    if (el.querySelector(selectedSel)) continue;
    const t = textOf(el) || clean(el.getAttribute("title")) || clean(el.getAttribute("aria-label"));
    if (t && t.length <= 80 && !seenOpt.has(t)) { seenOpt.add(t); out.selected_options.push(t); }
  }

  // Images. Gallery and description areas are taken as product images; anything else (recommendations,
  // shop banners) goes to other_images, which the review screen leaves unticked.
  const GALLERY = '[class*="gallery" i],[class*="mainPic" i],[class*="thumb" i],[id*="J_UlThumb" i],[class*="PicGallery" i]';
  const DESC = '[id*="desc" i],[class*="desc" i],[class*="detail" i]';
  const RECOMMEND = '[class*="recommend" i],[class*="similar" i],[class*="guess" i],[class*="shopRec" i]';
  const LAZY_ATTRS = ["data-src", "data-ks-lazyload", "data-lazyload", "data-original"];
  const seenImg = new Set();
  let pending = 0, hasGallery = !!document.querySelector(GALLERY);
  for (const img of document.images) {
    const lazy = LAZY_ATTRS.map((a) => abs(img.getAttribute(a))).find(Boolean);
    const w = img.naturalWidth || 0, h = img.naturalHeight || 0;
    const loaded = img.complete && w > 0;
    const placeholder = loaded && (w < 150 || h < 150);
    let url = "";
    const srcset = img.getAttribute("srcset") || img.getAttribute("data-srcset");
    if (srcset) {
      const best = srcset.split(",").map((p) => p.trim().split(/\s+/))
        .sort((a, b) => (parseFloat(b[1]) || 0) - (parseFloat(a[1]) || 0))[0];
      if (best) url = abs(best[0]);
    }
    if (lazy && (!loaded || placeholder)) { url = url || lazy; pending++; }   // real image not shown yet
    else if (!url) {
      if (placeholder) continue;                                               // icon or 1px tracker
      url = abs(img.currentSrc) || abs(img.getAttribute("src")) || lazy || "";
      if (!url || !loaded) continue;
    }
    if (!url || seenImg.has(url)) continue;
    seenImg.add(url);
    const inRecommend = img.closest(RECOMMEND);
    // Product images have their own limit, so a long recommendation list cannot crowd them out.
    const productCount = out.images.length + out.detail_images.length;
    if (!inRecommend && img.closest(DESC)) { if (productCount < 50) out.detail_images.push(url); }
    else if (!inRecommend && img.closest(GALLERY)) { if (productCount < 50) out.images.push(url); }
    else if (out.other_images.length < 20) out.other_images.push(url);
  }
  if (!hasGallery) out.notes.push("대표 이미지 영역을 찾지 못했습니다. 이미지는 '기타'로 표시되니 검토 화면에서 직접 고르세요.");
  if (pending) out.notes.push("아직 화면에 안 나온 이미지 " + pending + "개가 있습니다. 페이지 끝까지 내린 뒤 다시 가져오면 더 정확합니다.");
  if (!out.selected_options.length) out.notes.push("선택된 옵션을 찾지 못했습니다. 옵션이 있는 상품이면 옵션을 누른 뒤 다시 가져오세요.");
  if (!out.title && !out.price_texts.length) out.status = "no_product";
  return out;
})();
