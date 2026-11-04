"""견적 생성 → 승인 → 모의 게시 → 주간 실행 → 초안 내보내기.

실계정 게시 어댑터는 이 단계에서 구현하지 않는다. 채널 정책/API가 검증되기 전까지 실채널은 blocked 이다.
모의 어댑터는 account 가 'mock:' 로 시작하는 게시 대상에만 사용할 수 있고 실제 게시 성공으로 집계되지 않는다.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from .pricing import (ChannelTerms, FxRate, MAX_AGE, OptionCostInput, PriceQuote, SaleTerms, ShippingRateCard,
                      ValidationError, quote_price, _aware)
from .store import Store, canonical, iso, now_utc, sha

APPROVAL_TTL = timedelta(hours=24)
MAX_BULK_APPROVE = 100
EXPECTED_MARGIN = Decimal("0.20")
REAL_CHANNELS_VERIFIED: dict[str, bool] = {"smartstore": False, "danggeun": False, "bunjang": False}  # 미검증 -> blocked


# ---------------- 견적 ----------------
@dataclasses.dataclass
class RateBook:
    fx: FxRate
    shipping: ShippingRateCard
    channels: dict[str, ChannelTerms]
    sale: dict[str, SaleTerms] = dataclasses.field(default_factory=dict)


def _ser(o: Any) -> Any:
    if dataclasses.is_dataclass(o):
        return {k: _ser(v) for k, v in dataclasses.asdict(o).items()}
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_ser(x) for x in o]
    if isinstance(o, datetime):
        return iso(o)
    if isinstance(o, Decimal):
        return str(o)
    return o


def option_input(o: dict) -> OptionCostInput:
    g = lambda k, d="0": Decimal(o.get(k, d))
    return OptionCostInput(
        unit_price=Decimal(o["unit_price"]), currency=o["currency"], quantity=o["quantity"],
        weight_g=Decimal(o["weight_g"]) if o.get("weight_g") else None,
        dims_cm=tuple(Decimal(x) for x in o["dims_cm"]) if o.get("dims_cm") else None,
        china_shipping_krw=g("china_shipping_krw"), handling_krw=g("handling_krw"),
        seller_customs_krw=g("seller_customs_krw"), domestic_shipping_krw=g("domestic_shipping_krw"),
        payment_fee_rate=g("payment_fee_rate"), reserve_rate=g("reserve_rate"))


def price_product(store: Store, product_id: int, channel: str, rates: RateBook, now: datetime | None = None) -> list[PriceQuote]:
    """모든 옵션을 채널별로 독립 계산해 새 세대(generation)로 저장한다."""
    now = _aware(now or now_utc())
    with store.tx() as c:
        p = store.get_product(c, product_id)
    if p is None:
        raise KeyError(product_id)
    terms = rates.channels[channel]
    sale = rates.sale.get(channel, SaleTerms())
    quotes, items = [], []
    for o in p["options"]:
        q = quote_price(option_input(o), rates.fx, rates.shipping, terms, sale, now)
        quotes.append(q)
        vu = None
        if q.publishable:
            vu = iso(min(_aware(rates.fx.observed_at) + MAX_AGE["fx"], _aware(rates.shipping.observed_at) + MAX_AGE["shipping"],
                         _aware(terms.observed_at) + MAX_AGE["channel"]))
        items.append({"source_option_id": o["source_option_id"],
                      "inputs": {"option": o, "fx": _ser(rates.fx), "shipping": _ser(rates.shipping),
                                 "channel": _ser(terms), "sale": _ser(sale)},
                      "result": q.as_dict(), "valid_until": vu})
    store.save_quotes(product_id, channel, items)
    return quotes


# ---------------- 게시 가능 검사 ----------------
def screen_blockers(p: dict) -> list[str]:
    b = []
    if p["compliance"]["restricted_flags"]:
        b.append(f"제외 대상 카테고리: {','.join(p['compliance']['restricted_flags'])}")
    if not p["compliance"]["sale_allowed_confirmed"]:
        b.append("판매 가능 근거(sale_allowed_confirmed) 없음")
    if not p["images"]:
        b.append("이미지 없음")
    if not p.get("supply_url"):
        b.append("공급처 URL 없음")
    if not p.get("est_delivery_days"):
        b.append("예상 배송 기간 없음")
    return b


def blockers_before_approval(store: Store, c, product_id: int, channel: str, now: datetime) -> list[str]:
    p = store.get_product(c, product_id)
    if p is None:
        return ["상품 없음"]
    b = screen_blockers(p)
    if p["status"] == "rejected":
        b.append("검토에서 제외됨")
    tr = store.latest_translation(c, product_id)
    if tr is None or tr["status"] != "reviewed":
        b.append("검수 완료된 번역 없음")
    qs = store.latest_quotes(c, product_id, channel)
    if len(qs) != len(p["options"]):
        b.append("전 옵션 견적 없음")
    for q in qs:
        r = q["result"]
        if not r.get("publishable") or r.get("status") != "ok":
            b.append(f"옵션 {q['source_option_id']} 견적 확정 불가: {', '.join(r.get('blockers') or [r.get('status')])}")
        elif Decimal(r["margin"]) < EXPECTED_MARGIN:
            b.append(f"옵션 {q['source_option_id']} 마진 미달")
        if q["valid_until"] is None or _aware(datetime.fromisoformat(q["valid_until"])) < now:
            b.append(f"옵션 {q['source_option_id']} 견적 입력 만료")
    return b


def approve(store: Store, product_ids: list[int], channel: str, account: str, actor: str,
            now: datetime | None = None) -> dict[int, list[str]]:
    """통과한 상품만 승인하고, 못 한 상품은 사유를 반환한다. 일괄 최대 100개."""
    if len(product_ids) > MAX_BULK_APPROVE:
        raise ValidationError(f"일괄 승인은 최대 {MAX_BULK_APPROVE}개입니다")
    if not actor:
        raise ValidationError("승인 주체(actor)가 필요합니다")
    now = _aware(now or now_utc())
    failed: dict[int, list[str]] = {}
    with store.tx() as c:
        for pid in product_ids:
            b = blockers_before_approval(store, c, pid, channel, now)
            if b:
                failed[pid] = b
                continue
            c.execute("UPDATE approvals SET revoked_at=?, revoke_reason='재승인으로 대체' WHERE product_id=? AND channel=? AND account=? AND revoked_at IS NULL",
                      (iso(now), pid, channel, account))
            c.execute("INSERT INTO approvals(product_id,channel,account,content_hash,approved_by,approved_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                      (pid, channel, account, store.content_hash(c, pid, channel), actor, iso(now), iso(now + APPROVAL_TTL)))
            c.execute("UPDATE products SET status='approved' WHERE id=? AND status!='rejected'", (pid,))
            store.audit(c, actor, "approve", {"product_id": pid, "channel": channel, "account": account})
    return failed


def exclude(store: Store, product_ids: list[int], actor: str, reason: str = "") -> None:
    with store.tx() as c:
        for pid in product_ids:
            c.execute("UPDATE products SET status='rejected' WHERE id=?", (pid,))
            c.execute("UPDATE approvals SET revoked_at=?, revoke_reason=? WHERE product_id=? AND revoked_at IS NULL",
                      (iso(now_utc()), f"제외: {reason}", pid))
            store.audit(c, actor, "exclude", {"product_id": pid, "reason": reason})


def publish_blockers(store: Store, c, product_id: int, channel: str, account: str, adapter: "ChannelAdapter",
                     now: datetime) -> list[str]:
    """게시 직전 검사. 승인 이후 어떤 입력이 바뀌었는지(해시)와 승인 만료를 확인한다."""
    b: list[str] = []
    if not adapter.verified(channel):
        b.append(f"채널 {channel} 미검증(blocked)")
    if adapter.is_mock and not account.startswith("mock:"):
        b.append("모의 어댑터는 mock: 계정에만 사용할 수 있습니다")
    b += blockers_before_approval(store, c, product_id, channel, now)
    ap = c.execute("SELECT * FROM approvals WHERE product_id=? AND channel=? AND account=? AND revoked_at IS NULL "
                   "ORDER BY id DESC LIMIT 1", (product_id, channel, account)).fetchone()
    if ap is None:
        b.append("승인 없음")
    else:
        if _aware(datetime.fromisoformat(ap["expires_at"])) < now:
            b.append("승인 만료")
        if ap["content_hash"] != store.content_hash(c, product_id, channel):
            b.append("승인 이후 내용 변경(재승인 필요)")
    return b


# ---------------- 어댑터 ----------------
class AdapterTimeout(Exception):
    """요청을 보냈지만 응답을 받지 못함 -> 결과 unknown."""


class AdapterRejected(Exception):
    """채널이 명시적으로 거부 (등록되지 않음이 확실)."""


class ChannelAdapter(Protocol):
    is_mock: bool
    def verified(self, channel: str) -> bool: ...
    def create(self, idem_key: str, payload: dict) -> str: ...
    def lookup(self, idem_key: str) -> str | None: ...


class MockChannelAdapter:
    """모의 채널. 원격 상태를 SQLite 에 저장해 프로세스 재시작 후에도 유지된다."""
    is_mock = True

    def __init__(self, store: Store, behavior: dict[str, str] | None = None) -> None:
        self.store = store
        self.behavior = behavior or {}   # idem_key -> "ok" | "lose_response" | "reject" | "crash"
        self.create_calls: list[str] = []

    def verified(self, channel: str) -> bool:
        return True

    def create(self, idem_key: str, payload: dict) -> str:
        self.create_calls.append(idem_key)
        mode = self.behavior.get(idem_key, "ok")
        if mode == "reject":
            raise AdapterRejected("mock reject")
        with self.store.tx() as c:
            row = c.execute("SELECT remote_id FROM mock_remote WHERE idempotency_key=?", (idem_key,)).fetchone()
            if row:   # 실채널과 달리 중복 요청을 그대로 받아들이는 최악 가정: 중복 기록
                raise AssertionError(f"중복 POST 감지: {idem_key}")
            rid = "MOCK-" + sha(idem_key)[:12]
            c.execute("INSERT INTO mock_remote VALUES(?,?,?)", (idem_key, rid, sha(payload)))
        if mode == "lose_response":
            raise AdapterTimeout("mock timeout after create")
        if mode == "crash":
            raise KeyboardInterrupt("simulated process kill")
        return rid

    def lookup(self, idem_key: str) -> str | None:
        with self.store.tx() as c:
            r = c.execute("SELECT remote_id FROM mock_remote WHERE idempotency_key=?", (idem_key,)).fetchone()
            return r[0] if r else None


class BlockedRealAdapter:
    """실채널 자리표시자: 공식 지원 근거 확인 전까지 어떤 게시도 허용하지 않는다."""
    is_mock = False
    def verified(self, channel: str) -> bool:
        return REAL_CHANNELS_VERIFIED.get(channel, False)
    def create(self, idem_key, payload):  # pragma: no cover
        raise RuntimeError("실채널 게시는 1단계에서 구현되지 않았습니다")
    def lookup(self, idem_key):  # pragma: no cover
        raise RuntimeError("실채널 조회는 1단계에서 구현되지 않았습니다")


# ---------------- 게시 ----------------
def idem_key(p: dict, channel: str, account: str) -> str:
    return f"{p['source']}:{p['source_product_id']}|{channel}|{account}"   # 주차와 무관: 다른 주에도 같은 키


def build_payload(store: Store, c, product_id: int, channel: str) -> dict:
    p = store.get_product(c, product_id)
    tr = store.latest_translation(c, product_id)
    qs = store.latest_quotes(c, product_id, channel)
    return {"title": tr["title_ko"], "description": tr["description_ko"], "images": p["images"],
            "options": [{"id": q["source_option_id"], "name": tr["option_names"].get(q["source_option_id"]),
                         "price": q["result"]["list_price"], "shipping": q["result"]["customer_shipping_krw"]} for q in qs]}


def publish(store: Store, product_id: int, channel: str, account: str, adapter: ChannelAdapter,
            run_key: str | None = None, now: datetime | None = None) -> str:
    """결과: published | skipped:<사유> | blocked:<사유> | unknown | failed"""
    now = _aware(now or now_utc())
    with store.tx() as c:                                  # 1) 검사 + 원자적 점유
        pub = c.execute("SELECT * FROM publications WHERE product_id=? AND channel=? AND account=?",
                        (product_id, channel, account)).fetchone()
        if pub and pub["state"] in ("published", "claimed", "unknown"):
            return f"skipped:{pub['state']}"
        b = publish_blockers(store, c, product_id, channel, account, adapter, now)
        if b:
            return "blocked:" + "; ".join(b)
        p = store.get_product(c, product_id)
        key = idem_key(p, channel, account)
        h = store.content_hash(c, product_id, channel)
        kind = "mock" if adapter.is_mock else "real"
        if pub is None:
            cur = c.execute("INSERT INTO publications(product_id,channel,account,state,adapter_kind,idempotency_key,content_hash,claimed_at,updated_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?)", (product_id, channel, account, "claimed", kind, key, h, iso(now), iso(now)))
            pub_id = cur.lastrowid
        else:
            pub_id = pub["id"]
            c.execute("UPDATE publications SET state='claimed', content_hash=?, claimed_at=?, updated_at=? WHERE id=?",
                      (h, iso(now), iso(now), pub_id))
        payload = build_payload(store, c, product_id, channel)
        c.execute("UPDATE products SET status='publishing' WHERE id=?", (product_id,))
    outcome, remote, detail = "failed", None, ""          # 2) 외부 호출은 트랜잭션 밖
    try:
        rid = adapter.create(key, payload)
        found = adapter.lookup(key)                       # 3) 응답만 믿지 않고 조회로 확인
        if found and found == rid:
            outcome, remote = "published", rid
        else:
            outcome, detail = "unknown", "등록 응답과 조회 결과 불일치"
    except AdapterTimeout as e:
        outcome, detail = "unknown", f"응답 유실: {e}"
    except AdapterRejected as e:
        outcome, detail = "failed", f"거부: {e}"
    except Exception as e:
        outcome, detail = "unknown", f"예외: {type(e).__name__}"   # 전송 여부 불명 -> 재POST 금지
        _finish(store, pub_id, product_id, outcome, remote, detail, run_key, now)
        raise
    _finish(store, pub_id, product_id, outcome, remote, detail, run_key, now)
    return outcome


def _finish(store: Store, pub_id: int, product_id: int, outcome: str, remote: str | None, detail: str,
            run_key: str | None, now: datetime) -> None:
    with store.tx() as c:
        c.execute("UPDATE publications SET state=?, remote_id=?, updated_at=? WHERE id=?", (outcome, remote, iso(now), pub_id))
        c.execute("INSERT INTO publish_attempts(publication_id,run_key,outcome,detail,created_at) VALUES(?,?,?,?,?)",
                  (pub_id, run_key, outcome, detail, iso(now)))
        c.execute("UPDATE products SET status=? WHERE id=?", ("published" if outcome == "published" else "approved", product_id))
        store.audit(c, "system", "publish_" + outcome, {"publication_id": pub_id, "detail": detail})


def recover_stale_claims(store: Store, adapter: ChannelAdapter, older_than: timedelta = timedelta(minutes=10),
                         now: datetime | None = None) -> dict[str, int]:
    """강제 종료로 남은 claimed 와 unknown 을 조회로 정리한다. 조회로 부재가 확인된 경우에만 재시도 가능(failed)."""
    now = _aware(now or now_utc())
    res = {"published": 0, "still_unknown": 0, "confirmed_absent": 0}
    with store.tx() as c:
        rows = c.execute("SELECT * FROM publications WHERE state IN ('claimed','unknown')").fetchall()
    for r in rows:
        if r["state"] == "claimed" and now - _aware(datetime.fromisoformat(r["claimed_at"])) < older_than:
            continue
        try:
            found = adapter.lookup(r["idempotency_key"])
        except Exception:
            found = "?ERR"
        with store.tx() as c:
            if found == "?ERR":
                c.execute("UPDATE publications SET state='unknown', updated_at=? WHERE id=?", (iso(now), r["id"]))
                res["still_unknown"] += 1
            elif found:
                c.execute("UPDATE publications SET state='published', remote_id=?, updated_at=? WHERE id=?", (found, iso(now), r["id"]))
                c.execute("UPDATE products SET status='published' WHERE id=?", (r["product_id"],))
                res["published"] += 1
            else:
                c.execute("UPDATE publications SET state='failed', updated_at=? WHERE id=?", (iso(now), r["id"]))
                c.execute("INSERT INTO publish_attempts(publication_id,run_key,outcome,detail,created_at) VALUES(?,?,?,?,?)",
                          (r["id"], None, "confirmed_absent", "조회로 미등록 확인", iso(now)))
                res["confirmed_absent"] += 1
    return res


# ---------------- 주간 실행 ----------------
def run_week(store: Store, week_key: str, jobs: list[tuple[int, str, str]], adapter: ChannelAdapter,
             now: datetime | None = None) -> dict[str, Any]:
    """jobs=[(product_id, channel, account)]. 재실행해도 완료 항목은 skipped 로 보존된다.
    mock_published 는 모의 성공이며 실제 게시 성공(real_published)과 분리 집계한다."""
    now = _aware(now or now_utc())
    with store.tx() as c:
        c.execute("INSERT INTO runs(run_key,status,started_at) VALUES(?, 'running', ?) "
                  "ON CONFLICT(run_key) DO UPDATE SET status='running'", (week_key, iso(now)))
    counts: dict[str, int] = {}
    for pid, ch, acct in jobs:
        r = publish(store, pid, ch, acct, adapter, run_key=week_key, now=now)
        k = r.split(":")[0]
        counts[k] = counts.get(k, 0) + 1
    with store.tx() as c:
        pubs = c.execute("SELECT adapter_kind, state, COUNT(*) n FROM publications GROUP BY adapter_kind, state").fetchall()
    tally = {(r["adapter_kind"], r["state"]): r["n"] for r in pubs}
    summary = {"week": week_key, "jobs": len(jobs), "outcomes": counts,
               "mock_published": tally.get(("mock", "published"), 0), "real_published": tally.get(("real", "published"), 0),
               "unknown": sum(n for (k, s), n in tally.items() if s == "unknown")}
    with store.tx() as c:
        c.execute("UPDATE runs SET status='done', summary=?, finished_at=? WHERE run_key=?", (canonical(summary), iso(now), week_key))
    return summary


# ---------------- 초안 내보내기 ----------------
def _csv_safe(v: Any) -> str:
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_draft(store: Store, product_id: int, channel: str, out_dir: str | os.PathLike) -> Path:
    """검토용 초안 패키지. 게시 성공으로 집계되지 않으며 DRAFT 표시를 포함한다."""
    with store.tx() as c:
        p = store.get_product(c, product_id)
        tr = store.latest_translation(c, product_id)
        qs = store.latest_quotes(c, product_id, channel)
    if p is None or tr is None or not qs:
        raise ValidationError("번역과 견적이 있는 상품만 내보낼 수 있습니다")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in f"{p['source']}_{p['source_product_id']}_{channel}")
    d = Path(out_dir) / safe
    d.mkdir(parents=True, exist_ok=True)
    (d / "README.txt").write_text("DRAFT - 검토용 초안입니다. 게시되지 않았으며 게시 성공으로 집계되지 않습니다.\n", encoding="utf-8")
    (d / "description.txt").write_text(f"{tr['title_ko']}\n\n{tr['description_ko']}\n", encoding="utf-8")
    (d / "images.txt").write_text("\n".join(p["images"]) + "\n", encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["option_id", "option_name", "list_price_krw", "customer_shipping_krw", "margin", "publishable"])
    for q in qs:
        r = q["result"]
        w.writerow([_csv_safe(q["source_option_id"]), _csv_safe(tr["option_names"].get(q["source_option_id"], "")),
                    r.get("list_price"), r.get("customer_shipping_krw"), r.get("margin"), r.get("publishable")])
    (d / "options.csv").write_text(buf.getvalue(), encoding="utf-8-sig", newline="")
    (d / "draft.json").write_text(json.dumps({"draft": True, "channel": channel, "title": tr["title_ko"],
                                              "prices": {q["source_option_id"]: q["result"].get("list_price") for q in qs}},
                                             ensure_ascii=False, indent=2), encoding="utf-8")
    return d
