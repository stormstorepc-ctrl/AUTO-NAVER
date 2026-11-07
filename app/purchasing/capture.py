"""Product data sent by the AUTO-NAVER Chrome extension from a Taobao/Tmall tab the user opened.

The extension only reads the page the user is looking at, after the user clicks its button.
This module validates that payload strictly and turns a capture plus the reviewer's
confirmation into a product. Prices for options the user did not select are never guessed:
each capture carries the price shown for the selected option only, and the reviewer confirms it.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal

from .assist import _delivery_days, _image_list, taobao_item
from .importer import validate_product
from .pricing import ValidationError

MAX_CAPTURE_BYTES = 512 * 1024
CAPTURE_STATUSES = {"ok", "login_required", "captcha", "no_product"}


def _short_text(v, name: str, maxlen: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValidationError(f"{name}: 문자열이어야 합니다")
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()
    return v[:maxlen]


def _text_list(v, name: str, maxlen: int, limit: int) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValidationError(f"{name}: 목록이어야 합니다")
    out = []
    for x in v[:limit]:
        t = _short_text(x, name, maxlen)
        if t and t not in out:
            out.append(t)
    return out


def _https_only(urls: list[str]) -> list[str]:
    out = [u for u in urls if u.startswith("https://") or u.startswith("http://")]
    return out[:50]


def validate_capture(payload) -> dict:
    """Validate the extension payload. Identity comes from the page URL only."""
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValidationError("확장 프로그램 데이터 형식이 올바르지 않습니다. 확장 프로그램을 최신으로 바꾸세요.")
    status = payload.get("status")
    if status not in CAPTURE_STATUSES:
        raise ValidationError("status 값이 올바르지 않습니다.")
    if status != "ok":
        raise ValidationError({"login_required": "타오바오 로그인 화면입니다. 로그인한 뒤 상품 페이지에서 다시 누르세요.",
                               "captcha": "타오바오 보안 확인 화면입니다. 직접 확인을 마친 뒤 다시 누르세요.",
                               "no_product": "상품 정보를 찾지 못했습니다. 상품 상세 페이지에서 다시 누르세요."}[status])
    item_id, clean_url = taobao_item(payload.get("url", ""))
    title = _short_text(payload.get("title"), "title", 500)
    if not title:
        raise ValidationError("상품 제목을 찾지 못했습니다. 페이지가 다 열린 뒤 다시 누르세요.")
    for key in ("images", "detail_images", "other_images"):
        if not isinstance(payload.get(key) or [], list):
            raise ValidationError(f"{key}: 목록이어야 합니다")
    images = _https_only(_image_list(payload.get("images") or []))
    detail = [u for u in _https_only(_image_list(payload.get("detail_images") or [])) if u not in images]
    other = [u for u in _https_only(_image_list(payload.get("other_images") or [])) if u not in images and u not in detail]
    return {
        "item_id": item_id, "url": clean_url, "title": title,
        "price_texts": _text_list(payload.get("price_texts"), "price_texts", 80, 20),
        "selected_options": _text_list(payload.get("selected_options"), "selected_options", 120, 10),
        "images": images, "detail_images": detail[:max(0, 50 - len(images))],
        "other_images": other[:20],  # separate limit: never takes room from product images
        "notes": _text_list(payload.get("notes"), "notes", 200, 10),
        "captured_at": _short_text(payload.get("captured_at"), "captured_at", 40),
    }


_MONEY = re.compile(r"[¥￥]\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*元")
_BARE = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*$")
_VALID = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$")
_RANGE = re.compile(r"\d\s*(?:[-~～—]|至|到(?!手))\s*[¥￥]?\s*\d")
_ORIGINAL = re.compile(r"原价|划线价|吊牌价|市场价|参考价|专柜价")
_FINAL = re.compile(r"到手价?|券后价?|折后价?|促销价|优惠价|活动价|现价|售价|抢购价")


def first_price(price_texts: list[str]) -> str:
    """A suggested purchase price, or "" when the page does not make it clear.

    Only money-marked amounts (¥/￥ before, 元 after) or a text that is just a number count.
    Original/strike-through prices (原价 …) are ignored; a price marked as the final price (到手价, 券后 …)
    wins. Any range (12.5-30, ¥12.50 至 ¥30.00), any malformed amount (¥39.999), or two different
    unmarked prices leave the field blank for the reviewer. The smallest number is never picked blindly.
    """
    final, plain = set(), set()
    for t in price_texts:
        t = t.replace("，", ",").replace("．", ".")
        if _RANGE.search(t):
            return ""
        last = 0
        found = False
        for m in _MONEY.finditer(t):
            found = True
            amount = m.group(1) or m.group(2)
            if not _VALID.match(amount) or (m.end() < len(t) and t[m.end()].isdigit()):
                return ""
            label = t[last:m.start()]
            last = m.end()
            value = Decimal(amount.replace(",", ""))
            if _ORIGINAL.search(label):
                continue
            (final if _FINAL.search(label) else plain).add(value)
        if not found:
            m = _BARE.match(t)
            if m:
                if not _VALID.match(m.group(1)):
                    return ""
                plain.add(Decimal(m.group(1).replace(",", "")))
    chosen = final if final else plain
    return str(next(iter(chosen))) if len(chosen) == 1 else ""


def option_id(name: str) -> str:
    return "sku-" + hashlib.sha256(name.encode()).hexdigest()[:12]


def product_from_capture(capture: dict, existing: dict | None, form: dict) -> dict:
    """Merge one confirmed capture into the product. Other options and images already saved are kept."""
    data = capture["data"]
    option_name = _short_text(form.get("option_name"), "option_name", 300) or "기본"
    price = (form.get("unit_price") or "").strip()
    if not price:
        raise ValidationError("이 옵션의 가격(위안)을 확인해서 넣어주세요.")
    chosen = [u for u in form.get("images", [])
              if u in data["images"] + data["detail_images"] + data.get("other_images", [])]
    extra = _image_list(form.get("image_urls", ""))
    oid = option_id(option_name)
    old_options = (existing or {}).get("options", [])
    previous = next((o for o in old_options if o["source_option_id"] == oid), None)
    # Re-capturing an option updates what was captured (name, price) and keeps everything else that was
    # entered before (weight, size, cost fields). Only a newly typed weight replaces the old one.
    new_option = {**(previous or {}), "source_option_id": oid, "name": option_name, "unit_price": price,
                  "currency": "CNY", "quantity": (previous or {}).get("quantity", 1)}
    if (form.get("weight_g") or "").strip():
        new_option["weight_g"] = form["weight_g"].strip()
    options = [new_option if o["source_option_id"] == oid else o for o in old_options]
    if previous is None:
        options.append(new_option)
    images = list((existing or {}).get("images", []))
    for u in chosen + extra:
        if u not in images:
            images.append(u)
    days_form = {"min": (form.get("delivery_min") or "").strip(), "max": (form.get("delivery_max") or "").strip()}
    days = _delivery_days(days_form) if days_form["min"] or days_form["max"] else (existing or {}).get("est_delivery_days")
    keep = existing or {}
    return validate_product({
        "source": "taobao", "source_product_id": capture["item_id"], "supply_url": capture["url"],
        "title_src": keep.get("title_src") or data["title"], "category": keep.get("category", ""),
        "description_src": keep.get("description_src", ""), "images": images[:50], "est_delivery_days": days,
        "compliance": {"sale_allowed_confirmed": form.get("sale_allowed") == "yes" or
                       bool(keep.get("compliance", {}).get("sale_allowed_confirmed")),
                       "restricted_flags": keep.get("compliance", {}).get("restricted_flags", [])},
        "options": options,
    })
