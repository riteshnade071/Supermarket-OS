import enum
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.models.core import gen_uuid


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    UPI = "upi"
    CARD = "card"
    CREDIT = "credit"


class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    RECEIVED = "received"
    CANCELLED = "cancelled"


# ---------- CUSTOMER ----------

class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id = Column(UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False)
    name = Column(String)
    phone = Column(String, index=True)
    loyalty_points = Column(Integer, default=0)
    credit_balance = Column(Float, default=0.0)  # amount customer owes
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- SALES / POS ----------

class Sale(Base):
    __tablename__ = "sales"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id = Column(UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=False), ForeignKey("customers.id"), nullable=True)
    cashier_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)

    bill_number = Column(String, index=True)
    subtotal = Column(Float, default=0.0)
    discount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    payment_method = Column(Enum(PaymentMethod), default=PaymentMethod.CASH)
    is_offline_sync = Column(Boolean, default=False)  # true if created offline and synced later
    is_cancelled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    sale_id = Column(UUID(as_uuid=False), ForeignKey("sales.id"), nullable=False)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id"), nullable=False)
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batches.id"), nullable=True)

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    gst_rate = Column(Float, default=0.0)
    line_total = Column(Float, nullable=False)


# ---------- PURCHASE / SUPPLIER ----------

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id = Column(UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id"), nullable=False)
    supplier_id = Column(UUID(as_uuid=False), ForeignKey("suppliers.id"), nullable=False)

    status = Column(Enum(PurchaseOrderStatus), default=PurchaseOrderStatus.DRAFT)
    is_ai_suggested = Column(Boolean, default=False)
    total_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    received_at = Column(DateTime, nullable=True)


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    purchase_order_id = Column(UUID(as_uuid=False), ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id"), nullable=False)

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    line_total = Column(Float, nullable=False)
