from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.transactions import Sale, SaleItem
from app.models.core import Product
from app.schemas.schemas import DashboardSummary
from app.services.reorder_service import get_low_stock_alerts
from app.services.expiry_service import get_expiry_alerts

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(tenant_id: str, store_id: str, db: Session = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    sales_today = (
        db.query(Sale)
        .filter(Sale.store_id == store_id, Sale.created_at >= today_start, Sale.is_cancelled == False)  # noqa: E712
        .all()
    )

    total_sales = sum(s.total for s in sales_today)
    total_bills = len(sales_today)
    avg_bill = round(total_sales / total_bills, 2) if total_bills else 0.0

    # gross profit = sum over sale items of (unit_price - product.purchase_price) * qty
    gross_profit = 0.0
    for sale in sales_today:
        items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            cost = product.purchase_price if product else 0.0
            gross_profit += (item.unit_price - cost) * item.quantity

    margin_percent = round((gross_profit / total_sales) * 100, 2) if total_sales else 0.0

    low_stock = get_low_stock_alerts(db, tenant_id, store_id)
    expiring = get_expiry_alerts(db, tenant_id, store_id, days_ahead=7)

    return DashboardSummary(
        date=today_start.strftime("%Y-%m-%d"),
        total_sales=round(total_sales, 2),
        total_bills=total_bills,
        avg_bill_value=avg_bill,
        gross_profit=round(gross_profit, 2),
        margin_percent=margin_percent,
        low_stock_count=len(low_stock),
        expiring_soon_count=len(expiring),
    )


@router.get("/actions-required")
def actions_required(tenant_id: str, store_id: str, db: Session = Depends(get_db)):
    """
    The 'AI Manager' feed - combines low-stock + expiry alerts into one
    prioritized action list, exactly like the original plan's mockup.
    """
    low_stock = get_low_stock_alerts(db, tenant_id, store_id)
    expiring = get_expiry_alerts(db, tenant_id, store_id, days_ahead=7)

    actions = []
    for item in low_stock[:10]:
        actions.append({
            "type": "reorder",
            "priority": "high" if (item["days_left"] or 99) <= 2 else "medium",
            "message": f"{item['product_name']} stock khatam ho sakta hai {item['days_left']} din mein. Suggested purchase: {item['suggested_purchase_qty']} units.",
            "data": item,
        })

    for item in expiring[:10]:
        actions.append({
            "type": "expiry",
            "priority": "high" if (item["days_to_expiry"] or 99) <= 2 else "medium",
            "message": f"{item['product_name']} ({item['quantity']} units) expire ho raha hai {item['days_to_expiry']} din mein.",
            "data": item,
        })

    return {"actions": actions, "count": len(actions)}
