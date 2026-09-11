"""
Smart Reorder Engine.
Looks at last 30 days of sales for a product+store, computes average daily sale,
and flags products that will run out soon + suggests a purchase quantity.

Also does Price Intelligence: compares every supplier's quoted rate for a
product (from SupplierProductPrice) against what you're currently paying,
and surfaces the saving if a cheaper supplier exists. This is what makes the
alert feed an "AI manager" instead of a plain low-stock list — it doesn't
just say what to buy, it says who to buy it from and why.
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.core import Product, StockLevel, Supplier, SupplierProductPrice
from app.models.transactions import SaleItem, Sale


def get_avg_daily_sale(db: Session, store_id: str, product_id: str, days: int = 30) -> float:
    since = datetime.utcnow() - timedelta(days=days)
    total_sold = (
        db.query(func.coalesce(func.sum(SaleItem.quantity), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(
            Sale.store_id == store_id,
            SaleItem.product_id == product_id,
            Sale.created_at >= since,
            Sale.is_cancelled == False,  # noqa: E712
        )
        .scalar()
    )
    return round((total_sold or 0) / days, 2)


def get_best_supplier_price(db: Session, tenant_id: str, product_id: str):
    """
    Cheapest quoted rate across all suppliers for this product.
    Returns (supplier_name, price) or (None, None) if no prices are on file.
    """
    row = (
        db.query(SupplierProductPrice, Supplier)
        .join(Supplier, Supplier.id == SupplierProductPrice.supplier_id)
        .filter(SupplierProductPrice.tenant_id == tenant_id, SupplierProductPrice.product_id == product_id)
        .order_by(SupplierProductPrice.price.asc())
        .first()
    )
    if not row:
        return None, None
    price_row, supplier = row
    return supplier.name, price_row.price


def get_low_stock_alerts(db: Session, tenant_id: str, store_id: str):
    """Returns list of dicts: product running low + suggested purchase qty + best price."""
    products = db.query(Product).filter(Product.tenant_id == tenant_id, Product.is_active == True).all()  # noqa: E712
    alerts = []

    for product in products:
        stock = (
            db.query(StockLevel)
            .filter(StockLevel.store_id == store_id, StockLevel.product_id == product.id)
            .first()
        )
        current_qty = stock.quantity if stock else 0
        avg_daily = get_avg_daily_sale(db, store_id, product.id)

        # Only alert if stock at or below reorder level, OR will run out within 3 days
        days_left = (current_qty / avg_daily) if avg_daily > 0 else float("inf")

        if current_qty <= product.reorder_level or days_left <= 3:
            # Suggested purchase: bring stock up to max_stock, accounting for ~2 days supplier lead time buffer
            safety_stock = max(product.min_stock, int(avg_daily * 2))
            suggested_qty = max(product.max_stock - current_qty, safety_stock)

            supplier_name = None
            if product.supplier_id:
                supplier = db.query(Supplier).filter(Supplier.id == product.supplier_id).first()
                if supplier:
                    supplier_name = supplier.name

            current_rate = product.purchase_price if product.purchase_price else None

            # --- Price Intelligence ---
            best_supplier_name, best_rate = get_best_supplier_price(db, tenant_id, product.id)
            potential_saving = None
            if best_rate is not None and current_rate:
                # Only worth surfacing if the "best" supplier is actually cheaper
                # than what we're currently paying, and it isn't the same supplier.
                if best_rate < current_rate and best_supplier_name != supplier_name:
                    potential_saving = round((current_rate - best_rate) * suggested_qty, 2)
                else:
                    best_supplier_name, best_rate = None, None

            alerts.append({
                "product_id": product.id,
                "product_name": product.name,
                "current_stock": current_qty,
                "reorder_level": product.reorder_level,
                "avg_daily_sale": avg_daily,
                "days_left": round(days_left, 1) if days_left != float("inf") else None,
                "suggested_purchase_qty": suggested_qty,
                "suggested_supplier": supplier_name,
                "suggested_rate": current_rate,
                "best_supplier_name": best_supplier_name,
                "best_supplier_rate": best_rate,
                "potential_saving": potential_saving,
            })

    # Most urgent first
    alerts.sort(key=lambda a: (a["days_left"] is None, a["days_left"]))
    return alerts
