"""Run one MacroMart -> local SQLite sync cycle.

Usage:
    .venv\Scripts\python.exe run_macromart_sync.py --limit 100
"""

import argparse
import sys

from sqlalchemy import select

from app.crawlers.macromart import MacroMartCrawler
from app.db import Base, SessionLocal, engine
from app.models import Product
from app.services import apply_source_update, log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        items = MacroMartCrawler().crawl(limit=max(1, min(args.limit, 500)))
        new = changed = skipped = 0

        for item in items:
            url = item.get("url")
            if item.get("error") or not url:
                skipped += 1
                continue

            external_id = url[:100]
            product = db.scalar(select(Product).where(Product.external_id == external_id))
            if not product:
                product = Product(
                    external_id=external_id,
                    name=item.get("name") or "미상 상품",
                    category=item.get("category_path") or "",
                    status="PENDING",
                )
                db.add(product)
                db.flush()
                new += 1
            else:
                changed += 1

            product.name = item.get("name") or product.name
            if item.get("brand"):
                product.brand = item["brand"]
            if item.get("model"):
                product.model = item["model"]
            if item.get("category_path"):
                product.category = item["category_path"]
            if item.get("representative_image"):
                product.representative_image = item["representative_image"]
            if item.get("detail_html"):
                product.detail_html = item["detail_html"]

            apply_source_update(
                db,
                product,
                int(item.get("source_price") or 0),
                int(item.get("source_stock") or 0),
            )

        log(db, "LOCAL_SYNC", f"매크로마트 동기화 완료 신규={new}, 갱신={changed}, 제외={skipped}")
        db.commit()
        print(f"완료: 신규={new}, 갱신={changed}, 제외={skipped}")
        return 0
    except Exception as exc:
        db.rollback()
        try:
            log(db, "LOCAL_SYNC", str(exc), None, "ERROR")
            db.commit()
        except Exception:
            db.rollback()
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
