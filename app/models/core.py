import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    OWNER = "owner"
    MANAGER = "manager"
    CASHIER = "cashier"


# ---------- TENANT / STORE ----------

class Tenant(Base):
    """One Tenant = one supermarket business (may have multiple stores)."""
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    plan = Column(String, default="starter")  # starter / business / enterprise
    created_at = Column(DateTime, default=datetime.utcnow)

    stores = relationship("Store", back_populates="tenant", cascade="all, delete-orphan")
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")


class Store(Base):
    __tablename__ = "stores"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    address = Column(String)
    gstin = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="stores")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.CASHIER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users")


# ---------- PRODUCT / INVENTORY ----------

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String)
    email = Column(String)
    address = Column(String)
    avg_delivery_days = Column(Integer, default=2)
    rating = Column(Float, default=5.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "barcode", name="uq_tenant_barcode"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    category_id = Column(String(36), ForeignKey("categories.id"), nullable=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=True)

    name = Column(String, nullable=False)
    barcode = Column(String, index=True)
    hsn_code = Column(String)
    gst_rate = Column(Float, default=0.0)  # e.g. 5, 12, 18
    unit = Column(String, default="pcs")   # pcs, kg, ltr

    purchase_price = Column(Float, default=0.0)
    selling_price = Column(Float, nullable=False)
    mrp = Column(Float)

    min_stock = Column(Integer, default=5)
    max_stock = Column(Integer, default=100)
    reorder_level = Column(Integer, default=10)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Batch(Base):
    """Batch/expiry tracking per product per store."""
    __tablename__ = "batches"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)

    batch_number = Column(String)
    quantity = Column(Integer, default=0)
    purchase_price = Column(Float)
    expiry_date = Column(DateTime, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow)


class InventoryTransaction(Base):
    """Immutable ledger of every stock movement. Source of truth for stock levels."""
    __tablename__ = "inventory_transactions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    batch_id = Column(String(36), ForeignKey("batches.id"), nullable=True)

    change_type = Column(String, nullable=False)  # purchase, sale, return, damage, expiry, transfer_in, transfer_out, adjustment
    quantity_change = Column(Integer, nullable=False)  # positive or negative
    reference_id = Column(String)  # sale id / purchase order id etc
    note = Column(Text)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class StockLevel(Base):
    """Denormalized current stock per store+product for fast reads. Always derived from InventoryTransaction."""
    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("store_id", "product_id", name="uq_store_product"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
