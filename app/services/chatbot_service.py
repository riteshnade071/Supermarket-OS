"""
Owner AI Assistant — powered by Google Gemini (free tier, no card required).

Answers the owner's questions about the shop by giving Gemini two things
as context: (1) a compact "how to use this app" guide, and (2) today's
real sales/purchase numbers pulled fresh from the database. This is what
lets it answer both "aaj kitni sale hui" (data question) and "reorder
kaise karu" (how-to question) from the same chat box.

Needs a GEMINI_API_KEY environment variable — get a free one (no credit
card) at aistudio.google.com -> Get API Key. Every other feature in the
app works fine without it - only this assistant needs the key.
"""
import os
from datetime import datetime
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.core import Product, Supplier
from app.models.transactions import Sale, SaleItem, PurchaseOrder

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"  # free tier, good quality/speed balance
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

APP_HELP_GUIDE = """
Supermarket OS — how each screen works:

BILLING / POS (pos.html):
- Scan a barcode: a USB/Bluetooth gun types it automatically, or tap the camera button to scan with the phone camera.
- Can also just search a product by name in the search box.
- Pick payment method (Cash/UPI/Card/Credit) before checkout.
- Past sales can be cancelled, which automatically reverses the stock deduction.
- Works offline too — bills made without internet sync automatically once connection is back.

INVENTORY (inventory.html):
- "Add Product" registers a new item: name, barcode, price, GST rate, min/max/reorder stock levels.
- "Receive Stock" logs goods arriving from a supplier, optionally with a batch number + expiry date.
- Expiry alerts appear automatically for batches expiring within 7 days.
- "Adjust Stock" is for manual corrections — damage, theft write-off, physical count mismatch.

PURCHASE & SUPPLIERS (purchase.html):
- "Add Supplier" registers a supplier's contact details.
- "Reorder Suggestions" tab shows what's running low and how much to buy, based on the last 30 days of sales speed.
- "Supplier price list" lets the owner record what each supplier charges per product — the app automatically flags the cheapest one and shows potential savings on the dashboard.
- Purchase Orders can be created and marked Received (full or partial) when goods arrive — stock updates automatically.

DASHBOARD (dashboard.html):
- Shows today's total sales, gross profit, margin %, and bill count.
- "Actions Required" feed combines low-stock alerts, expiry alerts, and supplier price comparisons into one prioritized list — the daily to-do list.
"""


def _today_summary(db: Session, store_id: str) -> str:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    sales = (
        db.query(Sale)
        .filter(Sale.store_id == store_id, Sale.created_at >= today_start, Sale.is_cancelled == False)  # noqa: E712
        .all()
    )
    total_sales = sum(s.total for s in sales)
    bill_count = len(sales)

    top_items = (
        db.query(Product.name, func.sum(SaleItem.quantity).label("qty"))
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.store_id == store_id, Sale.created_at >= today_start, Sale.is_cancelled == False)  # noqa: E712
        .group_by(Product.name)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(5)
        .all()
    )
    top_items_str = ", ".join(f"{n} ({int(q)} units)" for n, q in top_items) if top_items else "no sales yet today"

    purchase_orders = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.store_id == store_id, PurchaseOrder.created_at >= today_start)
        .all()
    )
    po_lines = []
    for po in purchase_orders:
        supplier = db.query(Supplier).filter(Supplier.id == po.supplier_id).first()
        status = po.status.value if hasattr(po.status, "value") else po.status
        po_lines.append(f"- {po.order_number} to {supplier.name if supplier else 'Unknown supplier'}: Rs.{po.total_amount} ({status})")

    return f"""Today's business data ({today_start.strftime('%Y-%m-%d')}):
- Total sales: Rs.{round(total_sales, 2)} across {bill_count} bills
- Top-selling items today: {top_items_str}
- Purchase orders placed today: {len(purchase_orders)}
{chr(10).join(po_lines) if po_lines else "(no purchase orders today)"}
"""


async def ask_owner_assistant(db: Session, store_id: str, question: str) -> str:
    if not GEMINI_API_KEY:
        return (
            "AI assistant abhi set up nahi hua — backend ke Environment settings me "
            "GEMINI_API_KEY add karna hoga (aistudio.google.com se free milta hai, koi card nahi chahiye)."
        )

    system_prompt = (
        "You are the in-app assistant for Supermarket OS, talking directly to the shop owner. "
        "ALWAYS reply in the exact same language/script the owner just wrote their question in — "
        "if they write in Hindi (Devanagari), reply in Hindi; if Hinglish, reply in Hinglish; if "
        "English, reply in English; if Marathi or any other language, match that. Never switch "
        "language on your own.\n\n"
        "Be a general-purpose assistant, not limited to the app — the owner can ask ANYTHING "
        "(business advice, general knowledge, calculations, translations, personal questions, "
        "anything at all) and you should answer it helpfully, the same way any capable assistant "
        "would. On top of that, you have two special resources below: today's real business data "
        "for this store, and a guide to how this specific app works. Use them when the question is "
        "about the shop's sales/purchases or about using the app — for everything else, just answer "
        "from your own general knowledge.\n\n"
        "Be concise and direct — the owner is busy running a shop, no long preambles. If a question "
        "needs data you don't have here (like last month's numbers or a specific old bill), say so "
        "honestly instead of guessing.\n\n"
        f"{APP_HELP_GUIDE}\n\n{_today_summary(db, store_id)}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                GEMINI_URL,
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "content-type": "application/json",
                },
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": question}]}],
                    "generationConfig": {
                        "maxOutputTokens": 1024,
                        # Keep the assistant's internal "thinking" minimal so the
                        # token budget goes to the actual answer, not invisible
                        # reasoning tokens — this is what was causing empty replies.
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                },
            )
            res.raise_for_status()
            data = res.json()

            block_reason = data.get("promptFeedback", {}).get("blockReason")
            if block_reason:
                return "Ye sawaal answer nahi ho paya (content filter). Alag tarike se pooch ke dekho."

            candidates = data.get("candidates", [])
            if not candidates:
                return "Jawab nahi mil paya, dobara try karo."
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            return text.strip() or "Jawab nahi mil paya, dobara try karo."
    except Exception:
        return "AI assistant abhi jawab nahi de paya — network issue ho sakta hai. Thodi der baad try karo."
