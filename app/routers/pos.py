import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.transactions import Sale, SaleItem, PaymentMethod
from app.models.core import Product, Batch, User
from app.schemas.schemas import SaleCreate, SaleOut
from app.services.inventory_service import record_stock_movement, get_current_stock
from app.services.expiry_service import get_fefo_batch
from app.auth import get_current_user

router = APIRouter(prefix="/pos", tags=["POS / Billing"])


@router.post("/sales", response_model=SaleOut)
def create_sale(payload: SaleCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Create a bill. Deducts stock (FEFO batch-aware), computes tax + total.
    This is the single most important endpoint in the system - cashier hits this
    every transaction, offline-first client should queue this call and replay
    on reconnect.
    """
    tenant_id = current_user.tenant_id
    if not payload.items:
        raise HTTPException(400, "Bill must have at least one item")

    subtotal = 0.0
    tax_amount = 0.0
    sale_items_data = []

    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.tenant_id == tenant_id).first()
        if not product:
            raise HTTPException(404, f"Product {item.product_id} not found")

        current_stock = get_current_stock(db, payload.store_id, item.product_id)
        if current_stock < item.quantity:
            raise HTTPException(400, f"Insufficient stock for {product.name}: have {current_stock}, need {item.quantity}")

        line_total = item.unit_price * item.quantity
        line_tax = line_total * (item.gst_rate / 100)
        subtotal += line_total
        tax_amount += line_tax

        batch = get_fefo_batch(db, payload.store_id, item.product_id)

        sale_items_data.append({
            "product_id": item.product_id,
            "batch_id": batch.id if batch else None,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "gst_rate": item.gst_rate,
            "line_total": line_total,
        })

    total = subtotal + tax_amount - payload.discount

    sale = Sale(
        tenant_id=tenant_id,
        store_id=payload.store_id,
        customer_id=payload.customer_id,
        cashier_id=current_user.id,
        bill_number=payload.bill_number or f"BILL-{uuid.uuid4().hex[:8].upper()}",
        subtotal=subtotal,
        discount=payload.discount,
        tax_amount=tax_amount,
        total=total,
        payment_method=PaymentMethod(payload.payment_method),
    )
    db.add(sale)
    db.flush()

    for item_data in sale_items_data:
        sale_item = SaleItem(sale_id=sale.id, **item_data)
        db.add(sale_item)

        record_stock_movement(
            db,
            tenant_id=tenant_id,
            store_id=payload.store_id,
            product_id=item_data["product_id"],
            batch_id=item_data["batch_id"],
            change_type="sale",
            quantity_change=-item_data["quantity"],
            reference_id=sale.id,
            created_by=current_user.id,
        )
        if item_data["batch_id"]:
            batch = db.query(Batch).filter_by(id=item_data["batch_id"]).first()
            if batch:
                batch.quantity -= item_data["quantity"]

    db.commit()
    db.refresh(sale)
    return sale


@router.post("/sales/{sale_id}/cancel")
def cancel_sale(sale_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Cancel a bill and reverse stock deduction."""
    sale = db.query(Sale).filter(Sale.id == sale_id, Sale.tenant_id == current_user.tenant_id).first()
    if not sale:
        raise HTTPException(404, "Sale not found")
    if sale.is_cancelled:
        raise HTTPException(400, "Sale already cancelled")

    items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
    for item in items:
        record_stock_movement(
            db,
            tenant_id=current_user.tenant_id,
            store_id=sale.store_id,
            product_id=item.product_id,
            batch_id=item.batch_id,
            change_type="return",
            quantity_change=item.quantity,
            reference_id=sale.id,
            note="Sale cancelled",
            created_by=current_user.id,
        )

    sale.is_cancelled = True
    db.commit()
    return {"status": "cancelled", "sale_id": sale_id}


@router.get("/sales", response_model=list[SaleOut])
def list_sales(store_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Sale)
        .filter(Sale.tenant_id == current_user.tenant_id, Sale.store_id == store_id, Sale.is_cancelled == False)  # noqa: E712
        .order_by(Sale.created_at.desc())
        .limit(100)
        .all()
    )
