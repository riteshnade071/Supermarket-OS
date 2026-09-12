import csv
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import Product, Batch, StockLevel, User
from app.schemas.schemas import ProductCreate, ProductOut, ExpiryAlert
from app.services.inventory_service import record_stock_movement, get_current_stock
from app.services.expiry_service import get_expiry_alerts
from app.auth import get_current_user

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.post("/products/bulk-import")
async def bulk_import_products(
    store_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a CSV to add many products in one go — instead of typing each one
    in by hand, which can take hours for a shop with hundreds of SKUs.

    Expected header row (case-insensitive), only 'name' and 'selling_price'
    are required, everything else has a sensible default:
    name, barcode, selling_price, purchase_price, gst_rate, unit,
    opening_stock, min_stock, max_stock, reorder_level, expiry_date

    'expiry_date' (format YYYY-MM-DD) is optional — if given along with
    opening_stock, a proper Batch record is created so FEFO and expiry
    alerts work for that opening stock too, not just for stock received later.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV file appears to be empty")

    normalized_fields = {f.strip().lower(): f for f in reader.fieldnames}

    def get_val(row, key):
        actual_key = normalized_fields.get(key)
        if not actual_key:
            return None
        val = row.get(actual_key, "")
        return val.strip() if val else None

    def to_float(row, key, default):
        v = get_val(row, key)
        try:
            return float(v) if v else default
        except ValueError:
            return default

    def to_int(row, key, default):
        v = get_val(row, key)
        try:
            return int(float(v)) if v else default
        except ValueError:
            return default

    def to_date(row, key):
        v = get_val(row, key)
        if not v:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                continue
        return None

    tenant_id = current_user.tenant_id
    existing_barcodes = {
        p.barcode for p in
        db.query(Product.barcode).filter(Product.tenant_id == tenant_id, Product.barcode.isnot(None)).all()
    }

    created = 0
    skipped = []
    row_num = 1  # header counts as row 1, so data starts at row 2

    for row in reader:
        row_num += 1
        name = get_val(row, "name")
        selling_price_raw = get_val(row, "selling_price")

        if not name or not selling_price_raw:
            skipped.append({"row": row_num, "reason": "missing name or selling_price"})
            continue

        try:
            selling_price = float(selling_price_raw)
        except ValueError:
            skipped.append({"row": row_num, "reason": f"invalid selling_price '{selling_price_raw}'"})
            continue

        barcode = get_val(row, "barcode")
        if barcode and barcode in existing_barcodes:
            skipped.append({"row": row_num, "reason": f"barcode '{barcode}' already exists — skipped"})
            continue

        product = Product(
            tenant_id=tenant_id,
            name=name,
            barcode=barcode,
            unit=get_val(row, "unit") or "pcs",
            gst_rate=to_float(row, "gst_rate", 0.0),
            purchase_price=to_float(row, "purchase_price", 0.0),
            selling_price=selling_price,
            min_stock=to_int(row, "min_stock", 5),
            max_stock=to_int(row, "max_stock", 100),
            reorder_level=to_int(row, "reorder_level", 10),
        )
        db.add(product)
        db.flush()  # get product.id for the stock movement below

        opening_stock = to_int(row, "opening_stock", 0)
        expiry_date = to_date(row, "expiry_date")

        if opening_stock > 0:
            batch = None
            # If an expiry date is given, create a real Batch so FEFO and
            # expiry alerts pick up this opening stock too — not just stock
            # received later through the normal "Receive Stock" flow.
            if expiry_date:
                batch = Batch(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    product_id=product.id,
                    quantity=opening_stock,
                    purchase_price=product.purchase_price,
                    expiry_date=expiry_date,
                )
                db.add(batch)
                db.flush()

            record_stock_movement(
                db,
                tenant_id=tenant_id,
                store_id=store_id,
                product_id=product.id,
                batch_id=batch.id if batch else None,
                change_type="purchase",
                quantity_change=opening_stock,
                note="Bulk CSV import — opening stock",
                created_by=current_user.id,
            )

        if barcode:
            existing_barcodes.add(barcode)
        created += 1

    db.commit()
    return {"created": created, "skipped_count": len(skipped), "skipped_details": skipped[:25]}


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
