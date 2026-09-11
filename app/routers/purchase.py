import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import User, Supplier, Product, SupplierProductPrice
from app.models.transactions import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus
from app.schemas.schemas import (
    PurchaseOrderCreate, LowStockAlert, SupplierCreate, SupplierOut,
    PurchaseOrderListItem, PurchaseOrderDetail, PurchaseOrderItemDetail, ReceiveOrderRequest,
    SupplierPriceIn, SupplierPriceOut,
)
from app.services.reorder_service import get_low_stock_alerts
from app.services.inventory_service import record_stock_movement
from app.auth import get_current_user

router = APIRouter(prefix="/purchase", tags=["Purchase & Suppliers"])


@router.get("/reorder-suggestions", response_model=list[LowStockAlert])
def reorder_suggestions(store_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    The AI Smart Reorder Engine. Returns products that are about to run out,
    with a suggested purchase quantity based on the last 30 days of sales velocity.
    """
    return get_low_stock_alerts(db, current_user.tenant_id, store_id)


# ---------- SUPPLIERS ----------

@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(store_id: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Suppliers are shared across all stores of a tenant - store_id accepted but not filtered on."""
    return (
        db.query(Supplier)
        .filter(Supplier.tenant_id == current_user.tenant_id)
        .order_by(Supplier.name.asc())
        .all()
    )


@router.post("/suppliers", response_model=SupplierOut)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    supplier = Supplier(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        phone=payload.phone,
        gstin=payload.gstin,
        credit_days=payload.credit_days,
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


# ---------- SUPPLIER PRICES (Price Intelligence) ----------

@router.post("/supplier-prices", response_model=SupplierPriceOut)
def set_supplier_price(payload: SupplierPriceIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Record/update what a supplier quotes for a product. This is the data
    source the AI reorder feed uses to say 'buy from B instead, save ₹X' —
    add a few suppliers' rates for your fast-moving products and the
    dashboard alerts start showing potential savings automatically.
    """
    supplier = db.query(Supplier).filter(Supplier.id == payload.supplier_id, Supplier.tenant_id == current_user.tenant_id).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    product = db.query(Product).filter(Product.id == payload.product_id, Product.tenant_id == current_user.tenant_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    existing = (
        db.query(SupplierProductPrice)
        .filter(SupplierProductPrice.supplier_id == payload.supplier_id, SupplierProductPrice.product_id == payload.product_id)
        .first()
    )
    if existing:
        existing.price = payload.price
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    row = SupplierProductPrice(
        tenant_id=current_user.tenant_id,
        supplier_id=payload.supplier_id,
        product_id=payload.product_id,
        price=payload.price,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/supplier-prices/{product_id}", response_model=list[SupplierPriceOut])
def list_supplier_prices(product_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """All known supplier quotes for one product, cheapest first — for a manual price-compare view."""
    return (
        db.query(SupplierProductPrice)
        .filter(SupplierProductPrice.tenant_id == current_user.tenant_id, SupplierProductPrice.product_id == product_id)
        .order_by(SupplierProductPrice.price.asc())
        .all()
    )


# ---------- PURCHASE ORDERS ----------

@router.post("/orders")
def create_purchase_order(
    payload: PurchaseOrderCreate,
    is_ai_suggested: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.items:
        raise HTTPException(400, "Purchase order must have at least one item")

    supplier = db.query(Supplier).filter(Supplier.id == payload.supplier_id, Supplier.tenant_id == current_user.tenant_id).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    total = sum(item.quantity * item.purchase_price for item in payload.items)
    order_number = f"PO-{uuid.uuid4().hex[:8].upper()}"

    po = PurchaseOrder(
        tenant_id=current_user.tenant_id,
        store_id=payload.store_id,
        supplier_id=payload.supplier_id,
        status=PurchaseOrderStatus.SENT,  # creation IS "sending" in this simple workflow
        is_ai_suggested=is_ai_suggested,
        order_number=order_number,
        expected_date=payload.expected_date,
        total_amount=total,
    )
    db.add(po)
    db.flush()

    for item in payload.items:
        db.add(PurchaseOrderItem(
            purchase_order_id=po.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.purchase_price,
            line_total=item.quantity * item.purchase_price,
        ))

    db.commit()
    db.refresh(po)
    return {"id": po.id, "order_number": po.order_number, "status": po.status, "total_amount": po.total_amount}


@router.get("/orders", response_model=list[PurchaseOrderListItem])
def list_purchase_orders(store_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    orders = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.tenant_id == current_user.tenant_id, PurchaseOrder.store_id == store_id)
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )

    result = []
    for po in orders:
        supplier = db.query(Supplier).filter(Supplier.id == po.supplier_id).first()
        item_count = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == po.id).count()
        result.append(PurchaseOrderListItem(
            id=po.id,
            order_number=po.order_number,
            supplier_name=supplier.name if supplier else "Unknown",
            created_at=po.created_at,
            item_count=item_count,
            total_amount=po.total_amount,
            status=po.status.value if hasattr(po.status, "value") else po.status,
        ))
    return result


@router.get("/orders/{order_id}", response_model=PurchaseOrderDetail)
def get_purchase_order(order_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.tenant_id == current_user.tenant_id).first()
    if not po:
        raise HTTPException(404, "Purchase order not found")

    supplier = db.query(Supplier).filter(Supplier.id == po.supplier_id).first()
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == po.id).all()

    item_details = []
    for it in items:
        product = db.query(Product).filter(Product.id == it.product_id).first()
        item_details.append(PurchaseOrderItemDetail(
            product_id=it.product_id,
            product_name=product.name if product else "Unknown",
            quantity=it.quantity,
            received_quantity=it.received_quantity or 0,
            purchase_price=it.unit_price,
        ))

    return PurchaseOrderDetail(
        id=po.id,
        order_number=po.order_number,
        supplier_id=po.supplier_id,
        supplier_name=supplier.name if supplier else "Unknown",
        status=po.status.value if hasattr(po.status, "value") else po.status,
        total_amount=po.total_amount,
        created_at=po.created_at,
        expected_date=po.expected_date,
        items=item_details,
    )


@router.post("/orders/{order_id}/receive")
def receive_purchase_order(
    order_id: str,
    payload: ReceiveOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Confirm goods received against a purchase order: increases stock for each
    item, tracks partial receipt, and marks the order received/partially received.
    """
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.tenant_id == current_user.tenant_id).first()
    if not po:
        raise HTTPException(404, "Purchase order not found")

    po_items = {it.product_id: it for it in db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == po.id).all()}

    for line in payload.items:
        po_item = po_items.get(line.product_id)
        if not po_item:
            continue  # ignore products that weren't part of this order

        qty = int(line.quantity)
        if qty <= 0:
            continue

        po_item.received_quantity = (po_item.received_quantity or 0) + qty

        record_stock_movement(
            db,
            tenant_id=current_user.tenant_id,
            store_id=payload.store_id,
            product_id=line.product_id,
            change_type="purchase",
            quantity_change=qty,
            reference_id=po.id,
            note=f"Received against {po.order_number}",
            created_by=current_user.id,
        )

        if line.purchase_price:
            product = db.query(Product).filter(Product.id == line.product_id).first()
            if product:
                product.purchase_price = line.purchase_price

    all_items = list(po_items.values())
    fully_received = all(i.received_quantity >= i.quantity for i in all_items)
    any_received = any((i.received_quantity or 0) > 0 for i in all_items)

    if fully_received:
        po.status = PurchaseOrderStatus.RECEIVED
        po.received_at = datetime.utcnow()
    elif any_received:
        po.status = PurchaseOrderStatus.PARTIALLY_RECEIVED

    db.commit()
    return {"status": "received", "order_status": po.status.value if hasattr(po.status, "value") else po.status}
