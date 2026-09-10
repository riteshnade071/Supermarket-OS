from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.core import Batch, Product


def get_expiry_alerts(db: Session, tenant_id: str, store_id: str, days_ahead: int = 7):
    """Batches expiring within `days_ahead` days, with quantity still remaining."""
    cutoff = datetime.utcnow() + timedelta(days=days_ahead)

    batches = (
        db.query(Batch)
        .filter(
            Batch.tenant_id == tenant_id,
            Batch.store_id == store_id,
            Batch.quantity > 0,
            Batch.expiry_date != None,  # noqa: E711
            Batch.expiry_date <= cutoff,
        )
        .order_by(Batch.expiry_date.asc())
        .all()
    )

    alerts = []
    for batch in batches:
        product = db.query(Product).filter(Product.id == batch.product_id).first()
        days_to_expiry = (batch.expiry_date - datetime.utcnow()).days if batch.expiry_date else None
        alerts.append({
            "product_id": batch.product_id,
            "product_name": product.name if product else "Unknown",
            "batch_id": batch.id,
            "quantity": batch.quantity,
            "expiry_date": batch.expiry_date,
            "days_to_expiry": days_to_expiry,
        })
    return alerts


def get_fefo_batch(db: Session, store_id: str, product_id: str):
    """First Expiry First Out - pick the oldest-expiry batch with stock available."""
    return (
        db.query(Batch)
        .filter(
            Batch.store_id == store_id,
            Batch.product_id == product_id,
            Batch.quantity > 0,
        )
        .order_by(Batch.expiry_date.asc().nulls_last())
        .first()
    )
