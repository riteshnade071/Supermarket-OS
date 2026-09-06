from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import User
from app.models.transactions import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus
from app.schemas.schemas import PurchaseOrderCreate, LowStockAlert
from app.services.reorder_service import get_low_stock_alerts
from app.auth import get_current_user

router = APIRouter(prefix="/purchase", tags=["Purchase & Suppliers"])


@router.get("/reorder-suggestions", response_model=list[LowStockAlert])
def reorder_suggestions(store_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    The AI Smart Reorder Engine. Returns products that are about to run out,
    with a suggested purchase quantity based on the last 30 days of sales velocity.
    """
    return get_low_stock_alerts(db, current_user.tenant_id, store_id)


@router.post("/orders")
def create_purchase_order(
    payload: PurchaseOrderCreate,
    is_ai_suggested: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.items:
        raise HTTPException(400, "Purchase order must have at least one item")

    total = sum(item.quantity * item.unit_price for item in payload.items)

    po = PurchaseOrder(
        tenant_id=current_user.tenant_id,
        store_id=payload.store_id,
        supplier_id=payload.supplier_id,
        status=PurchaseOrderStatus.DRAFT,
        is_ai_suggested=is_ai_suggested,
        total_amount=total,
    )
    db.add(po)
    db.flush()

    for item in payload.items:
        db.add(PurchaseOrderItem(
            purchase_order_id=po.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.quantity * item.unit_price,
        ))

    db.commit()
    db.refresh(po)
    return {"id": po.id, "status": po.status, "total_amount": po.total_amount}


@router.get("/orders")
def list_purchase_orders(store_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.tenant_id == current_user.tenant_id, PurchaseOrder.store_id == store_id)
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )
