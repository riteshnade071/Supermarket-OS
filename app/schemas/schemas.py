from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ---------- AUTH ----------

class RegisterStoreRequest(BaseModel):
    tenant_name: str
    store_name: str
    owner_name: str
    phone: str
    password: str


class LoginRequest(BaseModel):
    phone: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str
    role: str
    tenant_id: str
    store_id: Optional[str] = None


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
    expected_date: Optional[datetime] = None
    items: List[PurchaseOrderItemIn]


class PurchaseOrderReceive(BaseModel):
    purchase_order_id: str
    batch_number: Optional[str] = None
    expiry_date: Optional[datetime] = None


# ---------- SUPPLIERS ----------

class SupplierCreate(BaseModel):
    store_id: Optional[str] = None  # accepted for frontend compatibility, suppliers are tenant-wide
    name: str
    phone: Optional[str] = None
    gstin: Optional[str] = None
    credit_days: int = 0


class SupplierOut(BaseModel):
    id: str
    name: str
    phone: Optional[str]
    gstin: Optional[str]
    credit_days: int
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- PURCHASE ORDER DETAIL / RECEIVING ----------

class PurchaseOrderListItem(BaseModel):
    id: str
    order_number: Optional[str]
    supplier_name: str
    created_at: datetime
    item_count: int
    total_amount: float
    status: str


class PurchaseOrderItemDetail(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    received_quantity: int
    purchase_price: float


class PurchaseOrderDetail(BaseModel):
    id: str
    order_number: Optional[str]
    supplier_id: str
    supplier_name: str
    status: str
    total_amount: float
    created_at: datetime
    expected_date: Optional[datetime]
    items: List[PurchaseOrderItemDetail]


class ReceiveOrderItem(BaseModel):
    product_id: str
    quantity: float
    purchase_price: float = 0.0


class ReceiveOrderRequest(BaseModel):
    store_id: str
    items: List[ReceiveOrderItem]


# ---------- DASHBOARD ----------

class LowStockAlert(BaseModel):
    product_id: str
    product_name: str
    current_stock: int
    reorder_level: int
    avg_daily_sale: float
    days_left: Optional[float] = None
    suggested_purchase_qty: int
    suggested_supplier: Optional[str] = None
    suggested_rate: Optional[float] = None


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


# ---------- CUSTOMER CRM ----------

class CustomerCreate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


class CustomerOut(BaseModel):
    id: str
    name: Optional[str]
    phone: Optional[str]
    loyalty_points: int
    credit_balance: float
    created_at: datetime

    class Config:
        from_attributes = True


class FavoriteProduct(BaseModel):
    product_id: str
    product_name: str
    times_bought: int


class CustomerProfile(BaseModel):
    id: str
    name: Optional[str]
    phone: Optional[str]
    loyalty_points: int
    credit_balance: float
    total_purchases: int
    lifetime_spend: float
    avg_bill_value: float
    last_visit: Optional[datetime]
    favorite_products: List[FavoriteProduct]
