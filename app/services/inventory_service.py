"""
Core inventory logic. EVERY stock change in the whole system must go through
record_stock_movement() so that InventoryTransaction stays the single source of truth
and StockLevel (fast-read cache) never drifts out of sync.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.core import InventoryTransaction, StockLevel


def record_stock_movement(
    db: Session,
    tenant_id: str,
    store_id: str,
    product_id: str,
    change_type: str,
    quantity_change: int,
    batch_id: str | None = None,
    reference_id: str | None = None,
    note: str | None = None,
    created_by: str | None = None,
) -> InventoryTransaction:
    txn = InventoryTransaction(
        tenant_id=tenant_id,
        store_id=store_id,
        product_id=product_id,
        batch_id=batch_id,
        change_type=change_type,
        quantity_change=quantity_change,
        reference_id=reference_id,
        note=note,
        created_by=created_by,
    )
    db.add(txn)

    stock = (
        db.query(StockLevel)
        .filter(StockLevel.store_id == store_id, StockLevel.product_id == product_id)
        .first()
    )
    if stock is None:
        stock = StockLevel(
            tenant_id=tenant_id,
            store_id=store_id,
            product_id=product_id,
            quantity=0,
        )
        db.add(stock)
        db.flush()

    stock.quantity += quantity_change
    stock.updated_at = datetime.utcnow()

    db.flush()
    return txn


def get_current_stock(db: Session, store_id: str, product_id: str) -> int:
    stock = (
        db.query(StockLevel)
        .filter(StockLevel.store_id == store_id, StockLevel.product_id == product_id)
        .first()
    )
    return stock.quantity if stock else 0
