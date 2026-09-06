from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import Tenant, Store, User, UserRole
from app.schemas.schemas import RegisterStoreRequest, LoginRequest, TokenResponse
from app.auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register-store", response_model=TokenResponse)
def register_store(payload: RegisterStoreRequest, db: Session = Depends(get_db)):
    """
    One-time setup for a new supermarket: creates the Tenant (business),
    its first Store, and an Owner user - then logs them straight in.
    Use this once per supermarket, not once per employee.
    """
    existing = db.query(User).filter(User.phone == payload.phone).first()
    if existing:
        raise HTTPException(400, "This phone number is already registered. Try logging in instead.")

    tenant = Tenant(name=payload.tenant_name, plan="starter")
    db.add(tenant)
    db.flush()  # get tenant.id

    store = Store(tenant_id=tenant.id, name=payload.store_name)
    db.add(store)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        store_id=store.id,
        name=payload.owner_name,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=UserRole.OWNER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        name=user.name,
        role=user.role.value,
        tenant_id=user.tenant_id,
        store_id=user.store_id,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == payload.phone).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Incorrect phone number or password.")
    if not user.is_active:
        raise HTTPException(403, "This account has been disabled. Contact your store owner.")

    token = create_access_token({"sub": user.id})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        name=user.name,
        role=user.role.value,
        tenant_id=user.tenant_id,
        store_id=user.store_id,
    )


@router.get("/me", response_model=TokenResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Used by the frontend to check whether a saved login is still valid."""
    return TokenResponse(
        access_token="",  # not reissuing here, just confirming identity
        user_id=current_user.id,
        name=current_user.name,
        role=current_user.role.value,
        tenant_id=current_user.tenant_id,
        store_id=current_user.store_id,
    )
