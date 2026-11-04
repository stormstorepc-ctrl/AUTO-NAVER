"""SQLite 저장소 (표준 라이브러리). 상품·옵션·견적·번역·승인·게시 이력을 버전과 함께 보존한다."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from .pricing import ValidationError

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_product_id TEXT NOT NULL,
  data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'discovered',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(source, source_product_id));
CREATE TABLE IF NOT EXISTS variants(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  source_option_id TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(product_id, source_option_id));
CREATE TABLE IF NOT EXISTS translations(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), version INTEGER NOT NULL,
  title_ko TEXT NOT NULL, description_ko TEXT NOT NULL, option_names TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', source_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(product_id, version));
CREATE TABLE IF NOT EXISTS quotes(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), channel TEXT NOT NULL,
  source_option_id TEXT NOT NULL, generation INTEGER NOT NULL, inputs TEXT NOT NULL, result TEXT NOT NULL,
  valid_until TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), channel TEXT NOT NULL,
  account TEXT NOT NULL, content_hash TEXT NOT NULL, approved_by TEXT NOT NULL, approved_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, revoked_at TEXT, revoke_reason TEXT);
CREATE TABLE IF NOT EXISTS publications(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), channel TEXT NOT NULL,
  account TEXT NOT NULL, state TEXT NOT NULL, adapter_kind TEXT NOT NULL, idempotency_key TEXT NOT NULL,
  remote_id TEXT, content_hash TEXT, claimed_at TEXT, updated_at TEXT NOT NULL,
  UNIQUE(product_id, channel, account));
CREATE TABLE IF NOT EXISTS publish_attempts(
  id INTEGER PRIMARY KEY, publication_id INTEGER NOT NULL REFERENCES publications(id), run_key TEXT,
  outcome TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  run_key TEXT PRIMARY KEY, status TEXT NOT NULL, summary TEXT, started_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS mock_remote(
  idempotency_key TEXT PRIMARY KEY, remote_id TEXT NOT NULL, payload_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT, event TEXT NOT NULL, detail TEXT);
"""

_SECRET_KEYS = re.compile(r"(pass|secret|token|cookie|key|authorization|customs_id|pccc)", re.I)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


class Store:
    def __init__(self, path: str = "purchasing.db") -> None:
        self.path = path
        c = self.connect()
        try:
            c.executescript(SCHEMA)
        finally:
            c.close()

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        if self.path != ":memory:":
            c.execute("PRAGMA journal_mode=WAL")
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE: 쓰기 락을 선점하여 점유/검사를 원자적으로 수행한다."""
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def audit(self, c: sqlite3.Connection, actor: str | None, event: str, detail: Any = None) -> None:
        c.execute("INSERT INTO audit(at,actor,event,detail) VALUES(?,?,?,?)",
                  (iso(now_utc()), actor, event, canonical(redact(detail)) if detail is not None else None))

    # ---- 상품 ----
    def upsert_products(self, products: list[dict], actor: str = "import", expected_version: int | None = None) -> dict:
        added = updated = unchanged = 0
        with self.tx() as c:
            for p in products:
                row = c.execute("SELECT id,data,version FROM products WHERE source=? AND source_product_id=?",
                                (p["source"], p["source_product_id"])).fetchone()
                if expected_version is not None and (row is None or row["version"] != expected_version):
                    raise ValidationError("상품 내용이 변경됐습니다. 화면을 새로 열고 다시 진행하세요.")
                ts = iso(now_utc())
                if row is None:
                    cur = c.execute("INSERT INTO products(source,source_product_id,data,created_at,updated_at) VALUES(?,?,?,?,?)",
                                    (p["source"], p["source_product_id"], canonical(p), ts, ts))
                    pid = cur.lastrowid
                    added += 1
                elif row["data"] == canonical(p):
                    unchanged += 1
                    continue
                else:
                    pid = row["id"]
                    c.execute("UPDATE products SET data=?, version=version+1, updated_at=? WHERE id=?",
                              (canonical(p), ts, pid))
                    updated += 1
                for o in p["options"]:
                    c.execute("INSERT INTO variants(product_id,source_option_id,data) VALUES(?,?,?) "
                              "ON CONFLICT(product_id,source_option_id) DO UPDATE SET data=excluded.data",
                              (pid, o["source_option_id"], canonical(o)))
            self.audit(c, actor, "import", {"added": added, "updated": updated, "unchanged": unchanged})
        return {"added": added, "updated": updated, "unchanged": unchanged}

    def get_product(self, c: sqlite3.Connection, product_id: int) -> dict | None:
        r = c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not r:
            return None
        d = json.loads(r["data"])
        d.update(id=r["id"], version=r["version"], status=r["status"])
        return d

    def list_product_ids(self) -> list[int]:
        with self.tx() as c:
            return [r[0] for r in c.execute("SELECT id FROM products ORDER BY id")]

    # ---- 번역 ----
    def add_translation(self, product_id: int, title_ko: str, description_ko: str, option_names: dict[str, str],
                        reviewed: bool = False, expected_version: int | None = None) -> int:
        with self.tx() as c:
            p = self.get_product(c, product_id)
            if p is None:
                raise KeyError(product_id)
            if expected_version is not None and p["version"] != expected_version:
                raise ValidationError("상품 원문이 변경됐습니다. 화면을 새로 열고 번역을 확인하세요.")
            v = (c.execute("SELECT COALESCE(MAX(version),0) FROM translations WHERE product_id=?", (product_id,)).fetchone()[0]) + 1
            src_hash = sha({"t": p["title_src"], "d": p["description_src"], "o": {o["source_option_id"]: o["name"] for o in p["options"]}})
            c.execute("INSERT INTO translations(product_id,version,title_ko,description_ko,option_names,status,source_hash,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?)", (product_id, v, title_ko, description_ko, canonical(option_names),
                                                  "reviewed" if reviewed else "draft", src_hash, iso(now_utc())))
            return v

    def review_translation(self, product_id: int, version: int, actor: str) -> None:
        with self.tx() as c:
            p = self.get_product(c, product_id)
            tr = self.latest_translation(c, product_id)
            if not p or not tr or tr["version"] != version:
                raise ValidationError("최신 번역을 다시 확인하세요.")
            source_hash = sha({"t": p["title_src"], "d": p["description_src"],
                               "o": {o["source_option_id"]: o["name"] for o in p["options"]}})
            if tr["source_hash"] != source_hash:
                raise ValidationError("원문이 변경됐습니다. 번역을 다시 저장하고 검수하세요.")
            c.execute("UPDATE translations SET status='reviewed' WHERE product_id=? AND version=?", (product_id, version))
            self.audit(c, actor, "translation_reviewed", {"product_id": product_id, "version": version})

    def latest_translation(self, c: sqlite3.Connection, product_id: int) -> dict | None:
        r = c.execute("SELECT * FROM translations WHERE product_id=? ORDER BY version DESC LIMIT 1", (product_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["option_names"] = json.loads(d["option_names"])
        return d

    # ---- 견적 ----
    def latest_quotes(self, c: sqlite3.Connection, product_id: int, channel: str) -> list[dict]:
        g = c.execute("SELECT MAX(generation) FROM quotes WHERE product_id=? AND channel=?", (product_id, channel)).fetchone()[0]
        if g is None:
            return []
        rows = c.execute("SELECT * FROM quotes WHERE product_id=? AND channel=? AND generation=? ORDER BY source_option_id",
                         (product_id, channel, g)).fetchall()
        return [{**dict(r), "inputs": json.loads(r["inputs"]), "result": json.loads(r["result"])} for r in rows]

    def save_quotes(self, product_id: int, channel: str, items: list[dict]) -> int:
        with self.tx() as c:
            g = (c.execute("SELECT COALESCE(MAX(generation),0) FROM quotes WHERE product_id=? AND channel=?",
                           (product_id, channel)).fetchone()[0]) + 1
            for it in items:
                c.execute("INSERT INTO quotes(product_id,channel,source_option_id,generation,inputs,result,valid_until,created_at) "
                          "VALUES(?,?,?,?,?,?,?,?)", (product_id, channel, it["source_option_id"], g, canonical(it["inputs"]),
                                                      canonical(it["result"]), it.get("valid_until"), iso(now_utc())))
            return g

    # ---- 해시 ----
    def content_hash(self, c: sqlite3.Connection, product_id: int, channel: str) -> str:
        """승인 대상 버전: 상품·옵션(원가/이미지)·번역·채널 견적(가격·배송 조건)의 해시."""
        p = self.get_product(c, product_id)
        tr = self.latest_translation(c, product_id)
        qs = self.latest_quotes(c, product_id, channel)
        p_core = {k: v for k, v in p.items() if k not in ("id", "status", "version")}
        return sha({"product": p_core,
                    "translation": None if tr is None else {k: tr[k] for k in ("version", "title_ko", "description_ko", "option_names", "source_hash")},
                    "quotes": [{"opt": q["source_option_id"], "inputs": q["inputs"], "result": q["result"]} for q in qs]})
