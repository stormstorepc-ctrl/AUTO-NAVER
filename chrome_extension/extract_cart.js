// Injected into the Taobao/Tmall cart tab the user clicked on (activeTab). Reads the rows already on screen.
// It does not open product pages or scroll. The value of the last expression is returned to the popup.
(() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const textOf = (el) => clean(el && (el.innerText || el.textContent));
  const abs = (u) => {
    if (!u || /^(data|blob|javascript):/i.test(u)) return "";
    try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : ""; } catch (e) { return ""; }
  };
  const itemId = (href) => {
    let u;
    try { u = new URL(href, location.href); } catch (e) { return ""; }
    if (!/(^|\.)(taobao|tmall)\.com$/.test(u.hostname)) return "";
    if (!/item\.htm|\/item\/|\/i\d+\.htm/.test(u.pathname)) return "";
    const id = u.searchParams.get("id") || (u.pathname.match(/(\d{6,20})\.htm/) || [])[1] || "";
    return /^\d{6,20}$/.test(id) ? id : "";
  };
  const out = { schema: 1, kind: "cart", status: "ok", url: location.href, items: [], notes: [],
                captured_at: new Date().toISOString() };

  if (/(^|\.)login\.(taobao|tmall)\.com$/.test(location.hostname) || document.querySelector("input[type=password]")) {
    out.status = "login_required"; return out;
  }
  if (document.querySelector('[id*="nocaptcha" i],[class*="nocaptcha" i],[class*="baxia-dialog" i],[id*="baxia-dialog" i]')) {
    out.status = "captcha"; return out;
  }

  // Every link to a product, grouped by product id.
  const byId = new Map();
  for (const a of document.querySelectorAll("a[href]")) {
    const id = itemId(a.getAttribute("href"));
    if (!id) continue;
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(a);
  }
  const idsIn = (el) => {
    const s = new Set();
    for (const a of el.querySelectorAll("a[href]")) { const id = itemId(a.getAttribute("href")); if (id) s.add(id); }
    return s;
  };
  const complete = (t) => /[¥￥]\s*\d|\d\.\d|\d\s*元/.test(t);
  const seenRows = new Set();

  for (const [id, anchors] of byId) {
    // The row is the largest ancestor that still contains links to this product only.
    for (const first of anchors) {
      let row = first;
      // Stop before a parent that holds a second row of the same product (two checkboxes) or a whole page section.
      while (row.parentElement && row.parentElement !== document.body) {
        const parent = row.parentElement;
        if (idsIn(parent).size !== 1) break;
        if (parent.querySelectorAll('input[type="checkbox"]').length > 1) break;
        if (textOf(parent).length > 500) break;
        row = parent;
      }
      if (seenRows.has(row)) continue;       // same row reached from another link (title + picture)
      seenRows.add(row);
      if (row.closest('[class*="recommend" i],[class*="guess" i],[class*="similar" i]')) continue;

      const title = anchors.filter((a) => row.contains(a)).map((a) => textOf(a) || clean(a.getAttribute("title")))
        .sort((x, y) => y.length - x.length)[0] || "";
      const img = row.querySelector("img");
      const image = img ? (abs(img.getAttribute("data-src")) || abs(img.currentSrc) || abs(img.getAttribute("src"))) : "";
      const skuEl = [...row.querySelectorAll('[class*="sku" i],[class*="props" i],[class*="spec" i]')]
        .filter((el) => !el.querySelector('[class*="sku" i],[class*="props" i],[class*="spec" i]'));
      const sku = [...new Set(skuEl.map(textOf).filter((t) => t && t.length <= 120))].join(" / ");
      const priceEls = [...row.querySelectorAll('[class*="price" i]')]
        .filter((el) => { const t = textOf(el); return t && t.length <= 40 && complete(t); });
      const prices = [];
      for (const el of priceEls) {
        if (priceEls.some((o) => o !== el && el.contains(o))) continue;
        let t = textOf(el);
        if (el.closest('del,s,[class*="origin" i],[class*="original" i],[class*="lineThrough" i]') && !/原价|划线价/.test(t)) t = "原价 " + t;
        if (!prices.includes(t)) prices.push(t);
      }
      const qtyEl = row.querySelector('input[type="text"],input[type="number"],input:not([type])');
      const qty = qtyEl && /^\d{1,4}$/.test(qtyEl.value || "") ? parseInt(qtyEl.value, 10) : null;
      const checkbox = row.querySelector('input[type="checkbox"]');
      out.items.push({ item_id: id, url: first.href, title: title.slice(0, 300), sku_text: sku.slice(0, 300),
                       price_texts: prices.slice(0, 6), image, quantity: qty, checked: checkbox ? !!checkbox.checked : null });
      if (out.items.length >= 200) break;
    }
    if (out.items.length >= 200) break;
  }
  if (!out.items.length) out.status = "no_product";
  return out;
})();
