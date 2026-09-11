from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.models import core, transactions  # noqa: F401 - registers models with Base
from app.routers import auth, pos, inventory, purchase, dashboard, customers, chatbot

app = FastAPI(
    title="Supermarket OS",
    description="Billing + Inventory + Purchase + AI Reorder — ek hi platform.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(pos.router)
app.include_router(inventory.router)
app.include_router(purchase.router)
app.include_router(dashboard.router)
app.include_router(customers.router)
app.include_router(chatbot.router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"status": "ok", "message": "Supermarket OS API running"}


@app.get("/health")
def health():
    return {"status": "healthy"}
