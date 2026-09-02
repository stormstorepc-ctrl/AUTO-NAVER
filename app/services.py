from math import ceil
from sqlalchemy.orm import Session
from .models import Product, SyncLog
from .settings import settings

def log(db: Session, action: str, message: str, product_id: int | None = None, level: str = 'INFO'):
    db.add(SyncLog(action=action, message=message, product_id=product_id, level=level))

def calculate_sale_price(supply_price: int) -> int:
    if supply_price <= 0:
        return 0
    raw = ceil(supply_price * (1 + settings.default_margin_rate))
    unit = max(settings.price_round_unit, 1)
    return ((raw + unit - 1) // unit) * unit

def apply_source_update(db: Session, p: Product, source_price: int, source_stock: int):
    old = p.last_source_price
    p.supply_price = source_price
    p.last_source_price = source_price
    p.stock = max(0, source_stock - settings.default_safety_stock)
    if source_price == 1 or source_stock <= settings.default_safety_stock:
        p.sale_price = 0
        p.status = 'SOLD_OUT'
    else:
        if old and abs(source_price - old) / old > settings.max_auto_price_change_rate:
            p.status = 'PRICE_REVIEW'
        else:
            p.sale_price = max(calculate_sale_price(source_price), settings.default_min_sale_price)
            p.status = 'PENDING'
    log(db, 'SOURCE_SYNC', f'공급가={source_price}, 재고={source_stock}, 상태={p.status}', p.id)
