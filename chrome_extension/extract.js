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
    images: [], detail_images: [], notes: [], captured_at: new Date().toISOString(),
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

  // Prices: short texts inside elements whose class mentions "price". Raw text is kept; nothing is computed here.
  const seenPrice = new Set();
  for (const el of document.querySelectorAll('[class*="price" i]')) {
    if (el.querySelector('[class*="price" i]')) continue; // innermost only
    const t = textOf(el);
    if (t && t.length <= 40 && /\d/.test(t) && !seenPrice.has(t)) { seenPrice.add(t); out.price_texts.push(t); }
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

  // Images: loaded source, lazy-load attributes, and the largest srcset candidate. Tiny icons are skipped.
  const seenImg = new Set();
  let pending = 0;
  for (const img of document.images) {
    const cands = [img.currentSrc, img.getAttribute("src"), img.getAttribute("data-src"),
                   img.getAttribute("data-ks-lazyload"), img.getAttribute("data-lazyload")];
    const srcset = img.getAttribute("srcset") || img.getAttribute("data-srcset");
    if (srcset) {
      const best = srcset.split(",").map((p) => p.trim().split(/\s+/))
        .sort((a, b) => (parseFloat(b[1]) || 0) - (parseFloat(a[1]) || 0))[0];
      if (best) cands.unshift(best[0]);
    }
    const url = cands.map(abs).find(Boolean);
    if (!url || seenImg.has(url)) continue;
    const w = img.naturalWidth || 0, h = img.naturalHeight || 0;
    const loaded = img.complete && w > 0;
    if (loaded && (w < 150 || h < 150)) continue;
    if (!loaded) {
      if (!img.getAttribute("data-src") && !img.getAttribute("data-ks-lazyload") && !img.getAttribute("data-lazyload")) continue;
      pending++;
    }
    seenImg.add(url);
    const inDetail = img.closest('[id*="desc" i],[class*="desc" i],[class*="detail" i]');
    (inDetail ? out.detail_images : out.images).push(url);
    if (out.images.length + out.detail_images.length >= 50) break;
  }
  if (pending) out.notes.push("아직 화면에 안 나온 이미지 " + pending + "개가 있습니다. 페이지 끝까지 내린 뒤 다시 가져오면 더 정확합니다.");
  if (!out.selected_options.length) out.notes.push("선택된 옵션을 찾지 못했습니다. 옵션이 있는 상품이면 옵션을 누른 뒤 다시 가져오세요.");
  if (!out.title && !out.price_texts.length) out.status = "no_product";
  return out;
})();
