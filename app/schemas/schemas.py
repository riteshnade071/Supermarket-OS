from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ---------- PRODUCT ----------

class ProductCreate(BaseModel):
    name: str
    barcode: Optional[str] = None
    hsn_code: Optional[str] = None
    gst_rate: float = 0.0
    unit: str = "pcs"
    purchase_price: float = 0.0
    selling_price: float
    mrp: Optional[float] = None
    min_stock: int = 5
    max_stock: int = 100
    reorder_level: int = 10
    category_id: Optional[str] = None
    supplier_id: Optional[str] = None


class ProductOut(ProductCreate):
    id: str
    is_active: bool

    class Config:
        from_attributes = True


# ---------- SALE / POS ----------

class SaleItemIn(BaseModel):
    product_id: str
    quantity: int
    unit_price: float
    gst_rate: float = 0.0


class SaleCreate(BaseModel):
    store_id: str
    customer_id: Optional[str] = None
    cashier_id: Optional[str] = None
    items: List[SaleItemIn]
    discount: float = 0.0
    payment_method: str = "cash"
    bill_number: Optional[str] = None


class SaleOut(BaseModel):
    id: str
    bill_number: Optional[str]
    subtotal: float
    discount: float
    tax_amount: float
    total: float
    payment_method: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- PURCHASE ----------

class PurchaseOrderItemIn(BaseModel):
    product_id: str
    quantity: int
    unit_price: float


class PurchaseOrderCreate(BaseModel):
    store_id: str
    supplier_id: str
    items: List[PurchaseOrderItemIn]


class PurchaseOrderReceive(BaseModel):
    purchase_order_id: str
    batch_number: Optional[str] = None
    expiry_date: Optional[datetime] = None


# ---------- DASHBOARD ----------

class LowStockAlert(BaseModel):
    product_id: str
    product_name: str
    current_stock: int
    reorder_level: int
    avg_daily_sale: float
    days_left: Optional[float] = None
    suggested_purchase_qty: int


class ExpiryAlert(BaseModel):
    product_id: str
    product_name: str
    batch_id: str
    quantity: int
    expiry_date: Optional[datetime]
    days_to_expiry: Optional[int]


class DashboardSummary(BaseModel):
    date: str
    total_sales: float
    total_bills: int
    avg_bill_value: float
    gross_profit: float
    margin_percent: float
    low_stock_count: int
    expiring_soon_count: int
