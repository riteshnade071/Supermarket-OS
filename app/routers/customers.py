from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.transactions import Customer, Sale, SaleItem
from app.models.core import Product, User
from app.schemas.schemas import CustomerCreate, CustomerOut, CustomerProfile, FavoriteProduct
from app.auth import get_current_user

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("/find-or-create", response_model=CustomerOut)
def find_or_create_customer(
    payload: CustomerCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Used at the billing counter. If a phone number is given, this finds the
    existing customer by phone or creates one. Some customers decline to
    share a phone number - in that case we still record the name (if given)
    as a one-off customer with no phone, since there's no reliable way to
    match them to a future visit.
    """
    if not payload.phone and not payload.name:
        raise HTTPException(400, "Provide at least a name or a phone number")

    if payload.phone:
        customer = (
            db.query(Customer)
            .filter(Customer.tenant_id == current_user.tenant_id, Customer.phone == payload.phone)
            .first()
        )
        if customer:
            if payload.name and not customer.name:
                customer.name = payload.name
                db.commit()
                db.refresh(customer)
            return customer

    customer = Customer(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        phone=payload.phone,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("", response_model=list[CustomerOut])
def list_customers(search: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List customers, optionally filtered by name/phone substring (for cashier search-as-you-type)."""
    query = db.query(Customer).filter(Customer.tenant_id == current_user.tenant_id)
    if search:
        like = f"%{search}%"
        query = query.filter((Customer.name.ilike(like)) | (Customer.phone.ilike(like)))
    return query.order_by(Customer.created_at.desc()).limit(50).all()


@router.get("/{customer_id}", response_model=CustomerProfile)
def get_customer_profile(customer_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Full customer profile: lifetime spend, average bill, last visit, and
    favorite products - everything the plan's 'Customer CRM' section asked for.
    """
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.tenant_id == current_user.tenant_id)
        .first()
    )
    if not customer:
        raise HTTPException(404, "Customer not found")

    sales = (
        db.query(Sale)
        .filter(Sale.customer_id == customer_id, Sale.is_cancelled == False)  # noqa: E712
        .all()
    )

    total_purchases = len(sales)
    lifetime_spend = sum(s.total for s in sales)
    avg_bill = round(lifetime_spend / total_purchases, 2) if total_purchases else 0.0
    last_visit = max((s.created_at for s in sales), default=None)

    # favorite products: count how often each product appears across this customer's sale items
    favorites_query = (
        db.query(
            SaleItem.product_id,
            Product.name.label("product_name"),
            func.count(SaleItem.id).label("times_bought"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(Sale.customer_id == customer_id, Sale.is_cancelled == False)  # noqa: E712
        .group_by(SaleItem.product_id, Product.name)
        .order_by(func.count(SaleItem.id).desc())
        .limit(5)
        .all()
    )

    favorite_products = [
        FavoriteProduct(product_id=row.product_id, product_name=row.product_name, times_bought=row.times_bought)
        for row in favorites_query
    ]

    return CustomerProfile(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        loyalty_points=customer.loyalty_points,
        credit_balance=customer.credit_balance,
        total_purchases=total_purchases,
        lifetime_spend=round(lifetime_spend, 2),
        avg_bill_value=avg_bill,
        last_visit=last_visit,
        favorite_products=favorite_products,
    )
