"""상품/옵션 JSON·CSV 가져오기와 검증. 외부 텍스트는 평문 데이터로만 취급하고 실행/렌더링하지 않는다."""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from .pricing import SUPPORTED_SOURCE_CURRENCIES, MAX_QUANTITY, ValidationError, D

SCHEMA_VERSION = 1
ALLOWED_RESTRICTED_FLAGS = {"electric", "battery", "food", "cosmetic", "medical", "children", "counterfeit", "hazmat"}
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_TEXT = 20000


@dataclass
class ImportReport:
    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)   # {"index", "source_product_id", "errors"}

    @property
    def summary(self) -> dict:
        return {"accepted": len(self.accepted), "rejected": len(self.rejected)}


def _text(v: Any, name: str, required: bool = True, maxlen: int = MAX_TEXT) -> str:
    if v is None or v == "":
        if required:
            raise ValidationError(f"{name}: 필수값 누락")
        return ""
    if not isinstance(v, str):
        raise ValidationError(f"{name}: 문자열이어야 합니다")
    v = _CTRL.sub("", v).strip()
    if required and not v:
        raise ValidationError(f"{name}: 필수값 누락")
    if len(v) > maxlen:
        raise ValidationError(f"{name}: 길이 초과")
    return v


def _url(v: Any, name: str, required: bool = True) -> str:
    s = _text(v, name, required, 2000)
    if s and urlparse(s).scheme not in ("http", "https"):
        raise ValidationError(f"{name}: http/https URL만 허용합니다")
    return s


def _validate_option(o: Any, seen: set[str]) -> dict:
    if not isinstance(o, dict):
        raise ValidationError("option: 객체여야 합니다")
    oid = _text(o.get("source_option_id"), "source_option_id", maxlen=200)
    if oid in seen:
        raise ValidationError(f"옵션 ID 중복: {oid}")
    seen.add(oid)
    cur = _text(o.get("currency", "CNY"), "currency", maxlen=8)
    if cur not in SUPPORTED_SOURCE_CURRENCIES:
        raise ValidationError(f"currency: 지원하지 않는 통화 {cur!r}")
    price = D(o.get("unit_price"), "unit_price")
    if price < 0:
        raise ValidationError("unit_price: 음수 불가")
    qty = o.get("quantity", 1)
    if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QUANTITY:
        raise ValidationError(f"quantity: 1~{MAX_QUANTITY} 정수여야 합니다")
    out = {"source_option_id": oid, "name": _text(o.get("name"), "option.name", maxlen=300),
           "currency": cur, "unit_price": str(price), "quantity": qty}
    if o.get("weight_g") not in (None, ""):
        w = D(o["weight_g"], "weight_g")
        if w <= 0:
            raise ValidationError("weight_g: 0보다 커야 합니다")
        out["weight_g"] = str(w)
    if o.get("dims_cm") not in (None, ""):
        dims = o["dims_cm"]
        if not isinstance(dims, (list, tuple)) or len(dims) != 3 or any(D(x, "dims_cm") <= 0 for x in dims):
            raise ValidationError("dims_cm: 양수 3개([L,W,H])여야 합니다")
        out["dims_cm"] = [str(D(x, "dims_cm")) for x in dims]
    for k in ("china_shipping_krw", "handling_krw", "seller_customs_krw", "domestic_shipping_krw"):
        if o.get(k) not in (None, ""):
            d = D(o[k], k)
            if d < 0:
                raise ValidationError(f"{k}: 음수 불가")
            out[k] = str(d)
    for k in ("payment_fee_rate", "reserve_rate"):
        if o.get(k) not in (None, ""):
            d = D(o[k], k)
            if not 0 <= d < 1:
                raise ValidationError(f"{k}: 0 이상 1 미만")
            out[k] = str(d)
    return out


def validate_product(p: Any) -> dict:
    if not isinstance(p, dict):
        raise ValidationError("product: 객체여야 합니다")
    comp = p.get("compliance") or {}
    if not isinstance(comp, dict):
        raise ValidationError("compliance: 객체여야 합니다")
    flags = comp.get("restricted_flags") or []
    if not isinstance(flags, list) or any(f not in ALLOWED_RESTRICTED_FLAGS for f in flags):
        raise ValidationError(f"restricted_flags: 허용값 {sorted(ALLOWED_RESTRICTED_FLAGS)}")
    if not isinstance(comp.get("sale_allowed_confirmed", False), bool):
        raise ValidationError("sale_allowed_confirmed: 불리언이어야 합니다")
    images = p.get("images") or []
    if not isinstance(images, list) or len(images) > 50:
        raise ValidationError("images: 목록(최대 50)이어야 합니다")
    days = p.get("est_delivery_days")
    if days is not None:
        if (not isinstance(days, dict) or not all(isinstance(days.get(k), int) and not isinstance(days.get(k), bool)
                                                  for k in ("min", "max")) or not 0 < days["min"] <= days["max"] <= 120):
            raise ValidationError("est_delivery_days: {min,max} 1~120 정수, min<=max")
    opts_raw = p.get("options")
    if not isinstance(opts_raw, list) or not opts_raw or len(opts_raw) > 200:
        raise ValidationError("options: 1~200개의 목록이어야 합니다")
    seen: set[str] = set()
    return {
        "source": _text(p.get("source", "taobao"), "source", maxlen=50),
        "source_product_id": _text(p.get("source_product_id"), "source_product_id", maxlen=200),
        "title_src": _text(p.get("title_src"), "title_src", maxlen=500),
        "category": _text(p.get("category"), "category", False, 300),
        "description_src": _text(p.get("description_src"), "description_src", False),
        "supply_url": _url(p.get("supply_url"), "supply_url", False),
        "images": [_url(u, "images[]") for u in images],
        "est_delivery_days": days,
        "compliance": {"sale_allowed_confirmed": bool(comp.get("sale_allowed_confirmed", False)),
                       "restricted_flags": sorted(flags)},
        "options": [_validate_option(o, seen) for o in opts_raw],
    }


def import_json(raw: str | bytes) -> ImportReport:
    try:
        doc = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ValidationError(f"JSON 파싱 실패: {e}")
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(f"schema_version={SCHEMA_VERSION}이 필요합니다")
    prods = doc.get("products")
    if not isinstance(prods, list):
        raise ValidationError("products: 목록이어야 합니다")
    return _collect(prods)


CSV_COLUMNS = ["schema_version", "source", "source_product_id", "title_src", "category", "description_src",
               "supply_url", "images", "delivery_min", "delivery_max", "sale_allowed_confirmed",
               "restricted_flags", "source_option_id", "option_name", "unit_price", "currency", "quantity",
               "weight_g", "dims_cm", "china_shipping_krw", "handling_krw", "seller_customs_krw",
               "domestic_shipping_krw", "payment_fee_rate", "reserve_rate"]


def import_csv(raw: str) -> ImportReport:
    """옵션 1행씩. 같은 (source, source_product_id) 행은 한 상품으로 묶는다. images/flags는 '|' 구분."""
    reader = csv.DictReader(io.StringIO(raw))
    missing = {"schema_version", "source_product_id", "title_src", "source_option_id", "unit_price"} - set(reader.fieldnames or [])
    if missing:
        raise ValidationError(f"CSV 필수 열 누락: {sorted(missing)}")
    groups: dict[tuple, dict] = {}
    bad: list[dict] = []
    for i, row in enumerate(reader, start=2):
        if (row.get("schema_version") or "").strip() != str(SCHEMA_VERSION):
            bad.append({"index": i, "source_product_id": row.get("source_product_id"), "errors": ["schema_version 불일치"]})
            continue
        key = (row.get("source") or "taobao", row.get("source_product_id"))
        g = groups.setdefault(key, {"source": key[0], "source_product_id": key[1], "title_src": row.get("title_src"),
                                    "category": row.get("category"), "description_src": row.get("description_src"),
                                    "supply_url": row.get("supply_url"),
                                    "images": [x for x in (row.get("images") or "").split("|") if x],
                                    "compliance": {"sale_allowed_confirmed": (row.get("sale_allowed_confirmed") or "").lower() in ("1", "true", "yes"),
                                                   "restricted_flags": [x for x in (row.get("restricted_flags") or "").split("|") if x]},
                                    "options": []})
        if row.get("delivery_min") or row.get("delivery_max"):
            try:
                g["est_delivery_days"] = {"min": int(row["delivery_min"]), "max": int(row["delivery_max"])}
            except (TypeError, ValueError):
                g["est_delivery_days"] = {"min": "x", "max": "x"}
        try:
            qty = int(row.get("quantity") or 1)
        except ValueError:
            qty = -1
        opt = {"source_option_id": row.get("source_option_id"), "name": row.get("option_name"),
               "unit_price": row.get("unit_price"), "currency": row.get("currency") or "CNY", "quantity": qty}
        for k in ("weight_g", "china_shipping_krw", "handling_krw", "seller_customs_krw", "domestic_shipping_krw",
                  "payment_fee_rate", "reserve_rate"):
            if row.get(k):
                opt[k] = row[k]
        if row.get("dims_cm"):
            opt["dims_cm"] = row["dims_cm"].split("x")
        g["options"].append(opt)
    rep = _collect(list(groups.values()))
    rep.rejected.extend(bad)
    return rep


def _collect(prods: list) -> ImportReport:
    rep = ImportReport()
    seen: set[tuple[str, str]] = set()
    for i, p in enumerate(prods):
        pid = p.get("source_product_id") if isinstance(p, dict) else None
        try:
            v = validate_product(p)
            key = (v["source"], v["source_product_id"])
            if key in seen:
                raise ValidationError(f"상품 ID 중복: {key[1]}")
            seen.add(key)
            rep.accepted.append(v)
        except ValidationError as e:
            rep.rejected.append({"index": i, "source_product_id": pid if isinstance(pid, str) else None, "errors": [str(e)]})
    return rep
