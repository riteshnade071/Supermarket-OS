from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import Product, Batch, StockLevel, User
from app.schemas.schemas import ProductCreate, ProductOut, ExpiryAlert
from app.services.inventory_service import record_stock_movement, get_current_stock
from app.services.expiry_service import get_expiry_alerts
from app.auth import get_current_user

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.post("/products", response_model=ProductOut)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tenant_id = current_user.tenant_id
    existing = None
    if payload.barcode:
        existing = db.query(Product).filter(Product.tenant_id == tenant_id, Product.barcode == payload.barcode).first()
    if existing:
        raise HTTPException(400, "Product with this barcode already exists")

    product = Product(tenant_id=tenant_id, **payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Product).filter(Product.tenant_id == current_user.tenant_id, Product.is_active == True).all()  # noqa: E712


@router.get("/products-with-stock")
def list_products_with_stock(store_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """One call for the management screen: every product plus its current stock in this store."""
    products = db.query(Product).filter(Product.tenant_id == current_user.tenant_id, Product.is_active == True).all()  # noqa: E712
    stock_rows = db.query(StockLevel).filter(StockLevel.store_id == store_id).all()
    stock_by_product = {row.product_id: row.quantity for row in stock_rows}

    return [
        {
            "id": p.id,
            "name": p.name,
            "barcode": p.barcode,
            "gst_rate": p.gst_rate,
            "unit": p.unit,
            "purchase_price": p.purchase_price,
            "selling_price": p.selling_price,
            "min_stock": p.min_stock,
            "max_stock": p.max_stock,
            "reorder_level": p.reorder_level,
            "current_stock": stock_by_product.get(p.id, 0),
        }
        for p in products
    ]


@router.get("/products/barcode/{barcode}", response_model=ProductOut)
def get_product_by_barcode(barcode: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Used by the POS billing screen when cashier scans a barcode."""
    product = db.query(Product).filter(Product.tenant_id == current_user.tenant_id, Product.barcode == barcode).first()
    if not product:
        raise HTTPException(404, "Product not found for this barcode")
    return product


@router.get("/stock/{store_id}/{product_id}")
def get_stock(store_id: str, product_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    qty = get_current_stock(db, store_id, product_id)
    return {"store_id": store_id, "product_id": product_id, "quantity": qty}


@router.post("/receive-stock")
def receive_stock(
    store_id: str,
    product_id: str,
    quantity: int,
    purchase_price: float,
    batch_number: str | None = None,
    expiry_date: datetime | None = None,
    supplier_reference: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Goods received from supplier -> creates a batch (if expiry tracked) and increases stock."""
    tenant_id = current_user.tenant_id
    batch = None
    if expiry_date or batch_number:
        batch = Batch(
            tenant_id=tenant_id,
            store_id=store_id,
            product_id=product_id,
            batch_number=batch_number,
            quantity=quantity,
            purchase_price=purchase_price,
            expiry_date=expiry_date,
        )
        db.add(batch)
        db.flush()

    record_stock_movement(
        db,
        tenant_id=tenant_id,
        store_id=store_id,
        product_id=product_id,
        batch_id=batch.id if batch else None,
        change_type="purchase",
        quantity_change=quantity,
        reference_id=supplier_reference,
        note="Stock received from supplier",
        created_by=current_user.id,
    )

    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == tenant_id).first()
    if product:
        product.purchase_price = purchase_price

    db.commit()
    return {"status": "received", "quantity": quantity, "batch_id": batch.id if batch else None}


@router.post("/adjust-stock")
def adjust_stock(
    store_id: str,
    product_id: str,
    quantity_change: int,
    reason: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manual correction - damage, theft write-off, physical count adjustment. Always logged."""
    if reason not in ("damage", "adjustment", "expiry"):
        raise HTTPException(400, "reason must be one of: damage, adjustment, expiry")

    record_stock_movement(
        db,
        tenant_id=current_user.tenant_id,
        store_id=store_id,
        product_id=product_id,
        change_type=reason,
        quantity_change=quantity_change,
        note=f"Manual adjustment: {reason}",
        created_by=current_user.id,
    )
    db.commit()
    return {"status": "adjusted", "quantity_change": quantity_change}


@router.get("/expiry-alerts", response_model=list[ExpiryAlert])
def expiry_alerts(store_id: str, days_ahead: int = 7, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_expiry_alerts(db, current_user.tenant_id, store_id, days_ahead)
